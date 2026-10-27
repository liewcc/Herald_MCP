# Herald MCP — Agent Usage Guide

Herald is a peer-to-peer messaging and remote execution system for AI agents across machines.
Agents communicate via a central relay server using MCP tools.

## Setup

Humans: run `setup.bat` (installs git, Python and Tailscale if missing, pip deps, Tailscale login, then the wizard). Never hand-edit
`config.json` after the fact — rerun `python setup_wizard.py` instead.

### AI installers — follow these steps in order

Install the **relay PC first**: its wizard output gives the URL and token every other PC needs.

**Step 0 — Make sure you can touch the real machine.** Run `$env:LOCALAPPDATA` in PowerShell.
If it contains `\Packages\sandbox.` or `\AC`, you are inside a sandboxed agent (e.g. the ChatGPT
desktop app): anything you install lands in the sandbox. Stop and ask the user to run the steps in
a real shell, or to double-click `setup.bat`.

**Step 1 — Ask the user. Install nothing until every answer is in.**

1. **Role**: does this PC host the relay for a **new** network (`relay`), or **join** an existing one (`join`)?
2. **Peer name** for this PC (default: lower-case hostname).
3. **Join only**: the relay URL (`http://<relay Tailscale IP>:7700`) and the relay's **token** — both
   printed at the end of the relay PC's wizard run, also in that PC's `config.json`.
4. **Peers** this PC will talk to (comma-separated, may be empty).
5. **Join only, if `config.json` already exists**: replace it, or keep it and add this relay as an
   extra network (`--add-network LABEL`, needs `--peers`). An extra network lets this PC reach those
   peers, but it is only *controlled* through its default network.
6. **Autostart** at logon? Yes for unattended PCs (the default).

**Getting the URL and token to the joining PC — the user carries them.** You run on the joining
PC and cannot read the relay PC's files, so ask the user to copy them over and paste them into
the chat. Tell them exactly what to run **on the relay PC** (cmd or PowerShell; adjust the path if
Herald lives elsewhere):

```
tailscale ip -4
python -c "import json; print(json.load(open(r'C:\AI\Herald_MCP\config.json'))['token'])"
```

The first line is the IP for the URL (`http://<that IP>:7700`); the second prints the token (64
hex characters). If it answers "Python was not found", use `type C:\AI\Herald_MCP\config.json`
instead and have them copy the value after `"token":` (without the quotes). If the relay was just installed, the same two values are on the last lines of its
wizard output (`role = join, URL = ..., token = ...`). Then **you** pass them to the wizard with
`--server-url` and `--token` — never ask the user to edit `config.json` themselves. If you can
already reach the relay PC (e.g. via `exec_shell`), read the token there yourself instead of
asking. Treat the token as a password: fine in this private chat, never in a public post, issue
or commit.

When you install the **relay** yourself, the opposite applies: give the user the URL and token
from the wizard output and tell them to paste both to whoever (or whichever AI) installs the
other PCs.

**Step 2 — Install the prerequisites: git, the code, Python, Tailscale, dependencies.**
- git: `git --version`. If missing:
  `winget install --id Git.Git --source winget --accept-source-agreements --accept-package-agreements`,
  then open a new shell (PATH is stale in the current one).
- The code: `git clone https://github.com/liewcc/Herald_MCP.git C:\AI\Herald_MCP` (or copy the folder).
- Everything else in one call — it checks each item and installs only what is missing, without prompting:

  ```
  cmd /c "call C:\AI\Herald_MCP\setup.bat --prereqs"
  ```

  It installs Python 3.12 (user scope) and Tailscale via winget, reloads PATH itself, runs
  `pip install -r requirements.txt`, and ends with `[OK] Prerequisites ready.` (exit code 0). A
  non-zero exit means Python or pip failed — read the `ERROR:` line. Tailscale installs
  machine-wide, so **Windows shows an admin prompt on the desktop: ask the user to click Yes**, or
  the step waits. If winget itself is missing, the output says which tool to install by hand.
  All installs use `--source winget`: the default msstore source asks to accept terms and hangs a
  non-interactive shell.
- If it prints `Tailscale is installed but not logged in`, that is expected on a fresh PC — Step 3.

**Step 3 — Tailscale login and sharing. The user does the browser parts; you verify.** You cannot
log in or click Share for them. Ask them to, on every PC:
- log in to Tailscale (tray icon > Log in, or run `tailscale up` and open the link it prints);
- make the PCs see each other: log every PC into the same Tailscale account, or have the relay PC's
  owner open https://login.tailscale.com/admin/machines, click `...` on the relay machine > Share,
  and send the link to the other PC's account to accept.

Then check yourself: `tailscale ip -4` prints this PC's `100.x.x.x` address, and on a joining PC
`tailscale status` lists the relay PC's address. Do not continue until both hold.

**Step 4 — Run the wizard with every answer as a flag.** With `--yes` it never prompts; a missing
answer makes it exit with `ERROR: no answer for '...'` instead of hanging.

| Role | Required flags | Optional |
|---|---|---|
| relay | `--role relay --name N --yes` | `--peers`, `--token` (default: keep the existing relay token, else generate one), `--no-autostart` |
| join | `--role join --name N --server-url URL --token T --yes` | `--peers`, `--add-network LABEL` (needs `--peers`), `--no-autostart` |

```
python setup_wizard.py --role relay --name abby --peers cc --yes
python setup_wizard.py --role join  --name leno --server-url http://100.x.x.x:7700 --token <hex> --peers April --yes
python setup_wizard.py --role join  --name cc   --server-url http://100.x.x.x:7700 --token <hex> --peers abby --add-network abby --yes
```

Most robust: run the same flags **through setup.bat**, so a just-installed Python and a fresh PATH
are used. It re-checks the prerequisites (fast once installed), passes the flags to the wizard,
and skips its Claude/Antigravity questions because stdin is empty:

```
cmd /c "call C:\AI\Herald_MCP\setup.bat --role join --name leno --server-url http://100.x.x.x:7700 --token <hex> --yes <NUL"
```

Do this only after Step 3: if Tailscale is not logged in, a full `setup.bat` run starts
`tailscale up` and waits for the browser login.

What it does: for `join` it checks the relay's `/health` with the token **before** writing
`config.json`. It backs up an existing (even corrupt) `config.json` to `config.json.bak`, stops any
relay/tray already running from this checkout (never `mcp_server.py`), writes the Startup-folder
`herald_autostart.vbs` (relay via `python.exe` with a hidden console — never `pythonw`, uvicorn dies
without a console; tray via `pythonw`), removes stale `herald_tray.lnk` / `run_shell_agent.vbs`
entries that would start a duplicate tray, and starts Herald.

**Step 5 — Check the result.**

| Output | Meaning / action |
|---|---|
| relay: `[OK] Relay running` + `role = join, URL = http://<ip>:7700, token = <token>` | Success. Give URL and token to the user for the other PCs — privately, the token is the only lock. |
| join: `Relay check: OK` then `[OK] Herald started` | Success. |
| `Relay check failed: bad-token` | Wrong token — copy it again from the relay PC. |
| `Relay check failed: unreachable (...)` | Back to Step 3 (Tailscale login / Share), or the relay PC is off. |
| relay: `ERROR: relay check on port 7700 failed (...)` | Run `python server.py` in a console to see the error; `bad-token` there means another relay already holds port 7700. |
| peers can't connect to a working relay | Allow inbound TCP 7700 in Windows Firewall on the relay PC. |

Finally, from the controlling PC: `exec_shell(peer_name="<name>", cmd="hostname")` must return
that PC's hostname. If it times out intermittently, check for two trays on the peer
(`Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Select-Object ProcessId,CommandLine`)
and rerun the wizard, which leaves exactly one.

**Step 6 — Controller PCs only:** register `mcp_server.py` with the agent host and restart it —
Claude Code: `claude mcp add herald -- <python.exe> <repo>\mcp_server.py`; Claude Desktop: add it
under `mcpServers` in `claude_desktop_config.json`. Use the **full path** of the python.exe that
has Herald's dependencies (`python -c "import sys; print(sys.executable)"`), not a bare `python` —
a PC can have several installs. (A full interactive `setup.bat` run offers Claude Code and
Antigravity and does this for you.)

`windows-mcp` (remote desktop control for `ask_peer`, as on April) is optional and must live in
its **own** environment (e.g. a separate venv): it pulls `mcp` 2.x, and `mcp_server.py` needs `mcp<2`.

**Changing settings later:** rerun the wizard with new flags — never hand-edit `config.json`.
A relay rerun keeps its token, so connected peers stay connected.

Rules learned the hard way:
- `schtasks /Create` needs admin on many PCs — that is why autostart uses the Startup folder.
- One tray per peer: two subscribers make the relay's work queue drop `exec_shell` commands.
  Don't also tick the tray UI's **Start on Login** (it adds `herald_tray.lnk` beside the VBS).
- Write files with Python (`python -c` / the wizard), not PowerShell here-strings: a pasted
  `'@ | Set-Content ...` line ends up inside the JSON.
- When a human pastes your commands: one command per block, and tell them not to copy the
  `PS C:\...>` prompt. In PowerShell, `npm`/`.ps1` scripts may be blocked by execution policy — use cmd.

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
