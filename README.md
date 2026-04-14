# Memex

Small MCP memory server for keeping contexts, chats, and uploaded sources together.

## Setup

1. Create a virtual environment and install dependencies.
   ```bash
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and fill in:
   - `MEMORY_API_KEY`
   - `FIREBASE_SERVICE_ACCOUNT_KEY`
   - Cloudinary keys if you want uploads
3. Run:
   ```bash
   python server.py
   ```

## Render

Build command: `pip install -r requirements.txt`

Start command: `uvicorn server:mcp --host 0.0.0.0 --port $PORT`

## Services

Firebase stores the contexts, conversations, and file index. Cloudinary handles uploads for the source manager.

## Notes

- API auth uses `MEMORY_API_KEY`.
- Tool auth reads from MCP metadata (`_meta.api_key`).
- HTTP routes under `/sources` use `x-api-key`.

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
