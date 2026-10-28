<p align="center"><img src="img/logo_nbg.png" width="50%"></p>

# Herald MCP

**Herald lets the AI assistants on several of your computers talk to each other and work together.**

Say you use Claude Code on your laptop, and you also have an office PC and a home server. With Herald, the
Claude on your laptop can:

- run a command on the office PC and read the result (`exec_shell`),
- ask the AI on the home server to do a job and answer back (`ask_peer`),
- send files to, and receive files from, any of them (`send_file`, `deposit_file`).

The PCs do not need public IPs or open router ports. They reach each other over
[Tailscale](https://tailscale.com), a free private network, through one small message hub called the
**relay**.

### Claude and GPT, on different computers, working as one team

**This is the point of Herald:** the AIs do not have to come from the same vendor or sit on the same
machine. Herald is in daily use on a network of several Windows PCs where:

- **Claude Code** runs on several of the PCs, and the Claude on the main PC directs the others: runs
  commands on them, asks their Claude to do a job, collects files and results;
- **GPT** runs on another PC, through OpenAI's **Codex CLI**. The Claude on the main PC hands it a coding
  task through Herald, Codex does the work on its own machine, and the result comes back to Claude.

```
   Main PC  ── Claude Code (directs the work)
      │
      │  Herald, over Tailscale
      ├──────────►  Server PC      ── Claude Code   "check the scan log and fix the error"
      ├──────────►  Accounting PC  ── Claude Code   "export this month's report"
      └──────────►  Another PC     ── Codex CLI / GPT   "write and test this module"
```

Why that matters: most multi-agent tools run every agent **on one machine**, and usually from **one
vendor**. MCP itself connects an AI to tools on its own computer. Herald fills the gap between them: it
is the wire that lets an AI on one computer reach an AI on another, whatever model each one runs. That
means each job can go to the machine that holds the data, the licence or the hardware, and to the model
that is best at it.

What each side needs:

| Role on a PC | What it takes |
|--------------|---------------|
| **Directs other PCs** (controller) | An agent that can load MCP tools: the **Claude Code CLI**, Claude Desktop or Antigravity. Herald's installer registers itself with Claude Code and Antigravity. |
| **Answers questions** (`ask_peer`) | The Herald tray plus the **Claude Code CLI, logged in**: with **Auto Reply** on, the tray starts `claude` to answer each message. |
| **Does work on command** (`exec_shell`) | Only the Herald tray. A command-line agent on that PC, such as the **Codex CLI (GPT)**, can then be started and given a task from another PC, as long as `allowlist.json` on that PC permits the command that launches it. |

> [!IMPORTANT]
> **Herald needs the AI's command-line tool (CLI), not just its desktop app.** A PC with only the Claude
> Desktop or ChatGPT app installed cannot answer `ask_peer` or take work from other PCs: Herald starts
> the `claude` / `codex` program, and the ChatGPT app's agent runs in a sandbox that cannot reach the
> rest of the PC. In past installs exactly this was missed, and those PCs silently never answered.
> `setup.bat` now installs the CLI and has you log in; see [Before You Start](#before-you-start).

Handing a task to Codex from another PC looks like this (Codex is started through `python`, which the
default allowlist permits; it needs `--dangerously-bypass-approvals-and-sandbox` because its own sandbox
cannot start inside the tray's background process):

```
exec_shell(peer_name="gpt-pc", timeout=180, cmd="python -c \"import subprocess; subprocess.run('codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check -C C:\\work -', shell=True, input='Write and test parser.py')\"")
```

---

## Table of Contents

- [Claude and GPT, on different computers, working as one team](#claude-and-gpt-on-different-computers-working-as-one-team)
- [Key Concepts](#key-concepts)
- [Before You Start](#before-you-start)
- [Installation](#installation)
  - [Option A — Let an AI Agent Install It (recommended)](#option-a--let-an-ai-agent-install-it-recommended)
  - [Option B — Install by Hand](#option-b--install-by-hand)
  - [Check That It Works](#check-that-it-works)
  - [Troubleshooting](#troubleshooting)
- [Starting and Stopping Herald](#starting-and-stopping-herald)
- [System Tray UI](#system-tray-ui)
- [Why Herald MCP?](#why-herald-mcp)
- [Architecture](#architecture)
- [Security](#security)
- [Files](#files)

---

## Key Concepts

Read this once; the installer will ask you about each of these.

```
             Office PC                 Home server
           (client: leno)             (client: dv)
                  \                       /
                   \   Tailscale (100.x)  /
                    \                   /
                 +----------------------------+
                 |  Relay PC (also a client)  |
                 |  April: server.py + tray   |
                 +----------------------------+
                               |
                          Your laptop
                    (client + controller: cc)
```

| Term | What it means |
|------|---------------|
| **Network** | A group of PCs that share one relay and one token. Most people need exactly one. |
| **Relay** | The message hub (`server.py`). It runs on **one** PC of the network, one that is usually switched on. Every message between PCs passes through it. Install it with role **relay**. |
| **Client** | Every PC in the network, the relay PC included, runs the Herald **tray** (`herald_tray.py`). The tray keeps a connection to the relay and carries out what other PCs ask for. A PC that is not the relay is installed with role **join**. |
| **Controller** | A client whose AI (Claude Code, Claude Desktop, Antigravity) has Herald's tools registered, so it can send commands to the others. A PC can be controlled without being a controller. |
| **Peer name** | Each PC's short name in the network, e.g. `April`, `leno`. You use it to address that PC. |
| **Token** | A long random password, created when the relay is installed. Every PC in the network needs the same token. Keep it private. |
| **Tailscale** | Gives each PC a private `100.x.x.x` address that the others can reach from anywhere. Herald relies on it to connect PCs on different networks. |

**Install order:** first the relay PC (its installer prints the relay URL and token), then each of the
other PCs with role **join**, using that URL and token.

---

## Before You Start

Prepare these first, so the installation runs straight through:

1. **Windows 10 or 11** on every PC, and an account that can approve an administrator prompt (needed
   once, to install Tailscale). The tray is Windows-only.
2. **A Tailscale account.** Sign up free at <https://login.tailscale.com/start>. You can sign in with
   a Google, Microsoft or GitHub account.
3. **Decide which PC hosts the relay.** Pick one that stays on most of the time. If it is off, the
   other PCs cannot reach each other.
4. **Decide how the PCs will see each other on Tailscale.** Either:
   - log **every PC into the same Tailscale account** (simplest), or
   - use separate accounts, and have the relay PC's owner **share** the relay machine with the other
     accounts: <https://login.tailscale.com/admin/machines> → `...` on the relay machine → **Share**.
5. **A peer name for each PC** (default: its lower-case Windows computer name).
6. **Decide which AI CLI each PC gets, and have its account ready.** The installer installs the CLI
   itself; you only log in. The desktop apps (Claude Desktop, ChatGPT) do **not** count.

   | AI CLI | Needed for | Account |
   |--------|-----------|---------|
   | **Claude Code** (recommended on every PC) | Answering `ask_peer` (Auto Reply), controlling other PCs | Claude Pro or Max |
   | **Codex CLI** (optional) | Letting GPT take coding work handed over from another PC | A ChatGPT account (Go works) |
   | None | A PC that only runs commands it is sent (`exec_shell`) | — |

The installer takes care of the rest: git, Python 3.12, Tailscale, the Python packages and the AI CLIs
you choose are installed automatically if they are missing.

---

## Installation

There are two ways. Both give the same result. Do the **relay PC first**, then the others.

### Option A — Let an AI Agent Install It (recommended)

If the PC already has a coding agent with shell access (the **Code** tab of Claude Desktop, Claude Code,
Antigravity, Codex CLI), let it do the work. The repository's [CLAUDE.md](CLAUDE.md) has a step-by-step
script written for agents: it asks you every question up front, installs the prerequisites **and the AI
CLIs** (Claude Code, Codex), runs the setup wizard without prompts, and checks the result.

Paste this to the agent on the PC you are installing:

> Install Herald MCP on this PC by following the "AI installers" section of
> https://github.com/liewcc/Herald_MCP/blob/master/CLAUDE.md.
> This PC is the **relay** of a new network. *(or:)* This PC **joins** an existing network.

The agent cannot do the parts that need you in person. Expect to:

- click **Yes** on the Windows administrator prompt when Tailscale is installed;
- log in to Tailscale in the browser page that opens;
- log in to the AI CLI: run `claude auth login` (and/or `codex login`) in a terminal when the agent asks;
- share the relay machine on Tailscale, if the PCs use different accounts;
- **relay PC:** copy the relay URL and token the agent reports, and keep them for the other PCs;
- **joining PC:** paste that URL and token into the chat when the agent asks.

> [!NOTE]
> Sandboxed agents (for example the ChatGPT desktop app) cannot install software on the real PC. The
> agent checks for this first and tells you to use Option B instead.

### Option B — Install by Hand

#### Step 1 — Tailscale on every PC

`setup.bat` installs Tailscale for you, but the login and the sharing are yours to do:

1. On each PC, log in to Tailscale with your account (tray icon → **Log in**). If Tailscale is not
   installed yet, `setup.bat` installs it and opens the sign-in page for you in Step 2.
2. Make sure the PCs can see each other: same account on every PC, or the relay machine shared with
   the other accounts (see [Before You Start](#before-you-start), item 4).
3. Check from a command prompt: `tailscale ip -4` shows this PC's `100.x.x.x` address, and
   `tailscale status` lists the other PCs.

#### Step 2 — Install the relay PC

1. Download the repository: green **Code** button → **Download ZIP**, then extract it to a permanent
   folder, e.g. `C:\AI\Herald_MCP`. Do not run it from the Downloads folder: autostart points at this
   location.
2. Double-click **`setup.bat`**. It checks git, Python and Tailscale and installs what is missing (approve
   the administrator prompt for Tailscale), then installs the Python packages.
3. **AI CLI.** If the Claude Code CLI is missing, setup asks **Install it?** → `y` (Enter). It then asks
   whether to install the **Codex CLI** too → `y` only if this PC should run GPT. For each CLI that is
   installed but not logged in, a browser page opens: sign in, then come back to the setup window.
   Setup prints `[OK] Claude Code CLI, logged in` (and the same for Codex) when it worked.
4. The setup wizard starts. Answer:
   - **Is this PC hosting the relay for a NEW network, or joining?** → `1` (relay)
   - **Peer name** → e.g. `April`
   - **Peers this PC will talk to** → the names of the other PCs, comma-separated (you can leave it blank
     and add them later)
   - **Generate a new token?** → `y`
   - **Write it?** → `y` (the wizard shows the settings first)
   - **Start Herald automatically at logon?** → `y` for a PC that should always be reachable
5. When it finishes, the wizard prints a line like this. **Copy it somewhere safe**, every other PC needs it:
   ```
   role = join, URL = http://100.101.102.103:7700, token = 3f9c…(64 characters)
   ```
6. If this PC is also a controller, answer `y` when `setup.bat` offers to register Herald with Claude
   Code / Antigravity.

The relay PC now runs two things: the relay (`server.py`) and its own tray.

#### Step 3 — Install each of the other PCs

1. Download and extract the repository as in Step 2.
2. Double-click **`setup.bat`**. Install and log in to the AI CLI as in Step 2, item 3, then answer the
   wizard:
   - **Hosting or joining?** → `2` (join)
   - **Peer name** → e.g. `leno`
   - **Peers this PC will talk to** → e.g. `April`
   - **Relay URL** → the URL from the relay PC, e.g. `http://100.101.102.103:7700`
   - **Relay token** → the token from the relay PC
3. The wizard **tests the URL and token before writing anything**. If the test fails, it explains what
   to fix and lets you retry (see [Troubleshooting](#troubleshooting)).
4. Confirm **Write it?**, answer the autostart question, and on controller PCs let `setup.bat` register Herald with Claude Code
   / Antigravity.

#### Step 4 — Restart the AI on controller PCs

Restart Claude Code (or Antigravity) so it loads the Herald tools.

### Check That It Works

- A Herald icon is in the Windows system tray of every PC. Open it, go to the **Network** tab: each PC
  that is running should be a green box (see [System Tray UI](docs/system-tray-ui.md)).
- From a controller PC, ask the AI: *"Use exec_shell to run `hostname` on leno."* It should answer with
  that PC's computer name.
- For a PC with Claude Code and **Auto Reply** on: *"Use ask_peer to ask leno what day it is."* Its Claude
  should answer within about a minute.

To change settings later (another relay, new peers, a new name), run `python setup_wizard.py` again
instead of editing `config.json` by hand.

### Troubleshooting

| What you see | What to do |
|--------------|------------|
| `Relay check failed: bad-token` | The token was copied wrong. Copy it again from the relay PC, without spaces. |
| `Relay check failed: unreachable` | Tailscale is not logged in on this PC, the relay PC is not in `tailscale status` (share it or use the same account), or the relay PC is switched off. |
| Joining PCs still cannot connect to a running relay | On the relay PC, allow inbound TCP port **7700** in Windows Firewall. |
| `exec_shell` sometimes times out | Two trays are running on that PC. Run `python setup_wizard.py` there again: it leaves exactly one. |
| The AI has no Herald tools | Register them and restart the AI: `claude mcp add -s user herald -- <full path of python.exe> <Herald folder>\mcp_server.py` |
| `ask_peer` to a PC never gets an answer | That PC has no Claude Code CLI, it is not logged in, or Auto Reply is off. On that PC: `claude auth status` must show `"loggedIn": true`; if not, `winget install Anthropic.ClaudeCode` and/or `claude auth login`. |
| Only Claude Desktop or the ChatGPT app is installed | Not enough: rerun `setup.bat` and let it install the CLI. |
| The tray runs elevated and Claude says it is not logged in | The browser login does not reach an elevated process. Run `claude setup-token` and save the token as the user environment variable `CLAUDE_CODE_OAUTH_TOKEN`, then restart the tray. |

Running your own relay on a cloud server instead of a PC? See [docs/admin-setup.md](docs/admin-setup.md).

---

## Starting and Stopping Herald

Herald starts automatically at logon if you chose autostart. To start it by hand: `python herald_tray.py`
(on the relay PC also `python server.py`).

To stop it: right-click the tray icon → **Exit**. This closes the connection to the relay at once; the PC
receives nothing from other PCs until the tray runs again.

> [!NOTE]
> **Closing the tray = zero inbound exposure.** While the tray runs it keeps an outbound connection to the
> relay, which can push commands to this PC at any time. `allowlist.json` decides which shell commands
> other PCs may run here; keep it as tight as you can.

---

## System Tray UI

The tray window has four tabs (Messages, Comm Log, Remote Tasks, Network) and switches for autostart,
Auto Reply and notifications. See [docs/system-tray-ui.md](docs/system-tray-ui.md).

---

## Why Herald MCP?

Herald MCP occupies a unique "Personal Bridge" niche: it turns a private computer into a reachable, AI-accessible node via a persistent, self-hosted relay. Unlike agent frameworks (which manage AI logic) or sandboxed environments (which manage security isolation), Herald focuses purely on remote accessibility — allowing frontier AIs to interact directly with your real local environment via MCP tools.

**What it is not:** Herald is a minimal agent communication and transport layer — it provides multi-agent delegation, tool execution, and message relaying via MCP, but does not manage reasoning, planning, or memory (those are delegated to the connected AI, e.g. Claude). It is also not sandboxed: commands run directly on the host shell. The tray daemon is Windows-only; Linux/Mac require manual startup.

| Approach | AI ↔ AI across PCs | Mixed vendors (Claude + GPT) | Remote Shell | Relay | Self-hosted | Sandboxed |
|:---|:---|:---|:---|:---|:---|:---|
| **Herald MCP** | Yes | Yes | Yes (real host) | Yes (built-in) | Yes | No |
| **Agent Frameworks** (AutoGen, CrewAI) | No (one process) | Via API keys, same machine | Via tools only | No | Yes | No |
| **Sandbox Envs** (OpenHands, E2B) | No | Varies | Yes (container) | No | Varies | Yes |
| **Official MCP Servers** | No (local only) | n/a | No (local only) | No | Yes | No |

---

## Architecture

Herald MCP is designed as a federated communication system where multiple local instances communicate via a stateless, central relay (on one of your PCs, or on a cloud server). This architecture eliminates the need for peer-to-peer port forwarding, firewall traversal, or local server hosting.

```
                           +-----------------------------+
                           |        Cloud Server         |
                           |         (server.py)         |
                           +--------------+--------------+
                                          ^
                          HTTP/SSE Pull   |   HTTP Post Ask/Reply
                          & Push Events   |   & File Deposits
                                          v
                          +---------------+--------------+
                          |      Your Windows Host       |
                          +------------------------------+
                          |                              |
                          |   +----------------------+   |
                          |   |   herald_tray.py     |   |
                          |   | (System Tray Daemon) |   |
                          |   +-----------+----------+   |
                          |               |              |
                          |       Spawns  v Background   |
                          |   +----------------------+   |
                          |   |      claude.exe      |   |
                          |   |    (Claude Code)     |   |
                          |   +-----------+----------+   |
                          |               |              |
                          |       Starts  v StdIO        |
                          |   +----------------------+   |
                          |   |    mcp_server.py     |   |
                          |   |     (MCP Server)     |   |
                          |   +----------------------+   |
                          |                              |
                          +------------------------------+
```

### 1. Component Overview

| Component | File | Role |
|-----------|------|------|
| **Cloud Server** | `server.py` | Stateless FastAPI hub; routes messages and file deposits between peers via in-memory queues |
| **Local MCP Server** | `mcp_server.py` | Exposes Herald tools (`ask_peer`, `exec_shell`, `reply`, etc.) to the local AI assistant via the MCP protocol |
| **System Tray Daemon** | `herald_tray.py` | Persistent Windows background process; holds the SSE connection, executes shell commands, and spawns AI agents for auto-reply |

---

### 2. Message Delivery Model

Herald uses **SSE-based push** with **work-queue semantics** — each message goes to exactly one subscriber.

When a local daemon starts, it opens a long-lived GET request to the server's `/subscribe` endpoint. The server maps each peer name to a single `asyncio.Queue`. When a message arrives for that peer, it is pushed onto the queue and streamed to the one active subscriber. If the connection drops, the daemon automatically reconnects with a 5-second back-off.

---

### 3. Execution Paths

Herald supports two communication pathways:

#### Path A — Direct Shell (`exec_shell`)

No AI needed on the remote side. The tray daemon executes the command directly in PowerShell after validating it against `allowlist.json`.

```
[Machine A]              [Cloud Server]           [Machine B Tray]
     |                         |                         |
     |-- POST /ask ----------->|                         |
     |   {type: "shell",       |                         |
     |    cmd: "..."}          |-- SSE push ------------>|
     |                         |                         | validate allowlist
     |                         |                         | run powershell
     |                         |<-- POST /reply ---------|
     |<-- stdout/stderr -------|                         |
```

#### Path B — AI Agent Round-Trip (`ask_peer`)

Used when the remote peer needs to reason, use tools, or produce a natural-language reply.

```
[Machine A]              [Cloud Server]           [Machine B Tray]
     |                         |                         |
     |-- POST /ask ----------->|                         |
     |   {message: "..."}      |-- SSE push ------------>|
     |                         |                         | spawn claude.exe
     |                         |                  [claude.exe subprocess]
     |                         |<-- GET /pending --------|
     |                         |--- message body ------->|
     |                         |                         | reason + tools
     |                         |<-- POST /reply ---------|
     |<-- reply answer --------|                         |
```

The spawned `claude.exe` is restricted to only `mcp__herald__get_pending` and `mcp__herald__reply` — it cannot access local files or run shell commands.

---

### 4. File Transfer

| Method | Tool | Use case |
|--------|------|----------|
| **Inline attachment** | `send_file` | Small files (≤ 5 MB) sent alongside a message; base64-encoded in the `/ask` payload |
| **Mailbox deposit** | `deposit_file` / `get_deposits` / `save_attachment` | Larger or async transfers; server holds the file in memory until the receiver fetches it (default TTL: 30 min) |

Direct file writes via `exec_shell` are typically blocked by the allowlist — use `deposit_file` instead.

---

### 5. Auto-Reply Lifecycle

When **Auto Reply** is enabled in the tray UI:

1. An incoming `ask_peer` message triggers the SSE handler in `herald_tray.py`.
2. The daemon checks whether a previous `claude.exe` subprocess is still running (single-instance guard). If busy, the message is queued.
3. A new `claude.exe` is spawned headlessly with `-p` (non-interactive) mode and a fixed `--allowedTools` list.
4. Claude fetches the pending message, formulates a reply, and calls `reply()` to close the round-trip.

---

### 6. Component Interaction: herald_tray.py vs mcp_server.py

These two processes serve opposite directions — one listens, one speaks.

| | `herald_tray.py` | `mcp_server.py` |
|--|--|--|
| **Started by** | Windows startup / manually | Claude Desktop (automatic) |
| **Direction** | **Inbound** — holds the SSE connection; receives remote messages | **Outbound** — exposes tools to the local AI; sends messages |
| **Analogy** | The machine's "ear" | The machine's "mouth" |
| **If closed** | Machine goes deaf — no remote messages received | Local AI loses Herald tools |

**Critical rule:** `mcp_server.py` has zero inbound capability. Even if Claude Desktop is open, closing `herald_tray.py` means no remote peer can reach this machine.

| Tray | Claude Desktop | Can receive `exec_shell`? | Can receive `ask_peer`? |
|------|---------------|--------------------------|------------------------|
| ✅ Running | ✅ Open | ✅ Yes | ✅ Yes |
| ✅ Running | ❌ Closed | ✅ Yes | ❌ No (no AI to reply) |
| ❌ Exited | ✅ Open | ❌ No | ❌ No |
| ❌ Exited | ❌ Closed | ❌ No | ❌ No |

---

## Security

> [!IMPORTANT]
> Herald MCP is a personal/hobbyist tool designed for trusted-machine scenarios (e.g., controlling your own second PC or connecting Claude on another machine you own). It is **not** commercial-grade P2P software, **not** designed for untrusted peers, and **not** a replacement for hardened enterprise remote-access tools like RDP or SSH.

### Trust Model & Built-in Guards
Herald operates under a shared-secret trust model. It implements the following safeguards:
- **Relay Token:** `server.py` refuses to start without a token and rejects (401) every request without a matching `X-Herald-Token` header. All peers share the same `token` in `config.json`.
- **Outbound-Only SSE:** The client daemon in `herald_tray.py` initiates outbound connections; no inbound firewall ports are opened.
- **Command Guard:** `exec_shell` commands are parsed with PowerShell's own parser; only a single pipeline whose every element matches `allowlist.json` runs. `;`, `$(...)`, `(...)`, `{...}`, variables, `&` and redirection are rejected.
- **Restricted Auto-Reply:** The daemon spawns `claude.exe` with `--allowedTools` restricted to `get_pending` and `reply`, preventing the remote agent from executing local commands or accessing local files.

### Limitations & Non-Goals
- **Shared Secret Only:** Every token holder can impersonate any peer name; there is no per-peer identity.
- **No Transit Encryption:** Message payloads and file deposits are sent unencrypted (relying entirely on the relay server's TLS/HTTPS).
- **Broad Rules:** The default `python ` and `claude` rules still permit arbitrary code for token holders.
- **Stateless Relay:** The cloud `server.py` stores all active messages and file deposits in-memory, readable by any token holder.

### Recommended Mitigations
1. **Use HTTPS:** Run the relay server behind a reverse proxy (e.g., Caddy/Nginx) with TLS.
2. **Minimize Allowlist:** Keep commands in `allowlist.json` as restrictive as possible.
3. **Exit Daemon When Idle:** Right-click the tray icon → **Exit** when you no longer need remote access. For maximum control, uncheck **Start on Login** in the tray window — this removes the automatic Windows startup entry so the daemon does not launch on boot. With auto-start disabled, Herald is completely offline until you manually run `herald_tray.py`, giving you explicit control over when your machine is reachable.
4. **Keep URL and Token Private:** Do not publish your relay server URL or token. The relay is plain HTTP, so without TLS or a private network (e.g. Tailscale) the token can be sniffed.

---

## Files

| File | Purpose |
|------|---------|
| `server.py` | Cloud server (central hub) |
| `mcp_server.py` | Local MCP server (started automatically by your AI host) |
| `herald_tray.py` | Windows system tray daemon with UI and Auto Reply |
| `setup.bat` | Installer: git, Python, Tailscale (if missing), dependencies, the Claude Code / Codex CLI and their logins, then the setup wizard; `--prereqs [claude] [codex]` for the first part only |
| `setup_wizard.py` | Asks role/network/token first, verifies the relay, writes `config.json`, sets up autostart |
| `server_deploy.ps1` | Deploy Herald to a new cloud server |
| `config.example.json` | Configuration template |
