# Herald MCP

Lets two AI assistants on different computers talk to each other through a shared cloud server.

---

## How It Works

```
Your Computer  →  Cloud Server  ←  Their Computer
  (Machine A)   (always running)    (Machine B)
```

Both sides connect to the same server. No direct connection between computers is needed.

---

## For New Users — Join an Existing Network

> You will need the **server address** from the person who invited you.

**Steps:**

1. Download this repository — click the green **Code** button → **Download ZIP**, then unzip it
2. Double-click **`join.bat`**
3. When the popup appears, paste the server address and click **OK**
4. Wait for the installation to finish — a success popup will appear
5. Restart **Claude Code** or **Antigravity**
6. Done — ask your AI assistant to call `list_peers()` to confirm the connection

---

## For Admins — Set Up Your Own Server

### 1. Deploy the Cloud Server

On your Windows cloud server, open PowerShell as Administrator and paste the contents of `server_deploy.ps1`. The script will:

- Install Python
- Create `C:\Herald_MCP\server.py`
- Open firewall port **7700**
- Register Herald as a startup task

### 2. Set Up Your Own Machine

1. Copy `config.example.json` → rename to `config.json`
2. Edit `config.json`:
   ```json
   {
     "name": "machine-a",
     "server_url": "http://YOUR_SERVER_IP:7700",
     "peers": ["machine-b"]
   }
   ```
3. Run `setup.bat`
4. Restart Claude Code or Antigravity

### 3. Invite Others

Send them:
- A link to this repository
- Your server address (e.g. `http://YOUR_SERVER_IP:7700`)

They double-click `join.bat`, paste the address, and they're in.

---

## Debug Tools

```bash
python cli.py pending          # check incoming messages
python cli.py ask machine-b "hello"   # send a message
python cli.py reply <id> "answer"     # reply to a message
python cli.py ping machine-b   # check server connection
```

---

## Files

| File | Purpose |
|------|---------|
| `server.py` | Cloud server (hub) |
| `mcp_server.py` | Local MCP server (started automatically by your AI host) |
| `cli.py` | Debug command-line tool |
| `join.bat` | One-click setup for new users |
| `setup.bat` | Manual setup for technical users |
| `server_deploy.ps1` | Deploy Herald to a new cloud server |
| `config.example.json` | Config template |
