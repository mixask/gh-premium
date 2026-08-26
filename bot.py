"""
Greedy Hudzell Discord bot (minimal)
Commands: /key  /renew  /status
Env:
  DISCORD_TOKEN
  ADMIN_SECRET
  API_BASE          default https://greedyhudzell.xyz
  STATUS_CHANNEL_ID default 1472311662307574025
  ADMIN_ROLE_IDS    optional comma-separated role ids
  SELLER_ROLE_IDS   optional comma-separated role ids
  OWNER_USER_IDS    optional; default includes main owner
"""

from __future__ import annotations

import os
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

API_BASE = os.getenv("API_BASE", "https://greedyhudzell.xyz").rstrip("/")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
STATUS_CHANNEL_ID = int(os.getenv("STATUS_CHANNEL_ID", "1472311662307574025"))

# Hardcoded owner (full perms on all commands)
DEFAULT_OWNERS = {1332400034892873761}


def _parse_ids(raw: str) -> set[int]:
    out: set[int] = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


ADMIN_ROLE_IDS = _parse_ids(os.getenv("ADMIN_ROLE_IDS", ""))
SELLER_ROLE_IDS = _parse_ids(os.getenv("SELLER_ROLE_IDS", ""))
OWNER_USER_IDS = DEFAULT_OWNERS | _parse_ids(os.getenv("OWNER_USER_IDS", ""))

STATUS_MAP = {
    "down": "🔴-down",
    "testing": "🟠-testing",
    "working": "🟢-working",
    "possible_ban": "🔵-possible-ban",
}

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


def _member_role_ids(member: discord.Member) -> set[int]:
    return {r.id for r in getattr(member, "roles", [])}


def is_owner(user: discord.abc.User) -> bool:
    return int(user.id) in OWNER_USER_IDS


def is_admin(member: discord.Member) -> bool:
    if is_owner(member):
        return True
    if member.guild_permissions.administrator:
        return True
    roles = _member_role_ids(member)
    if ADMIN_ROLE_IDS and roles & ADMIN_ROLE_IDS:
        return True
    return False


def is_seller(member: discord.Member) -> bool:
    if is_admin(member):
        return True
    roles = _member_role_ids(member)
    if SELLER_ROLE_IDS and roles & SELLER_ROLE_IDS:
        return True
    return False


async def api(method: str, path: str, payload: Optional[dict] = None) -> tuple[int, dict]:
    url = f"{API_BASE}{path}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ADMIN_SECRET}",
    }
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(method, url, json=payload, headers=headers) as resp:
            try:
                data = await resp.json(content_type=None)
            except Exception:
                text = await resp.text()
                data = {"success": False, "reason": f"bad_response: {text[:200]}"}
            if not isinstance(data, dict):
                data = {"success": False, "reason": "invalid_json_body"}
            return resp.status, data


@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"[GH] logged in as {bot.user} | synced {len(synced)} commands")
    except Exception as e:
        print(f"[GH] sync error: {e}")


@bot.tree.command(name="key", description="Generate a Greedy Hudzell key")
@app_commands.describe(
    plan="Subscription length",
    username="Optional Roblox username to bind now",
)
@app_commands.choices(
    plan=[
        app_commands.Choice(name="day (24h)", value="day"),
        app_commands.Choice(name="week", value="week"),
        app_commands.Choice(name="month", value="month"),
        app_commands.Choice(name="year", value="year"),
    ]
)
async def cmd_key(
    interaction: discord.Interaction,
    plan: app_commands.Choice[str],
    username: Optional[str] = None,
):
    if not isinstance(interaction.user, discord.Member) or not is_seller(interaction.user):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    if not ADMIN_SECRET:
        await interaction.response.send_message("ADMIN_SECRET not set on host.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    payload = {"plan": plan.value}
    if username:
        payload["username"] = username.strip()

    status, data = await api("POST", "/admin/generate", payload)
    if not data.get("success"):
        await interaction.followup.send(
            f"Failed ({status}): `{data.get('reason', data)}`",
            ephemeral=True,
        )
        return

    key = data.get("key", "?")
    exp = data.get("expires_at")
    pending = data.get("pending")
    msg = (
        f"**Key created**\n"
        f"```{key}```\n"
        f"Plan: `{data.get('plan')}`\n"
        f"Expires (unix): `{exp}`\n"
        f"Username: `{data.get('username') or 'pending (bind on first use)'}`\n"
        f"Pending bind: `{pending}`"
    )
    await interaction.followup.send(msg, ephemeral=True)


@bot.tree.command(name="renew", description="Extend a key by N days")
@app_commands.describe(key="Full key GH-XXXX-XXXX-XXXX", days="Days to add (1-365)")
async def cmd_renew(interaction: discord.Interaction, key: str, days: app_commands.Range[int, 1, 365]):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    if not ADMIN_SECRET:
        await interaction.response.send_message("ADMIN_SECRET not set on host.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    status, data = await api("POST", "/admin/renew", {"key": key.strip(), "days": int(days)})
    if not data.get("success"):
        await interaction.followup.send(
            f"Failed ({status}): `{data.get('reason', data)}`",
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        f"**Renewed** `{data.get('key')}`\n"
        f"User: `{data.get('username')}`\n"
        f"New expires_at: `{data.get('expires_at')}`\n"
        f"Plan: `{data.get('plan')}`",
        ephemeral=True,
    )


@bot.tree.command(name="status", description="Set GH status channel name")
@app_commands.describe(state="Service state")
@app_commands.choices(
    state=[
        app_commands.Choice(name="🔴 down", value="down"),
        app_commands.Choice(name="🟠 testing", value="testing"),
        app_commands.Choice(name="🟢 working", value="working"),
        app_commands.Choice(name="🔵 possible ban", value="possible_ban"),
    ]
)
async def cmd_status(interaction: discord.Interaction, state: app_commands.Choice[str]):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return

    channel = interaction.guild.get_channel(STATUS_CHANNEL_ID) if interaction.guild else None
    if channel is None:
        try:
            channel = await bot.fetch_channel(STATUS_CHANNEL_ID)
        except Exception:
            channel = None
    if channel is None or not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            f"Channel `{STATUS_CHANNEL_ID}` not found / no access.",
            ephemeral=True,
        )
        return

    new_name = STATUS_MAP[state.value]
    try:
        await channel.edit(name=new_name, reason=f"Status by {interaction.user}")
    except discord.Forbidden:
        await interaction.response.send_message(
            "Missing **Manage Channels** permission.",
            ephemeral=True,
        )
        return
    except Exception as e:
        await interaction.response.send_message(f"Edit failed: `{e}`", ephemeral=True)
        return

    await interaction.response.send_message(f"Status → **{new_name}**", ephemeral=True)


def main():
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN env is empty")
    if not ADMIN_SECRET:
        print("[GH] WARNING: ADMIN_SECRET empty — /key and /renew will fail")
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
