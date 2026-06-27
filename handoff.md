# Herald MCP — Handoff Notes

## Session 2026-06-28 — Shell Allowlist, Tray UI, Token-Burn Fix, ask_peer

### What was done

**1. Allowlist externalized to `allowlist.json`**
Shell command allowlist moved from hardcoded Python to `allowlist.json` in the repo root.
Supports `{"type": "prefix", "value": "..."}` and `{"type": "regex", "value": "..."}` rules.
Both `herald_tray.py` (April's runtime) and `shell_agent.py` (legacy, not started at boot) read from it.

**2. shell_agent merged into herald_tray**
Root cause of duplicate-subscriber bug: `run_shell_agent.vbs` at startup created a second SSE
subscriber for April. Relay uses work-queue delivery (each message goes to exactly ONE subscriber),
so shell commands and chat messages were racing to the wrong handler.

Fix: shell_agent logic folded into `herald_tray.py`'s SSE thread. The VBS startup shortcut was
deleted. Only `herald_tray.lnk` remains in `C:\Users\HP\AppData\Roaming\Microsoft\Windows\Start
Menu\Programs\Startup\` — this starts herald_tray.py (which now handles both shell and chat).

Shell commands never trigger `claude.exe`. Chat messages still trigger `invoke_claude_reply`.

**3. ask_peer timeout — final approach**
- Relay is work-queue, NOT pub-sub: message is held while `/ask` connection is open
- Fire-and-forget (short connection) causes relay to clear the message before claude reads it
- MCP framework kills tool calls at roughly 60–120s (exact value unknown; caused `-32001` at 305s)
- **Current approach:** 50s blocking httpx timeout in `mcp_server.py`'s `ask_peer`
- This keeps the relay connection alive long enough for April's claude to respond (~30–45s)
- If it times out, returns `{"status": "timeout", "message_id": ...}` — caller can `get_pending`

**4. REPLY_PROMPT must use `reply`, not `ask_peer`**
Critical lesson: if April's claude is told to respond via `ask_peer("cc", ...)`, it opens a NEW
blocking `/ask` to the relay waiting for cc to reply — deadlock. The correct tool is
`reply(message_id, answer)` which delivers directly into cc's waiting `/ask` connection.

```python
REPLY_PROMPT = (
    "Use herald MCP tools. Call get_pending to retrieve incoming messages. "
    "For each message, call reply(message_id=<id>, answer=<your response>). "
    "When done, exit."
)
ALLOWED_TOOLS = "mcp__herald__get_pending,mcp__herald__reply"
```

**5. Per-message try/except in SSE loop**
Any unhandled exception in the SSE message-processing loop kills the entire SSE connection.
Wrapped per-message code in `try/except Exception: pass` so individual bad messages don't crash
the stream.

**6. herald_comm.log**
`mcp_server.py` on cc's side writes JSON-lines to `herald_comm.log` (same directory).
Herald tray tails this file every 300ms for the Comm Log tab in the UI.
Format: `{"ts": "HH:MM:SS", "dir": "out|in", "tool": "exec_shell|ask_peer", "peer": "...", ...}`

**7. Tray UI (herald_tray.py)**
Window: 720×520, resizable. Three tabs:
- **Messages** — incoming chat messages, auto-reply button
- **Comm Log** — tails `herald_comm.log`, color-coded by direction
- **Remote Tasks** — fires exec_shell to get peer's tasklist on demand

### Key architecture facts

- Relay: `http://202.59.9.164:7700` — VPS, always-on
- Relay delivery model: **work-queue** (one subscriber gets the message; no broadcast)
- SSE subscriber: `herald_tray.py` subscribes as the local peer name on startup
- shell_agent.py: still in repo but not started at boot; functionality lives in herald_tray.py
- April's startup: only `herald_tray.lnk` in Startup folder
- April's Python: `C:\Users\HP\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe`
- Herald on April: `C:\AI\Herald_MCP\`

### Verified working (end of session)

- `exec_shell("April", "Get-Date")` → returns stdout in < 3s
- `ask_peer("April", "你好 April...")` → April's claude replied within 50s
- No duplicate SSE subscribers; run_shell_agent.vbs removed
- Shell commands do NOT trigger claude.exe (no token burn)

### Remaining / future work

- Tray UI comm log and remote tasks tabs: basic implementation in, not heavily tested
- UUID-based peer naming (see below) — avoids rename-breaks-routing issue
- ask_peer still occasionally times out if claude is slow to start; no retry logic yet
- herald_tray UI styling is minimal; no message history persistence

---

## Potential Upgrade: Auto-Sync Peer Names Across Machines

**Problem:** When a machine renames itself (via the tray UI or by editing `config.json`),
all other machines still have the old name in their local `peers` list. There is no
automatic sync — each peer must manually update their config.

**Research date:** 2026-06-26

### Three Approaches (from distributed systems / service mesh patterns)

#### 1. UUID Indirection (Recommended by Gemi)
Assign each machine a permanent UUID at setup time. The `name` field becomes a display
label only. The `peers` list stores UUIDs, not names. On rename, the machine broadcasts
a `{uuid, old_name, new_name}` message; peers update their local label mapping without
touching the peers list.

- **Reliability:** Highest — rename never breaks routing
- **Complexity:** Low once migrated; requires a one-time UUID assignment for existing machines
- **Herald fit:** Best long-term solution; industry standard

#### 2. Broadcast / Gossip
On rename, broadcast `{old_name, new_name, timestamp}` to the relay server. Online peers
receive it and patch their local `config.json` automatically. Peers that were offline
request an incremental sync from the relay on reconnect.

- **Reliability:** High
- **Complexity:** Medium — must handle concurrent renames with timestamps/version numbers
- **Herald fit:** High; minimal architecture change, fits 2–5 machine scale

#### 3. Centralized Registry (Service Mesh style)
Move the `peers` list out of local `config.json` entirely and into the relay server
(e.g. a `/registry` endpoint). Each machine registers its current name on startup.
Other machines query the relay instead of reading local config.

- **Reliability:** High (single source of truth)
- **Complexity:** Medium — relay needs registry management logic (`/register`, `/registry` endpoints)
- **Herald fit:** Moderate; Herald's VPS relay is always-on, so the dependency risk is low.
  Also the smallest code delta: relay already owns the routing layer.

### Recommendation

For a quick win: **Approach 3 (Centralized Registry)** — the relay is already always-on
and owns routing. Adding `/register` + `/registry` endpoints to `server.py` and having
`herald_tray.py` call `/register` on startup is a small, contained change.

For long-term correctness: **Approach 1 (UUID)** eliminates the rename problem entirely
and is worth considering if the network grows beyond 5 machines.

Approaches can be combined: UUIDs as keys, relay as registry, gossip for real-time updates.
