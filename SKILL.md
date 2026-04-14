---
name: memory-mcp
description: >
  Persistent memory for slash-command shortcuts like /OS and /React.
---

# Memory MCP Guide

## Setup

- Render deployment URL, for example `https://memory-mcp.onrender.com`
- `MEMORY_API_KEY` from the deployment environment

## Client Setup

### Claude

1. Open **Files** in the left sidebar.
2. Go to **MCP Servers** and add a server.
3. Use `Memory MCP` as the name, the Render URL as the server URL, and your `MEMORY_API_KEY`.

Test it with:

```text
/OS what are operating systems?
```

### ChatGPT

Add the same server details in **Settings & Tools** -> **MCP Servers**.

### Other MCP Clients

- Server URL: `https://memory-mcp.onrender.com` or your custom domain
- API key: `MEMORY_API_KEY`
- Protocol: MCP

## Behaviour Notes

Read auth from MCP metadata:

```text
_meta: { api_key: "<Your MEMORY_API_KEY>" }
```

If a tool returns `{"error": "Unauthorized"}`, the key is missing or wrong.

If the first word starts with `/`, use `switch_context`.

For `status: loaded`, show the context name, recent sessions, and files before answering.

For `status: not_found`, ask whether the user wants the context created.

For `list_contexts`, show a simple table with shortcut, name, description, and created date.

Use `save_conversation` when the user is done, leaving, or asks to save the session.

Use `update_conversation` when continuing a loaded conversation and only new messages need to be appended.

Use `get_conversation` when the user wants a specific stored session.

Use `search_conversations` for keyword lookups in a context. It checks tags first, then falls back to summary text.

Files are indexed by the CLI tool, not by the chatbot:

```bash
python index_file.py --context <shortcut> --file path/to/file.pdf
```

Supported types:
- `.pdf`
- `.txt`, `.md`, `.py`, `.js`, `.ts`, `.json`, `.yaml`, `.csv`, `.sql`, `.html`, `.css`, `.sh`, `.ps1`, `.env`, `.log`, `.toml`, `.xml`
- images like `.jpg`, `.png`, `.gif`, `.webp`

After `switch_context`, show indexed files briefly if any exist.

When the user asks about a file, call `get_file_content` and answer from `extracted_text`.

If a tool returns an error, surface it once and stop there unless the user asks again.

The server exposes `GET /health` and should return `{"status": "ok"}`.

## Tool Reference

| Tool | Purpose |
|---|---|
| `switch_context` | Load a context by shortcut |
| `register_context` | Create a new context |
| `list_contexts` | List all registered shortcuts |
| `save_conversation` | Persist a completed conversation |
| `get_conversation` | Fetch a specific past conversation |
| `update_conversation` | Append messages to an existing record |
| `search_conversations` | Keyword search across past sessions |
| `list_files` | List indexed files for a context |
| `get_file_content` | Read a file's extracted text |