"""Metadata helper for chat history."""

import json
import logging

from config import NVIDIA_API_KEY

log = logging.getLogger("memory-mcp.summariser")

_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
_MODEL = "google/gemma-3-27b-it"

_SYSTEM_PROMPT = """You are a conversation metadata extractor.
Given a list of chat messages, return ONLY a valid JSON object with exactly these fields:
  "title"   : a short (5-8 word) descriptive title for the conversation
  "summary" : a 2-3 sentence summary of what was discussed
  "tags"    : an array of 3-6 lowercase keyword strings

Return ONLY the JSON object — no markdown fences, no explanation, no extra text."""


def generate_metadata(messages: list[dict]) -> dict:
    """
    Call NVIDIA NIM (gemma-3-27b-it) to produce title, summary, and tags
    from a list of {role, content} message dicts.

    Falls back gracefully if NVIDIA_API_KEY is not configured.
    """
    if not NVIDIA_API_KEY:
        log.warning("NVIDIA_API_KEY not set — returning placeholder metadata")
        return {
            "title": "Untitled Conversation",
            "summary": "No summary available (NVIDIA_API_KEY not configured).",
            "tags": [],
        }

    try:
        from openai import OpenAI
    except ImportError:
        log.error("openai package not installed — run: pip install openai>=1.0.0")
        return {"title": "Untitled Conversation", "summary": "", "tags": []}

    client = OpenAI(base_url=_NVIDIA_BASE_URL, api_key=NVIDIA_API_KEY)

    convo_text = "\n".join(
        f"{m.get('role', 'unknown').upper()}: {m.get('content', '')}"
        for m in messages
    )

    try:
        response = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Extract metadata from this conversation:\n\n" + convo_text
                    ),
                },
            ],
            temperature=0.3,
            max_tokens=512,
        )
        raw = response.choices[0].message.content.strip()

        # model sometimes sends fenced JSON, just peel it off
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        result = json.loads(raw)
        return {
            "title": str(result.get("title", "Untitled")),
            "summary": str(result.get("summary", "")),
            "tags": [str(t).lower().strip() for t in result.get("tags", [])],
        }

    except json.JSONDecodeError as exc:
        log.error("Failed to parse NVIDIA response as JSON: %s", exc)
        return {
            "title": "Untitled Conversation",
            "summary": "Summary generation failed (JSON parse error).",
            "tags": [],
        }
    except Exception as exc:
        log.error("NVIDIA NIM call failed: %s", exc)
        return {
            "title": "Untitled Conversation",
            "summary": f"Summary generation failed: {exc}",
            "tags": [],
        }
