# For Admins — Set Up Your Own Server

## 1. Deploy the Cloud Server

On a Windows cloud server, open PowerShell as Administrator and run the contents of `server_deploy.ps1`.

The script will:
- Install Python
- Create `C:\Herald_MCP\server.py`
- Open firewall port **7700**
- Register Herald as a startup task

## 2. Configure Your Machine

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

## 3. Invite Others

Send them a link to this repository and your server address (e.g. `http://YOUR_SERVER_IP:7700`). They run `join.bat`, paste the address, and they're in.
