# Herald MCP
A system for connecting AI assistants across computers via a shared cloud server.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Getting Started](#getting-started)
  - [For New Users — Join an Existing Network](#for-new-users--join-an-existing-network)
  - [For Admins — Set Up Your Own Server](#for-admins--set-up-your-own-server)
- [System Tray UI](#system-tray-ui)
- [Files](#files)

---

## How It Works

Two computers communicate through a central cloud server — no direct connection needed.

```
Your Computer  →  Cloud Server  ←  Their Computer
  (Machine A)   (always running)    (Machine B)
```

---

## Getting Started

### For New Users — Join an Existing Network

> **You'll need the server address from your inviter.**
> Python is automatically installed by `join.bat` if missing. Your peer name is set to your Windows hostname (`COMPUTERNAME`).

1. Download the repository as ZIP (green **Code** button → **Download ZIP**) and extract it.
2. Double-click `join.bat`.
3. Paste the server address in the popup and click **OK**.
4. Wait for installation to complete (success popup will appear).
5. Restart **Claude Code** or **Antigravity**.
6. Confirm with your AI assistant by calling `list_peers()`.

---

### For Admins — Set Up Your Own Server

For administrators who want to deploy and configure their own cloud server, see [docs/admin-setup.md](docs/admin-setup.md).

---

## System Tray UI

For details on the graphical user interface and its features, see [docs/system-tray-ui.md](docs/system-tray-ui.md).

---

## Files

| File | Purpose |
|------|---------|
| `server.py` | Cloud server (central hub) |
| `mcp_server.py` | Local MCP server (started automatically by your AI host) |
| `herald_tray.py` | Windows system tray daemon with UI and Auto Reply |
| `join.bat` | One-click setup for new users |
| `setup.bat` | Manual setup for technical users |
| `server_deploy.ps1` | Deploy Herald to a new cloud server |
| `config.example.json` | Configuration template |
