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
- **Export Log** — save console output to file

### Player Management
- **Live player list** — see all connected players with details
- **Player Stats Bar** — total, human, and bot counts
- **Kick & Ban** — manage players directly from the UI
- **Bot controls** — add/remove T or CT bots, scramble teams
- **Broadcast messages** — send announcements to all players
- **Auto-refresh** — toggle automatic player list updates

### Map Management
- **Full map pool** — Active Duty, Hostage, Wingman, and Deathmatch categories
- **Workshop Maps** — add custom maps by Steam Workshop URL or ID
- **Steam Workshop browser** — direct link to browse CS2 workshop
- **One-click map change** — switch maps instantly

### Server Settings (CVars)
- **167+ CVars across 12 categories:**
  - General Server, Game Mode, Round Settings, Teams & Players
  - Economy, Communication, Bots, Weapons & Items
  - Practice & Debug, Vote Settings, Damage & Hitboxes, Misc Gameplay
- **Live values** — load current server values with one click
- **Batch apply** — edit multiple settings and apply all at once
- **Auto cheat-unlock** — automatically toggles `sv_cheats` for cheat-protected CVars

### Quick Commands
- **78 pre-built commands** across 6 categories:
  - Match Control, Bots, Practice Mode, Communication, Game Rules, Admin & Server
- **One-click execution** — instant server changes

### Config Templates
- **11 ready-to-use presets:**
  - Competitive 5v5, Casual, Deathmatch, Wingman 2v2, Retake
  - Practice/Warmup, Aim Training, Surf/Bhop, 1v1 Arena, Headshot Only, Pistol Only
- **One-click apply** — load an entire configuration instantly

### Configuration Files
- **Export current settings** — save server state as `.cfg` file
- **Custom Config Editor** — write raw commands and execute or save
- **Saved configs browser** — view, execute, and delete saved configs
- **8 pre-built config files** — ready to use server configurations

---

## Screenshots

> The interface uses the classic Counter-Strike 1.6 visual style via [cs16.css](https://github.com/ekmas/cs16.css)

| Dashboard | Console | Settings |
|-----------|---------|----------|
| Connection, server info, quick actions | Full RCON console with history | 167+ CVars with live server values |

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| **Backend** | Python 3.10+, Flask 3.0 |
| **Frontend** | Vanilla JavaScript (IIFE module pattern) |
| **Styling** | [cs16.css](https://github.com/ekmas/cs16.css) + custom CSS |
| **Protocol** | Valve Source RCON (TCP) |
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

# Run the controller
python app.py
```

The web interface will be available at **http://localhost:5000**

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
├── app.py                  # Flask backend — all API routes & data
├── rcon_client.py          # Valve Source RCON protocol client
├── requirements.txt        # Python dependencies
├── templates/
│   └── index.html          # Main dashboard (8-tab interface)
├── static/
│   ├── css/
│   │   └── app.css         # Custom styles extending cs16.css
│   └── js/
│       └── app.js          # Frontend application (IIFE module)
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

### Commands

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/command` | Execute RCON command `{command}` |
| `GET` | `/api/history` | Get command history |
| `POST` | `/api/history/clear` | Clear command history |

### Players

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/players` | List connected players |
| `POST` | `/api/kick` | Kick player `{player_id, reason}` |
| `POST` | `/api/ban` | Ban player `{player_id, duration, reason}` |
| `POST` | `/api/say` | Send chat message `{message}` |

### Maps

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/maps` | Get all map categories |
| `POST` | `/api/changemap` | Change map `{map_name}` |
| `GET` | `/api/workshop/maps` | List saved workshop maps |
| `POST` | `/api/workshop/add` | Add workshop map `{name, id}` |
| `DELETE` | `/api/workshop/remove/<id>` | Remove workshop map |

### Server Settings

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/cvars` | Get all CVar definitions (167+) |
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
| `POST` | `/api/load_config` | Load/view a config `{name}` |
| `DELETE` | `/api/delete_config` | Delete a config `{name}` |

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
| `FLASK_DEBUG` | `true` | Enable Flask debug mode |

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
| **Warmup** | Extended warmup with all weapons |
| **Aim Training** | Headshot only, pistol rounds |
| **Surf/Bhop** | Bunny hopping, air acceleration |
| **1v1 Arena** | Duel settings |
| **Pistol Only** | Pistol-only rounds |

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
