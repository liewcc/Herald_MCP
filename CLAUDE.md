# Herald MCP — Agent Usage Guide

Herald is a peer-to-peer messaging and remote execution system for AI agents across machines.
Agents communicate via a central relay server using MCP tools.

## Setup

1. Copy `config.json.example` to `config.json` and set:
   - `peer_name` — this machine's name on the network
   - `relay_url` — URL of the relay server
2. Configure your agent host (Claude Desktop, Cursor, etc.) to load `mcp_server.py` as an MCP server.
3. On unattended peers, start `herald_tray.py` at boot — it maintains the persistent SSE connection.

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
- Commands must match the allowlist defined in `allowlist.json` (repo root)
- Allowed by default: `Get-*`, `git `, `python `, `dir`, `ls`, `tasklist`, `schtasks `, `echo `
- Multi-line scripts are blocked — use `python -c "..."` for complex single-line operations
- Quote escaping in `python -c`: use `chr(34)` instead of nested quotes

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
