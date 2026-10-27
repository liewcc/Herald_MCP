# Herald MCP — Agent Usage Guide

Herald is a peer-to-peer messaging and remote execution system for AI agents across machines.
Agents communicate via a central relay server using MCP tools.

## Setup

Humans: run `setup.bat` (installs Python if missing, pip deps, then the wizard). Never hand-edit
`config.json` after the fact — rerun `python setup_wizard.py` instead.

### AI installers — collect the answers BEFORE installing anything

Ask the user these questions first, and do not start installing until every one is answered:

1. **Role**: is this PC hosting the relay for a **new** network (`relay`), or **joining** an existing one (`join`)?
2. **Peer name** for this PC (default: lower-case hostname).
3. **Join only**: relay URL (`http://<relay Tailscale IP>:7700`) and the relay's **token**
   (from the relay PC's `config.json`). A relay generates its own token.
4. **Peers** this PC will talk to (comma-separated, may be empty).
5. **Join only, if `config.json` already exists**: replace it, or add this relay as an extra
   network (`--add-network LABEL`; needs `--peers`; the PC can then reach those peers but is only
   *controlled* via its default network).
6. **Autostart** at logon (unattended PC)? Default yes.

Prerequisite for any cross-network setup: Tailscale installed and logged in on both PCs, and the
relay PC visible from the joining PC in `tailscale status` (same tailnet, or the relay node shared
to the joining PC's Tailscale account).

Then run the wizard non-interactively with every answer as a flag (it fails fast instead of prompting):

```
python setup_wizard.py --role relay --name abby --peers cc --yes
python setup_wizard.py --role join  --name leno --server-url http://100.x.x.x:7700 --token <hex> --peers April --yes
```

For `join` it checks the relay's `/health` with the token **before** writing `config.json`, and
explains the failure (unreachable = Tailscale/share/relay down; 401 = wrong token). It then stops
any running relay/tray from this checkout, writes the Startup-folder `herald_autostart.vbs`
(relay via `python.exe` hidden console — never `pythonw`, uvicorn dies without a console; tray via
`pythonw`), removes stale `herald_tray.lnk`/`run_shell_agent.vbs` entries that would start a
duplicate tray, and starts Herald. `python setup_wizard.py --self-test` checks the wizard itself.

Rules learned the hard way:
- Run installs in a **real** shell on the target PC. A sandboxed desktop agent (e.g. the ChatGPT
  app; `$env:LOCALAPPDATA` contains `\Packages\sandbox.`) cannot touch the real machine.
- `schtasks /Create` needs admin on many PCs — that is why autostart uses the Startup folder.
- One tray per peer: two subscribers make the relay's work queue drop `exec_shell` commands.
  Don't also tick the tray UI's **Start on Login** (it adds `herald_tray.lnk` beside the VBS).
- Write files with Python (`python -c` / the wizard), not PowerShell here-strings: a pasted
  `'@ | Set-Content ...` line ends up inside the JSON.

Controller PCs also register `mcp_server.py` with their agent host (Claude Desktop, Claude Code,
Antigravity); `setup.bat` offers this.

The relay (`server.py`) refuses to start without a token (`HERALD_TOKEN` env or `"token"` in its
config.json) and returns 401 to any request whose `X-Herald-Token` header doesn't match.
`server_deploy.ps1` generates one on first deploy. The relay speaks plain HTTP, so the token is
visible on the wire: prefer a private network (e.g. Tailscale) over a public IP.

Run `python test_security.py` after touching auth or the shell guard.

## Available Tools

| Tool | Description |
|------|-------------|
| `ping_peer` | Check if a peer is reachable |
| `exec_shell` | **Primary tool** — run a shell command on a remote peer (no AI needed on the remote side) |
| `ask_peer` | Send a message to a remote peer's AI agent and wait for a reply |
| `get_pending` | Check inbox for incoming messages |
| `reply` | Reply to a pending incoming message |
| `deposit_file` | Non-blocking file transfer to a peer |
| `get_deposits` | Retrieve files deposited for this machine |
| `save_attachment` | Decode and save attachments to a local directory |

## Choosing the Right Tool

```
Need to run a shell command on a remote machine?
  └─ Use exec_shell  ← always available, no AI on remote side needed

Need the remote machine's AI to think, reason, or use tools?
  └─ Use ask_peer  ← requires an AI agent running on the remote peer
```

**Default: `exec_shell`** — it is faster, cheaper, and works even when no AI is running on the remote peer.

## exec_shell

Runs a PowerShell command on a remote peer running `herald_tray.py`.

```python
exec_shell(peer_name="<remote>", cmd="Get-Date")
```

**Constraints:**
- The command is parsed with PowerShell's own parser. It must be **one pipeline**, and **every**
  element must match a rule in `allowlist.json` (repo root), e.g. `tasklist | findstr /i claude`
- Rejected: `;`, newlines, `$(...)`, `(...)`, `{...}`, `$variables`, `&` / `.` invocation,
  `>` redirection, `.Method()` calls, `@{}` hashtables
- Allowed by default: `Get-*`, `git `, `python `, `dir`, `ls`, `tasklist`, `schtasks `, `echo `,
  `findstr `, `Select-Object`, `Sort-Object`, `Format-Table`, `Format-List`, `Measure-Object`
- `python ` and `claude` rules still allow arbitrary code (`python -c ...`); the relay token is
  what keeps strangers out, not the allowlist
- Quote escaping in `python -c`: use `chr(34)` instead of nested quotes; `"..."` is fine as long
  as it contains no `$`

## ask_peer

Sends a message to the remote peer's AI agent and waits for a reply (blocking, up to ~50s).

```python
ask_peer(peer_name="<remote>", message="What files are in C:\\AI?")
```

**Rules:**
- One action per message — multi-step instructions time out
- The remote peer must have an AI agent running and configured to auto-reply
- If the call times out, use `get_pending` to retrieve the reply when it arrives

```
# WRONG — likely to time out:
ask_peer("Take a screenshot, find the button, click it, then describe the result")

# CORRECT — one action at a time:
ask_peer("Take a screenshot and return the coordinates of the Submit button")
ask_peer("Click (452, 310)")
ask_peer("Take a screenshot and describe what changed")
```

## Architecture

```
[Your machine]
  └─ exec_shell ──► relay server (SSE push) ──► herald_tray.py on remote
                                                  (executes command, returns stdout)

  └─ ask_peer ───► relay server ─────────────► remote AI agent
                                                  (thinks, uses tools, calls reply())
                        ◄── reply() ──────────────┘
```

The relay uses a **work-queue** delivery model: each message goes to exactly one subscriber.
`herald_tray.py` on the remote machine holds the persistent SSE connection.

## Incoming Messages

To check and respond to messages sent to this machine:

```python
get_pending()           # returns list of pending messages
reply(message_id, answer)  # reply to a specific message
```

## File Transfer

Direct file writes via `exec_shell` may be blocked by the allowlist. Use `deposit_file` instead:

```python
# Sender:
deposit_file(peer_name="<remote>", file_path="C:\\path\\to\\file.txt", message="here is the file")

# Receiver:
get_deposits()          # lists available files
save_attachment(...)    # saves to local path
```

## Key Rules

1. **`exec_shell` first** — use `ask_peer` only when remote AI reasoning is required
2. **One action per `ask_peer`** — multi-step messages time out
3. **No polling** — herald_tray uses SSE push; do not loop `get_pending` on a timer
4. **Check the allowlist** — if a command is rejected, add a rule to `allowlist.json`

## Prohibited Patterns

- Looping `get_pending` on a timer — burns tokens, SSE push makes this unnecessary
- Multi-step `ask_peer` messages — always break into atomic calls
- Using `ask_peer` when `exec_shell` would suffice
- Writing files via `exec_shell` if `Out-File`/`Set-Content` are not in the allowlist — use `deposit_file`
