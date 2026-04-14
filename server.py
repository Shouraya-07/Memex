"""Memory MCP server."""

import io
import hmac
import logging
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

import firebase_client as db
import summariser
from config import (
    CLOUDINARY_API_KEY,
    CLOUDINARY_API_SECRET,
    CLOUDINARY_CLOUD_NAME,
    EXTRACTED_TEXT_CHUNK_SIZE,
    HOST,
    MAX_UPLOAD_BYTES,
    MEMORY_API_KEY,
    PORT,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger("memory-mcp")

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".svg"}
_PDF_EXTS = {".pdf"}
_TEXT_EXTS = {
        ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx",
        ".html", ".css", ".json", ".yaml", ".yml", ".toml",
        ".sh", ".bat", ".ps1", ".sql", ".csv", ".xml", ".ini",
        ".env", ".cfg", ".conf", ".log",
}

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_template(filename: str) -> str:
    return (_TEMPLATES_DIR / filename).read_text(encoding="utf-8")


def _tool_api_key(ctx: Context | None) -> str | None:
    if not ctx or not ctx.request_context.meta:
        return None
    meta = ctx.request_context.meta
    extras = getattr(meta, "model_extra", None) or {}
    api_key = extras.get("api_key") or extras.get("x_api_key")
    if isinstance(api_key, str):
        return api_key.strip()
    return None

mcp = FastMCP(
    name="memory-mcp",
    host=HOST,
    port=PORT,
    instructions=(
        "Memory store for conversations, files, and context shortcuts. "
        "Use switch_context for /SHORTCUT lookups, register_context for new ones, "
        "list_contexts for the current set, save_conversation to persist a chat, "
        "and search_conversations to find older sessions."
    ),
)

def _api_key_ok(api_key: str | None) -> bool:
    if not MEMORY_API_KEY:
        log.error("MEMORY_API_KEY is not configured")
        return False
    if not api_key:
        return False
    return hmac.compare_digest(api_key.strip(), MEMORY_API_KEY)


def _request_api_key(request: Request) -> str | None:
    header_key = request.headers.get("x-api-key")
    if header_key:
        return header_key.strip()
    query_key = request.query_params.get("api_key")
    if query_key:
        return query_key.strip()
    return None


def _normalize_context_id(raw: str) -> str:
    raw = raw or ""
    return raw.lstrip("/").lower().strip()


def _infer_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _PDF_EXTS:
        return "pdf"
    if ext in _TEXT_EXTS:
        return "text"
    return "binary"


def _extract_text(temp_path: Path) -> str:
    ext = temp_path.suffix.lower()
    if ext in _IMAGE_EXTS:
        return ""
    if ext in _PDF_EXTS:
        try:
            from pdfminer.high_level import extract_text as pdf_extract

            return pdf_extract(str(temp_path)) or ""
        except Exception as exc:
            log.warning("PDF text extraction failed: %s", exc)
            return ""

    try:
        return temp_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return temp_path.read_text(encoding="latin-1")
        except Exception:
            return ""
    except Exception as exc:
        log.warning("Text extraction failed: %s", exc)
        return ""


def _upload_to_cloudinary(file_content: bytes, filename: str, context_id: str) -> dict:
    try:
        import cloudinary
        import cloudinary.uploader
    except ImportError as exc:
        raise RuntimeError("cloudinary package is not installed") from exc

    if not all([CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET]):
        raise RuntimeError("Cloudinary credentials are missing in .env")

    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET,
    )
    folder = f"memory/{context_id}"
    result = cloudinary.uploader.upload(
        io.BytesIO(file_content),
        folder=folder,
        resource_type="auto",
        use_filename=True,
        filename_override=filename,
        unique_filename=True,
    )
    return {
        "public_id": result.get("public_id", ""),
        "url": result.get("secure_url", ""),
        "resource_type": result.get("resource_type", "raw"),
    }


def _delete_from_cloudinary(public_id: str, resource_type: str | None) -> bool:
    try:
        import cloudinary
        import cloudinary.uploader
    except ImportError:
        return False

    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET,
    )

    candidates: list[str] = []
    seen: set[str] = set()
    for candidate in [resource_type, "raw", "image", "video"]:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        candidates.append(candidate)

    for candidate in candidates:
        try:
            result = cloudinary.uploader.destroy(public_id, resource_type=candidate)
            if result.get("result") in {"ok", "not found"}:
                return True
        except Exception:
            continue
    return False

    # small stuff first

@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "server": "memory-mcp",
    })


@mcp.custom_route("/sources", methods=["GET"])
async def sources_page(request: Request) -> HTMLResponse:
    # TODO: split this into static assets if the page grows again.
    return HTMLResponse(_load_template("sources.html"))


@mcp.custom_route("/api/sources/upload", methods=["POST"])
async def upload_source(request: Request) -> JSONResponse:
    api_key = _request_api_key(request)
    if not _api_key_ok(api_key):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    form = await request.form()
    context_raw = str(form.get("context_id", ""))
    uploads = list(form.getlist("files"))
    if not uploads:
        single_upload = form.get("file")
        if single_upload is not None:
            uploads = [single_upload]

    if not context_raw or not uploads:
        return JSONResponse({"error": "context_id and at least one file are required"}, status_code=400)

    context_id = _normalize_context_id(context_raw)
    indexed: list[dict] = []
    failed: list[dict] = []

    for upload in uploads:
        file_name = getattr(upload, "filename", "source.bin") or "source.bin"
        upload_size = getattr(upload, "size", None)
        temp_path: Path | None = None
        try:
            if isinstance(upload_size, int) and upload_size > MAX_UPLOAD_BYTES:
                failed.append({
                    "filename": file_name,
                    "error": f"File exceeds max size of {MAX_UPLOAD_BYTES} bytes",
                })
                continue

            file_bytes = await upload.read()
            if not file_bytes:
                failed.append({"filename": file_name, "error": "Uploaded file is empty"})
                continue
            if len(file_bytes) > MAX_UPLOAD_BYTES:
                failed.append({
                    "filename": file_name,
                    "error": f"File exceeds max size of {MAX_UPLOAD_BYTES} bytes",
                })
                continue

            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file_name).suffix) as tmp:
                tmp.write(file_bytes)
                temp_path = Path(tmp.name)

            cloud = _upload_to_cloudinary(file_bytes, file_name, context_id)
            extracted_text = _extract_text(temp_path)

            file_id = str(uuid.uuid4())
            chunk_meta = db.save_file_text_chunks(
                context_id,
                file_id,
                extracted_text,
                EXTRACTED_TEXT_CHUNK_SIZE,
            )
            record = {
                "file_id": file_id,
                "filename": file_name,
                "file_type": _infer_file_type(file_name),
                "cloudinary_public_id": cloud["public_id"],
                "cloudinary_url": cloud["url"],
                "cloudinary_resource_type": cloud["resource_type"],
                "extracted_text_preview": extracted_text[:1000],
                "extracted_text_chunk_count": chunk_meta["chunk_count"],
                "extracted_text_char_count": chunk_meta["char_count"],
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
            }
            db.save_file_index(context_id, record)
            indexed.append({"file_id": file_id, "filename": file_name})
        except Exception as exc:
            log.error("upload_source failed for %s: %s", file_name, exc)
            failed.append({"filename": file_name, "error": str(exc)})
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)

    if not indexed:
        return JSONResponse({"error": "All uploads failed", "failed": failed}, status_code=500)

    return JSONResponse({
        "status": "indexed",
        "context_id": context_id,
        "indexed": indexed,
        "failed": failed,
        "indexed_count": len(indexed),
        "failed_count": len(failed),
    })


@mcp.custom_route("/api/sources/{context_id}", methods=["GET"])
async def list_sources(request: Request) -> JSONResponse:
    api_key = _request_api_key(request)
    if not _api_key_ok(api_key):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    context_id = _normalize_context_id(request.path_params.get("context_id", ""))
    if not context_id:
        return JSONResponse({"error": "context_id is required"}, status_code=400)

    try:
        files = db.list_files(context_id)
        return JSONResponse({"files": files, "count": len(files), "context_id": context_id})
    except Exception as exc:
        log.error("list_sources failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@mcp.custom_route("/api/sources/{context_id}/{file_id}", methods=["DELETE"])
async def delete_source(request: Request) -> JSONResponse:
    api_key = _request_api_key(request)
    if not _api_key_ok(api_key):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    context_id = _normalize_context_id(request.path_params.get("context_id", ""))
    file_id = request.path_params.get("file_id", "").strip()
    if not context_id or not file_id:
        return JSONResponse({"error": "context_id and file_id are required"}, status_code=400)

    try:
        existing = db.get_file_content(context_id, file_id)
        if existing.get("status") == "not_found":
            return JSONResponse({"error": "Source not found"}, status_code=404)

        removed_remote = _delete_from_cloudinary(
            existing.get("cloudinary_public_id", ""),
            existing.get("cloudinary_resource_type"),
        )
        db.delete_file_index(context_id, file_id)
        return JSONResponse({
            "status": "deleted",
            "file_id": file_id,
            "filename": existing.get("filename", "unknown"),
            "cloudinary_deleted": removed_remote,
        })
    except Exception as exc:
        log.error("delete_source failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)

# MCP tools

@mcp.tool(
    description="Load a context by shortcut and return recent files and chats."
)
def switch_context(shortcut: str, ctx: Context) -> dict:
    if not _api_key_ok(_tool_api_key(ctx)):
        return {"error": "Unauthorized"}
    log.info("switch_context -> %s", shortcut)
    return db.switch_context(shortcut)


@mcp.tool(
    description="Create a new shortcut with a name and short description."
)
def register_context(shortcut: str, name: str, description: str, ctx: Context) -> dict:
    if not _api_key_ok(_tool_api_key(ctx)):
        return {"error": "Unauthorized"}
    if not shortcut or not name:
        return {"error": "shortcut and name are required"}
    log.info("register_context -> shortcut=%s name=%s", shortcut, name)
    return db.register_context(shortcut, name, description)


@mcp.tool(
    description="List the saved contexts and their shortcuts."
)
def list_contexts(ctx: Context) -> dict:
    if not _api_key_ok(_tool_api_key(ctx)):
        return {"error": "Unauthorized"}
    log.info("list_contexts called")
    contexts = db.list_contexts()
    return {"contexts": contexts, "count": len(contexts)}


# memory writes

@mcp.tool(
    description="Save a conversation for a context and build metadata for it."
)
def save_conversation(
    context_id: str,
    messages: list[dict],
    ctx: Context,
) -> dict:
    if not _api_key_ok(_tool_api_key(ctx)):
        return {"error": "Unauthorized"}
    if not context_id:
        return {"error": "context_id is required"}
    if not messages:
        return {"error": "messages list is required and must not be empty"}
    log.info("save_conversation -> context=%s messages=%d", context_id, len(messages))
    try:
        metadata = summariser.generate_metadata(messages)
        return db.save_conversation(context_id, messages, metadata)
    except Exception as exc:
        log.error("save_conversation failed: %s", exc)
        return {"error": str(exc)}


@mcp.tool(
    description="Fetch one conversation by ID, including messages."
)
def get_conversation(context_id: str, conv_id: str, ctx: Context) -> dict:
    if not _api_key_ok(_tool_api_key(ctx)):
        return {"error": "Unauthorized"}
    if not context_id or not conv_id:
        return {"error": "context_id and conv_id are required"}
    log.info("get_conversation -> context=%s conv=%s", context_id, conv_id)
    return db.get_conversation(context_id, conv_id)


@mcp.tool(
    description="Patch an existing conversation with messages, title, summary, or tags."
)
def update_conversation(
    context_id: str,
    conv_id: str,
    ctx: Context,
    append_messages: list[dict] | None = None,
    new_summary: str | None = None,
    new_tags: list[str] | None = None,
    new_title: str | None = None,
) -> dict:
    if not _api_key_ok(_tool_api_key(ctx)):
        return {"error": "Unauthorized"}
    if not context_id or not conv_id:
        return {"error": "context_id and conv_id are required"}
    log.info("update_conversation -> context=%s conv=%s", context_id, conv_id)
    try:
        return db.update_conversation(
            context_id, conv_id, append_messages, new_summary, new_tags, new_title
        )
    except Exception as exc:
        log.error("update_conversation failed: %s", exc)
        return {"error": str(exc)}


# search stuff

@mcp.tool(
    description="Search a context by keywords and return lightweight matches."
)
def search_conversations(
    context_id: str,
    keywords: list[str],
    ctx: Context,
    limit: int = 10,
) -> dict:
    if not _api_key_ok(_tool_api_key(ctx)):
        return {"error": "Unauthorized"}
    if not context_id or not keywords:
        return {"error": "context_id and keywords are required"}
    log.info("search_conversations -> context=%s keywords=%s", context_id, keywords)
    try:
        results = db.search_conversations(context_id, keywords, limit)
        return {"results": results, "count": len(results)}
    except Exception as exc:
        log.error("search_conversations failed: %s", exc)
        return {"error": str(exc)}


# file tools

@mcp.tool(
    description="List indexed files for a context."
)
def list_files(context_id: str, ctx: Context) -> dict:
    if not _api_key_ok(_tool_api_key(ctx)):
        return {"error": "Unauthorized"}
    if not context_id:
        return {"error": "context_id is required"}
    log.info("list_files -> context=%s", context_id)
    files = db.list_files(context_id)
    return {"files": files, "count": len(files)}


@mcp.tool(
    description="Fetch a file record plus its extracted text."
)
def get_file_content(context_id: str, file_id: str, ctx: Context) -> dict:
    if not _api_key_ok(_tool_api_key(ctx)):
        return {"error": "Unauthorized"}
    if not context_id or not file_id:
        return {"error": "context_id and file_id are required"}
    log.info("get_file_content -> context=%s file=%s", context_id, file_id)
    return db.get_file_content(context_id, file_id)


# boot it

if __name__ == "__main__":
    log.info("Starting Memory MCP server on port %s", PORT)
    mcp.run(transport="sse")

