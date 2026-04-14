---
name: memory-mcp
description: >
  Persistent, project-scoped memory organized by slash-command shortcuts 
  (e.g. /OS, /React, /Firebase). Works with Claude, ChatGPT, and any MCP-compatible 
  chatbot. Each shortcut is an isolated context with its own conversation history, 
  keyword search, and file index. The MCP server is hosted on Render and securely 
  exposed for remote client access. It is backed by Firebase Firestore.
---

# Setup: Connecting to Different Chatbots

## Prerequisites
- Your Render deployment URL (e.g., `https://memory-mcp.onrender.com`)
- Your `MEMORY_API_KEY` from Render environment variables

## Claude (Anthropic)

1. **In Claude.ai Dashboard**:
   - Click **Files** (left sidebar)
   - Select **MCP Servers**
   - Click **Add Server**
   - Enter:
     - **Name**: `Memory MCP`
     - **URL**: Your Render deployment URL (e.g., `https://memory-mcp.onrender.com`)
     - **API Key**: Your `MEMORY_API_KEY`

2. **Test in Claude**:
   ```
   /OS what are operating systems?
   ```
   Should reply: "**/OS** context loaded — 0 past sessions · 0 files"

## ChatGPT (OpenAI)

1. **Ensure you have ChatGPT Plus or Pro** (MCP support)
2. **In ChatGPT Settings**:
   - Click **Settings & Tools** → **MCP Servers**
   - Click **Add Server**
   - Enter the same credentials as Claude
3. **Test in ChatGPT**:
   ```
   /React explain hooks
   ```

## Other MCP-Compatible Clients

Configure similarly:
- **Server URL**: `https://memory-mcp.onrender.com` (or your custom domain)
- **API Key**: `MEMORY_API_KEY`
- **Protocol**: Model Context Protocol (MCP)

---

# Memory MCP — Behaviour Guide (Phases 1–5)

## Authentication

Authenticate requests via MCP metadata:

```
_meta: { api_key: "<Your MEMORY_API_KEY>" }
```

Never omit it. If a tool returns `{"error": "Unauthorized"}`, the key is wrong or missing.

---

## Available Tools

| Tool | Phase | Purpose |
|---|---|---|
| `switch_context` | 1 | Load a context by shortcut |
| `register_context` | 1 | Create a new context |
| `list_contexts` | 1 | List all registered shortcuts |
| `save_conversation` | 2 | Persist a completed conversation |
| `get_conversation` | 2 | Fetch a specific past conversation |
| `update_conversation` | 2 | Append messages to an existing record |
| `search_conversations` | 3 | Keyword search across past sessions |
| `list_files` | 4 | List indexed files for a context |
| `get_file_content` | 4 | Read a file's extracted text |

---

## Phase 1 — Context Switching

### Trigger
Any message where the **first word** starts with `/` followed by a single word (case-insensitive).

```
/OS explain virtual memory          → shortcut = "/OS"
/react what are hooks               → shortcut = "/react"
/DB                                 → shortcut = "/DB"   (no question — just switch)
```

Tool calls must not pass `api_key` as a tool argument.

Use MCP request metadata instead:

```
_meta: { api_key: "<Your MEMORY_API_KEY>" }
```

If a tool returns `{"error": "Unauthorized"}`, the metadata key is missing or wrong.

---

## Available Tools

| Tool | Phase | Purpose |
|---|---|---|
| `switch_context` | 1 | Load a context by shortcut |
| `register_context` | 1 | Create a new context |
| `list_contexts` | 1 | List all registered shortcuts |
| `save_conversation` | 2 | Persist a completed conversation |
| `get_conversation` | 2 | Fetch a specific past conversation |
| `update_conversation` | 2 | Append messages to an existing record |
| `search_conversations` | 3 | Keyword search across past sessions |
| `list_files` | 4 | List indexed files for a context |
| `get_file_content` | 4 | Read a file's extracted text |

---

## Phase 1 — Context Switching

### Trigger
Any message where the **first word** starts with `/` followed by a single word (case-insensitive).

```
/OS explain virtual memory          → shortcut = "/OS"
/react what are hooks               → shortcut = "/react"
/DB                                 → shortcut = "/DB"   (no question — just switch)
```

### Action — always do this first, before anything else

```
switch_context(shortcut="<extracted shortcut>")
```

### On `status: loaded` — respond with this template

> **{name}** context loaded — {N} past sessions · {M} files

Then show recent conversation titles as a bullet list (if `recent_conversations` is not empty):
- Past sessions are in `recent_conversations[]` — show `title` and `updated_at`
- Files are in `files[]` — show `filename` and `file_type`

Then answer the user's actual question.

### On `status: not_found`

Ask: *"No context found for **{shortcut}**. Want me to create it?"*

If the user says yes:
1. Ask for a **name** (human-readable label) and a **description** (one sentence).
2. Call `register_context(shortcut, name, description)`.
3. Confirm: *"Created **{name}** as **{shortcut}**. You can now save conversations to it."*

### List all contexts

If the user asks *"what contexts do I have"* or *"show my shortcuts"*:

```
list_contexts()
```

Present results as a markdown table: Shortcut | Name | Description | Created.

---

## Phase 2 — Saving Conversations

### When to save
Call `save_conversation` once when the user says **"done"**, **"bye"**, **"save"**, **"end session"**, or similar.

```
save_conversation(
    context_id = "<current context_id>",
  messages   = [<entire {role, content} history for this context>]
)
```

- `context_id` is the **slug** (e.g. `"os"`, `"react"`), **not** the shortcut.
- `messages` must include **every** message since the context was loaded — both user and assistant turns.
- The server calls NVIDIA NIM (gemma-3-27b-it) to auto-generate `title`, `summary`, and `tags`.

**Confirm to the user:**
> Saved to **/OS** — *"{returned title}"*

### When to update instead of save
If you loaded a conversation via `get_conversation` earlier in the session, use `update_conversation` to append only the **new** messages:

```
update_conversation(
    context_id      = "...",
    conv_id         = "<conv_id from get_conversation>",
  append_messages = [<only the new messages>]
)
```

You may also pass `new_summary`, `new_tags`, or `new_title` to overwrite those fields.

### Retrieve a specific conversation
If the user says *"show me that session"* or references a past `conv_id`:

```
get_conversation(context_id="...", conv_id="<uuid>")
```

The returned `messages` array contains the full transcript.

---

## Phase 3 — Searching Past Sessions

### When to search
- Proactively, right after `switch_context`, if the user's question mentions a topic that may have been discussed before.
- Explicitly, when the user asks *"did we talk about X?"*, *"find my notes on Y"*, etc.

```
search_conversations(
    context_id = "...",
    keywords   = ["keyword1", "keyword2", "keyword3"],
    limit      = 10        # optional, default 10
)
```

- Keywords are matched against **tags** first (Firestore index), then fall back to **summary substring**.
- Pass 2–4 concise, lowercase keywords extracted from the user's question.

### Presenting results
If `count > 0`:
> Found **{count}** related session(s):
> - **{title}** ({updated_at}) — {summary}

Then answer the user's question, citing relevant sessions where helpful.

If `count == 0`:
> No past sessions found for those keywords. Answering from scratch…

---

## Phase 4 — File Indexing

### How files get indexed (outside Claude)
Files are indexed via the CLI tool — the user runs this in their terminal:

```bash
python index_file.py --context <shortcut> --file path/to/file.pdf
```

This uploads to Cloudinary and writes extracted text to Firestore. Claude does **not** call this tool — it is offline.

Supported types:
| Extension | Behaviour |
|---|---|
| `.pdf` | Text extracted with pdfminer.six |
| `.txt`, `.md`, `.py`, `.js`, `.ts`, `.json`, `.yaml`, `.csv`, `.sql`, `.html`, `.css`, `.sh`, `.ps1`, `.env`, `.log`, `.toml`, `.xml`, … | Read as UTF-8 |
| Images (`.jpg`, `.png`, `.gif`, `.webp`, …) | URL stored; no text extraction |

### After switch_context
If `files[]` is not empty, list them briefly:

> **{N} file(s) indexed in this context:**
> - `{filename}` ({file_type}) — uploaded {uploaded_at}

### When users ask about a file
If the user says *"what's in the PDF"*, *"summarise notes.md"*, *"read architecture.pdf"*:

1. Identify the correct `file_id` from the `files[]` list.
2. Call:
   ```
  get_file_content(context_id="...", file_id="<uuid>")
   ```
3. Use `extracted_text` to answer. If it's empty (image), tell the user text wasn't extracted and offer the `cloudinary_url`.

To list files manually:
```
list_files(context_id="...")
```

---

## Phase 5 — Hardening Behaviours

### Error handling
Every tool can return `{"error": "<message>"}`. When this happens:
- Surface the error message to the user clearly.
- Do **not** retry silently more than once.
- If `Unauthorized`, remind the user to resend `_meta.api_key` with the correct `MEMORY_API_KEY` value.

### Health check
The server exposes `GET http://localhost:8000/health`.
If tools are consistently failing, ask the user to check that the server is running:

```bash
# Start the server
cd "e:\Projects\Claude MAX"
.venv\Scripts\python.exe server.py
```

Expected response from /health:
```json
{"status": "ok", "timestamp": "...", "server": "memory-mcp"}
```

---

## Decision Flowchart (Quick Reference)

```
User message received
│
├─ Starts with /WORD?
│    ├─ YES → switch_context() immediately
│    │          ├─ loaded   → show header, recent sessions, files, then answer
│    │          └─ not_found → offer to register_context()
│    └─ NO  → continue normally
│
├─ Mentions past topic / "did we discuss"?
│    └─ search_conversations() → surface results → answer
│
├─ Asks about a file by name?
│    └─ get_file_content() → use extracted_text → answer
│
├─ Asks "what contexts do I have"?
│    └─ list_contexts() → show as table
│
└─ Says "done" / "bye" / "save"?
     ├─ New session  → save_conversation()    → confirm with title
     └─ Continuation → update_conversation()  → confirm updated
```

---

## Firestore Data Model (for reference)

```
contexts/
  {context_id}/                        ← e.g. "os", "react"
    shortcut: "/OS"
    name: "Operating Systems"
    description: "..."
    cloudinary_folder: "memory/os"

    conversations/
      {uuid}/
        conv_id, title, summary, tags[], messages[], created_at, updated_at

    file_index/
      {uuid}/
        file_id, filename, file_type, cloudinary_url, extracted_text, uploaded_at
```
