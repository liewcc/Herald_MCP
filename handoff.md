# Herald MCP — Handoff Notes

## 2026-10-28 — Setup wizard: still to verify on a blank PC

The setup.bat / setup_wizard.py rework passed its self-test, the setup.bat lint, test_security.py,
test_networks.py, two full isolated setup.bat runs (fake winget/tailscale/claude) and a live join
against abby's relay. These parts were **never run for real** — test them on a completely blank
Windows PC (or Windows Sandbox):

- [ ] Real winget installs of git, Python 3.12 (user scope) and Tailscale, and the PATH refresh
      that lets the same window find them afterwards.
- [ ] The Tailscale UAC admin prompt appears and the step waits for it.
- [ ] `tailscale up` opens the browser login, and setup continues after sign-in.
- [ ] `--prereqs` mode run by an AI installer ends with `[OK] Prerequisites ready.` (exit 0).
- [ ] Real `claude mcp remove/add -s user herald` (only the arguments were checked, with a fake claude).
- [ ] AI CLI step (setup.bat [3/6]): real `winget install Anthropic.ClaudeCode`, Node.js LTS via winget
      plus `npm install -g @openai/codex`, the PATH refresh finding `claude` / `codex` afterwards, and
      `claude auth login` / `codex login` opening the browser. Only fakes were used: one run showed
      `set /p` reads several lines from a pipe, so test answers by keyboard or a file, never a pipe.
- [ ] Antigravity registration on a PC that really has Antigravity installed.
- [ ] Tray UI: clicking **Start on Login** writes/removes the autostart entry, and starting a second
      tray shows the "Herald is already running" box.
- [ ] Desktop shortcut on a OneDrive-redirected Desktop.
- [ ] Non-English Windows and other Python versions (only tested on cc: English Windows, Python 3.12/3.14).
- [ ] Reboot: herald_autostart.vbs brings up the relay (python.exe, hidden console) and one tray.

Also pending: April, abby, leno and dv still run the old code. Pull master on each and restart the
tray before relying on the single-instance mutex.

### Plan for that PC: move the abby network's relay onto it

Target: `cc — abby — <newpc>`, with `<newpc>` as the relay host (and an exec_shell peer too).
abby goes back to being a plain peer. The blank-PC test above runs during step 1.

Today abby (100.104.102.15) is the relay, on abby's Tailscale account (`abbyang.office@`), with
abby's machine shared to cc's account. The order below matters: abby is switched over the **old**
relay, so cc must not switch first or it loses abby.

1. **On `<newpc>` (a human at the keyboard):** run `setup.bat`. Log in to Tailscale with **abby's**
   account so abby and `<newpc>` see each other without sharing. Wizard answers: role `relay`, name
   `<newpc>`, peers `abby,cc`, autostart yes. Write down the URL and token printed at the end.
   If peers cannot connect later, allow inbound TCP 7700 in Windows Firewall.
2. **Share `<newpc>` with cc (human, browser):** in abby's account at
   https://login.tailscale.com/admin/machines, open `...` on `<newpc>`, then Share to cc's account,
   and accept on cc. Sharing is per machine, so abby's existing share does not cover it.
   Check from cc: `tailscale status` lists `<newpc>`'s 100.x address.
3. **Check the new relay from cc** before touching anything: `check_relay(URL, token)` in
   setup_wizard.py must return `ok`.
4. **Switch abby to join (from cc, over the old relay):**
   - `exec_shell("abby", "git -C C:\AI\Herald_MCP pull")` brings in the new wizard.
   - The wizard kills abby's tray, and that tray is the process running the command, so start the
     wizard detached:
     `python -c "import subprocess; subprocess.Popen(r'python C:\AI\Herald_MCP\setup_wizard.py --role join --name abby --server-url <URL> --token <TOKEN> --peers cc --yes', stdout=open(r'C:\AI\Herald_MCP\wizard.log','w'), stderr=-2, creationflags=0x208)"`
   - The join drops the relay keys (`host`, `port`), stops abby's relay and rewrites
     `herald_autostart.vbs` to start only the tray.
   - abby can now be reached only through the new relay.
5. **Switch cc:** rerun `python setup_wizard.py --role join --name cc --server-url <URL> --token <TOKEN> --peers abby,<newpc> --yes`.
   It replaces the default network and keeps `networks.april`. `config.json.bak-abby` is then obsolete.
6. **Verify:**
   - `exec_shell("abby", "hostname")` returns `MSI`, and `exec_shell("<newpc>", "hostname")` answers.
   - abby's `C:\AI\Herald_MCP\wizard.log` ends with `[OK] Herald started`.
   - No `server.py` process is left on abby.
   - After a reboot of `<newpc>`, both peers come back without anyone touching them.
7. **Docs:** update the abby row and PC table in the global `CLAUDE.md`, and the
   `project_abby_network` memory: the relay host is now `<newpc>`, and cc's default network URL changed.

If step 4 fails halfway (abby on neither relay): the old relay is still in abby's autostart until
the wizard rewrites it, so a reboot of abby, or a human rerunning step 4's wizard command there,
recovers it.

---

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
