# For Admins — Set Up Your Own Server

## 1. Deploy the Cloud Server

On a Windows cloud server, open PowerShell as Administrator and run the contents of `server_deploy.ps1`.

The script will:
- Install Python
- Create `C:\Herald_MCP\server.py`
- Open firewall port **7700**
- Register Herald as a startup task

## 2. Configure Your Machine

1. Run `setup.bat` and choose **join**.
2. Enter the server address (`http://YOUR_SERVER_IP:7700`) and the token `server_deploy.ps1` printed
   (also in `C:\Herald_MCP\config.json` on the server). The wizard checks both before writing `config.json`.
3. Give this PC a name, and list the peers you want to talk to (each PC picks its own name in the wizard;
   default is its lower-case hostname).
4. Restart **Claude Code** or **Antigravity**.

## 3. Invite Others

Send them a link to this repository and your server address (e.g. `http://YOUR_SERVER_IP:7700`). They run `setup.bat`, choose **join**, and enter the address and the token; the wizard verifies both before writing anything.
