"""
CS2 Dedicated Server Controller
A web-based server management tool inspired by the classic CS 1.6 HLDS tool.
"""

import os
import re
import json
import time
import logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
from rcon_client import RCONClient, RCONError, RCONAuthError, RCONConnectionError

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.urandom(24)
CORS(app)  # Allow cross-origin requests from any port

# Detect Vercel serverless environment (read-only filesystem)
IS_VERCEL = os.environ.get('VERCEL') or os.environ.get('VERCEL_ENV')
DATA_DIR = '/tmp' if IS_VERCEL else os.path.dirname(__file__)


def data_path(*parts: str) -> str:
    """Return writable data path — uses /tmp on Vercel, local dir otherwise."""
    return os.path.join(DATA_DIR, *parts)

# Global RCON client instance
rcon = RCONClient()

# Command history
command_history = []
MAX_HISTORY = 500

# CS2 Map Pool
CS2_MAPS = {
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

# Common server CVars with descriptions — comprehensive CS2 list
CS2_CVARS = {
    "General Server": {
        "hostname": {"desc": "Server name displayed in browser", "type": "string", "default": "CS2 Server"},
        "sv_password": {"desc": "Server password (empty = public)", "type": "string", "default": ""},
        "rcon_password": {"desc": "Remote console password", "type": "string", "default": ""},
        "sv_cheats": {"desc": "Allow cheat commands (0/1)", "type": "bool", "default": "0"},
        "sv_lan": {"desc": "LAN mode, no Steam auth (0/1)", "type": "bool", "default": "0"},
        "sv_visiblemaxplayers": {"desc": "Max visible player slots (-1 = use maxplayers)", "type": "int", "default": "-1"},
        "sv_maxrate": {"desc": "Max bandwidth rate per client (0 = unlimited)", "type": "int", "default": "0"},
        "sv_minrate": {"desc": "Min bandwidth rate per client", "type": "int", "default": "128000"},
        "sv_maxupdaterate": {"desc": "Max server update rate", "type": "int", "default": "128"},
        "sv_minupdaterate": {"desc": "Min server update rate", "type": "int", "default": "64"},
        "tv_enable": {"desc": "Enable GOTV", "type": "bool", "default": "0"},
        "tv_delay": {"desc": "GOTV broadcast delay (seconds)", "type": "int", "default": "10"},
        "tv_title": {"desc": "GOTV title", "type": "string", "default": ""},
        "sv_allowupload": {"desc": "Allow clients to upload custom content", "type": "bool", "default": "1"},
        "sv_allowdownload": {"desc": "Allow clients to download content", "type": "bool", "default": "1"},
        "sv_downloadurl": {"desc": "URL for fast downloads", "type": "string", "default": ""},
        "sv_pure": {"desc": "Pure server mode (0/1/2)", "type": "int", "default": "1"},
        "sv_hibernate_when_empty": {"desc": "Server hibernates when no players", "type": "bool", "default": "1"},
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
        "sv_deadtalk": {"desc": "Dead players chat to all (0/1)", "type": "bool", "default": "0"},
        "sv_kick_ban_duration": {"desc": "Ban duration after kick (minutes, 0=permanent)", "type": "int", "default": "15"},
        "mp_drop_knife_enable": {"desc": "Allow dropping knife", "type": "bool", "default": "0"},
        "mp_backup_round_auto": {"desc": "Auto backup rounds", "type": "bool", "default": "1"},
        "mp_humanteam": {"desc": "Force human team (any/T/CT)", "type": "string", "default": "any"},
        "mp_endwarmup_player_count": {"desc": "Player count to auto-end warmup", "type": "int", "default": "0"},
    },
}

# Quick command presets — using proper CS2 RCON commands
QUICK_COMMANDS = {
    "Match Control": [
        {"label": "Restart Round", "cmd": "mp_restartgame 1", "icon": ""},
        {"label": "Restart (5s)", "cmd": "mp_restartgame 5", "icon": ""},
        {"label": "Pause Match", "cmd": "mp_pause_match", "icon": ""},
        {"label": "Unpause Match", "cmd": "mp_unpause_match", "icon": ""},
        {"label": "End Warmup", "cmd": "mp_warmup_end", "icon": ""},
        {"label": "Swap Teams", "cmd": "mp_swapteams", "icon": ""},
        {"label": "Scramble Teams", "cmd": "mp_scrambleteams", "icon": ""},
        {"label": "End Match", "cmd": "mp_maxrounds 0", "icon": ""},
    ],
    "Bots": [
        {"label": "Add T Bot", "cmd": "bot_add_t", "icon": ""},
        {"label": "Add CT Bot", "cmd": "bot_add_ct", "icon": ""},
        {"label": "Add Bot (any)", "cmd": "bot_add", "icon": ""},
        {"label": "Kick Bots", "cmd": "bot_kick", "icon": ""},
        {"label": "Freeze Bots", "cmd": "bot_stop 1", "icon": ""},
        {"label": "Unfreeze Bots", "cmd": "bot_stop 0", "icon": ""},
        {"label": "Bots Don't Shoot", "cmd": "bot_dont_shoot 1", "icon": ""},
        {"label": "Bots Can Shoot", "cmd": "bot_dont_shoot 0", "icon": ""},
        {"label": "Bots Knives Only", "cmd": "bot_knives_only 1", "icon": ""},
        {"label": "Bots All Weapons", "cmd": "bot_knives_only 0", "icon": ""},
        {"label": "Bot Difficulty Easy", "cmd": "bot_difficulty 0", "icon": ""},
        {"label": "Bot Difficulty Hard", "cmd": "bot_difficulty 2", "icon": ""},
        {"label": "Bot Difficulty Expert", "cmd": "bot_difficulty 3", "icon": ""},
        {"label": "Fill 10 Bots", "cmd": "bot_quota 10", "icon": ""},
        {"label": "Fill 20 Bots", "cmd": "bot_quota 20", "icon": ""},
        {"label": "Bots Zombie Mode", "cmd": "bot_zombie 1", "icon": ""},
    ],
    "Practice Mode": [
        {"label": "Cheats ON", "cmd": "sv_cheats 1", "icon": ""},
        {"label": "Cheats OFF", "cmd": "sv_cheats 0", "icon": ""},
        {"label": "Infinite Ammo ON", "cmd": "sv_infinite_ammo 1", "icon": ""},
        {"label": "Infinite Reserve Ammo", "cmd": "sv_infinite_ammo 2", "icon": ""},
        {"label": "Infinite Ammo OFF", "cmd": "sv_infinite_ammo 0", "icon": ""},
        {"label": "Nade Trajectory ON", "cmd": "sv_grenade_trajectory_prac_pipreview 1", "icon": ""},
        {"label": "Nade Trajectory OFF", "cmd": "sv_grenade_trajectory_prac_pipreview 0", "icon": ""},
        {"label": "Show Impacts ON", "cmd": "sv_showimpacts 1", "icon": ""},
        {"label": "Show Impacts OFF", "cmd": "sv_showimpacts 0", "icon": ""},
        {"label": "No Freeze Time", "cmd": "mp_freezetime 0", "icon": ""},
        {"label": "Long Round (60min)", "cmd": "mp_roundtime 60", "icon": ""},
        {"label": "Buy Anywhere", "cmd": "mp_buy_anywhere 1", "icon": ""},
        {"label": "Max Money", "cmd": "mp_maxmoney 65535", "icon": ""},
        {"label": "Start Money Max", "cmd": "mp_startmoney 65535", "icon": ""},
        {"label": "Bunny Hop ON", "cmd": "sv_enablebunnyhopping 1", "icon": ""},
        {"label": "Auto Bunny Hop", "cmd": "sv_autobunnyhopping 1", "icon": ""},
        {"label": "Show All on Radar", "cmd": "mp_radar_showall 1", "icon": ""},
    ],
    "Communication": [
        {"label": "Alltalk ON", "cmd": "sv_alltalk 1", "icon": ""},
        {"label": "Alltalk OFF", "cmd": "sv_alltalk 0", "icon": ""},
        {"label": "Full Alltalk ON", "cmd": "sv_full_alltalk 1", "icon": ""},
        {"label": "Full Alltalk OFF", "cmd": "sv_full_alltalk 0", "icon": ""},
        {"label": "Dead Talk ON", "cmd": "sv_deadtalk 1", "icon": ""},
        {"label": "Dead Talk OFF", "cmd": "sv_deadtalk 0", "icon": ""},
        {"label": "Voice ON", "cmd": "sv_voiceenable 1", "icon": ""},
        {"label": "Voice OFF", "cmd": "sv_voiceenable 0", "icon": ""},
    ],
    "Game Rules": [
        {"label": "Friendly Fire ON", "cmd": "mp_friendlyfire 1", "icon": ""},
        {"label": "Friendly Fire OFF", "cmd": "mp_friendlyfire 0", "icon": ""},
        {"label": "Headshot Only ON", "cmd": "mp_damage_headshot_only 1", "icon": ""},
        {"label": "Headshot Only OFF", "cmd": "mp_damage_headshot_only 0", "icon": ""},
        {"label": "Free Armor+Helmet", "cmd": "mp_free_armor 2", "icon": ""},
        {"label": "Free Kevlar Only", "cmd": "mp_free_armor 1", "icon": ""},
        {"label": "No Free Armor", "cmd": "mp_free_armor 0", "icon": ""},
        {"label": "All Defusers", "cmd": "mp_defuser_allocation 2", "icon": ""},
        {"label": "No Defusers", "cmd": "mp_defuser_allocation 0", "icon": ""},
        {"label": "FFA Deathmatch", "cmd": "mp_teammates_are_enemies 1", "icon": ""},
        {"label": "Normal Teams", "cmd": "mp_teammates_are_enemies 0", "icon": ""},
        {"label": "C4 Timer 25s", "cmd": "mp_c4timer 25", "icon": ""},
        {"label": "C4 Timer 40s", "cmd": "mp_c4timer 40", "icon": ""},
        {"label": "C4 Timer 60s", "cmd": "mp_c4timer 60", "icon": ""},
        {"label": "Drop Knife ON", "cmd": "mp_drop_knife_enable 1", "icon": ""},
        {"label": "Walk-Through Teammates", "cmd": "mp_solid_teammates 0", "icon": ""},
    ],
    "Admin & Server": [
        {"label": "Server Status", "cmd": "status", "icon": ""},
        {"label": "List Maps", "cmd": "maps *", "icon": ""},
        {"label": "Write Config", "cmd": "host_writeconfig", "icon": ""},
        {"label": "Ban List", "cmd": "banlist", "icon": ""},
        {"label": "Write Ban List", "cmd": "writeid", "icon": ""},
        {"label": "GOTV ON", "cmd": "tv_enable 1", "icon": ""},
        {"label": "GOTV OFF", "cmd": "tv_enable 0", "icon": ""},
        {"label": "Exec server.cfg", "cmd": "exec server.cfg", "icon": ""},
        {"label": "Exec gamemode_competitive.cfg", "cmd": "exec gamemode_competitive.cfg", "icon": ""},
        {"label": "Exec gamemode_casual.cfg", "cmd": "exec gamemode_casual.cfg", "icon": ""},
        {"label": "Exec gamemode_deathmatch.cfg", "cmd": "exec gamemode_deathmatch.cfg", "icon": ""},
        {"label": "Exec gamemode_armsrace.cfg", "cmd": "exec gamemode_armsrace.cfg", "icon": ""},
        {"label": "Hibernate OFF", "cmd": "sv_hibernate_when_empty 0", "icon": ""},
    ],
}

# Config file templates
CONFIG_TEMPLATES = {
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
        "description": "Retake practice — short rounds, free armor, fast buys",
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
        "description": "1v1 aim duels — headshot only, free armor, infinite money",
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
        "description": "Practice aim — infinite ammo, impacts visible, long rounds",
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
        "description": "Surf & bunny hop settings — auto bhop, no stamina",
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
        "description": "Hide and Seek — CTs seek after freeze, no radar, long rounds",
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
    entry = {
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
def index():
    """Main dashboard page."""
    return render_template('index.html')


@app.route('/api/connect', methods=['POST'])
def api_connect():
    """Connect to the RCON server."""
    data = request.json
    host = data.get('host', '').strip()
    port = int(data.get('port', 27015))
    password = data.get('password', '').strip()

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
def api_disconnect():
    """Disconnect from the RCON server."""
    rcon.disconnect()
    add_to_history("[DISCONNECT]", "Disconnected from server")
    return jsonify({"success": True, "message": "Disconnected"})


@app.route('/api/status', methods=['GET'])
def api_status():
    """Get connection status and basic server info."""
    connected = rcon.is_connected()
    result = {
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
def api_command():
    """Execute an RCON command. Auto-handles cheat-protected cvars."""
    data = request.json
    command = data.get('command', '').strip()

    if not command:
        return jsonify({"success": False, "error": "No command provided"})

    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected to server"})

    try:
        response = rcon.execute(command)

        # If the command was rejected as cheat-protected, auto-enable sv_cheats,
        # re-run the command, then disable sv_cheats again
        if response and 'cheat protected' in response.lower():
            logger.info(f"Cheat-protected command detected: {command} — enabling sv_cheats temporarily")
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
def api_kick():
    """Kick a player."""
    data = request.json
    player_id = data.get('player_id')
    reason = data.get('reason', '')

    try:
        response = rcon.kick_player(player_id, reason)
        add_to_history(f"kick {player_id}", response)
        return jsonify({"success": True, "response": response})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/ban', methods=['POST'])
def api_ban():
    """Ban a player."""
    data = request.json
    player_id = data.get('player_id')
    duration = int(data.get('duration', 0))

    try:
        response = rcon.ban_player(player_id, duration)
        add_to_history(f"ban {player_id} {duration}m", response)
        return jsonify({"success": True, "response": response})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/changemap', methods=['POST'])
def api_changemap():
    """Change the map."""
    data = request.json
    map_name = data.get('map', '').strip()

    if not map_name:
        return jsonify({"success": False, "error": "No map specified"})

    try:
        response = rcon.change_map(map_name)
        add_to_history(f"changelevel {map_name}", response or "Map change initiated")
        return jsonify({"success": True, "response": response or "Map change initiated"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/say', methods=['POST'])
def api_say():
    """Send a message to server chat."""
    data = request.json
    message = data.get('message', '').strip()

    if not message:
        return jsonify({"success": False, "error": "No message"})

    try:
        response = rcon.say(message)
        add_to_history(f'say "{message}"', response or "Message sent")
        return jsonify({"success": True, "response": "Message sent"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/cvar', methods=['POST'])
def api_set_cvar():
    """Set a server CVar. Auto-handles cheat-protected cvars."""
    data = request.json
    cvar = data.get('cvar', '').strip()
    value = data.get('value', '').strip()

    if not cvar:
        return jsonify({"success": False, "error": "No CVar specified"})

    try:
        response = rcon.set_cvar(cvar, value)

        # Auto-handle cheat-protected cvars
        if response and 'cheat protected' in response.lower():
            logger.info(f"Cheat-protected cvar: {cvar} — enabling sv_cheats temporarily")
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
def api_get_cvar(cvar_name):
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

    data = request.json
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
def api_apply_template():
    """Apply a config template to the server."""
    data = request.json
    template_name = data.get('template', '')

    if template_name not in CONFIG_TEMPLATES:
        return jsonify({"success": False, "error": "Unknown template"})

    if not rcon.is_connected():
        return jsonify({"success": False, "error": "Not connected"})

    template = CONFIG_TEMPLATES[template_name]
    results = []

    try:
        for cvar, value in template['cvars'].items():
            if value:  # Skip empty values (they're commands, not cvars)
                response = rcon.execute(f"{cvar} {value}")
                results.append(f"{cvar} {value}")
            else:
                response = rcon.execute(cvar)
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


def _init_workshop_maps():
    """Copy bundled workshop_maps.json to writable dir on first run (Vercel)."""
    if IS_VERCEL and not os.path.exists(WORKSHOP_MAPS_FILE):
        src = os.path.join(os.path.dirname(__file__), 'workshop_maps.json')
        if os.path.exists(src):
            import shutil
            shutil.copy2(src, WORKSHOP_MAPS_FILE)


def load_workshop_maps() -> list:
    """Load saved workshop maps from JSON file."""
    _init_workshop_maps()
    if os.path.exists(WORKSHOP_MAPS_FILE):
        with open(WORKSHOP_MAPS_FILE, 'r') as f:
            return json.load(f)
    return []


def save_workshop_maps(maps: list):
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
def api_workshop_add():
    """Add a workshop map to favorites."""
    data = request.json
    workshop_input = data.get('workshop_id', '').strip()
    name = data.get('name', '').strip()

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
def api_workshop_remove():
    """Remove a workshop map from favorites."""
    data = request.json
    workshop_id = data.get('workshop_id', '').strip()

    maps = load_workshop_maps()
    maps = [m for m in maps if m['id'] != workshop_id]
    save_workshop_maps(maps)

    return jsonify({"success": True, "message": "Map removed", "maps": maps})


@app.route('/api/workshop/load', methods=['POST'])
def api_workshop_load():
    """Load a workshop map on the server via RCON."""
    data = request.json
    workshop_id = data.get('workshop_id', '').strip()

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
def api_export_config():
    """Export current server settings as a config file."""
    data = request.json
    name = data.get('name', 'custom_config')
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
    _init_server_configs(config_dir)
    os.makedirs(config_dir, exist_ok=True)

    configs = []
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
def api_load_config(filename):
    """Load a saved config file content."""
    config_dir = data_path('server_configs')
    filepath = os.path.join(config_dir, filename)

    if not os.path.exists(filepath):
        return jsonify({"success": False, "error": "Config file not found"})

    with open(filepath, 'r') as f:
        content = f.read()

    return jsonify({"success": True, "filename": filename, "content": content})


@app.route('/api/delete_config/<filename>', methods=['DELETE'])
def api_delete_config(filename):
    """Delete a saved config file."""
    config_dir = data_path('server_configs')
    filepath = os.path.join(config_dir, filename)

    if not os.path.exists(filepath):
        return jsonify({"success": False, "error": "Config file not found"})

    try:
        os.remove(filepath)
        return jsonify({"success": True, "message": f"Deleted {filename}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ============== HELPERS ==============

def _init_server_configs(config_dir: str):
    """Copy bundled server_configs to writable dir on first run (Vercel)."""
    if IS_VERCEL and not os.path.exists(config_dir):
        src = os.path.join(os.path.dirname(__file__), 'server_configs')
        if os.path.exists(src):
            import shutil
            shutil.copytree(src, config_dir)


def save_last_connection(host, port, password):
    """Save last successful connection details."""
    config_path = data_path('last_connection.json')
    data = {"host": host, "port": port, "password": password}
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


@app.route('/api/last_connection', methods=['GET'])
def api_last_connection():
    """Get last saved connection."""
    conn = load_last_connection()
    if conn:
        return jsonify({"success": True, "connection": conn})
    return jsonify({"success": False})


# ============== MAIN ==============

if __name__ == '__main__':
    print("=" * 60)
    print("  CS2 Dedicated Server Controller")
    print("  Open http://localhost:5000 in your browser")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=True)
