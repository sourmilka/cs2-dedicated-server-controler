# CS2 Dedicated Server Controller

A full-featured web-based control panel for Counter-Strike 2 dedicated servers, inspired by the classic Half-Life Dedicated Server (HLDS) tool. Built with **Flask** and styled with **[cs16.css](https://github.com/ekmas/cs16.css)** for an authentic retro Counter-Strike aesthetic.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0+-green?logo=flask&logoColor=white)
![CS2](https://img.shields.io/badge/Counter--Strike%202-Server%20Tool-orange?logo=counterstrike&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## Features

### Dashboard
- **Live connection management** — connect to any CS2 server with IP, port, and RCON password
- **Real-time server info** — hostname, current map, player count updated automatically
- **Quick Stats** — at-a-glance player stats and server state
- **Quick Actions** — one-click restart, end warmup, pause/unpause, swap teams, kick bots, quick map changes
- **Server Chat** — send messages directly to all players
- **Recent Commands** — history of recently executed commands

### Console
- **Full RCON console** — execute any server command with real-time output
- **Command history** — navigate with arrow keys (Up/Down)
- **Quick toolbar** — one-click status, maps, restart, sv_cheats, kick bots
- **Command Reference** — built-in reference grid of common CS2 commands
- **Live Command Search** — search server commands/cvars directly on the running server
- **CVar Dump** — dump all server cvars to console
- **Export Log** — save console output to file

### Player Management
- **Live player list** — see all connected players with details
- **Player Stats Bar** — total, human, and bot counts
- **Kick & Ban** — kick, ban by ID, IP ban, unban from the UI
- **Ban list viewer** — view and manage all active bans
- **Move players** — move players between teams (T/CT/Spec)
- **Mute players** — mute/unmute individual players
- **Bot controls** — add/remove T or CT bots, scramble teams
- **Broadcast messages** — send announcements to all players
- **Auto-refresh** — toggle automatic player list updates

### Map Management
- **Full map pool** — Active Duty, Hostage, Wingman, and Deathmatch categories
- **Workshop Maps** — add custom maps by Steam Workshop URL or ID
- **Workshop Collections** — load entire Steam Workshop collections by ID
- **Steam Workshop browser** — direct link to browse CS2 workshop
- **One-click map change** — switch maps instantly

### Server Settings (CVars)
- **207 CVars across 19 categories:**
  - General Server, Game Mode, Round Settings, Teams & Players
  - Economy, Communication, Bots, Weapons & Items
  - Practice & Debug, Vote Settings, Damage & Hitboxes, Misc Gameplay
  - GOTV, Network, Physics & Movement, Spectator
  - Team Branding, Hostage Mode, Server Logging
- **Live values** — load current server values with one click
- **Batch apply** — edit multiple settings and apply all at once
- **Auto cheat-unlock** — automatically toggles `sv_cheats` for cheat-protected CVars

### Quick Commands
- **133 pre-built commands** across 13 categories:
  - Match Control, Bots, Practice Mode, Communication, Game Rules, Admin & Server
  - GOTV, Warmup & Halftime, Round Backups, Economy Shortcuts
  - Physics Fun, Overtime Controls, Logging
- **One-click execution** — instant server changes

### Config Templates
- **11 ready-to-use presets:**
  - Competitive 5v5, Casual, Deathmatch, Wingman 2v2, Retake
  - Practice, 1v1 Arena, Knife Round, Aim Training, Surf/Bhop, Hide and Seek
- **One-click apply** — load an entire configuration instantly

### Configuration Files
- **Export current settings** — save server state as `.cfg` file
- **Custom Config Editor** — write raw commands and execute or save
- **Saved configs browser** — view, execute, and delete saved configs
- **8 pre-built config files** — ready to use server configurations

### Monitor
- **Performance** — real-time server stats with auto-polling (CPU, tick rate, player counts)
- **GOTV** — view GOTV status, start/stop recording
- **Round Backups** — list and restore round backup files
- **Scheduled Tasks** — create recurring commands with intervals, persistent across restarts

---

## Screenshots

> The interface uses the classic Counter-Strike 1.6 visual style via [cs16.css](https://github.com/ekmas/cs16.css)

| Dashboard | Console | Settings |
|-----------|---------|----------|
| Connection, server info, quick actions | Full RCON console with command search | 207 CVars with live server values |

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| **Backend** | Python 3.10+, Flask 3.0 |
| **Frontend** | Vanilla JavaScript (IIFE module pattern) |
| **Styling** | [cs16.css](https://github.com/ekmas/cs16.css) + custom CSS |
| **Protocol** | Valve Source RCON (TCP) |
| **WSGI Server** | waitress (production) |
| **CORS** | flask-cors |

---

## Quick Start

### Prerequisites

- **Python 3.10+** installed
- A **CS2 Dedicated Server** with RCON enabled
- Server launch options must include: `-port 27015 +rcon_password YOUR_PASSWORD`

### Installation

```bash
# Clone the repository
git clone https://github.com/sourmilka/cs2-dedicated-server-controler.git
cd cs2-dedicated-server-controler

# Install dependencies
pip install -r requirements.txt

# (Optional) Set admin password for HTTP Basic Auth
set CS2_ADMIN_PASSWORD=your_password

# Run the controller
python app.py
```

The web interface will be available at **http://localhost:5000**

> **Security:** Set the `CS2_ADMIN_PASSWORD` environment variable to protect the web interface with HTTP Basic Auth. Without it, anyone with network access can control your server.

### Connect to Your Server

1. Open `http://localhost:5000` in your browser
2. Enter your server address (IP or hostname)
3. Enter the RCON port (default: `27015`)
4. Enter your RCON password
5. Click **Connect**

The controller auto-saves your last connection and will attempt to reconnect on page load.

---

## Project Structure

```
cs2-dedicated-server-controler/
├── app.py                  # Flask backend — 49 API routes, 207 CVars, all data
├── rcon_client.py          # Valve Source RCON protocol client
├── requirements.txt        # Python dependencies
├── templates/
│   └── index.html          # Main dashboard (9-tab interface)
├── static/
│   ├── css/
│   │   └── app.css         # Custom styles extending cs16.css
│   └── js/
│       └── app.js          # Frontend application (IIFE module, 52 functions)
├── server_configs/         # Saved .cfg configuration files
│   ├── competitive.cfg
│   ├── casual.cfg
│   ├── deathmatch.cfg
│   ├── practice.cfg
│   ├── warmup.cfg
│   ├── retake.cfg
│   ├── 1v1_arena.cfg
│   └── surf_bhop.cfg
├── workshop_maps.json      # Saved workshop map entries
├── last_connection.json    # Auto-saved connection (gitignored)
├── scheduled_tasks.json    # Persisted scheduled tasks (gitignored)
├── .gitignore
├── LICENSE
└── README.md
```

---

## API Reference

All endpoints return JSON. The backend runs on `http://localhost:5000`.

### Connection

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/connect` | Connect to server `{host, port, password}` |
| `POST` | `/api/disconnect` | Disconnect from server |
| `GET` | `/api/status` | Get connection status & server info |
| `GET` | `/api/last_connection` | Get last saved connection details |

### Commands

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/command` | Execute RCON command `{command}` |
| `GET` | `/api/history` | Get command history |
| `POST` | `/api/history/clear` | Clear command history |
| `POST` | `/api/find` | Search server commands/cvars `{query}` |
| `GET` | `/api/cvarlist` | Dump all server cvars |

### Players

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/players` | List connected players |
| `POST` | `/api/kick` | Kick player `{player_id, reason}` |
| `POST` | `/api/ban` | Ban player `{player_id, duration, reason}` |
| `POST` | `/api/say` | Send chat message `{message}` |
| `POST` | `/api/move_player` | Move player to team `{player_id, team}` |
| `POST` | `/api/mute_player` | Mute/unmute player `{player_id}` |

### Bans

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/bans` | List all active bans |
| `POST` | `/api/unban` | Unban player by ID `{player_id}` |
| `POST` | `/api/ban_ip` | Ban IP address `{ip, duration}` |
| `POST` | `/api/unban_ip` | Unban IP address `{ip}` |

### Maps

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/maps` | Get all map categories |
| `POST` | `/api/changemap` | Change map `{map_name}` |
| `GET` | `/api/workshop/maps` | List saved workshop maps |
| `POST` | `/api/workshop/add` | Add workshop map `{name, id}` |
| `POST` | `/api/workshop/remove` | Remove workshop map `{id}` |
| `POST` | `/api/workshop/load` | Load a workshop map `{id}` |
| `POST` | `/api/workshop/collection` | Load workshop collection `{collection_id}` |

### Server Settings

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/cvars` | Get all CVar definitions (207) |
| `GET` | `/api/cvar?name=X` | Get current value of a CVar |
| `POST` | `/api/cvar` | Set a CVar `{name, value}` |
| `POST` | `/api/cvar/batch` | Set multiple CVars `{cvars: {name: value}}` |

### Templates & Configs

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/templates` | List all config templates |
| `POST` | `/api/apply_template` | Apply template `{template_id}` |
| `GET` | `/api/quick_commands` | Get quick command presets |
| `POST` | `/api/export_config` | Export server config `{name}` |
| `GET` | `/api/saved_configs` | List saved .cfg files |
| `GET` | `/api/load_config/<name>` | Load/view a config file |
| `DELETE` | `/api/delete_config/<name>` | Delete a config file |

### Monitor & GOTV

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/server/stats` | Get server performance stats |
| `GET` | `/api/gotv/status` | Get GOTV status |
| `POST` | `/api/gotv/record` | Start GOTV recording `{name}` |
| `POST` | `/api/gotv/stop` | Stop GOTV recording |
| `GET` | `/api/round_backup` | List round backup files |
| `POST` | `/api/round_backup/restore` | Restore round backup `{filename}` |

### Scheduled Tasks

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/scheduled_tasks` | List all scheduled tasks |
| `POST` | `/api/scheduled_tasks` | Create scheduled task `{command, interval, name}` |
| `DELETE` | `/api/scheduled_tasks/<id>` | Cancel/delete a scheduled task |
| `POST` | `/api/scheduled_tasks/<id>/restart` | Restart a saved task |

---

## RCON Protocol

This project includes a custom implementation of the **Valve Source RCON Protocol** ([developer.valve.com](https://developer.valvesoftware.com/wiki/Source_RCON_Protocol)).

Key features of the RCON client:
- **Multi-packet response handling** — correctly reassembles fragmented responses
- **Authentication** — proper SERVERDATA_AUTH handshake
- **Thread-safe** — uses threading locks for concurrent access
- **Auto-reconnect** — connection state management with error recovery
- **Auto cheat-unlock** — detects cheat-protected CVars and auto-toggles `sv_cheats`

---

## Configuration

### CS2 Server Launch Options

Add these to your CS2 dedicated server launch options:

```
-dedicated -port 27015 +rcon_password YOUR_PASSWORD +game_type 0 +game_mode 0 +map de_dust2
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASK_PORT` | `5000` | Port for the web interface |
| `FLASK_DEBUG` | `false` | Set to `1`/`true`/`yes` to enable Flask debug mode |
| `CS2_ADMIN_PASSWORD` | *(none)* | Set to enable HTTP Basic Auth on all routes |
| `SECRET_KEY` | *(random)* | Flask secret key (set for consistent sessions) |

---

## Built-in Config Templates

| Template | Description |
|----------|-------------|
| **Competitive 5v5** | Standard MR12, overtime, full economy |
| **Casual** | Relaxed rules, alltalk, auto-balance |
| **Deathmatch** | FFA, infinite respawns, max money |
| **Wingman 2v2** | Short rounds, fast-paced |
| **Retake** | Retake practice scenarios |
| **Practice** | Infinite ammo, noclip, grenade trails |
| **1v1 Arena** | Duel settings |
| **Knife Round** | Knife-only competitive round |
| **Aim Training** | Headshot only, pistol rounds |
| **Surf/Bhop** | Bunny hopping, air acceleration |
| **Hide and Seek** | Hide and seek game mode |

---

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- **[cs16.css](https://github.com/ekmas/cs16.css)** by ekmas — Counter-Strike 1.6 CSS library
- **[Valve Source RCON Protocol](https://developer.valvesoftware.com/wiki/Source_RCON_Protocol)** — protocol specification
- Inspired by the original **HLDS (Half-Life Dedicated Server)** tool by Valve

---

<p align="center">
  <strong>CS2 Dedicated Server Controller</strong><br>
  Built for server admins who love the classics.
</p>
