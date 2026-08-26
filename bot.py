"""
Greedy Hudzell Discord bot
Env:
  DISCORD_TOKEN
  ADMIN_SECRET
  API_BASE              default https://greedyhudzell.xyz
  STATUS_CHANNEL_ID     default 1472311662307574025
  ADMIN_ROLE_IDS        optional
  SELLER_ROLE_IDS       optional
  OWNER_USER_IDS        optional
  GITHUB_TOKEN          optional (higher rate limit for update watcher)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

# -------------------- Config --------------------
API_BASE = os.getenv("API_BASE", "https://greedyhudzell.xyz").rstrip("/")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

STATUS_CHANNEL_ID = int(os.getenv("STATUS_CHANNEL_ID", "1472311662307574025"))
AUTO_ROLE_ID = int(os.getenv("AUTO_ROLE_ID", "1448728578844786978"))
VERIFY_CHANNEL_ID = int(os.getenv("VERIFY_CHANNEL_ID", "1424116614856441856"))
VERIFY_CATEGORY_ID = int(os.getenv("VERIFY_CATEGORY_ID", "1453098727253479526"))
VERIFIED_ROLE_ID = int(os.getenv("VERIFIED_ROLE_ID", "1445500571640402052"))
RULES_CHANNEL_ID = int(os.getenv("RULES_CHANNEL_ID", "1424116614856441856"))
REACT_CHANNEL_ID = int(os.getenv("REACT_CHANNEL_ID", "1448624840905855037"))
ROLE_PARKOUR_ANN = int(os.getenv("ROLE_PARKOUR_ANN", "1445398639462584450"))
ROLE_GH_UPDATES = int(os.getenv("ROLE_GH_UPDATES", "1443554745481560084"))
UPDATES_CHANNEL_ID = int(os.getenv("UPDATES_CHANNEL_ID", "1428800296926314506"))

GH_REPO = os.getenv("GH_REPO", "mixask/GH")
WATCH_FILES = ("greedy.lua", "greedyloader.lua")

DEFAULT_OWNERS = {1332400034892873761}
DATA_PATH = Path(os.getenv("DATA_PATH", "data.json"))

STATUS_MAP = {
    "down": "🔴-down",
    "testing": "🟠-testing",
    "working": "🟢-working",
    "possible_ban": "🔵-possible-ban",
}

YES_WORDS = {
    "yes", "y", "yeah", "yep", "yea", "sure", "ok", "okay", "agree",
    "i agree", "accept", "accepted", "да", "д", "согласен", "согласна",
}
NO_WORDS = {
    "no", "n", "nope", "nah", "decline", "disagree", "reject", "refuse",
    "нет", "н", "не согласен", "не согласна",
}

BROWSER_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


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

# -------------------- Persistence --------------------
_default_data: dict[str, Any] = {
    "key_whitelist": [],          # user ids allowed to /key (sellers)
    "verify_message_id": None,
    "react_message_id": None,
    "file_sha": {},               # path -> sha
    "pending_tickets": {},        # channel_id -> {user_id, created}
}


def load_data() -> dict[str, Any]:
    if DATA_PATH.exists():
        try:
            data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
            for k, v in _default_data.items():
                data.setdefault(k, v)
            return data
        except Exception:
            pass
    return json.loads(json.dumps(_default_data))


def save_data(data: dict[str, Any]) -> None:
    DATA_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


DATA = load_data()

# -------------------- Bot --------------------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)


def is_owner(user: discord.abc.User) -> bool:
    return int(user.id) in OWNER_USER_IDS


def _member_role_ids(member: discord.Member) -> set[int]:
    return {r.id for r in getattr(member, "roles", [])}


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
    if int(member.id) in set(DATA.get("key_whitelist") or []):
        return True
    roles = _member_role_ids(member)
    if SELLER_ROLE_IDS and roles & SELLER_ROLE_IDS:
        return True
    return False


async def api(method: str, path: str, payload: Optional[dict] = None) -> tuple[int, dict]:
    url = f"{API_BASE}{path}"
    headers = {
        **BROWSER_HEADERS,
        "Authorization": f"Bearer {ADMIN_SECRET}",
        "Referer": API_BASE + "/",
        "Origin": API_BASE,
    }
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(method, url, json=payload, headers=headers) as resp:
            raw = await resp.text()
            if resp.status in (403, 503) and ("Just a moment" in raw or "cf-browser-verification" in raw):
                return resp.status, {
                    "success": False,
                    "reason": "Cloudflare blocked the request.",
                }
            try:
                data = json.loads(raw)
            except Exception:
                data = {"success": False, "reason": f"bad_response: {raw[:200]}"}
            if not isinstance(data, dict):
                data = {"success": False, "reason": "invalid_json_body"}
            return resp.status, data


# -------------------- Verify UI --------------------
class VerifyView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Verify",
        style=discord.ButtonStyle.green,
        custom_id="gh:verify:open",
        emoji="✅",
    )
    async def verify_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Use this in the server.", ephemeral=True)
            return

        member = interaction.user
        # already verified?
        if any(r.id == VERIFIED_ROLE_ID for r in member.roles):
            await interaction.response.send_message("You are already verified.", ephemeral=True)
            return

        # existing ticket?
        for ch_id, meta in list((DATA.get("pending_tickets") or {}).items()):
            if int(meta.get("user_id", 0)) == member.id:
                ch = interaction.guild.get_channel(int(ch_id))
                if ch:
                    await interaction.response.send_message(
                        f"You already have a ticket: {ch.mention}",
                        ephemeral=True,
                    )
                    return

        category = interaction.guild.get_channel(VERIFY_CATEGORY_ID)
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            ),
            interaction.guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True
            ),
        }
        # staff can see
        for role in interaction.guild.roles:
            if role.permissions.administrator or role.id in ADMIN_ROLE_IDS:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        safe_name = re.sub(r"[^a-z0-9\-]", "", member.name.lower())[:20] or "user"
        try:
            channel = await interaction.guild.create_text_channel(
                name=f"verify-{safe_name}",
                category=category if isinstance(category, discord.CategoryChannel) else None,
                overwrites=overwrites,
                reason=f"Verify ticket for {member}",
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "Bot cannot create channels (need Manage Channels).",
                ephemeral=True,
            )
            return

        DATA.setdefault("pending_tickets", {})[str(channel.id)] = {
            "user_id": member.id,
            "created": int(time.time()),
        }
        save_data(DATA)

        rules = f"<#{RULES_CHANNEL_ID}>"
        await channel.send(
            f"{member.mention}\n"
            f"Do you agree to our {rules}, **TOS** and **Privacy Policy**?\n"
            f"Reply with **yes** / **no** (or agree / decline)."
        )
        await interaction.response.send_message(
            f"Ticket created: {channel.mention}",
            ephemeral=True,
        )


# -------------------- Events --------------------
@bot.event
async def on_ready():
    bot.add_view(VerifyView())
    try:
        synced = await bot.tree.sync()
        print(f"[GH] logged in as {bot.user} | synced {len(synced)} commands")
    except Exception as e:
        print(f"[GH] sync error: {e}")

    await setup_persist_messages()
    if not github_watcher.is_running():
        github_watcher.start()
    if not ticket_cleaner.is_running():
        ticket_cleaner.start()


@bot.event
async def on_member_join(member: discord.Member):
    role = member.guild.get_role(AUTO_ROLE_ID)
    if role:
        try:
            await member.add_roles(role, reason="Auto role on join")
        except Exception as e:
            print(f"[GH] auto-role fail: {e}")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if not message.guild or not isinstance(message.author, discord.Member):
        return

    meta = (DATA.get("pending_tickets") or {}).get(str(message.channel.id))
    if not meta:
        return
    if int(meta.get("user_id", 0)) != message.author.id:
        return

    text = (message.content or "").strip().lower()
    if not text:
        return

    if text in YES_WORDS or any(text.startswith(w + " ") for w in YES_WORDS):
        role = message.guild.get_role(VERIFIED_ROLE_ID)
        if role:
            try:
                await message.author.add_roles(role, reason="Agreed to TOS")
            except Exception as e:
                await message.channel.send(f"Could not add role: `{e}`")
                return
        await message.channel.send(
            f"{message.author.mention} verified. This ticket will close in **30 minutes**."
        )
        DATA["pending_tickets"][str(message.channel.id)]["close_at"] = int(time.time()) + 30 * 60
        save_data(DATA)
        return

    if text in NO_WORDS or any(text.startswith(w + " ") for w in NO_WORDS):
        await message.channel.send(
            "You need to agree to the TOS and rules to get access."
        )
        return


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == (bot.user.id if bot.user else 0):
        return
    if payload.message_id != DATA.get("react_message_id"):
        return
    guild = bot.get_guild(payload.guild_id) if payload.guild_id else None
    if not guild:
        return
    member = guild.get_member(payload.user_id)
    if not member:
        try:
            member = await guild.fetch_member(payload.user_id)
        except Exception:
            return

    emoji = str(payload.emoji)
    role_id = None
    if emoji == "📢":
        role_id = ROLE_GH_UPDATES
    elif emoji == "🎮":
        role_id = ROLE_PARKOUR_ANN
    if not role_id:
        return
    role = guild.get_role(role_id)
    if role:
        try:
            await member.add_roles(role, reason="Reaction role")
        except Exception as e:
            print(f"[GH] reaction add role: {e}")


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.message_id != DATA.get("react_message_id"):
        return
    guild = bot.get_guild(payload.guild_id) if payload.guild_id else None
    if not guild:
        return
    try:
        member = await guild.fetch_member(payload.user_id)
    except Exception:
        return
    emoji = str(payload.emoji)
    role_id = None
    if emoji == "📢":
        role_id = ROLE_GH_UPDATES
    elif emoji == "🎮":
        role_id = ROLE_PARKOUR_ANN
    if not role_id:
        return
    role = guild.get_role(role_id)
    if role:
        try:
            await member.remove_roles(role, reason="Reaction role remove")
        except Exception:
            pass


async def setup_persist_messages():
    """Post verify + react messages once; keep IDs in data.json."""
    # Verify
    try:
        vch = bot.get_channel(VERIFY_CHANNEL_ID) or await bot.fetch_channel(VERIFY_CHANNEL_ID)
        if isinstance(vch, discord.TextChannel):
            mid = DATA.get("verify_message_id")
            exists = False
            if mid:
                try:
                    await vch.fetch_message(int(mid))
                    exists = True
                except Exception:
                    exists = False
            if not exists:
                embed = discord.Embed(
                    title="Verification",
                    description=(
                        "Click **Verify** to open a private ticket and accept the TOS / rules.\n"
                        f"Rules: <#{RULES_CHANNEL_ID}>"
                    ),
                    color=0xC9A227,
                )
                msg = await vch.send(embed=embed, view=VerifyView())
                DATA["verify_message_id"] = msg.id
                save_data(DATA)
                print("[GH] verify message posted")
    except Exception as e:
        print(f"[GH] verify setup: {e}")

    # React roles
    try:
        rch = bot.get_channel(REACT_CHANNEL_ID) or await bot.fetch_channel(REACT_CHANNEL_ID)
        if isinstance(rch, discord.TextChannel):
            mid = DATA.get("react_message_id")
            exists = False
            if mid:
                try:
                    m = await rch.fetch_message(int(mid))
                    exists = True
                    # ensure bot reactions
                    for e in ("📢", "🎮"):
                        try:
                            await m.add_reaction(e)
                        except Exception:
                            pass
                except Exception:
                    exists = False
            if not exists:
                text = (
                    "React with 📢 if you want to be pinged when **Greedy Hudzell** updates\n"
                    "React with 🎮 if you want to be pinged when **Parkour Legacy** updates!"
                )
                msg = await rch.send(text)
                await msg.add_reaction("📢")
                await msg.add_reaction("🎮")
                DATA["react_message_id"] = msg.id
                save_data(DATA)
                print("[GH] react message posted")
    except Exception as e:
        print(f"[GH] react setup: {e}")


# -------------------- Tasks --------------------
@tasks.loop(minutes=5)
async def ticket_cleaner():
    now = int(time.time())
    tickets = dict(DATA.get("pending_tickets") or {})
    changed = False
    for ch_id, meta in tickets.items():
        close_at = meta.get("close_at")
        if not close_at or now < int(close_at):
            continue
        ch = bot.get_channel(int(ch_id))
        if ch:
            try:
                await ch.send("Closing ticket...")
                await asyncio.sleep(1)
                await ch.delete(reason="Verify ticket auto-close")
            except Exception as e:
                print(f"[GH] ticket close: {e}")
        DATA["pending_tickets"].pop(str(ch_id), None)
        changed = True
    if changed:
        save_data(DATA)


@tasks.loop(minutes=3)
async def github_watcher():
    """Poll GitHub commits for watched files and announce updates."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "GreedyHudzell-Bot"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"

    channel = bot.get_channel(UPDATES_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(UPDATES_CHANNEL_ID)
        except Exception:
            return
    if not isinstance(channel, discord.TextChannel):
        return

    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        for path in WATCH_FILES:
            try:
                url = f"https://api.github.com/repos/{GH_REPO}/commits?path={path}&per_page=1"
                async with session.get(url) as resp:
                    if resp.status != 200:
                        print(f"[GH] github {path} HTTP {resp.status}")
                        continue
                    commits = await resp.json()
                if not commits:
                    continue
                sha = commits[0].get("sha")
                if not sha:
                    continue
                prev = (DATA.get("file_sha") or {}).get(path)
                if prev is None:
                    # first run — seed only, no announce
                    DATA.setdefault("file_sha", {})[path] = sha
                    save_data(DATA)
                    continue
                if prev == sha:
                    continue

                commit = commits[0].get("commit") or {}
                message = (commit.get("message") or "").strip()
                title_line = message.split("\n")[0][:120]
                body = "\n".join(message.split("\n")[1:]).strip()
                is_big = "big" in message.lower()

                if path == "greedyloader.lua":
                    label = "Loader"
                else:
                    label = "Hudzell"

                ping = ""
                if is_big:
                    ping = f"<@&{ROLE_GH_UPDATES}>\n"

                text = (
                    f"{ping}**Greedy {label} updated!**\n"
                    f"{title_line}\n"
                    f"```\n{(body or message)[:1800]}\n```\n"
                    f"https://github.com/{GH_REPO}/commit/{sha}"
                )
                await channel.send(text)
                DATA.setdefault("file_sha", {})[path] = sha
                save_data(DATA)
                print(f"[GH] announced update {path} {sha[:7]}")
            except Exception as e:
                print(f"[GH] watcher {path}: {e}")


@github_watcher.before_loop
async def before_github():
    await bot.wait_until_ready()


@ticket_cleaner.before_loop
async def before_cleaner():
    await bot.wait_until_ready()


# -------------------- Commands --------------------
@bot.tree.command(name="key", description="Generate a Greedy Hudzell key")
@app_commands.describe(plan="Subscription length", username="Optional Roblox username to bind now")
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
    payload: dict[str, Any] = {"plan": plan.value}
    if username:
        payload["username"] = username.strip()
    status, data = await api("POST", "/admin/generate", payload)
    if not data.get("success"):
        await interaction.followup.send(f"Failed ({status}): `{data.get('reason', data)}`", ephemeral=True)
        return
    msg = (
        f"**Key created**\n```{data.get('key')}```\n"
        f"Plan: `{data.get('plan')}`\n"
        f"Expires (unix): `{data.get('expires_at')}`\n"
        f"Username: `{data.get('username') or 'pending'}`\n"
        f"Pending: `{data.get('pending')}`"
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
        await interaction.followup.send(f"Failed ({status}): `{data.get('reason', data)}`", ephemeral=True)
        return
    await interaction.followup.send(
        f"**Renewed** `{data.get('key')}`\nUser: `{data.get('username')}`\n"
        f"New expires_at: `{data.get('expires_at')}`\nPlan: `{data.get('plan')}`",
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
        await interaction.response.send_message(f"Channel `{STATUS_CHANNEL_ID}` not found.", ephemeral=True)
        return
    new_name = STATUS_MAP[state.value]
    try:
        await channel.edit(name=new_name, reason=f"Status by {interaction.user}")
    except discord.Forbidden:
        await interaction.response.send_message("Missing **Manage Channels**.", ephemeral=True)
        return
    except Exception as e:
        await interaction.response.send_message(f"Edit failed: `{e}`", ephemeral=True)
        return
    await interaction.response.send_message(f"Status → **{new_name}**", ephemeral=True)


@bot.tree.command(name="keycheck", description="Check key status (claimed / unclaimed / expired)")
@app_commands.describe(key="Full key GH-XXXX-XXXX-XXXX")
async def cmd_keycheck(interaction: discord.Interaction, key: str):
    if not isinstance(interaction.user, discord.Member) or not is_seller(interaction.user):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    if not ADMIN_SECRET:
        await interaction.response.send_message("ADMIN_SECRET not set on host.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    status, data = await api("GET", f"/admin/key/{key.strip()}")
    if status == 404 or data.get("error"):
        await interaction.followup.send(f"Not found: `{data.get('error', data)}`", ephemeral=True)
        return
    username = str(data.get("username") or "")
    pending = username.startswith("pending_")
    claimed = "unclaimed" if pending else "claimed"
    st = data.get("status") or ("REVOKED" if data.get("revoked") else "?")
    await interaction.followup.send(
        f"**Key** `{data.get('key')}`\n"
        f"Status: `{st}`\n"
        f"Bind: **{claimed}**\n"
        f"Username: `{username}`\n"
        f"Plan: `{data.get('plan', 'day')}`\n"
        f"Created: `{data.get('created_at')}`\n"
        f"Expires: `{data.get('expires_at')}`\n"
        f"Executed: `{data.get('executed')}`\n"
        f"Last exec: `{data.get('last_execution')}`",
        ephemeral=True,
    )


@bot.tree.command(name="whitelist", description="Add/remove users allowed to use /key")
@app_commands.describe(action="add or remove", user="Discord user")
@app_commands.choices(
    action=[
        app_commands.Choice(name="add", value="add"),
        app_commands.Choice(name="remove", value="remove"),
        app_commands.Choice(name="list", value="list"),
    ]
)
async def cmd_whitelist(
    interaction: discord.Interaction,
    action: app_commands.Choice[str],
    user: Optional[discord.User] = None,
):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return

    wl: list = list(DATA.get("key_whitelist") or [])

    if action.value == "list":
        if not wl:
            await interaction.response.send_message("Whitelist empty (only admins/sellers).", ephemeral=True)
            return
        lines = [f"<@{i}> (`{i}`)" for i in wl]
        await interaction.response.send_message("**Key whitelist:**\n" + "\n".join(lines), ephemeral=True)
        return

    if user is None:
        await interaction.response.send_message("Specify a user.", ephemeral=True)
        return

    uid = int(user.id)
    if action.value == "add":
        if uid not in wl:
            wl.append(uid)
            DATA["key_whitelist"] = wl
            save_data(DATA)
        await interaction.response.send_message(f"Added {user.mention} to key whitelist.", ephemeral=True)
    else:
        if uid in wl:
            wl = [x for x in wl if x != uid]
            DATA["key_whitelist"] = wl
            save_data(DATA)
        await interaction.response.send_message(f"Removed {user.mention} from key whitelist.", ephemeral=True)


@bot.tree.command(name="setup_messages", description="Force re-post verify/react messages (admin)")
async def cmd_setup_messages(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    DATA["verify_message_id"] = None
    DATA["react_message_id"] = None
    save_data(DATA)
    await interaction.response.send_message("Reposting...", ephemeral=True)
    await setup_persist_messages()
    await interaction.followup.send("Done.", ephemeral=True)


def main():
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN env is empty")
    if not ADMIN_SECRET:
        print("[GH] WARNING: ADMIN_SECRET empty — key commands will fail")
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
