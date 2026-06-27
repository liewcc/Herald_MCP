# Herald MCP
A system for connecting AI assistants across computers via a shared cloud server.

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

#### 1. Deploy the Cloud Server

On a Windows cloud server, open PowerShell as Administrator and run the contents of `server_deploy.ps1`.

The script will:
- Install Python
- Create `C:\Herald_MCP\server.py`
- Open firewall port **7700**
- Register Herald as a startup task

#### 2. Configure Your Machine

1. Copy `config.example.json` → rename to `config.json`.
2. Edit `config.json`:
   ```json
   {
     "name": "machine-a",
     "server_url": "http://YOUR_SERVER_IP:7700",
     "peers": ["machine-b"]
   }
   ```
   - `"name"`: your own computer's name
   - `"peers"`: list of other machines you want to communicate with (they get their name from `join.bat`, which uses `%COMPUTERNAME%`)
3. Run `setup.bat`.
4. Restart **Claude Code** or **Antigravity**.

#### 3. Invite Others

Send them a link to this repository and your server address (e.g. `http://YOUR_SERVER_IP:7700`). They run `join.bat`, paste the address, and they're in.

---

## System Tray UI

- **Launch:** Run `python herald_tray.py` (starts automatically on Windows startup after `--install`).
- **Left-click tray icon** to open/close the Herald window.
- **Rename machine:** Click the machine name at the top of the window (saves to `config.json` immediately).
- **Auto Reply toggle:** Enables automatic handling of incoming messages via Claude.
- **Exit:** Right-click tray icon → **Exit**.

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

