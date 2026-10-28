# System Tray UI

- **Launch:** Run `python herald_tray.py` (starts automatically on Windows startup after `--install`).
- **Left-click tray icon** to open the Herald window. Closing the window (X) hides it back to the tray; the connection keeps running.
- **Rename machine:** Click the machine name at the top of the window (saves to `config.json` immediately).
- **Exit:** Right-click tray icon → **Exit**, or the **Exit** button in the window.

## Tabs

| Tab | What it shows |
|-----|---------------|
| **Messages** | Incoming messages and file deposits from peers, as they arrive over SSE. |
| **Comm Log** | The full two-way log from `herald_comm.log`: every `exec_shell` and `ask_peer` sent or received. |
| **Remote Tasks** | Run a preset (or typed) command on a peer and see its output, e.g. which `claude` / `python` processes are running there. Each peer is reached through the relay of the network it belongs to. |
| **Network** | Which PCs are connected right now, one diagram per relay (see below). |

## Network tab

![Network tab](img/network-tab.png)

Each relay in `config.json` (the top level plus every entry under `networks`) gets its own star diagram, with the relay in the middle and that network's peers around it.

| Mark | Meaning |
|------|---------|
| Green dot, solid line | Online: the peer's tray holds a live connection to this relay |
| Grey dot, dotted line | Offline: no tray connected from that PC |
| Hollow dot with `?` | Unknown: the relay is unreachable, or runs an older `server.py` that does not report who is online |
| Dark ring | This PC |
| Blue box, "runs on X" | The relay is up; X is the PC that hosts it |
| Red dashed box | The relay cannot be reached |

Below each diagram: the round-trip time to the relay and how many of its peers are online.

- **Click a PC** to jump to Remote Tasks with that peer selected.
- The tab refreshes when you open it, then every 15 seconds while it stays open. Nothing is polled while the window is hidden.
- Peers come from each network's `peers` list in `config.json`. A PC that is connected but missing from that list will not be drawn.
- This PC's tray subscribes only to the **top-level** relay, so it shows as offline in every other network. That is accurate: peers there cannot send commands to it.

### Showing IP addresses

Add an optional `ips` map to `config.json` to print each peer's address under its dot. It also lets the tab name the host of a relay that is down, by matching the relay URL's IP:

```json
"ips": {
  "April": "100.68.212.3",
  "leno": "100.95.136.109"
}
```

### Relay requirement

The online/offline state comes from the relay's `/health` endpoint, which returns `"online": [...]`, the peers whose tray is subscribed at that moment. Relays running an older `server.py` show every peer as `?` until they are updated and restarted.

## Bottom bar

- **Start on Login:** Adds or removes the Windows startup entry.
- **Auto Reply:** Invokes Claude once per incoming chat message to answer it (event-driven, no cost while idle).
- **Notify:** Shows a Windows toast when a peer runs a command, sends a file or talks to this PC's AI (at most one per peer per minute).
