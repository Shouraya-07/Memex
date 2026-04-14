"""Simple CLI to upload+index one file into a context."""

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# loading env here to keep this script standalone
from dotenv import load_dotenv
load_dotenv()

from config import (
    CLOUDINARY_CLOUD_NAME,
    CLOUDINARY_API_KEY,
    CLOUDINARY_API_SECRET,
)
import firebase_client as db

# extensions i care about right now
_IMAGE_EXTS   = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".svg"}
_PDF_EXTS     = {".pdf"}
_TEXT_EXTS    = {
    ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".html", ".css", ".json", ".yaml", ".yml", ".toml",
    ".sh", ".bat", ".ps1", ".sql", ".csv", ".xml", ".ini",
    ".env", ".cfg", ".conf", ".log",
}

def _upload_to_cloudinary(file_path: Path, context_id: str) -> dict:
    """Upload a file and return ids."""
    try:
        import cloudinary
        import cloudinary.uploader
    except ImportError:
        print("ERROR: cloudinary package not installed. Run: pip install cloudinary>=1.36.0")
        sys.exit(1)

    if not all([CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET]):
        print("ERROR: Cloudinary credentials missing. Set CLOUDINARY_CLOUD_NAME, "
              "CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET in .env")
        sys.exit(1)

    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET,
    )

    folder = f"memory/{context_id}"
    result = cloudinary.uploader.upload(
        str(file_path),
        folder=folder,
        resource_type="auto",
        use_filename=True,
        unique_filename=True,
    )
    return {
        "public_id": result["public_id"],
        "url":       result["secure_url"],
    }


def _extract_text(file_path: Path) -> str:
    """Extract text from a file based on its extension."""
    ext = file_path.suffix.lower()

    if ext in _IMAGE_EXTS:
        return ""  # Images: URL stored only

    if ext in _PDF_EXTS:
        try:
            from pdfminer.high_level import extract_text as pdf_extract
            return pdf_extract(str(file_path)) or ""
        except ImportError:
            print("WARNING: pdfminer.six not installed. Run: pip install pdfminer.six>=20221105")
            return ""
        except Exception as exc:
            print(f"WARNING: PDF text extraction failed: {exc}")
            return ""

    # Text / code files
    try:
        return file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return file_path.read_text(encoding="latin-1")
        except Exception:
            return ""
    except Exception as exc:
        print(f"WARNING: Could not read file: {exc}")
        return ""


def _infer_file_type(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    if ext in _IMAGE_EXTS:   return "image"
    if ext in _PDF_EXTS:     return "pdf"
    if ext in _TEXT_EXTS:    return "text"
    return "binary"


def index_file(context_id: str, file_path_str: str) -> None:
    file_path = Path(file_path_str).resolve()

    if not file_path.exists():
        print(f"ERROR: File not found: {file_path}")
        sys.exit(1)

    print(f"Indexing '{file_path.name}' into context '{context_id}' …")

    # upload first
    print("  → Uploading to Cloudinary …")
    cloud = _upload_to_cloudinary(file_path, context_id)
    print(f"  ✓ Uploaded: {cloud['url']}")

    # then extract text
    print("  → Extracting text …")
    extracted_text = _extract_text(file_path)
    char_count = len(extracted_text)
    print(f"  ✓ Extracted {char_count:,} characters")

    # TODO: Firestore doc limit is 1MB, large PDFs can fail here if text is huge.
    # this CLI still stores extracted text in one doc unlike the server chunk path.
    file_id   = str(uuid.uuid4())
    file_doc  = {
        "file_id":              file_id,
        "filename":             file_path.name,
        "file_type":            _infer_file_type(file_path),
        "cloudinary_public_id": cloud["public_id"],
        "cloudinary_url":       cloud["url"],
        "extracted_text":       extracted_text,
        "uploaded_at":          datetime.now(timezone.utc).isoformat(),
    }
    print("  → Writing to Firestore …")
    result = db.save_file_index(context_id, file_doc)
    print(f"  ✓ Indexed: file_id={result['file_id']}")

    print(f"\n✅ Done. '{file_path.name}' is now searchable in /{context_id.upper()}")


def main():
    parser = argparse.ArgumentParser(
        description="Upload and index a file into a Memory MCP context."
    )
    parser.add_argument(
        "--context", "-c",
        required=True,
        help="Context shortcut, e.g. 'os' or '/OS'",
    )
    parser.add_argument(
        "--file", "-f",
        required=True,
        help="Path to the file to index",
    )
    args = parser.parse_args()

    # Normalise context: strip leading slash, lowercase
    context_id = args.context.lstrip("/").lower().strip()
    index_file(context_id, args.file)


if __name__ == "__main__":
    main()
