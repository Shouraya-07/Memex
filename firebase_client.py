"""Tiny Firestore wrapper for this project."""

import uuid
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import credentials, firestore

from config import FIREBASE_KEY

DEFAULT_TEXT_CHUNK_SIZE = 8000

# firebase bootstrapping (good enough for now)

def _init():
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(FIREBASE_KEY))
    return firestore.client()

db = _init()

# little helpers

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ctx_ref(context_id: str):
    return db.collection("contexts").document(context_id)

def _normalize_shortcut(shortcut: str) -> str:
    # handles /OS and OS and random spacing
    return shortcut.lstrip("/").lower().strip()

# context stuff

def register_context(shortcut: str, name: str, description: str) -> dict:
    # storing uppercase shortcut but lowercase doc id keeps query logic simple
    context_id = _normalize_shortcut(shortcut)
    ref = _ctx_ref(context_id)

    if ref.get().exists:
        return {
            "status": "already_exists",
            "context_id": context_id,
            "message": f"Context '{shortcut}' already exists. Use switch_context to load it.",
        }

    doc = {
        "context_id":        context_id,
        "shortcut":          f"/{context_id.upper()}",
        "name":              name,
        "description":       description,
        "cloudinary_folder": f"memory/{context_id}",
        "created_at":        _now(),
    }
    ref.set(doc)
    return {"status": "created", "context_id": context_id, "shortcut": doc["shortcut"]}


def list_contexts() -> list[dict]:
    """List all contexts."""
    docs = db.collection("contexts").stream()
    return [
        {
            "shortcut":    d.get("shortcut"),
            "name":        d.get("name"),
            "description": d.get("description"),
            "created_at":  d.get("created_at"),
        }
        for d in (snap.to_dict() for snap in docs)
        if d.get("shortcut")
    ]


def switch_context(shortcut: str) -> dict:
    """Load context + recent sessions + files."""
    context_id = _normalize_shortcut(shortcut)
    snap = _ctx_ref(context_id).get()

    if not snap.exists:
        return {
            "status":  "not_found",
            "message": (
                f"No context found for '{shortcut}'. "
                f"Create it first with register_context."
            ),
        }

    meta = snap.to_dict()

    # quick snapshot of recent chats
    conv_snaps = (
        _ctx_ref(context_id)
        .collection("conversations")
        .order_by("updated_at", direction=firestore.Query.DESCENDING)
        .limit(5)
        .stream()
    )
    recent_conversations = [
        {
            "conv_id":    c.get("conv_id"),
            "title":      c.get("title"),
            "summary":    c.get("summary"),
            "tags":       c.get("tags", []),
            "updated_at": c.get("updated_at"),
        }
        for c in (s.to_dict() for s in conv_snaps)
        if c.get("conv_id")
    ]

    # and file list for context switch UX
    file_snaps = (
        _ctx_ref(context_id)
        .collection("file_index")
        .order_by("uploaded_at", direction=firestore.Query.DESCENDING)
        .stream()
    )
    files = [
        {
            "file_id":   f.get("file_id"),
            "filename":  f.get("filename"),
            "file_type": f.get("file_type"),
            "url":       f.get("cloudinary_url"),
        }
        for f in (s.to_dict() for s in file_snaps)
        if f.get("file_id")
    ]

    return {
        "status":               "loaded",
        "context_id":           context_id,
        "shortcut":             meta.get("shortcut"),
        "name":                 meta.get("name"),
        "description":          meta.get("description"),
        "cloudinary_folder":    meta.get("cloudinary_folder"),
        "recent_conversations": recent_conversations,
        "files":                files,
    }


# conversation saves/updates

def save_conversation(
    context_id: str, messages: list[dict], metadata: dict
) -> dict:
    # yes this writes the whole message list every time
    context_id = _normalize_shortcut(context_id)
    conv_id = str(uuid.uuid4())
    now = _now()
    doc = {
        "conv_id":    conv_id,
        "context_id": context_id,
        "title":      metadata.get("title", "Untitled"),
        "summary":    metadata.get("summary", ""),
        "tags":       metadata.get("tags", []),
        "messages":   messages,
        "created_at": now,
        "updated_at": now,
    }
    _ctx_ref(context_id).collection("conversations").document(conv_id).set(doc)
    return {
        "status":  "saved",
        "conv_id": conv_id,
        "title":   doc["title"],
        "summary": doc["summary"],
        "tags":    doc["tags"],
    }


def get_conversation(context_id: str, conv_id: str) -> dict:
    """Fetch a full conversation document including messages."""
    context_id = _normalize_shortcut(context_id)
    snap = (
        _ctx_ref(context_id)
        .collection("conversations")
        .document(conv_id)
        .get()
    )
    if not snap.exists:
        return {"status": "not_found", "conv_id": conv_id}
    return snap.to_dict()


def update_conversation(
    context_id: str,
    conv_id: str,
    append_messages: list[dict] | None = None,
    new_summary: str | None = None,
    new_tags: list[str] | None = None,
    new_title: str | None = None,
) -> dict:
    """Patch existing conversation."""
    context_id = _normalize_shortcut(context_id)
    ref = _ctx_ref(context_id).collection("conversations").document(conv_id)
    snap = ref.get()
    if not snap.exists:
        return {"status": "not_found", "conv_id": conv_id}

    updates: dict = {"updated_at": _now()}
    if append_messages:
        existing = snap.to_dict().get("messages", [])
        updates["messages"] = existing + append_messages
    if new_summary is not None:
        updates["summary"] = new_summary
    if new_tags is not None:
        updates["tags"] = new_tags
    if new_title is not None:
        updates["title"] = new_title

    ref.update(updates)
    return {"status": "updated", "conv_id": conv_id}


# searching old sessions

def search_conversations(
    context_id: str, keywords: list[str], limit: int = 10
) -> list[dict]:
    """
    Search conversations for a context by keywords.

    Strategy:
      1. Firestore array-contains-any on the tags field (up to 10 keywords)
      2. Client-side substring filter on summary as a fallback
    Returns lightweight dicts (no messages).
    """
    context_id = _normalize_shortcut(context_id)

    # Firestore hard-limits this query to max 10 values
    search_tags = [k.lower().strip() for k in keywords[:10]]

    try:
        snaps = (
            _ctx_ref(context_id)
            .collection("conversations")
            .where("tags", "array_contains_any", search_tags)
            .order_by("updated_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        results = [
            {
                "conv_id":    s.get("conv_id"),
                "title":      s.get("title"),
                "summary":    s.get("summary"),
                "tags":       s.get("tags", []),
                "updated_at": s.get("updated_at"),
            }
            for s in (snap.to_dict() for snap in snaps)
            if s.get("conv_id")
        ]
    except Exception:
        results = []

    # Fallback: substring search on summary if tag search returned nothing
    if not results:
        all_snaps = (
            _ctx_ref(context_id)
            .collection("conversations")
            .order_by("updated_at", direction=firestore.Query.DESCENDING)
            .stream()
        )
        needle = " ".join(keywords).lower()
        results = [
            {
                "conv_id":    s.get("conv_id"),
                "title":      s.get("title"),
                "summary":    s.get("summary"),
                "tags":       s.get("tags", []),
                "updated_at": s.get("updated_at"),
            }
            for s in (snap.to_dict() for snap in all_snaps)
            if s.get("conv_id") and needle in (s.get("summary", "") + " " + s.get("title", "")).lower()
        ][:limit]

    return results


# file index bits

def save_file_index(context_id: str, file_doc: dict) -> dict:
    """Write a file index entry to contexts/{id}/file_index/{file_id}."""
    context_id = _normalize_shortcut(context_id)
    file_id = file_doc["file_id"]
    _ctx_ref(context_id).collection("file_index").document(file_id).set(file_doc)
    return {"status": "indexed", "file_id": file_id}


def save_file_text_chunks(
    context_id: str,
    file_id: str,
    extracted_text: str,
    chunk_size: int = DEFAULT_TEXT_CHUNK_SIZE,
) -> dict:
    """Store extracted text in chunk docs."""
    context_id = _normalize_shortcut(context_id)
    if not extracted_text:
        return {"chunk_count": 0, "char_count": 0}

    chunk_size = max(512, int(chunk_size))
    chunks = [
        extracted_text[i : i + chunk_size]
        for i in range(0, len(extracted_text), chunk_size)
    ]

    chunk_ref = (
        _ctx_ref(context_id)
        .collection("file_index")
        .document(file_id)
        .collection("text_chunks")
    )

    # Firestore batch max is 500 ops; leaving some breathing room.
    for start in range(0, len(chunks), 400):
        batch = db.batch()
        for idx, text_chunk in enumerate(chunks[start : start + 400], start=start):
            doc_ref = chunk_ref.document(f"{idx:06d}")
            batch.set(doc_ref, {"index": idx, "text": text_chunk})
        batch.commit()

    return {"chunk_count": len(chunks), "char_count": len(extracted_text)}


def get_file_text_chunks(context_id: str, file_id: str) -> str:
    # name says chunks but this also stitches into one giant string
    context_id = _normalize_shortcut(context_id)
    snaps = (
        _ctx_ref(context_id)
        .collection("file_index")
        .document(file_id)
        .collection("text_chunks")
        .order_by("index", direction=firestore.Query.ASCENDING)
        .stream()
    )
    return "".join((s.to_dict() or {}).get("text", "") for s in snaps)


def list_files(context_id: str) -> list[dict]:
    """Return file index metadata (no extracted_text)."""
    context_id = _normalize_shortcut(context_id)
    snaps = (
        _ctx_ref(context_id)
        .collection("file_index")
        .order_by("uploaded_at", direction=firestore.Query.DESCENDING)
        .stream()
    )
    return [
        {
            "file_id":             f.get("file_id"),
            "filename":            f.get("filename"),
            "file_type":           f.get("file_type"),
            "cloudinary_url":      f.get("cloudinary_url"),
            "uploaded_at":         f.get("uploaded_at"),
        }
        for f in (snap.to_dict() for snap in snaps)
        if f.get("file_id")
    ]


def get_file_content(context_id: str, file_id: str) -> dict:
    """Return full file content."""
    context_id = _normalize_shortcut(context_id)
    snap = _ctx_ref(context_id).collection("file_index").document(file_id).get()
    if not snap.exists:
        return {"status": "not_found", "file_id": file_id}
    doc = snap.to_dict()
    extracted_text = get_file_text_chunks(context_id, file_id)
    return {
        "file_id": doc.get("file_id"),
        "filename": doc.get("filename"),
        "file_type": doc.get("file_type"),
        "cloudinary_public_id": doc.get("cloudinary_public_id"),
        "cloudinary_resource_type": doc.get("cloudinary_resource_type"),
        "cloudinary_url": doc.get("cloudinary_url"),
        "extracted_text": extracted_text,
        "extracted_text_chunk_count": doc.get("extracted_text_chunk_count", 0),
        "extracted_text_char_count": doc.get("extracted_text_char_count", 0),
        "uploaded_at": doc.get("uploaded_at"),
    }


def delete_file_index(context_id: str, file_id: str) -> dict:
    """Delete a file index entry from contexts/{id}/file_index/{file_id}."""
    context_id = _normalize_shortcut(context_id)
    ref = _ctx_ref(context_id).collection("file_index").document(file_id)
    if not ref.get().exists:
        return {"status": "not_found", "file_id": file_id}
    ref.delete()
    return {"status": "deleted", "file_id": file_id}
