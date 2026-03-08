"""
CS2 Dedicated Server Controller
A web-based server management tool inspired by the classic CS 1.6 HLDS tool.
"""

import os
import re
import json
import time
import logging
import functools
import threading
from datetime import datetime
from typing import Any, Callable, TypeVar, cast
from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS  # type: ignore[import-untyped]
from rcon_client import RCONClient, RCONAuthError, RCONConnectionError

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'cs2-server-controller-dev-key-change-me')
CORS(app, origins=['http://localhost:*', 'http://127.0.0.1:*', 'https://*.koyeb.app'])

DATA_DIR = os.path.dirname(__file__) or '.'

# ============== BASIC AUTH ==============
# Set CS2_ADMIN_PASSWORD env var to enable password protection.
# When not set, the dashboard is open (local-only use).
ADMIN_PASSWORD = os.environ.get('CS2_ADMIN_PASSWORD', '')


def check_auth(password: str) -> bool:
    """Check if the provided password matches."""
    return password == ADMIN_PASSWORD


def authenticate() -> Response:
    """Send a 401 response to trigger basic auth."""
    return Response(
        'Authentication required.', 401,
        {'WWW-Authenticate': 'Basic realm="CS2 Server Controller"'}
    )


F = TypeVar('F', bound=Callable[..., Any])


def requires_auth(f: F) -> F:
    """Decorator: require HTTP Basic Auth when CS2_ADMIN_PASSWORD is set."""
    @functools.wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        if not ADMIN_PASSWORD:
            return f(*args, **kwargs)
        auth = request.authorization
        if not auth or not check_auth(auth.password or ''):
            return authenticate()
        return f(*args, **kwargs)
    return decorated  # type: ignore[return-value]


def data_path(*parts: str) -> str:
    """Return writable data path."""
    return os.path.join(DATA_DIR, *parts)


def get_json_body() -> dict[str, Any]:
    """Safely get JSON body from request, returning empty dict if missing."""
    data: Any = request.get_json(silent=True)
    if isinstance(data, dict):
        return cast(dict[str, Any], data)
    return {}


def safe_config_path(filename: str) -> str | None:
    """Resolve a config filename and verify it stays inside the config directory."""
    config_dir = os.path.realpath(data_path('server_configs'))
    filepath = os.path.realpath(os.path.join(config_dir, filename))
    if not filepath.startswith(config_dir + os.sep) and filepath != config_dir:
        return None
    if not filename.endswith('.cfg'):
        return None
    return filepath

# Global RCON client instance
rcon = RCONClient()

# Command history
command_history: list[dict[str, Any]] = []
MAX_HISTORY = 500

# Scheduled tasks with file persistence
SCHEDULED_TASKS_FILE = data_path('scheduled_tasks.json')
scheduled_tasks: dict[str, dict[str, Any]] = {}
_task_counter = 0
_task_counter_lock = threading.Lock()


def _load_scheduled_tasks() -> dict[str, dict[str, Any]]:
    """Load scheduled tasks from JSON file."""
    if os.path.exists(SCHEDULED_TASKS_FILE):
        try:
            with open(SCHEDULED_TASKS_FILE, 'r') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return cast(dict[str, dict[str, Any]], data)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_scheduled_tasks() -> None:
    """Persist scheduled tasks to JSON file (excludes timer objects)."""
    data: dict[str, dict[str, Any]] = {}
    for tid, task in scheduled_tasks.items():
        data[tid] = {k: v for k, v in task.items() if k != '_timer'}
    try:
        with open(SCHEDULED_TASKS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except OSError:
        logger.warning("Could not save scheduled tasks")


# Load persisted tasks on startup (timers inactive until restarted)
scheduled_tasks.update(_load_scheduled_tasks())
if scheduled_tasks:
    with _task_counter_lock:
        _task_counter = max(
            (int(tid.replace('task_', '')) for tid in scheduled_tasks if tid.startswith('task_')),
            default=0
        )

# CS2 Map Pool
CS2_MAPS: dict[str, list[str]] = {
    "Active Duty": [
        "de_mirage", "de_inferno", "de_nuke", "de_overpass",
        "de_ancient", "de_anubis", "de_vertigo", "de_dust2"
    ],
    "Hostage": [
        "cs_office", "cs_italy"
    ],
    "Wingman": [
        "de_inferno", "de_overpass", "de_vertigo", "de_nuke",
        "de_shortdust", "de_lake", "de_boyard"
    ],
    "Deathmatch": [
        "de_dust2", "de_mirage", "de_inferno", "de_nuke",
        "de_overpass", "de_ancient", "de_anubis"
    ],
    "Workshop": []
}

# Common server CVars with descriptions â€” comprehensive CS2 list
CS2_CVARS = {
    "General Server": {
        "hostname": {"desc": "Server name displayed in browser", "type": "string", "default": "CS2 Server"},
        "sv_password": {"desc": "Server password (empty = public)", "type": "string", "default": ""},
        "rcon_password": {"desc": "Remote console password", "type": "string", "default": ""},
        "sv_cheats": {"desc": "Allow cheat commands (0/1)", "type": "bool", "default": "0"},
        "sv_lan": {"desc": "LAN mode, no Steam auth (0/1)", "type": "bool", "default": "0"},
        "sv_visiblemaxplayers": {"desc": "Max visible player slots (-1 = use maxplayers)", "type": "int", "default": "-1"},
        "sv_hibernate_when_empty": {"desc": "Server hibernates when no players", "type": "bool", "default": "1"},
        "sv_hibernate_postgame_delay": {"desc": "Seconds to hibernate after game ends", "type": "int", "default": "5"},
        "sv_steamauth_enforce": {"desc": "Enforce Steam authentication", "type": "bool", "default": "1"},
    },
    "Game Mode": {
        "game_type": {"desc": "Game type (0=classic, 1=gungame, 2=training, 3=custom)", "type": "int", "default": "0"},
        "game_mode": {"desc": "Game mode (depends on game_type)", "type": "int", "default": "0"},
        "mp_match_end_restart": {"desc": "Restart map when match ends", "type": "bool", "default": "0"},
        "mp_match_end_changelevel": {"desc": "Change to next map when match ends", "type": "bool", "default": "0"},
        "mp_endmatch_votenextmap": {"desc": "Vote for next map at match end", "type": "bool", "default": "1"},
        "mp_endmatch_votenextleveltime": {"desc": "Time to vote for next map (seconds)", "type": "int", "default": "20"},
    },
    "Round Settings": {
        "mp_maxrounds": {"desc": "Max rounds per half (total = 2x for comp)", "type": "int", "default": "24"},
        "mp_roundtime": {"desc": "Round time in minutes", "type": "float", "default": "1.92"},
        "mp_roundtime_defuse": {"desc": "Round time for defuse maps (minutes)", "type": "float", "default": "1.92"},
        "mp_roundtime_hostage": {"desc": "Round time for hostage maps (minutes)", "type": "float", "default": "2.0"},
        "mp_freezetime": {"desc": "Freeze time at round start (seconds)", "type": "int", "default": "15"},
        "mp_buytime": {"desc": "Buy time after round start (seconds)", "type": "int", "default": "20"},
        "mp_buy_anywhere": {"desc": "Allow buying anywhere on map (0/1)", "type": "bool", "default": "0"},
        "mp_warmuptime": {"desc": "Warmup time (seconds)", "type": "int", "default": "60"},
        "mp_warmup_pausetimer": {"desc": "Pause warmup timer", "type": "bool", "default": "0"},
        "mp_halftime": {"desc": "Enable halftime", "type": "bool", "default": "1"},
        "mp_halftime_pausetimer": {"desc": "Pause halftime timer", "type": "bool", "default": "0"},
        "mp_halftime_duration": {"desc": "Halftime duration (seconds)", "type": "int", "default": "15"},
        "mp_overtime_enable": {"desc": "Enable overtime", "type": "bool", "default": "0"},
        "mp_overtime_maxrounds": {"desc": "Max overtime rounds", "type": "int", "default": "6"},
        "mp_overtime_startmoney": {"desc": "Overtime starting money", "type": "int", "default": "10000"},
        "mp_overtime_halftime_pausetimer": {"desc": "Pause timer at overtime halftime", "type": "bool", "default": "0"},
        "mp_match_can_clinch": {"desc": "Can clinch match early", "type": "bool", "default": "1"},
        "mp_timelimit": {"desc": "Map time limit (minutes, 0 = no limit)", "type": "int", "default": "0"},
        "mp_round_restart_delay": {"desc": "Delay between rounds (seconds)", "type": "int", "default": "7"},
        "mp_c4timer": {"desc": "Bomb timer (seconds)", "type": "int", "default": "40"},
        "mp_win_panel_display_time": {"desc": "Win panel display time (seconds)", "type": "int", "default": "3"},
    },
    "Teams & Players": {
        "mp_autoteambalance": {"desc": "Auto-balance teams (0/1)", "type": "bool", "default": "1"},
        "mp_limitteams": {"desc": "Max team imbalance (0 = no limit)", "type": "int", "default": "2"},
        "mp_friendlyfire": {"desc": "Friendly fire on/off", "type": "bool", "default": "0"},
        "ff_damage_reduction_bullets": {"desc": "Friendly fire bullet damage multiplier", "type": "float", "default": "0.33"},
        "ff_damage_reduction_grenade": {"desc": "Friendly fire grenade damage multiplier", "type": "float", "default": "0.85"},
        "ff_damage_reduction_other": {"desc": "Friendly fire other damage multiplier", "type": "float", "default": "0.4"},
        "mp_autokick": {"desc": "Auto-kick idle/TK players", "type": "bool", "default": "1"},
        "mp_tkpunish": {"desc": "Punish team killers", "type": "bool", "default": "0"},
        "mp_spawnprotectiontime": {"desc": "Spawn protection time (seconds)", "type": "float", "default": "5"},
        "mp_respawn_on_death_t": {"desc": "Auto respawn Terrorists (for DM)", "type": "bool", "default": "0"},
        "mp_respawn_on_death_ct": {"desc": "Auto respawn CTs (for DM)", "type": "bool", "default": "0"},
        "mp_respawn_immunitytime": {"desc": "Respawn immunity time (seconds)", "type": "float", "default": "4"},
        "mp_death_drop_grenade": {"desc": "Drop grenades on death (0/1)", "type": "bool", "default": "1"},
        "mp_death_drop_gun": {"desc": "Drop guns on death (0=none, 1=best, 2=current)", "type": "int", "default": "1"},
        "mp_death_drop_defuser": {"desc": "Drop defuser on death", "type": "bool", "default": "1"},
        "mp_force_pick_time": {"desc": "Time to force team pick (seconds)", "type": "int", "default": "15"},
        "mp_force_assign_teams": {"desc": "Force team assignment", "type": "bool", "default": "0"},
    },
    "Economy": {
        "mp_startmoney": {"desc": "Starting money", "type": "int", "default": "800"},
        "mp_maxmoney": {"desc": "Max money", "type": "int", "default": "16000"},
        "mp_afterroundmoney": {"desc": "Money given after each round", "type": "int", "default": "0"},
        "mp_playercashawards": {"desc": "Enable individual cash awards", "type": "bool", "default": "1"},
        "mp_teamcashawards": {"desc": "Enable team cash awards", "type": "bool", "default": "1"},
        "cash_team_terrorist_win_bomb": {"desc": "T win by bomb reward", "type": "int", "default": "3500"},
        "cash_team_win_by_defusing_bomb": {"desc": "CT win by defuse reward", "type": "int", "default": "3500"},
        "cash_team_win_by_time_running_out_bomb": {"desc": "CT win by time reward", "type": "int", "default": "3250"},
        "cash_team_elimination_hostage_map_t": {"desc": "T elimination on hostage map", "type": "int", "default": "3000"},
        "cash_team_elimination_hostage_map_ct": {"desc": "CT elimination on hostage map", "type": "int", "default": "3000"},
        "cash_team_elimination_bomb_map": {"desc": "Team elimination on bomb map", "type": "int", "default": "3250"},
        "cash_team_hostage_alive": {"desc": "Reward per alive hostage", "type": "int", "default": "0"},
        "cash_team_hostage_interaction": {"desc": "Reward for hostage interaction", "type": "int", "default": "600"},
        "cash_team_loser_bonus": {"desc": "Loser bonus starting amount", "type": "int", "default": "1400"},
        "cash_team_loser_bonus_consecutive_rounds": {"desc": "Consecutive loss bonus increment", "type": "int", "default": "500"},
        "cash_team_planted_bomb_but_defused": {"desc": "Planted bomb but CT defused reward", "type": "int", "default": "800"},
        "cash_team_rescued_hostage": {"desc": "Rescued hostage reward", "type": "int", "default": "3500"},
        "cash_player_bomb_defused": {"desc": "Individual defuse reward", "type": "int", "default": "300"},
        "cash_player_bomb_planted": {"desc": "Individual plant reward", "type": "int", "default": "300"},
        "cash_player_killed_enemy_default": {"desc": "Kill reward (default weapons)", "type": "int", "default": "300"},
        "cash_player_rescued_hostage": {"desc": "Individual hostage rescue reward", "type": "int", "default": "1000"},
    },
    "Communication": {
        "sv_alltalk": {"desc": "All players hear each other (0/1)", "type": "bool", "default": "0"},
        "sv_deadtalk": {"desc": "Dead players talk to alive (0/1)", "type": "bool", "default": "0"},
        "sv_talk_enemy_dead": {"desc": "Dead hear enemy dead (0/1)", "type": "bool", "default": "0"},
        "sv_talk_enemy_living": {"desc": "Hear enemy alive players (0/1)", "type": "bool", "default": "0"},
        "sv_voiceenable": {"desc": "Enable voice chat (0/1)", "type": "bool", "default": "1"},
        "sv_full_alltalk": {"desc": "All talk with no restrictions", "type": "bool", "default": "0"},
        "sv_auto_full_alltalk_during_warmup_half_end": {"desc": "Alltalk during warmup/halftime", "type": "bool", "default": "1"},
        "mp_teammates_are_enemies": {"desc": "Teammates are enemies (FFA mode)", "type": "bool", "default": "0"},
    },
    "Bots": {
        "bot_quota": {"desc": "Number of bots on server", "type": "int", "default": "0"},
        "bot_quota_mode": {"desc": "Bot fill mode (normal/fill/match)", "type": "string", "default": "normal"},
        "bot_difficulty": {"desc": "Bot difficulty (0=easy, 1=normal, 2=hard, 3=expert)", "type": "int", "default": "1"},
        "bot_chatter": {"desc": "Bot chatter (off/radio/minimal/normal)", "type": "string", "default": "normal"},
        "bot_join_after_player": {"desc": "Bots only join after a human player", "type": "bool", "default": "1"},
        "bot_allow_rogues": {"desc": "Allow bots to go rogue", "type": "bool", "default": "1"},
        "bot_allow_grenades": {"desc": "Allow bots to use grenades", "type": "bool", "default": "1"},
        "bot_allow_snipers": {"desc": "Allow bots to use snipers", "type": "bool", "default": "1"},
        "bot_allow_shotguns": {"desc": "Allow bots to use shotguns", "type": "bool", "default": "1"},
        "bot_allow_machine_guns": {"desc": "Allow bots to use machine guns", "type": "bool", "default": "1"},
        "bot_allow_pistols": {"desc": "Allow bots to use pistols", "type": "bool", "default": "1"},
        "bot_allow_rifles": {"desc": "Allow bots to use rifles", "type": "bool", "default": "1"},
        "bot_allow_sub_machine_guns": {"desc": "Allow bots to use SMGs", "type": "bool", "default": "1"},
        "bot_autodifficulty_threshold_high": {"desc": "Auto difficulty high threshold", "type": "float", "default": "5.0"},
        "bot_autodifficulty_threshold_low": {"desc": "Auto difficulty low threshold", "type": "float", "default": "-2.0"},
        "bot_max_vision_distance_override": {"desc": "Override bot vision distance (-1=default)", "type": "int", "default": "-1"},
        "bot_dont_shoot": {"desc": "Bots won't shoot", "type": "bool", "default": "0"},
        "bot_knives_only": {"desc": "Bots use knives only", "type": "bool", "default": "0"},
        "bot_stop": {"desc": "Bots freeze in place", "type": "bool", "default": "0"},
        "bot_zombie": {"desc": "Bot zombie mode (don't move but can aim/shoot)", "type": "bool", "default": "0"},
        "bot_mimic": {"desc": "Bots mimic a player's actions", "type": "bool", "default": "0"},
        "bot_crouch": {"desc": "Bots always crouch", "type": "bool", "default": "0"},
    },
    "Weapons & Items": {
        "mp_weapons_allow_typecount": {"desc": "Max same weapon type per team (-1=unlimited)", "type": "int", "default": "-1"},
        "mp_weapons_allow_map_placed": {"desc": "Allow map-placed weapons", "type": "bool", "default": "1"},
        "mp_ct_default_primary": {"desc": "CT default primary weapon", "type": "string", "default": ""},
        "mp_ct_default_secondary": {"desc": "CT default secondary weapon", "type": "string", "default": ""},
        "mp_ct_default_grenades": {"desc": "CT default grenades", "type": "string", "default": ""},
        "mp_t_default_primary": {"desc": "T default primary weapon", "type": "string", "default": ""},
        "mp_t_default_secondary": {"desc": "T default secondary weapon", "type": "string", "default": ""},
        "mp_t_default_grenades": {"desc": "T default grenades", "type": "string", "default": ""},
        "mp_give_player_c4": {"desc": "Give bomb to random T", "type": "bool", "default": "1"},
        "mp_defuser_allocation": {"desc": "CT defuser kits (0=none, 1=random, 2=all)", "type": "int", "default": "0"},
        "mp_free_armor": {"desc": "Free armor (0=none, 1=kevlar, 2=kevlar+helmet)", "type": "int", "default": "0"},
        "mp_weapons_allow_zeus": {"desc": "Allow Zeus (taser)", "type": "int", "default": "1"},
        "mp_buy_allow_grenades": {"desc": "Allow buying grenades", "type": "bool", "default": "1"},
        "ammo_grenade_limit_flashbang": {"desc": "Max flashbangs", "type": "int", "default": "2"},
        "ammo_grenade_limit_total": {"desc": "Max total grenades", "type": "int", "default": "4"},
        "sv_infinite_ammo": {"desc": "Infinite ammo (0=off, 1=infinite clip, 2=infinite reserve)", "type": "int", "default": "0"},
    },
    "Practice & Debug": {
        "mp_restartgame": {"desc": "Restart game countdown (seconds)", "type": "int", "default": "0"},
        "sv_grenade_trajectory_prac_pipreview": {"desc": "Show grenade trajectory preview", "type": "bool", "default": "0"},
        "sv_grenade_trajectory_prac_trailtime": {"desc": "Grenade trajectory trail time", "type": "float", "default": "4"},
        "sv_showimpacts": {"desc": "Show bullet impacts (0=off, 1=server, 2=client, 3=both)", "type": "int", "default": "0"},
        "sv_showimpacts_time": {"desc": "How long impacts stay visible (seconds)", "type": "float", "default": "4"},
        "mp_radar_showall": {"desc": "Show all players on radar (0/1)", "type": "bool", "default": "0"},
        "mp_solid_teammates": {"desc": "Solid teammates (0=walk-through, 1=solid, 2=push)", "type": "int", "default": "1"},
        "sv_enablebunnyhopping": {"desc": "Enable bunnyhopping", "type": "bool", "default": "0"},
        "sv_autobunnyhopping": {"desc": "Auto bunnyhopping (hold space)", "type": "bool", "default": "0"},
        "sv_staminamax": {"desc": "Max stamina (affects landing slowdown)", "type": "float", "default": "80"},
        "sv_staminalandcost": {"desc": "Stamina cost on landing", "type": "float", "default": "0.05"},
        "sv_staminajumpcost": {"desc": "Stamina cost per jump", "type": "float", "default": "0.08"},
        "phys_pushscale": {"desc": "Physics push scale", "type": "float", "default": "1"},
    },
    "Vote Settings": {
        "sv_vote_allow_spectators": {"desc": "Spectators can vote", "type": "bool", "default": "0"},
        "sv_vote_creation_timer": {"desc": "Seconds between vote creation", "type": "int", "default": "120"},
        "sv_vote_failure_timer": {"desc": "Seconds before failed vote can be re-called", "type": "int", "default": "300"},
        "sv_vote_quorum_ratio": {"desc": "Minimum vote ratio to pass", "type": "float", "default": "0.501"},
        "sv_vote_timer_duration": {"desc": "How long a vote lasts (seconds)", "type": "int", "default": "15"},
        "sv_vote_issue_kick_allowed": {"desc": "Allow kick votes", "type": "bool", "default": "1"},
        "sv_vote_issue_changemap_allowed": {"desc": "Allow map change votes", "type": "bool", "default": "1"},
        "sv_vote_issue_restart_game_allowed": {"desc": "Allow restart game votes", "type": "bool", "default": "1"},
        "sv_vote_issue_scramble_teams_allowed": {"desc": "Allow scramble teams votes", "type": "bool", "default": "1"},
    },
    "Damage & Hitboxes": {
        "mp_damage_scale_ct_head": {"desc": "CT headshot damage scale", "type": "float", "default": "1.0"},
        "mp_damage_scale_ct_body": {"desc": "CT body damage scale", "type": "float", "default": "1.0"},
        "mp_damage_scale_t_head": {"desc": "T headshot damage scale", "type": "float", "default": "1.0"},
        "mp_damage_scale_t_body": {"desc": "T body damage scale", "type": "float", "default": "1.0"},
        "mp_damage_headshot_only": {"desc": "Headshot only mode", "type": "bool", "default": "0"},
        "mp_damage_vampiric_amount": {"desc": "HP gained per damage dealt (0=off)", "type": "float", "default": "0"},
    },
    "Misc Gameplay": {
        "mp_display_kill_assists": {"desc": "Display kill assists", "type": "bool", "default": "1"},
        "mp_freezetime_skip_announce": {"desc": "Skip freeze time announcements", "type": "bool", "default": "0"},
        "mp_hostagepenalty": {"desc": "Hostage kills before kick (0=off)", "type": "int", "default": "5"},
        "mp_ignore_round_win_conditions": {"desc": "Ignore round win conditions", "type": "bool", "default": "0"},
        "mp_item_staytime": {"desc": "How long dropped items stay (seconds)", "type": "int", "default": "20"},
        "mp_spectators_max": {"desc": "Max spectators", "type": "int", "default": "2"},
        "sv_kick_ban_duration": {"desc": "Ban duration after kick (minutes, 0=permanent)", "type": "int", "default": "15"},
        "mp_drop_knife_enable": {"desc": "Allow dropping knife", "type": "bool", "default": "0"},
        "mp_backup_round_auto": {"desc": "Auto backup rounds", "type": "bool", "default": "1"},
        "mp_humanteam": {"desc": "Force human team (any/T/CT)", "type": "string", "default": "any"},
        "mp_endwarmup_player_count": {"desc": "Player count to auto-end warmup", "type": "int", "default": "0"},
        "sv_party_mode": {"desc": "Party mode (chicken hats, confetti)", "type": "bool", "default": "0"},
        "mp_randomspawn": {"desc": "Random spawn locations", "type": "bool", "default": "0"},
        "mp_randomspawn_los": {"desc": "Random spawn with line-of-sight check", "type": "bool", "default": "0"},
        "cs_enable_teammate_collision": {"desc": "Enable teammate collision", "type": "bool", "default": "1"},
    },
    "GOTV": {
        "tv_enable": {"desc": "Enable GOTV", "type": "bool", "default": "0"},
        "tv_name": {"desc": "GOTV bot name", "type": "string", "default": "GOTV"},
        "tv_title": {"desc": "GOTV broadcast title", "type": "string", "default": ""},
        "tv_delay": {"desc": "GOTV broadcast delay (seconds)", "type": "int", "default": "10"},
        "tv_maxclients": {"desc": "Max GOTV spectators", "type": "int", "default": "128"},
        "tv_maxrate": {"desc": "Max GOTV bandwidth rate", "type": "int", "default": "0"},
        "tv_snapshotrate": {"desc": "GOTV snapshots per second", "type": "int", "default": "32"},
        "tv_autorecord": {"desc": "Auto-record matches", "type": "bool", "default": "0"},
        "tv_password": {"desc": "GOTV password (empty = public)", "type": "string", "default": ""},
        "tv_allow_camera_man": {"desc": "Allow cameraman in GOTV", "type": "bool", "default": "1"},
    },
    "Network": {
        "sv_maxrate": {"desc": "Max bandwidth per client (0=unlimited)", "type": "int", "default": "0"},
        "sv_minrate": {"desc": "Min bandwidth per client", "type": "int", "default": "128000"},
        "sv_maxupdaterate": {"desc": "Max update rate to clients", "type": "int", "default": "128"},
        "sv_minupdaterate": {"desc": "Min update rate to clients", "type": "int", "default": "64"},
        "sv_maxcmdrate": {"desc": "Max client command rate", "type": "int", "default": "128"},
        "sv_mincmdrate": {"desc": "Min client command rate", "type": "int", "default": "64"},
        "net_maxroutable": {"desc": "Max routable packet size", "type": "int", "default": "1200"},
        "sv_allowupload": {"desc": "Allow client uploads", "type": "bool", "default": "1"},
        "sv_allowdownload": {"desc": "Allow client downloads", "type": "bool", "default": "1"},
        "sv_downloadurl": {"desc": "Fast download URL", "type": "string", "default": ""},
        "sv_pure": {"desc": "Pure server mode (0/1/2)", "type": "int", "default": "1"},
    },
    "Physics & Movement": {
        "sv_gravity": {"desc": "Server gravity (800=normal, 0=zero-g)", "type": "int", "default": "800"},
        "sv_friction": {"desc": "Surface friction amount", "type": "float", "default": "5.2"},
        "sv_airaccelerate": {"desc": "Air acceleration (higher = more air control)", "type": "int", "default": "12"},
        "sv_wateraccelerate": {"desc": "Water acceleration", "type": "int", "default": "10"},
        "sv_maxspeed": {"desc": "Max player movement speed", "type": "int", "default": "320"},
        "sv_accelerate": {"desc": "Ground acceleration", "type": "float", "default": "5.5"},
    },
    "Spectator": {
        "mp_forcecamera": {"desc": "Camera mode (0=any, 1=team only, 2=first person)", "type": "int", "default": "1"},
        "sv_specnoclip": {"desc": "Spectators can noclip", "type": "bool", "default": "1"},
        "sv_specspeed": {"desc": "Spectator speed multiplier", "type": "float", "default": "3.0"},
    },
    "Team Branding": {
        "mp_teamname_1": {"desc": "CT team name (empty = default)", "type": "string", "default": ""},
        "mp_teamname_2": {"desc": "T team name (empty = default)", "type": "string", "default": ""},
        "mp_teamflag_1": {"desc": "CT team flag (country code, e.g. US)", "type": "string", "default": ""},
        "mp_teamflag_2": {"desc": "T team flag (country code, e.g. DE)", "type": "string", "default": ""},
        "mp_teamlogo_1": {"desc": "CT team logo filename", "type": "string", "default": ""},
        "mp_teamlogo_2": {"desc": "T team logo filename", "type": "string", "default": ""},
    },
    "Hostage Mode": {
        "mp_hostages_max": {"desc": "Max hostages per map", "type": "int", "default": "1"},
        "mp_hostages_rescuetowin": {"desc": "Hostages needed to win round", "type": "int", "default": "1"},
        "mp_hostages_run_speed_modifier": {"desc": "Hostage run speed multiplier", "type": "float", "default": "1.0"},
    },
    "Server Logging": {
        "sv_logfile": {"desc": "Log server output to file", "type": "bool", "default": "1"},
        "sv_log_onefile": {"desc": "Use single log file (no rotation)", "type": "bool", "default": "0"},
        "con_logfile": {"desc": "Console log file path", "type": "string", "default": ""},
        "sv_logecho": {"desc": "Echo log output to console", "type": "bool", "default": "1"},
        "sv_logbans": {"desc": "Log ban commands to file", "type": "bool", "default": "1"},
    },
}

# Quick command presets â€” using proper CS2 RCON commands
QUICK_COMMANDS = {
    "Match Control": [
        {"label": "Restart Round", "cmd": "mp_restartgame 1"},
        {"label": "Restart (5s)", "cmd": "mp_restartgame 5"},
        {"label": "Pause Match", "cmd": "mp_pause_match"},
        {"label": "Unpause Match", "cmd": "mp_unpause_match"},
        {"label": "End Warmup", "cmd": "mp_warmup_end"},
        {"label": "Swap Teams", "cmd": "mp_swapteams"},
        {"label": "Scramble Teams", "cmd": "mp_scrambleteams"},
        {"label": "End Match", "cmd": "mp_maxrounds 0"},
    ],
    "Bots": [
        {"label": "Add T Bot", "cmd": "bot_add_t"},
        {"label": "Add CT Bot", "cmd": "bot_add_ct"},
        {"label": "Add Bot (any)", "cmd": "bot_add"},
        {"label": "Kick Bots", "cmd": "bot_kick"},
        {"label": "Freeze Bots", "cmd": "bot_stop 1"},
        {"label": "Unfreeze Bots", "cmd": "bot_stop 0"},
        {"label": "Bots Don't Shoot", "cmd": "bot_dont_shoot 1"},
        {"label": "Bots Can Shoot", "cmd": "bot_dont_shoot 0"},
        {"label": "Bots Knives Only", "cmd": "bot_knives_only 1"},
        {"label": "Bots All Weapons", "cmd": "bot_knives_only 0"},
        {"label": "Bot Difficulty Easy", "cmd": "bot_difficulty 0"},
        {"label": "Bot Difficulty Hard", "cmd": "bot_difficulty 2"},
        {"label": "Bot Difficulty Expert", "cmd": "bot_difficulty 3"},
        {"label": "Fill 10 Bots", "cmd": "bot_quota 10"},
        {"label": "Fill 20 Bots", "cmd": "bot_quota 20"},
        {"label": "Bots Zombie Mode", "cmd": "bot_zombie 1"},
    ],
    "Practice Mode": [
        {"label": "Cheats ON", "cmd": "sv_cheats 1"},
        {"label": "Cheats OFF", "cmd": "sv_cheats 0"},
        {"label": "Infinite Ammo ON", "cmd": "sv_infinite_ammo 1"},
        {"label": "Infinite Reserve Ammo", "cmd": "sv_infinite_ammo 2"},
        {"label": "Infinite Ammo OFF", "cmd": "sv_infinite_ammo 0"},
        {"label": "Nade Trajectory ON", "cmd": "sv_grenade_trajectory_prac_pipreview 1"},
        {"label": "Nade Trajectory OFF", "cmd": "sv_grenade_trajectory_prac_pipreview 0"},
        {"label": "Show Impacts ON", "cmd": "sv_showimpacts 1"},
        {"label": "Show Impacts OFF", "cmd": "sv_showimpacts 0"},
        {"label": "No Freeze Time", "cmd": "mp_freezetime 0"},
        {"label": "Long Round (60min)", "cmd": "mp_roundtime 60"},
        {"label": "Buy Anywhere", "cmd": "mp_buy_anywhere 1"},
        {"label": "Max Money", "cmd": "mp_maxmoney 65535"},
        {"label": "Start Money Max", "cmd": "mp_startmoney 65535"},
        {"label": "Bunny Hop ON", "cmd": "sv_enablebunnyhopping 1"},
        {"label": "Auto Bunny Hop", "cmd": "sv_autobunnyhopping 1"},
        {"label": "Show All on Radar", "cmd": "mp_radar_showall 1"},
    ],
    "Communication": [
        {"label": "Alltalk ON", "cmd": "sv_alltalk 1"},
        {"label": "Alltalk OFF", "cmd": "sv_alltalk 0"},
        {"label": "Full Alltalk ON", "cmd": "sv_full_alltalk 1"},
        {"label": "Full Alltalk OFF", "cmd": "sv_full_alltalk 0"},
        {"label": "Dead Talk ON", "cmd": "sv_deadtalk 1"},
        {"label": "Dead Talk OFF", "cmd": "sv_deadtalk 0"},
        {"label": "Voice ON", "cmd": "sv_voiceenable 1"},
        {"label": "Voice OFF", "cmd": "sv_voiceenable 0"},
    ],
    "Game Rules": [
        {"label": "Friendly Fire ON", "cmd": "mp_friendlyfire 1"},
        {"label": "Friendly Fire OFF", "cmd": "mp_friendlyfire 0"},
        {"label": "Headshot Only ON", "cmd": "mp_damage_headshot_only 1"},
        {"label": "Headshot Only OFF", "cmd": "mp_damage_headshot_only 0"},
        {"label": "Free Armor+Helmet", "cmd": "mp_free_armor 2"},
        {"label": "Free Kevlar Only", "cmd": "mp_free_armor 1"},
        {"label": "No Free Armor", "cmd": "mp_free_armor 0"},
        {"label": "All Defusers", "cmd": "mp_defuser_allocation 2"},
        {"label": "No Defusers", "cmd": "mp_defuser_allocation 0"},
        {"label": "FFA Deathmatch", "cmd": "mp_teammates_are_enemies 1"},
        {"label": "Normal Teams", "cmd": "mp_teammates_are_enemies 0"},
        {"label": "C4 Timer 25s", "cmd": "mp_c4timer 25"},
        {"label": "C4 Timer 40s", "cmd": "mp_c4timer 40"},
        {"label": "C4 Timer 60s", "cmd": "mp_c4timer 60"},
        {"label": "Drop Knife ON", "cmd": "mp_drop_knife_enable 1"},
        {"label": "Walk-Through Teammates", "cmd": "mp_solid_teammates 0"},
    ],
    "Admin & Server": [
        {"label": "Server Status", "cmd": "status"},
        {"label": "List Maps", "cmd": "maps *"},
        {"label": "Write Config", "cmd": "host_writeconfig"},
        {"label": "Ban List", "cmd": "banlist"},
        {"label": "Write Ban List", "cmd": "writeid"},
        {"label": "GOTV ON", "cmd": "tv_enable 1"},
        {"label": "GOTV OFF", "cmd": "tv_enable 0"},
        {"label": "Exec server.cfg", "cmd": "exec server.cfg"},
        {"label": "Exec gamemode_competitive.cfg", "cmd": "exec gamemode_competitive.cfg"},
        {"label": "Exec gamemode_casual.cfg", "cmd": "exec gamemode_casual.cfg"},
        {"label": "Exec gamemode_deathmatch.cfg", "cmd": "exec gamemode_deathmatch.cfg"},
        {"label": "Exec gamemode_armsrace.cfg", "cmd": "exec gamemode_armsrace.cfg"},
        {"label": "Hibernate OFF", "cmd": "sv_hibernate_when_empty 0"},
    ],
    "GOTV": [
        {"label": "GOTV Status", "cmd": "tv_status"},
        {"label": "GOTV Enable", "cmd": "tv_enable 1"},
        {"label": "GOTV Disable", "cmd": "tv_enable 0"},
        {"label": "GOTV Stop Record", "cmd": "tv_stoprecord"},
        {"label": "GOTV Delay 10s", "cmd": "tv_delay 10"},
        {"label": "GOTV Delay 30s", "cmd": "tv_delay 30"},
        {"label": "GOTV Delay 60s", "cmd": "tv_delay 60"},
        {"label": "GOTV Delay 90s", "cmd": "tv_delay 90"},
        {"label": "GOTV Auto-Record ON", "cmd": "tv_autorecord 1"},
        {"label": "GOTV Auto-Record OFF", "cmd": "tv_autorecord 0"},
    ],
    "Warmup & Halftime": [
        {"label": "End Warmup", "cmd": "mp_warmup_end"},
        {"label": "Start Warmup", "cmd": "mp_warmup_start"},
        {"label": "Pause Warmup Timer", "cmd": "mp_warmup_pausetimer 1"},
        {"label": "Resume Warmup Timer", "cmd": "mp_warmup_pausetimer 0"},
        {"label": "Warmup 30s", "cmd": "mp_warmuptime 30"},
        {"label": "Warmup 60s", "cmd": "mp_warmuptime 60"},
        {"label": "Warmup 120s", "cmd": "mp_warmuptime 120"},
        {"label": "Pause Halftime", "cmd": "mp_halftime_pausetimer 1"},
        {"label": "Resume Halftime", "cmd": "mp_halftime_pausetimer 0"},
    ],
    "Round Backups": [
        {"label": "Auto Backup ON", "cmd": "mp_backup_round_auto 1"},
        {"label": "Auto Backup OFF", "cmd": "mp_backup_round_auto 0"},
        {"label": "Show Last Backup", "cmd": "mp_backup_round_file_last"},
    ],
    "Economy Shortcuts": [
        {"label": "Max Start Money", "cmd": "mp_startmoney 65535"},
        {"label": "Normal Start ($800)", "cmd": "mp_startmoney 800"},
        {"label": "Rich Start ($16000)", "cmd": "mp_startmoney 16000"},
        {"label": "Max Money Cap", "cmd": "mp_maxmoney 65535"},
        {"label": "Normal Money Cap", "cmd": "mp_maxmoney 16000"},
        {"label": "Free Money Each Round", "cmd": "mp_afterroundmoney 16000"},
        {"label": "No Free Money", "cmd": "mp_afterroundmoney 0"},
        {"label": "Cash Awards ON", "cmd": "mp_playercashawards 1"},
        {"label": "Cash Awards OFF", "cmd": "mp_playercashawards 0"},
        {"label": "Team Awards ON", "cmd": "mp_teamcashawards 1"},
        {"label": "Team Awards OFF", "cmd": "mp_teamcashawards 0"},
    ],
    "Physics Fun": [
        {"label": "Normal Gravity", "cmd": "sv_gravity 800"},
        {"label": "Moon Gravity", "cmd": "sv_gravity 200"},
        {"label": "Zero Gravity", "cmd": "sv_gravity 0"},
        {"label": "Heavy Gravity", "cmd": "sv_gravity 1600"},
        {"label": "Low Friction", "cmd": "sv_friction 1"},
        {"label": "Normal Friction", "cmd": "sv_friction 5.2"},
        {"label": "High Speed", "cmd": "sv_maxspeed 600"},
        {"label": "Normal Speed", "cmd": "sv_maxspeed 320"},
        {"label": "Surf Air Accel", "cmd": "sv_airaccelerate 150"},
        {"label": "Normal Air Accel", "cmd": "sv_airaccelerate 12"},
    ],
    "Overtime Controls": [
        {"label": "Overtime ON", "cmd": "mp_overtime_enable 1"},
        {"label": "Overtime OFF", "cmd": "mp_overtime_enable 0"},
        {"label": "OT 6 Rounds", "cmd": "mp_overtime_maxrounds 6"},
        {"label": "OT 3 Rounds", "cmd": "mp_overtime_maxrounds 3"},
        {"label": "Clinch ON", "cmd": "mp_match_can_clinch 1"},
        {"label": "Clinch OFF", "cmd": "mp_match_can_clinch 0"},
        {"label": "OT Money $10000", "cmd": "mp_overtime_startmoney 10000"},
        {"label": "OT Money $16000", "cmd": "mp_overtime_startmoney 16000"},
    ],
    "Logging": [
        {"label": "Log ON", "cmd": "log on"},
        {"label": "Log OFF", "cmd": "log off"},
        {"label": "Log Bans ON", "cmd": "sv_logbans 1"},
        {"label": "Log Echo ON", "cmd": "sv_logecho 1"},
        {"label": "Log Echo OFF", "cmd": "sv_logecho 0"},
    ],
}

# Config file templates
CONFIG_TEMPLATES: dict[str, dict[str, Any]] = {
    "competitive": {
        "name": "Competitive 5v5",
        "description": "Standard competitive settings (MR12)",
        "cvars": {
            "mp_maxrounds": "24",
            "mp_overtime_enable": "1",
            "mp_overtime_maxrounds": "6",
            "mp_freezetime": "15",
            "mp_roundtime_defuse": "1.92",
            "mp_roundtime_hostage": "2.0",
            "mp_buytime": "20",
            "mp_startmoney": "800",
            "mp_maxmoney": "16000",
            "mp_friendlyfire": "1",
            "mp_autoteambalance": "0",
            "mp_limitteams": "0",
            "mp_halftime": "1",
            "mp_match_can_clinch": "1",
            "sv_alltalk": "0",
            "sv_deadtalk": "0",
            "sv_talk_enemy_dead": "0",
            "bot_quota": "0",
            "mp_warmuptime": "60",
        }
    },
    "casual": {
        "name": "Casual",
        "description": "Casual gameplay settings",
        "cvars": {
            "mp_maxrounds": "15",
            "mp_freezetime": "5",
            "mp_roundtime_defuse": "2.25",
            "mp_buytime": "45",
            "mp_startmoney": "1000",
            "mp_maxmoney": "16000",
            "mp_friendlyfire": "0",
            "mp_autoteambalance": "1",
            "mp_limitteams": "2",
            "sv_alltalk": "1",
            "mp_warmuptime": "90",
        }
    },
    "deathmatch": {
        "name": "Deathmatch",
        "description": "Free-for-all deathmatch settings",
        "cvars": {
            "mp_maxrounds": "0",
            "mp_timelimit": "10",
            "mp_friendlyfire": "0",
            "mp_autoteambalance": "1",
            "mp_startmoney": "16000",
            "mp_maxmoney": "16000",
            "mp_buytime": "9999",
            "mp_buy_anywhere": "1",
            "mp_warmuptime": "15",
            "mp_respawn_on_death_t": "1",
            "mp_respawn_on_death_ct": "1",
            "sv_infinite_ammo": "2",
        }
    },
    "practice": {
        "name": "Practice / Nade Practice",
        "description": "Practice config with grenade trajectories and no limits",
        "cvars": {
            "sv_cheats": "1",
            "sv_infinite_ammo": "1",
            "mp_freezetime": "0",
            "mp_roundtime_defuse": "60",
            "mp_roundtime": "60",
            "mp_buytime": "9999",
            "mp_buy_anywhere": "1",
            "mp_maxmoney": "65535",
            "mp_startmoney": "65535",
            "mp_warmuptime": "0",
            "mp_warmup_end": "",
            "bot_kick": "",
            "mp_autoteambalance": "0",
            "mp_limitteams": "0",
            "sv_grenade_trajectory_prac_pipreview": "1",
            "sv_showimpacts": "1",
            "mp_restartgame": "1",
        }
    },
    "wingman": {
        "name": "Wingman 2v2",
        "description": "Wingman competitive settings",
        "cvars": {
            "mp_maxrounds": "16",
            "mp_freezetime": "10",
            "mp_roundtime_defuse": "1.5",
            "mp_buytime": "20",
            "mp_startmoney": "800",
            "mp_maxmoney": "16000",
            "mp_friendlyfire": "1",
            "mp_autoteambalance": "0",
            "mp_limitteams": "0",
            "mp_halftime": "1",
            "mp_warmuptime": "60",
            "bot_quota": "0",
        }
    },
    "retake": {
        "name": "Retake",
        "description": "Retake practice â€” short rounds, free armor, fast buys",
        "cvars": {
            "mp_maxrounds": "30",
            "mp_freezetime": "3",
            "mp_roundtime_defuse": "0.75",
            "mp_buytime": "5",
            "mp_startmoney": "16000",
            "mp_maxmoney": "16000",
            "mp_free_armor": "2",
            "mp_defuser_allocation": "2",
            "mp_friendlyfire": "0",
            "mp_autoteambalance": "0",
            "mp_limitteams": "0",
            "mp_round_restart_delay": "3",
            "mp_warmuptime": "15",
            "sv_alltalk": "1",
        }
    },
    "1v1_arena": {
        "name": "1v1 Arena",
        "description": "1v1 aim duels â€” headshot only, free armor, infinite money",
        "cvars": {
            "mp_maxrounds": "30",
            "mp_freezetime": "3",
            "mp_roundtime": "1.0",
            "mp_buytime": "10",
            "mp_startmoney": "65535",
            "mp_maxmoney": "65535",
            "mp_free_armor": "2",
            "mp_damage_headshot_only": "1",
            "mp_friendlyfire": "0",
            "mp_autoteambalance": "0",
            "mp_limitteams": "0",
            "mp_warmuptime": "15",
            "bot_quota": "0",
            "sv_alltalk": "1",
        }
    },
    "knife_round": {
        "name": "Knife Round",
        "description": "Knife-only round for side picks",
        "cvars": {
            "mp_maxrounds": "1",
            "mp_freezetime": "5",
            "mp_roundtime": "3",
            "mp_ct_default_primary": "",
            "mp_ct_default_secondary": "",
            "mp_t_default_primary": "",
            "mp_t_default_secondary": "",
            "mp_give_player_c4": "0",
            "mp_free_armor": "1",
            "mp_startmoney": "0",
            "mp_friendlyfire": "0",
            "mp_warmuptime": "10",
            "mp_drop_knife_enable": "0",
        }
    },
    "aim_training": {
        "name": "Aim Training",
        "description": "Practice aim â€” infinite ammo, impacts visible, long rounds",
        "cvars": {
            "sv_cheats": "1",
            "sv_infinite_ammo": "2",
            "mp_freezetime": "0",
            "mp_roundtime": "60",
            "mp_buytime": "9999",
            "mp_buy_anywhere": "1",
            "mp_maxmoney": "65535",
            "mp_startmoney": "65535",
            "mp_warmuptime": "0",
            "sv_showimpacts": "1",
            "mp_friendlyfire": "0",
            "mp_respawn_on_death_t": "1",
            "mp_respawn_on_death_ct": "1",
            "mp_free_armor": "2",
        }
    },
    "surf": {
        "name": "Surf / Bhop",
        "description": "Surf & bunny hop settings â€” auto bhop, no stamina",
        "cvars": {
            "sv_cheats": "1",
            "sv_enablebunnyhopping": "1",
            "sv_autobunnyhopping": "1",
            "sv_staminamax": "0",
            "sv_staminalandcost": "0",
            "sv_staminajumpcost": "0",
            "sv_infinite_ammo": "1",
            "mp_freezetime": "0",
            "mp_roundtime": "60",
            "mp_respawn_on_death_t": "1",
            "mp_respawn_on_death_ct": "1",
            "mp_friendlyfire": "0",
            "mp_warmuptime": "0",
        }
    },
    "hide_and_seek": {
        "name": "Hide and Seek",
        "description": "Hide and Seek â€” CTs seek after freeze, no radar, long rounds",
        "cvars": {
            "mp_maxrounds": "10",
            "mp_freezetime": "30",
            "mp_roundtime": "5",
            "mp_buytime": "0",
            "mp_startmoney": "0",
            "mp_friendlyfire": "0",
            "sv_alltalk": "0",
            "mp_radar_showall": "0",
            "mp_give_player_c4": "0",
            "mp_free_armor": "0",
            "mp_death_drop_gun": "0",
            "mp_warmuptime": "15",
        }
    },
}


def add_to_history(command: str, response: str, success: bool = True):
    """Add command and response to history."""
    entry: dict[str, Any] = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "command": command,
        "response": response,
        "success": success
    }
    command_history.append(entry)
    if len(command_history) > MAX_HISTORY:
        command_history.pop(0)


def parse_cvar_response(cvar_name: str, response: str) -> str:
    """
    Parse a CVar query response from CS2 to extract the current value.
    CS2 returns CVar values in various formats:
      "mp_maxrounds" = "24" ( def. "24" )
      "hostname" = "My Server" ( def. "" )
      "mp_maxrounds" is "24"
      mp_maxrounds = 24
      sv_cheats = false
    """
    if not response:
        return ""

    # Pattern 1: "cvar" = "value" (standard CS2 format with quotes)
    match = re.search(r'"' + re.escape(cvar_name) + r'"\s*=\s*"([^"]*)"', response)
    if match:
        return match.group(1)

    # Pattern 2: "cvar" is "value"
    match = re.search(r'"' + re.escape(cvar_name) + r'"\s+is\s+"([^"]*)"', response)
    if match:
        return match.group(1)

    # Pattern 3: Just look for = "value" anywhere (quoted)
    match = re.search(r'=\s*"([^"]*)"', response)
    if match:
        return match.group(1)

    # Pattern 4: cvar = value (unquoted, CS2 simple format)
    match = re.search(re.escape(cvar_name) + r'\s*=\s*(.+)', response)
    if match:
        return match.group(1).strip()

    # Pattern 5: response is just the value itself (simple commands)
    stripped = response.strip()
    if stripped and '\n' not in stripped and len(stripped) < 100:
        return stripped

    return ""


# ============== ROUTES ==============

@app.route('/')
@requires_auth
def index():
    """Main dashboard page."""
    return render_template('index.html')


@app.route('/api/connect', methods=['POST'])
@requires_auth
def api_connect():
    """Connect to the RCON server."""
    data = get_json_body()
    host = str(data.get('host', '')).strip()
    port = int(data.get('port', 27015))
    password = str(data.get('password', '')).strip()

    if not host or not password:
        return jsonify({"success": False, "error": "Host and password are required"})

    try:
        rcon.connect(host, port, password)
        add_to_history(f"[CONNECT] {host}:{port}", "Connected successfully")

        # Save last connection
        save_last_connection(host, port, password)

        return jsonify({
            "success": True,
            "message": f"Connected to {host}:{port}"
        })
    except RCONAuthError as e:
        add_to_history(f"[CONNECT] {host}:{port}", str(e), False)
        return jsonify({"success": False, "error": str(e)})
    except RCONConnectionError as e:
        add_to_history(f"[CONNECT] {host}:{port}", str(e), False)
        return jsonify({"success": False, "error": str(e)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/disconnect', methods=['POST'])
@requires_auth
def api_disconnect():
    """Disconnect from the RCON server."""
    rcon.disconnect()
    add_to_history("[DISCONNECT]", "Disconnected from server")
    return jsonify({"success": True, "message": "Disconnected"})


@app.route('/api/status', methods=['GET'])
@requires_auth
def api_status():
    """Get connection status and basic server info."""
    connected = rcon.is_connected()
    result: dict[str, Any] = {
        "connected": connected,
        "host": rcon.host,
        "port": rcon.port
    }

    if connected:
        try:
            info = rcon.get_server_info()
            result.update(info)
        except Exception as e:
            result['error'] = str(e)
            result['connected'] = False

    return jsonify(result)


@app.route('/api/command', methods=['POST'])
@requires_auth
def api_command():
    """Execute an RCON command. Auto-handles cheat-protected cvars."""
    data = get_json_body()
    command = str(data.get('command', '')).strip()

    if not command:
        return jsonify({"success": False, "error": "No command provided"})

    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected to server"})

    try:
        response = rcon.execute(command)

        # If the command was rejected as cheat-protected, auto-enable sv_cheats,
        # re-run the command, then disable sv_cheats again
        if response and 'cheat protected' in response.lower():
            logger.info(f"Cheat-protected command detected: {command} â€” enabling sv_cheats temporarily")
            rcon.execute("sv_cheats 1")
            time.sleep(0.05)
            response = rcon.execute(command)
            time.sleep(0.05)
            rcon.execute("sv_cheats 0")
            add_to_history(command, f"(cheat-unlocked) {response}")
            return jsonify({
                "success": True,
                "response": response,
                "command": command,
                "cheat_unlocked": True
            })

        add_to_history(command, response)
        return jsonify({
            "success": True,
            "response": response,
            "command": command
        })
    except RCONConnectionError as e:
        add_to_history(command, str(e), False)
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/players', methods=['GET'])
@requires_auth
def api_players():
    """Get list of connected players."""
    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected"})

    try:
        players = rcon.get_players()
        return jsonify({"success": True, "players": players})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/kick', methods=['POST'])
@requires_auth
def api_kick():
    """Kick a player."""
    data = get_json_body()
    player_id = str(data.get('player_id', ''))
    reason = str(data.get('reason', ''))

    if not player_id:
        return jsonify({"success": False, "error": "No player ID"})

    try:
        response = rcon.kick_player(player_id, reason)
        add_to_history(f"kick {player_id}", response)
        return jsonify({"success": True, "response": response})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/ban', methods=['POST'])
@requires_auth
def api_ban():
    """Ban a player."""
    data = get_json_body()
    player_id = str(data.get('player_id', ''))
    duration = int(data.get('duration', 0))

    if not player_id:
        return jsonify({"success": False, "error": "No player ID"})

    try:
        response = rcon.ban_player(player_id, duration)
        add_to_history(f"ban {player_id} {duration}m", response)
        return jsonify({"success": True, "response": response})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/changemap', methods=['POST'])
@requires_auth
def api_changemap():
    """Change the map."""
    data = get_json_body()
    map_name = str(data.get('map', '')).strip()

    if not map_name:
        return jsonify({"success": False, "error": "No map specified"})

    # Only allow safe map name characters (letters, digits, underscore, hyphen)
    if not re.match(r'^[a-zA-Z0-9_\-]+$', map_name):
        return jsonify({"success": False, "error": "Invalid map name"})

    try:
        response = rcon.change_map(map_name)
        add_to_history(f"changelevel {map_name}", response or "Map change initiated")
        return jsonify({"success": True, "response": response or "Map change initiated"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/say', methods=['POST'])
@requires_auth
def api_say():
    """Send a message to server chat."""
    data = get_json_body()
    message = str(data.get('message', '')).strip()

    if not message:
        return jsonify({"success": False, "error": "No message"})

    # Strip quotes to prevent RCON command injection via say
    message = message.replace('"', '').replace("'", '')

    try:
        response = rcon.say(message)
        add_to_history(f'say "{message}"', response or "Message sent")
        return jsonify({"success": True, "response": "Message sent"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/cvar', methods=['POST'])
@requires_auth
def api_set_cvar():
    """Set a server CVar. Auto-handles cheat-protected cvars."""
    data = get_json_body()
    cvar = str(data.get('cvar', '')).strip()
    value = str(data.get('value', '')).strip()

    if not cvar:
        return jsonify({"success": False, "error": "No CVar specified"})

    try:
        response = rcon.set_cvar(cvar, value)

        # Auto-handle cheat-protected cvars
        if response and 'cheat protected' in response.lower():
            logger.info(f"Cheat-protected cvar: {cvar} â€” enabling sv_cheats temporarily")
            rcon.execute("sv_cheats 1")
            time.sleep(0.05)
            response = rcon.set_cvar(cvar, value)
            time.sleep(0.05)
            rcon.execute("sv_cheats 0")

        add_to_history(f"{cvar} {value}", response)
        return jsonify({"success": True, "response": response})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/cvar/<cvar_name>', methods=['GET'])
def api_get_cvar(cvar_name: str):
    """Get a server CVar value."""
    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected"})

    try:
        response = rcon.get_cvar(cvar_name)
        value = parse_cvar_response(cvar_name, response)
        return jsonify({"success": True, "cvar": cvar_name, "value": value, "response": response})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/cvar/batch', methods=['POST'])
def api_get_cvars_batch():
    """Batch-fetch current server values for multiple CVars."""
    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected"})

    data = get_json_body()
    cvar_names = data.get('cvars', [])

    if not cvar_names:
        return jsonify({"success": False, "error": "No cvars specified"})

    results = {}
    for cvar_name in cvar_names:
        try:
            response = rcon.get_cvar(cvar_name)
            value = parse_cvar_response(cvar_name, response)
            results[cvar_name] = {"value": value, "raw": response}
            time.sleep(0.02)  # Small delay to avoid flooding
        except Exception as e:
            results[cvar_name] = {"value": None, "error": str(e)}

    return jsonify({"success": True, "values": results})


@app.route('/api/apply_template', methods=['POST'])
@requires_auth
def api_apply_template():
    """Apply a config template to the server."""
    data = get_json_body()
    template_name = str(data.get('template', ''))

    if template_name not in CONFIG_TEMPLATES:
        return jsonify({"success": False, "error": "Unknown template"})

    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected"})

    template: dict[str, Any] = CONFIG_TEMPLATES[template_name]
    results: list[str] = []

    try:
        for cvar, value in template['cvars'].items():
            if value:  # Skip empty values (they're commands, not cvars)
                rcon.execute(f"{cvar} {value}")
                results.append(f"{cvar} {value}")
            else:
                rcon.execute(cvar)
                results.append(cvar)
            time.sleep(0.05)  # Small delay between commands

        summary = f"Applied '{template['name']}' template ({len(results)} commands)"
        add_to_history(f"[TEMPLATE] {template['name']}", summary)
        return jsonify({"success": True, "response": summary, "details": results})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/maps', methods=['GET'])
def api_maps():
    """Get map pool."""
    return jsonify({"success": True, "maps": CS2_MAPS})


# ============== WORKSHOP MAPS ==============

WORKSHOP_MAPS_FILE = data_path('workshop_maps.json')


def load_workshop_maps() -> list[dict[str, str]]:
    """Load saved workshop maps from JSON file."""
    if os.path.exists(WORKSHOP_MAPS_FILE):
        with open(WORKSHOP_MAPS_FILE, 'r') as f:
            return json.load(f)
    return []


def save_workshop_maps(maps: list[dict[str, str]]):
    """Save workshop maps to JSON file."""
    with open(WORKSHOP_MAPS_FILE, 'w') as f:
        json.dump(maps, f, indent=2)


def parse_workshop_id(input_str: str) -> str | None:
    """Extract workshop ID from a URL or raw ID string."""
    input_str = input_str.strip()
    # Direct numeric ID
    if input_str.isdigit():
        return input_str
    # URL like https://steamcommunity.com/sharedfiles/filedetails/?id=3592238209
    match = re.search(r'[?&]id=(\d+)', input_str)
    if match:
        return match.group(1)
    # URL with just the number at the end
    match = re.search(r'(\d{6,})', input_str)
    if match:
        return match.group(1)
    return None


@app.route('/api/workshop/maps', methods=['GET'])
def api_workshop_maps():
    """Get saved workshop maps."""
    maps = load_workshop_maps()
    return jsonify({"success": True, "maps": maps})


@app.route('/api/workshop/add', methods=['POST'])
@requires_auth
def api_workshop_add():
    """Add a workshop map to favorites."""
    data = get_json_body()
    workshop_input = str(data.get('workshop_id', '')).strip()
    name = str(data.get('name', '')).strip()

    workshop_id = parse_workshop_id(workshop_input)
    if not workshop_id:
        return jsonify({"success": False, "error": "Invalid workshop ID or URL. Paste a Steam Workshop link or numeric ID."})

    if not name:
        name = f"Workshop Map {workshop_id}"

    maps = load_workshop_maps()

    # Check if already added
    for m in maps:
        if m['id'] == workshop_id:
            return jsonify({"success": False, "error": f"Map {workshop_id} already saved as '{m['name']}'."})

    maps.append({
        "id": workshop_id,
        "name": name,
        "added": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "url": f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
    })
    save_workshop_maps(maps)

    return jsonify({"success": True, "message": f"Added '{name}' (ID: {workshop_id})", "maps": maps})


@app.route('/api/workshop/remove', methods=['POST'])
@requires_auth
def api_workshop_remove():
    """Remove a workshop map from favorites."""
    data = get_json_body()
    workshop_id = str(data.get('workshop_id', '')).strip()

    maps = load_workshop_maps()
    maps = [m for m in maps if m['id'] != workshop_id]
    save_workshop_maps(maps)

    return jsonify({"success": True, "message": "Map removed", "maps": maps})


@app.route('/api/workshop/load', methods=['POST'])
@requires_auth
def api_workshop_load():
    """Load a workshop map on the server via RCON."""
    data = get_json_body()
    workshop_id = str(data.get('workshop_id', '')).strip()

    if not workshop_id or not workshop_id.isdigit():
        return jsonify({"success": False, "error": "Invalid workshop ID"})

    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected to server"})

    try:
        # CS2 command to load a workshop map
        response = rcon.execute(f"host_workshop_map {workshop_id}")
        add_to_history(f"host_workshop_map {workshop_id}", response or "Workshop map loading...")
        return jsonify({"success": True, "response": response or f"Loading workshop map {workshop_id}..."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/cvars', methods=['GET'])
def api_cvars():
    """Get CVar definitions."""
    return jsonify({"success": True, "cvars": CS2_CVARS})


@app.route('/api/quick_commands', methods=['GET'])
def api_quick_commands():
    """Get quick command presets."""
    return jsonify({"success": True, "commands": QUICK_COMMANDS})


@app.route('/api/templates', methods=['GET'])
def api_templates():
    """Get config templates."""
    templates = {}
    for key, tpl in CONFIG_TEMPLATES.items():
        templates[key] = {
            "name": tpl['name'],
            "description": tpl['description'],
            "cvar_count": len(tpl['cvars'])
        }
    return jsonify({"success": True, "templates": templates})


@app.route('/api/history', methods=['GET'])
def api_history():
    """Get command history."""
    return jsonify({"success": True, "history": command_history})


@app.route('/api/history/clear', methods=['POST'])
def api_clear_history():
    """Clear command history."""
    command_history.clear()
    return jsonify({"success": True})


@app.route('/api/export_config', methods=['POST'])
@requires_auth
def api_export_config():
    """Export current server settings as a config file."""
    data = get_json_body()
    name = str(data.get('name', 'custom_config'))
    cvars = data.get('cvars', {})

    config_dir = data_path('server_configs')
    os.makedirs(config_dir, exist_ok=True)

    filename = f"{name}.cfg"
    filepath = os.path.join(config_dir, filename)

    lines = [
        f"// CS2 Server Config: {name}",
        f"// Generated by CS2 Server Controller on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "// ==========================================",
        ""
    ]

    for cvar, value in cvars.items():
        lines.append(f'{cvar} "{value}"')

    with open(filepath, 'w') as f:
        f.write('\n'.join(lines))

    return jsonify({"success": True, "filename": filename, "path": filepath})


@app.route('/api/saved_configs', methods=['GET'])
def api_saved_configs():
    """List saved config files."""
    config_dir = data_path('server_configs')
    os.makedirs(config_dir, exist_ok=True)

    configs: list[dict[str, Any]] = []
    for f in os.listdir(config_dir):
        if f.endswith('.cfg'):
            filepath = os.path.join(config_dir, f)
            configs.append({
                "name": f,
                "size": os.path.getsize(filepath),
                "modified": datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M:%S')
            })

    return jsonify({"success": True, "configs": configs})


@app.route('/api/load_config/<filename>', methods=['GET'])
def api_load_config(filename: str):
    """Load a saved config file content."""
    filepath = safe_config_path(filename)
    if not filepath or not os.path.exists(filepath):
        return jsonify({"success": False, "error": "Config file not found"})

    with open(filepath, 'r') as f:
        content = f.read()

    return jsonify({"success": True, "filename": filename, "content": content})


@app.route('/api/delete_config/<filename>', methods=['DELETE'])
@requires_auth
def api_delete_config(filename: str):
    """Delete a saved config file."""
    filepath = safe_config_path(filename)
    if not filepath or not os.path.exists(filepath):
        return jsonify({"success": False, "error": "Config file not found"})

    try:
        os.remove(filepath)
        return jsonify({"success": True, "message": f"Deleted {filename}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ============== HELPERS ==============

def save_last_connection(host: str, port: int, password: str) -> None:
    """Save last successful connection details."""
    config_path = data_path('last_connection.json')
    data: dict[str, Any] = {"host": host, "port": port, "password": password}
    try:
        with open(config_path, 'w') as f:
            json.dump(data, f)
    except OSError:
        logger.warning("Could not save last connection (read-only filesystem)")


def load_last_connection():
    """Load last connection details."""
    config_path = data_path('last_connection.json')
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            return json.load(f)
    return None


@app.route('/favicon.ico')
def favicon():
    """Serve empty favicon to suppress 404."""
    return '', 204


@app.route('/api/last_connection', methods=['GET'])
@requires_auth
def api_last_connection():
    """Get last saved connection."""
    conn = load_last_connection()
    if conn:
        return jsonify({"success": True, "connection": conn})
    return jsonify({"success": False})


# ============== SERVER PERFORMANCE STATS ==============

@app.route('/api/server/stats', methods=['GET'])
@requires_auth
def api_server_stats():
    """Get server performance stats via the 'stats' RCON command."""
    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected"})
    try:
        raw = rcon.execute("stats")
        stats: dict[str, Any] = {"raw": raw}
        # Parse the stats output — typical format:
        # CPU   NetIn   NetOut    Uptime  Maps   FPS   Players  Svms    +-ms   ~tick
        # 10.0  12345.6  12345.6  123     1      128.00  5       1.23    0.45   100.0
        lines = [l.strip() for l in raw.strip().split('\n') if l.strip()]
        if len(lines) >= 2:
            values = lines[-1].split()
            if len(values) >= 7:
                stats['cpu'] = values[0]
                stats['net_in'] = values[1]
                stats['net_out'] = values[2]
                stats['uptime'] = values[3]
                stats['maps'] = values[4]
                stats['fps'] = values[5]
                stats['players'] = values[6]
            if len(values) >= 8:
                stats['sv_ms'] = values[7]
            if len(values) >= 9:
                stats['var_ms'] = values[8]
            if len(values) >= 10:
                stats['tick'] = values[9]
        return jsonify({"success": True, "stats": stats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ============== BAN MANAGEMENT ==============

@app.route('/api/bans', methods=['GET'])
@requires_auth
def api_bans():
    """Get the ban list (SteamID bans + IP bans)."""
    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected"})
    try:
        banlist_raw = rcon.execute("banlist")
        listip_raw = rcon.execute("listip")

        steamid_bans: list[str] = []
        ip_bans: list[str] = []

        for line in banlist_raw.split('\n'):
            line = line.strip()
            if line and not line.startswith('ID filter') and not line.startswith('-') and 'entries' not in line.lower():
                steamid_bans.append(line)

        for line in listip_raw.split('\n'):
            line = line.strip()
            if line and not line.startswith('IP filter') and not line.startswith('-') and 'entries' not in line.lower():
                ip_bans.append(line)

        return jsonify({
            "success": True,
            "steamid_bans": steamid_bans,
            "ip_bans": ip_bans,
            "raw_banlist": banlist_raw,
            "raw_listip": listip_raw
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/unban', methods=['POST'])
@requires_auth
def api_unban():
    """Unban a player by SteamID."""
    data = get_json_body()
    steamid = str(data.get('steamid', '')).strip()
    if not steamid:
        return jsonify({"success": False, "error": "No SteamID provided"})
    # Validate SteamID format (STEAM_X:Y:Z or [U:1:XXXXXXX])
    if not re.match(r'^(STEAM_\d:\d:\d+|\[U:\d:\d+\])$', steamid):
        return jsonify({"success": False, "error": "Invalid SteamID format"})
    try:
        response = rcon.execute(f"removeid {steamid}")
        rcon.execute("writeid")
        add_to_history(f"removeid {steamid}", response)
        return jsonify({"success": True, "response": response or "Ban removed"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/ban_ip', methods=['POST'])
@requires_auth
def api_ban_ip():
    """Ban an IP address."""
    data = get_json_body()
    ip = str(data.get('ip', '')).strip()
    duration = int(data.get('duration', 0))
    if not ip:
        return jsonify({"success": False, "error": "No IP provided"})
    # Validate IP format
    if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip):
        return jsonify({"success": False, "error": "Invalid IP format"})
    try:
        response = rcon.execute(f"addip {duration} {ip}")
        rcon.execute("writeip")
        add_to_history(f"addip {duration} {ip}", response)
        return jsonify({"success": True, "response": response or f"IP {ip} banned"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/unban_ip', methods=['POST'])
@requires_auth
def api_unban_ip():
    """Unban an IP address."""
    data = get_json_body()
    ip = str(data.get('ip', '')).strip()
    if not ip:
        return jsonify({"success": False, "error": "No IP provided"})
    if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip):
        return jsonify({"success": False, "error": "Invalid IP format"})
    try:
        response = rcon.execute(f"removeip {ip}")
        rcon.execute("writeip")
        add_to_history(f"removeip {ip}", response)
        return jsonify({"success": True, "response": response or f"IP {ip} unbanned"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ============== GOTV CONTROLS ==============

@app.route('/api/gotv/status', methods=['GET'])
@requires_auth
def api_gotv_status():
    """Get GOTV status."""
    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected"})
    try:
        raw = rcon.execute("tv_status")
        status: dict[str, Any] = {"raw": raw, "enabled": False}
        for line in raw.split('\n'):
            line = line.strip().lower()
            if 'not active' in line or 'tv not enabled' in line or 'disabled' in line:
                status['enabled'] = False
                break
            if 'sourcetv' in line or 'name' in line or 'clients' in line:
                status['enabled'] = True
        # Parse details
        for line in raw.split('\n'):
            line = line.strip()
            if ':' in line:
                key, _, val = line.partition(':')
                key = key.strip().lower().replace(' ', '_')
                status[key] = val.strip()
        return jsonify({"success": True, "gotv": status})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/gotv/record', methods=['POST'])
@requires_auth
def api_gotv_record():
    """Start GOTV recording."""
    data = get_json_body()
    name = str(data.get('name', '')).strip()
    if not name:
        name = f"demo_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    # Sanitize filename
    name = re.sub(r'[^a-zA-Z0-9_\-]', '_', name)
    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected"})
    try:
        response = rcon.execute(f"tv_record {name}")
        add_to_history(f"tv_record {name}", response)
        return jsonify({"success": True, "response": response or f"Recording started: {name}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/gotv/stop', methods=['POST'])
@requires_auth
def api_gotv_stop():
    """Stop GOTV recording."""
    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected"})
    try:
        response = rcon.execute("tv_stoprecord")
        add_to_history("tv_stoprecord", response)
        return jsonify({"success": True, "response": response or "Recording stopped"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ============== ROUND BACKUP & RESTORE ==============

@app.route('/api/round_backup', methods=['GET'])
@requires_auth
def api_round_backup():
    """Get information about round backups."""
    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected"})
    try:
        last = rcon.execute("mp_backup_round_file_last")
        auto = rcon.execute("mp_backup_round_auto")
        return jsonify({
            "success": True,
            "last_backup": last.strip() if last else "",
            "auto_backup_raw": auto.strip() if auto else ""
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/round_backup/restore', methods=['POST'])
@requires_auth
def api_round_backup_restore():
    """Restore a round from backup."""
    data = get_json_body()
    filename = str(data.get('filename', '')).strip()
    if not filename:
        return jsonify({"success": False, "error": "No backup filename provided"})
    # Sanitize - only allow safe chars for filenames
    if not re.match(r'^[a-zA-Z0-9_\-\.]+$', filename):
        return jsonify({"success": False, "error": "Invalid backup filename"})
    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected"})
    try:
        response = rcon.execute(f"mp_backup_restore_load_file {filename}")
        add_to_history(f"mp_backup_restore_load_file {filename}", response)
        return jsonify({"success": True, "response": response or f"Restoring from {filename}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ============== PLAYER TEAM MANAGEMENT ==============

@app.route('/api/move_player', methods=['POST'])
@requires_auth
def api_move_player():
    """Move a player to a specific team (CT=3, T=2, Spec=1)."""
    data = get_json_body()
    player_id = str(data.get('player_id', '')).strip()
    team = str(data.get('team', '')).strip()
    if not player_id:
        return jsonify({"success": False, "error": "No player ID"})
    if team not in ('1', '2', '3'):
        return jsonify({"success": False, "error": "Invalid team (1=Spec, 2=T, 3=CT)"})
    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected"})
    try:
        response = rcon.execute(f"cs_swap_player_team {player_id} {team}")
        add_to_history(f"cs_swap_player_team {player_id} {team}", response)
        return jsonify({"success": True, "response": response or "Player moved"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/mute_player', methods=['POST'])
@requires_auth
def api_mute_player():
    """Mute or unmute a player."""
    data = get_json_body()
    player_id = str(data.get('player_id', '')).strip()
    mute = data.get('mute', True)
    if not player_id:
        return jsonify({"success": False, "error": "No player ID"})
    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected"})
    try:
        cmd = f"sm_mute #{player_id}" if mute else f"sm_unmute #{player_id}"
        response = rcon.execute(cmd)
        add_to_history(cmd, response)
        return jsonify({"success": True, "response": response or ("Player muted" if mute else "Player unmuted")})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ============== SCHEDULED TASKS ==============

def _run_scheduled_task(task_id: str) -> None:
    """Execute a scheduled task."""
    task = scheduled_tasks.get(task_id)
    if not task or not rcon.is_connected():
        scheduled_tasks.pop(task_id, None)
        _save_scheduled_tasks()
        return
    try:
        command = task['command']
        response = rcon.execute(command)
        add_to_history(f"[SCHEDULED] {command}", response)
        task['last_run'] = datetime.now().strftime('%H:%M:%S')
        task['run_count'] = task.get('run_count', 0) + 1
        _save_scheduled_tasks()

        if task.get('repeat', False):
            interval = task.get('interval', 60)
            timer = threading.Timer(interval, _run_scheduled_task, args=[task_id])
            timer.daemon = True
            timer.start()
            task['_timer'] = timer
        else:
            scheduled_tasks.pop(task_id, None)
            _save_scheduled_tasks()
    except Exception as e:
        logger.error(f"Scheduled task {task_id} failed: {e}")
        scheduled_tasks.pop(task_id, None)
        _save_scheduled_tasks()


@app.route('/api/scheduled_tasks', methods=['GET'])
@requires_auth
def api_get_scheduled_tasks():
    """List all scheduled tasks."""
    tasks: list[dict[str, Any]] = []
    for tid, task in scheduled_tasks.items():
        tasks.append({
            "id": tid,
            "command": task.get('command', ''),
            "interval": task.get('interval', 0),
            "repeat": task.get('repeat', False),
            "last_run": task.get('last_run', ''),
            "run_count": task.get('run_count', 0),
            "created": task.get('created', ''),
        })
    return jsonify({"success": True, "tasks": tasks})


@app.route('/api/scheduled_tasks', methods=['POST'])
@requires_auth
def api_add_scheduled_task():
    """Add a new scheduled task."""
    global _task_counter
    data = get_json_body()
    command = str(data.get('command', '')).strip()
    interval = int(data.get('interval', 60))
    repeat = bool(data.get('repeat', False))

    if not command:
        return jsonify({"success": False, "error": "No command specified"})
    if interval < 5:
        return jsonify({"success": False, "error": "Interval must be at least 5 seconds"})
    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected"})

    with _task_counter_lock:
        _task_counter += 1
        task_id = f"task_{_task_counter}"

    task: dict[str, Any] = {
        "command": command,
        "interval": interval,
        "repeat": repeat,
        "created": datetime.now().strftime('%H:%M:%S'),
        "run_count": 0,
        "last_run": "",
    }
    scheduled_tasks[task_id] = task

    timer = threading.Timer(interval, _run_scheduled_task, args=[task_id])
    timer.daemon = True
    timer.start()
    task['_timer'] = timer

    _save_scheduled_tasks()

    return jsonify({"success": True, "id": task_id, "message": f"Task scheduled: {command} every {interval}s"})


@app.route('/api/scheduled_tasks/<task_id>', methods=['DELETE'])
@requires_auth
def api_delete_scheduled_task(task_id: str):
    """Cancel and remove a scheduled task."""
    task = scheduled_tasks.pop(task_id, None)
    if not task:
        return jsonify({"success": False, "error": "Task not found"})
    timer = task.get('_timer')
    if timer and hasattr(timer, 'cancel'):
        timer.cancel()
    _save_scheduled_tasks()
    return jsonify({"success": True, "message": f"Task {task_id} cancelled"})


@app.route('/api/scheduled_tasks/<task_id>/restart', methods=['POST'])
@requires_auth
def api_restart_scheduled_task(task_id: str):
    """Restart a saved scheduled task's timer."""
    task = scheduled_tasks.get(task_id)
    if not task:
        return jsonify({"success": False, "error": "Task not found"})
    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected"})
    # Cancel existing timer if any
    old_timer = task.get('_timer')
    if old_timer and hasattr(old_timer, 'cancel'):
        old_timer.cancel()
    interval = task.get('interval', 60)
    timer = threading.Timer(interval, _run_scheduled_task, args=[task_id])
    timer.daemon = True
    timer.start()
    task['_timer'] = timer
    return jsonify({"success": True, "message": f"Task {task_id} restarted (next run in {interval}s)"})


# ============== COMMAND / CVAR SEARCH ==============

@app.route('/api/find', methods=['POST'])
@requires_auth
def api_find():
    """Search for commands/cvars on the server using the 'find' command."""
    data = get_json_body()
    query = str(data.get('query', '')).strip()
    if not query:
        return jsonify({"success": False, "error": "No search query"})
    if not re.match(r'^[a-zA-Z0-9_\-\s]+$', query):
        return jsonify({"success": False, "error": "Invalid search query"})
    if len(query) > 64:
        return jsonify({"success": False, "error": "Query too long"})
    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected"})
    try:
        response = rcon.execute(f"find {query}")
        results: list[str] = []
        for line in response.split('\n'):
            line = line.strip()
            if line and not line.startswith('---') and 'matches' not in line.lower():
                results.append(line)
        add_to_history(f"find {query}", f"{len(results)} results")
        return jsonify({"success": True, "results": results, "raw": response, "count": len(results)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/cvarlist', methods=['GET'])
@requires_auth
def api_cvarlist():
    """Dump all server commands/cvars using cvarlist command."""
    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected"})
    try:
        response = rcon.execute("cvarlist")
        lines = [l.strip() for l in response.split('\n') if l.strip()]
        return jsonify({"success": True, "raw": response, "count": len(lines)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/workshop/collection', methods=['POST'])
@requires_auth
def api_workshop_collection():
    """Load a Steam Workshop collection on the server."""
    data = get_json_body()
    collection_input = str(data.get('collection_id', '')).strip()
    collection_id = parse_workshop_id(collection_input)
    if not collection_id:
        return jsonify({"success": False, "error": "Invalid collection ID or URL"})
    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected"})
    try:
        response = rcon.execute(f"host_workshop_collection {collection_id}")
        add_to_history(f"host_workshop_collection {collection_id}", response or "Loading collection...")
        return jsonify({"success": True, "response": response or f"Loading workshop collection {collection_id}..."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ============== MAIN ==============

if __name__ == '__main__':
    port = int(os.environ.get('PORT', os.environ.get('FLASK_PORT', 5000)))
    debug = os.environ.get('FLASK_DEBUG', '').lower() in ('1', 'true', 'yes')

    print("=" * 60)
    print("  CS2 Dedicated Server Controller")
    print(f"  Open http://localhost:{port} in your browser")
    if ADMIN_PASSWORD:
        print("  Auth: ENABLED (CS2_ADMIN_PASSWORD is set)")
    else:
        print("  Auth: DISABLED (set CS2_ADMIN_PASSWORD to enable)")
    print("=" * 60)

    if debug:
        app.run(host='0.0.0.0', port=port, debug=True)
    else:
        from waitress import serve  # type: ignore[import-untyped]
        serve(app, host='0.0.0.0', port=port)
