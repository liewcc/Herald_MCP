<p align="center"><img src="img/logo_nbg.png" width="50%"></p>

# Herald MCP
A system for connecting AI assistants across computers via a shared cloud server.

---

## Why Herald MCP?

Herald MCP occupies a unique "Personal Bridge" niche: it turns a private computer into a reachable, AI-accessible node via a persistent, self-hosted relay. Unlike agent frameworks (which manage AI logic) or sandboxed environments (which manage security isolation), Herald focuses purely on remote accessibility — allowing frontier AIs to interact directly with your real local environment via MCP tools.

**What it is not:** Herald is a minimal agent communication and transport layer — it provides multi-agent delegation, tool execution, and message relaying via MCP, but does not manage reasoning, planning, or memory (those are delegated to the connected AI, e.g. Claude). It is also not sandboxed: commands run directly on the host shell. The tray daemon is Windows-only; Linux/Mac require manual startup.

| Approach | Remote Shell | Relay | Self-hosted | Sandboxed |
|:---|:---|:---|:---|:---|
| **Herald MCP** | Yes (real host) | Yes (built-in) | Yes | No |
| **Agent Frameworks** (AutoGen, CrewAI) | Via tools only | No | Yes | No |
| **Sandbox Envs** (OpenHands, E2B) | Yes (container) | No | Varies | Yes |
| **Official MCP Servers** | No (local only) | No | Yes | No |

---

## Table of Contents

- [Why Herald MCP?](#why-herald-mcp)
- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Getting Started](#getting-started)
  - [Starting and Stopping Herald](#starting-and-stopping-herald)
  - [For New Users — Join an Existing Network](#for-new-users--join-an-existing-network)
  - [For Admins — Set Up Your Own Server](#for-admins--set-up-your-own-server)
- [System Tray UI](#system-tray-ui)
- [Security](#security)
- [Files](#files)

---

## How It Works

Two computers communicate through a central cloud server — no direct connection needed.

```
Your Computer  →  Cloud Server  ←  Their Computer
  (Machine A)   (always running)    (Machine B)
```

---

## Architecture

Herald MCP is designed as a federated communication system where multiple local instances communicate via a stateless, central cloud coordinator. This architecture eliminates the need for peer-to-peer port forwarding, firewall traversal, or local server hosting.

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

## Getting Started

### Starting and Stopping Herald

#### Starting

Herald starts automatically at logon after running `setup.bat` (or `setup_wizard.py`) with autostart on.

To start it manually:
```
python herald_tray.py
```

A Herald icon appears in the Windows system tray when it is running. Left-click to open the status window.

#### Stopping

Right-click the tray icon → **Exit**.

This immediately closes the SSE connection to the relay server. The machine will no longer receive any messages from remote peers until the tray is restarted.

#### Security Note

> **Closing the tray = zero inbound network exposure.**
>
> While the tray is running, Herald maintains a persistent outbound connection to the relay server over HTTP. The relay can push messages to this machine at any time. If you are on a sensitive network or want to ensure no inbound traffic, exit the tray. Restarting it later resumes the connection instantly.
>
> The `allowlist.json` file controls which shell commands remote peers are permitted to run via `exec_shell`. Review and restrict it to only the commands you are comfortable allowing.

---

### Install — New Network or Join an Existing One

Decide these **before** you start, so `config.json` is right the first time:

- **New network** (this PC hosts the relay) or **join** an existing network?
- Joining: the relay URL (`http://<relay Tailscale IP>:7700`) and its token (in the relay PC's `config.json`).
- A Tailscale account to log in with on every PC. The relay PC must end up visible in `tailscale status`
  (same Tailscale account, or the relay node shared to your account).

1. Download the repository as ZIP (green **Code** button → **Download ZIP**) and extract it.
2. Double-click `setup.bat`. It checks git, Python and Tailscale and installs whatever is missing (via winget;
   approve the Windows admin prompt for Tailscale), installs the Python dependencies, logs you in to
   Tailscale if needed, then runs the wizard.
3. Answer the wizard. When joining it tests the relay URL and token **before** writing anything,
   and explains what to fix if the check fails. A new relay prints the URL and token the other PCs need.
4. Restart **Claude Code** or **Antigravity** on PCs that control others.

To change settings later, rerun `python setup_wizard.py` instead of editing `config.json`.
AI installers: see the "AI installers" section in [CLAUDE.md](CLAUDE.md) for the non-interactive flags.

---

### For Admins — Set Up Your Own Server

For administrators who want to deploy and configure their own cloud server, see [docs/admin-setup.md](docs/admin-setup.md).

---

## System Tray UI

For details on the graphical user interface and its features, see [docs/system-tray-ui.md](docs/system-tray-ui.md).

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
| `setup.bat` | Installer: Python, dependencies, then the setup wizard |
| `setup_wizard.py` | Asks role/network/token first, verifies the relay, writes `config.json`, sets up autostart |
| `server_deploy.ps1` | Deploy Herald to a new cloud server |
| `config.example.json` | Configuration template |
