"""
scripts/register_slash_commands.py

Registers slash commands with Discord. Run this once (or after adding new commands).

Requires DISCORD_APP_ID and DISCORD_PUBLIC_KEY in your environment (or .env file).
You also need DISCORD_BOT_TOKEN — get it from the Bot tab in the Discord Developer Portal.

Usage:
    DISCORD_BOT_TOKEN=your_token python scripts/register_slash_commands.py
"""

import os
import sys

import requests

sys.path.insert(0, ".")

from backend.core.config import get_settings

settings = get_settings()

BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
if not BOT_TOKEN:
    print("ERROR: DISCORD_BOT_TOKEN not set.")
    print("Get it from: Discord Developer Portal → Your App → Bot → Token")
    sys.exit(1)

if not settings.discord_app_id:
    print("ERROR: DISCORD_APP_ID not set in environment.")
    sys.exit(1)

COMMANDS = [
    {
        "name": "today-record",
        "description": "Show today's NRFI picks and their current W/L record.",
        "type": 1,  # CHAT_INPUT (slash command)
    },
]

url = f"https://discord.com/api/v10/applications/{settings.discord_app_id}/commands"
headers = {
    "Authorization": f"Bot {BOT_TOKEN}",
    "Content-Type": "application/json",
}

print(f"Registering {len(COMMANDS)} global command(s) for app {settings.discord_app_id}...")

# PUT to the base URL does a bulk overwrite — replaces all global commands at once
resp = requests.put(url, headers=headers, json=COMMANDS, timeout=10)
if resp.status_code in (200, 201):
    for cmd in resp.json():
        print(f"  ✓ /{cmd['name']} registered (id={cmd['id']}).")
else:
    print(f"  ✗ Registration failed: {resp.status_code} — {resp.text}")

print("\nDone. Global commands can take up to 1 hour to propagate to all servers.")
print("For instant testing, register guild commands instead (pass ?guild_id=YOUR_SERVER_ID).")
