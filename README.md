# Memex

I built this because I was tired of losing context between Claude sessions.

It is a small MCP memory server that lets me:
- switch contexts with shortcuts like `/os` and `/react`
- save and search old conversation threads
- upload docs/PDFs as context files

It works with Claude, ChatGPT, and other MCP clients.

## Quick Start

1. Clone the repo and make a virtual env.
2. Install deps:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and set at least:
   - `MEMORY_API_KEY`
   - `FIREBASE_SERVICE_ACCOUNT_KEY`
   - Cloudinary keys if you want file uploads
4. Run:
   ```bash
   python server.py
   ```
5. Open:
   - `http://localhost:8000/health`
   - `http://localhost:8000/sources`

## Deploy

I deploy this on Render with:
- build command: `pip install -r requirements.txt`
- start command: `uvicorn server:mcp --host 0.0.0.0 --port $PORT`

## Notes

- API auth uses `MEMORY_API_KEY`.
- Tool auth reads from MCP metadata (`_meta.api_key`).
- For HTTP routes (`/sources`, upload/list/delete), send `x-api-key`.

## Tools

- `switch_context`
- `register_context`
- `list_contexts`
- `save_conversation`
- `get_conversation`
- `update_conversation`
- `search_conversations`
- `list_files`
- `get_file_content`
