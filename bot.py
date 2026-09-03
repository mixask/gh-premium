"""
Greedy Hudzell Discord bot — OAuth guild verify
User must authorize the bot (identify + guilds). Worker stores guild list.
Verify reads /api/discord/oauth/status and assigns executor roles.

Env:
  DISCORD_TOKEN, ADMIN_SECRET, API_BASE
  DISCORD_CLIENT_ID  (same app as OAuth)
  OAUTH_START_URL    default {API_BASE}/api/discord/oauth/start
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

API_BASE = os.getenv("API_BASE", "https://greedyhudzell.xyz").rstrip("/")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
KEY_LINK = os.getenv("KEY_LINK", "https://work.ink/28wp/Greedy-hudzell")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "").strip()
OAUTH_START_URL = os.getenv("OAUTH_START_URL", f"{API_BASE}/api/discord/oauth/start").rstrip("/")

STATUS_CHANNEL_ID = int(os.getenv("STATUS_CHANNEL_ID", "1472311662307574025"))
AUTO_ROLE_ID = int(os.getenv("AUTO_ROLE_ID", "1448728578844786978"))
LICENSE_PANEL_CHANNEL_ID = int(os.getenv("LICENSE_PANEL_CHANNEL_ID", "0") or 0)
VERIFY_CATEGORY_ID = int(os.getenv("VERIFY_CATEGORY_ID", "1453098727253479526"))
VERIFIED_ROLE_ID = int(os.getenv("VERIFIED_ROLE_ID", "1445500571640402052"))
FREE_REWIRE_ROLE_ID = int(os.getenv("FREE_REWIRE_ROLE_ID", "1545088955572158484"))
RULES_CHANNEL_ID = int(os.getenv("RULES_CHANNEL_ID", "1424116614856441856"))
REACT_CHANNEL_ID = int(os.getenv("REACT_CHANNEL_ID", "1448624840905855037"))
ROLE_PARKOUR_ANN = int(os.getenv("ROLE_PARKOUR_ANN", "1445398639462584450"))
ROLE_GH_UPDATES = int(os.getenv("ROLE_GH_UPDATES", "1443554745481560084"))
UPDATES_CHANNEL_ID = int(os.getenv("UPDATES_CHANNEL_ID", "1428800296926314506"))
GH_REPO = os.getenv("GH_REPO", "mixask/GH")
WATCH_FILES = ("greedy.lua", "greedyloader.lua")
DEFAULT_OWNERS = {1332400034892873761}
DATA_PATH = Path(os.getenv("DATA_PATH", "data.json"))
FORCE_TICKET_GUILD_ID = int(os.getenv("FORCE_TICKET_GUILD_ID", "1228053668797091904"))

EXECUTOR_GUILD_ROLES: dict[str, tuple[int, str]] = {
    "1289988589052104846": (1545091882101506048, "Potassium"),
    "1483453559692595252": (1545092000116904017, "Madium"),
    "1497654383234515131": (1545092121814499369, "Real"),
    "1448237723352825984": (1545092381265633340, "Volt"),
    "1376842062007111750": (1545092590901395496, "Wave"),
    "1329189629466771577": (1545093045555298404, "Synapse Z"),
    "1330492468700905472": (1545093326225543188, "Isaeva"),
    "1534485185427538022": (1545093448825311292, "Cosmic"),
    "943223926509699072": (1545093488251510884, "Velocity"),
    "1364170844867399722": (1545093815117811712, "SirHurt"),
    "1289659915790450849": (1545094729232941156, "Xeno"),
    "1262951163943452723": (1545094956564095046, "MacSploit"),
    "1253107828835483679": (1545095111015272488, "OpiumWare"),
    "1221935816515911850": (1545095225993855008, "Delta"),
}

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
    "User-Agent": "Mozilla/5.0 GreedyHudzellBot",
    "Accept": "application/json",
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
MESSAGE_WHITELIST = _parse_ids(os.getenv("MESSAGE_WHITELIST", "")) | OWNER_USER_IDS

_default_data: dict[str, Any] = {
    "key_whitelist": [],
    "react_message_id": None,
    "file_sha": {},
    "pending_tickets": {},
    "message_whitelist": [],
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

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.reactions = True
bot = commands.Bot(command_prefix="!", intents=intents)


def is_owner(user: discord.abc.User) -> bool:
    return int(user.id) in OWNER_USER_IDS


def _roles(m: discord.Member) -> set[int]:
    return {r.id for r in m.roles}


def is_admin(m: discord.Member) -> bool:
    if is_owner(m):
        return True
    if m.guild_permissions.administrator:
        return True
    return bool(ADMIN_ROLE_IDS and _roles(m) & ADMIN_ROLE_IDS)


def is_verified(m: discord.Member) -> bool:
    return is_admin(m) or VERIFIED_ROLE_ID in _roles(m)


def is_seller(m: discord.Member) -> bool:
    if is_admin(m):
        return True
    if int(m.id) in set(DATA.get("key_whitelist") or []):
        return True
    return bool(SELLER_ROLE_IDS and _roles(m) & SELLER_ROLE_IDS)


def can_message_cmd(user: discord.abc.User) -> bool:
    if is_owner(user) or int(user.id) in MESSAGE_WHITELIST:
        return True
    if int(user.id) in set(DATA.get("message_whitelist") or []):
        return True
    if int(user.id) in set(DATA.get("key_whitelist") or []):
        return True
    return isinstance(user, discord.Member) and is_admin(user)


async def api(method: str, path: str, payload: Optional[dict] = None) -> tuple[int, dict]:
    url = f"{API_BASE}{path}"
    headers = {**BROWSER_HEADERS, "Authorization": f"Bearer {ADMIN_SECRET}"}
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(method, url, json=payload, headers=headers) as resp:
            raw = await resp.text()
            try:
                data = json.loads(raw)
            except Exception:
                data = {"success": False, "reason": raw[:200]}
            if not isinstance(data, dict):
                data = {"success": False, "reason": "bad_json"}
            return resp.status, data


def _api_ok(data: dict) -> bool:
    return bool(data.get("ok") or data.get("success") or data.get("valid"))


def oauth_link_for(user_id: int) -> str:
    return f"{OAUTH_START_URL}?discord_id={user_id}"


async def fetch_oauth_status(user_id: int) -> dict:
    status, data = await api("GET", f"/api/discord/oauth/status?discord_id={user_id}")
    if status != 200:
        return {"authorized": False, "guild_ids": [], "error": data}
    return data


async def ensure_no_unverified_if_member(member: discord.Member) -> None:
    if VERIFIED_ROLE_ID not in _roles(member):
        return
    u = member.guild.get_role(AUTO_ROLE_ID)
    if u and u in member.roles:
        try:
            await member.remove_roles(u, reason="Has Member")
        except Exception:
            pass


async def ensure_free_rewire_role(member: discord.Member) -> None:
    r = member.guild.get_role(FREE_REWIRE_ROLE_ID)
    if r and r not in member.roles:
        try:
            await member.add_roles(r, reason="Free rewire")
        except Exception:
            pass


async def open_ticket(
    guild: discord.Guild,
    member: discord.Member,
    *,
    force_msg: bool = False,
    extra: str = "",
) -> Optional[discord.TextChannel]:
    for ch_id, meta in list((DATA.get("pending_tickets") or {}).items()):
        if int(meta.get("user_id", 0)) == member.id:
            ch = guild.get_channel(int(ch_id))
            if ch:
                return ch  # type: ignore
    category = guild.get_channel(VERIFY_CATEGORY_ID)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }
    for role in guild.roles:
        if role.permissions.administrator or role.id in ADMIN_ROLE_IDS:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
    safe = re.sub(r"[^a-z0-9\-]", "", member.name.lower())[:20] or "user"
    try:
        channel = await guild.create_text_channel(
            name=f"verify-{safe}",
            category=category if isinstance(category, discord.CategoryChannel) else None,
            overwrites=overwrites,
            reason=f"Verify {member}",
        )
    except discord.Forbidden:
        return None
    DATA.setdefault("pending_tickets", {})[str(channel.id)] = {
        "user_id": member.id,
        "created": int(time.time()),
    }
    save_data(DATA)
    if force_msg:
        text = (
            f"{member.mention}\n"
            "We couldnt verify you automatically, sorry for that. "
            "Moderators will assist you shortly.\n"
            "P.S. if moderators didnt answer for a long time, you can request a free key."
        )
    else:
        text = (
            f"{member.mention}\n"
            f"No matching executor communities on your authorized account.\n"
            f"Agree to <#{RULES_CHANNEL_ID}>, TOS & Privacy — reply **yes** / **no**."
        )
    if extra:
        text += f"\n{extra}"
    await channel.send(text)
    return channel


# ----- License UI -----
class LicenseVerifyModal(discord.ui.Modal, title="Activate license key"):
    key = discord.ui.TextInput(label="License key", min_length=8, max_length=64, required=True)
    roblox = discord.ui.TextInput(label="Roblox username", min_length=3, max_length=20, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.user, discord.Member):
            await interaction.followup.send("Server only.", ephemeral=True)
            return
        if not is_verified(interaction.user):
            await interaction.followup.send(
                "Server-verify first (Authorize bot → Verify), then activate key.",
                ephemeral=True,
            )
            return
        username = str(self.roblox.value).strip()
        if not re.match(r"^[A-Za-z0-9_]+$", username):
            await interaction.followup.send("Invalid Roblox username.", ephemeral=True)
            return
        _, data = await api(
            "POST",
            "/api/discord/verify-key",
            {
                "key": str(self.key.value).strip(),
                "username": username,
                "roblox_username": username,
                "discord_id": str(interaction.user.id),
            },
        )
        if not _api_ok(data):
            await interaction.followup.send(
                f"Failed: `{data.get('error') or data.get('reason') or data}`",
                ephemeral=True,
            )
            return
        await ensure_no_unverified_if_member(interaction.user)
        await ensure_free_rewire_role(interaction.user)
        await interaction.followup.send(
            f"**Key activated** · `{data.get('plan')}` · Roblox `{username}`",
            ephemeral=True,
        )


class LicenseRewireModal(discord.ui.Modal, title="Rewire key"):
    key = discord.ui.TextInput(label="License key", min_length=8, max_length=64, required=True)
    roblox = discord.ui.TextInput(label="New Roblox username", min_length=3, max_length=20, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.user, discord.Member):
            await interaction.followup.send("Server only.", ephemeral=True)
            return
        uname = str(self.roblox.value).strip()
        free_role = interaction.guild.get_role(FREE_REWIRE_ROLE_ID) if interaction.guild else None
        has_free = bool(free_role and free_role in interaction.user.roles)
        _, data = await api(
            "POST",
            "/api/discord/rewire",
            {
                "key": str(self.key.value).strip(),
                "username": uname,
                "roblox_username": uname,
                "discord_id": str(interaction.user.id),
                "free_rewire": has_free,
            },
        )
        if not _api_ok(data) and has_free:
            _, data = await api(
                "POST",
                "/admin/rewire",
                {
                    "key": str(self.key.value).strip(),
                    "username": uname,
                    "discord_id": str(interaction.user.id),
                    "force": True,
                },
            )
        if not _api_ok(data) and not data.get("success"):
            await interaction.followup.send(
                f"Rewire failed: `{data.get('error') or data.get('reason') or data}`",
                ephemeral=True,
            )
            return
        if has_free and free_role:
            try:
                await interaction.user.remove_roles(free_role, reason="Used free rewire")
            except Exception:
                pass
        await interaction.followup.send(
            f"**Rewired** → `{uname}`" + (" · free rewire used" if has_free else ""),
            ephemeral=True,
        )


class LicensePanelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Get free key", style=discord.ButtonStyle.link, url=KEY_LINK, row=1))

    @discord.ui.button(label="Verify key", style=discord.ButtonStyle.success, custom_id="cl:lic:v", row=0)
    async def v(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LicenseVerifyModal())

    @discord.ui.button(label="Rewire", style=discord.ButtonStyle.primary, custom_id="cl:lic:r", row=0)
    async def r(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LicenseRewireModal())


def license_embed() -> discord.Embed:
    return discord.Embed(
        title="License panel",
        description=(
            f"**Get free key** — {KEY_LINK}\n"
            "**Verify key** — needs server Member (OAuth verify first)\n"
            f"**Rewire** — paid or 1× free role `{FREE_REWIRE_ROLE_ID}`"
        ),
        color=0xD4AF37,
    )


# ----- Server verify via OAuth -----
class AuthorizeView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.add_item(
            discord.ui.Button(
                label="Authorize bot",
                style=discord.ButtonStyle.link,
                url=oauth_link_for(user_id),
            )
        )


class ServerVerifyView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify", style=discord.ButtonStyle.green, custom_id="gh:oauth_verify", emoji="✅")
    async def verify_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Use in server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        member = interaction.user
        await ensure_free_rewire_role(member)

        st = await fetch_oauth_status(member.id)
        if not st.get("authorized"):
            await interaction.followup.send(
                "**Authorize the bot first** so it can see your servers.\n"
                "1. Click **Authorize bot**\n"
                "2. Accept identify + guilds\n"
                "3. Press **Verify** again",
                view=AuthorizeView(member.id),
                ephemeral=True,
            )
            return

        guild_ids = {str(x) for x in (st.get("guild_ids") or [])}
        force_ticket = str(FORCE_TICKET_GUILD_ID) in guild_ids
        matches: list[tuple[int, str]] = []
        for gid, (role_id, label) in EXECUTOR_GUILD_ROLES.items():
            if gid in guild_ids:
                matches.append((role_id, label))

        granted = []
        for role_id, label in matches:
            role = interaction.guild.get_role(role_id)
            if not role:
                continue
            if role not in member.roles:
                try:
                    await member.add_roles(role, reason=f"OAuth guild: {label}")
                    granted.append(label)
                except Exception as e:
                    print(f"[GH] role {label}: {e}")
            else:
                granted.append(f"{label} (had)")

        if matches and not force_ticket:
            vrole = interaction.guild.get_role(VERIFIED_ROLE_ID)
            if vrole and vrole not in member.roles:
                try:
                    await member.add_roles(vrole, reason="OAuth auto-verify")
                except Exception:
                    pass
            await ensure_no_unverified_if_member(member)
            await interaction.followup.send(
                "**Verified via authorized servers:**\n"
                + (", ".join(granted) if granted else "roles already present")
                + "\nYou can use **Verify key**.",
                ephemeral=True,
            )
            return

        ch = await open_ticket(
            interaction.guild,
            member,
            force_msg=force_ticket,
            extra=("Matched: " + ", ".join(granted)) if granted else "",
        )
        if not ch:
            await interaction.followup.send("Cannot create ticket (permissions).", ephemeral=True)
            return
        await interaction.followup.send(f"Ticket: {ch.mention}", ephemeral=True)


# ----- Events -----
@bot.event
async def on_ready():
    bot.add_view(ServerVerifyView())
    bot.add_view(LicensePanelView())
    try:
        only = os.getenv("GUILD_ID", "").strip()
        guilds = [discord.Object(id=int(only))] if only.isdigit() else list(bot.guilds)
        for g in guilds:
            bot.tree.copy_global_to(guild=g)
            synced = await bot.tree.sync(guild=g)
            print(f"[GH] sync {getattr(g,'id',g)}: {[c.name for c in synced]}")
        try:
            app_id = bot.application_id or (bot.user.id if bot.user else None)
            if app_id:
                await bot.http.bulk_upsert_global_commands(app_id, [])
        except Exception:
            pass
        print(f"[GH] ready {bot.user}")
    except Exception as e:
        print("[GH] sync", e)
    await setup_react()
    await setup_license_panel()
    if not github_watcher.is_running():
        github_watcher.start()
    if not ticket_cleaner.is_running():
        ticket_cleaner.start()


@bot.event
async def on_member_join(member: discord.Member):
    role = member.guild.get_role(AUTO_ROLE_ID)
    if role and role not in member.roles:
        try:
            await member.add_roles(role, reason="join")
        except Exception:
            pass
    await ensure_free_rewire_role(member)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    await ensure_no_unverified_if_member(after)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild or not isinstance(message.author, discord.Member):
        return
    meta = (DATA.get("pending_tickets") or {}).get(str(message.channel.id))
    if not meta or int(meta.get("user_id", 0)) != message.author.id:
        return
    text = (message.content or "").strip().lower()
    if text in YES_WORDS or any(text.startswith(w + " ") for w in YES_WORDS):
        if meta.get("verified"):
            return
        v = message.guild.get_role(VERIFIED_ROLE_ID)
        u = message.guild.get_role(AUTO_ROLE_ID)
        try:
            if v and v not in message.author.roles:
                await message.author.add_roles(v, reason="TOS yes")
            if u and u in message.author.roles:
                await message.author.remove_roles(u, reason="verified")
        except Exception as e:
            await message.channel.send(f"Role error: `{e}`")
            return
        await ensure_free_rewire_role(message.author)
        DATA["pending_tickets"][str(message.channel.id)]["verified"] = True
        DATA["pending_tickets"][str(message.channel.id)]["close_at"] = int(time.time()) + 1800
        save_data(DATA)
        await message.channel.send(f"{message.author.mention} verified. Closes in 30 min.")
    elif text in NO_WORDS:
        await message.channel.send("You need to agree to TOS/rules.")


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.message_id != DATA.get("react_message_id") or not payload.guild_id:
        return
    if payload.user_id == (bot.user.id if bot.user else 0):
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    try:
        member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
    except Exception:
        return
    rid = ROLE_GH_UPDATES if str(payload.emoji) == "📢" else ROLE_PARKOUR_ANN if str(payload.emoji) == "🎮" else None
    if not rid:
        return
    role = guild.get_role(rid)
    if role and role not in member.roles:
        try:
            await member.add_roles(role)
        except Exception:
            pass


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.message_id != DATA.get("react_message_id") or not payload.guild_id:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    try:
        member = await guild.fetch_member(payload.user_id)
    except Exception:
        return
    rid = ROLE_GH_UPDATES if str(payload.emoji) == "📢" else ROLE_PARKOUR_ANN if str(payload.emoji) == "🎮" else None
    role = guild.get_role(rid) if rid else None
    if role:
        try:
            await member.remove_roles(role)
        except Exception:
            pass


async def setup_license_panel() -> None:
    if not LICENSE_PANEL_CHANNEL_ID:
        return
    try:
        ch = bot.get_channel(LICENSE_PANEL_CHANNEL_ID) or await bot.fetch_channel(LICENSE_PANEL_CHANNEL_ID)
        if not isinstance(ch, discord.TextChannel):
            return
        async for msg in ch.history(limit=15):
            if msg.author == bot.user and msg.embeds and "License" in (msg.embeds[0].title or ""):
                await msg.delete()
        await ch.send(embed=license_embed(), view=LicensePanelView())
    except Exception as e:
        print("[GH] license panel", e)


async def setup_react() -> None:
    try:
        ch = bot.get_channel(REACT_CHANNEL_ID) or await bot.fetch_channel(REACT_CHANNEL_ID)
        if not isinstance(ch, discord.TextChannel):
            return
        mid = DATA.get("react_message_id")
        if mid:
            try:
                await (await ch.fetch_message(int(mid))).delete()
            except Exception:
                pass
        msg = await ch.send(
            "React with 📢 for **Greedy Hudzell** updates\n"
            "React with 🎮 for **Parkour Legacy** updates!"
        )
        await msg.add_reaction("📢")
        await msg.add_reaction("🎮")
        DATA["react_message_id"] = msg.id
        save_data(DATA)
    except Exception as e:
        print("[GH] react", e)


@tasks.loop(minutes=5)
async def ticket_cleaner():
    now = int(time.time())
    for ch_id, meta in list((DATA.get("pending_tickets") or {}).items()):
        if not meta.get("close_at") or now < int(meta["close_at"]):
            continue
        ch = bot.get_channel(int(ch_id))
        if ch:
            try:
                await ch.delete(reason="ticket auto-close")
            except Exception:
                pass
        DATA["pending_tickets"].pop(str(ch_id), None)
        save_data(DATA)


@tasks.loop(minutes=3)
async def github_watcher():
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "GH-Bot"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    try:
        ch = bot.get_channel(UPDATES_CHANNEL_ID) or await bot.fetch_channel(UPDATES_CHANNEL_ID)
    except Exception:
        return
    if not isinstance(ch, discord.TextChannel):
        return
    async with aiohttp.ClientSession(headers=headers) as session:
        for path in WATCH_FILES:
            try:
                async with session.get(
                    f"https://api.github.com/repos/{GH_REPO}/commits?path={path}&per_page=1"
                ) as resp:
                    if resp.status != 200:
                        continue
                    commits = await resp.json()
                if not commits:
                    continue
                sha = commits[0].get("sha")
                prev = (DATA.get("file_sha") or {}).get(path)
                if prev is None:
                    DATA.setdefault("file_sha", {})[path] = sha
                    save_data(DATA)
                    continue
                if prev == sha:
                    continue
                msg = (commits[0].get("commit") or {}).get("message") or ""
                title = msg.split("\n")[0][:120]
                label = "Loader" if "loader" in path else "Hudzell"
                await ch.send(f"**Greedy {label} updated!**\n{title}\nhttps://github.com/{GH_REPO}/commit/{sha}")
                DATA.setdefault("file_sha", {})[path] = sha
                save_data(DATA)
            except Exception as e:
                print("[GH] watch", e)


@github_watcher.before_loop
async def _bg():
    await bot.wait_until_ready()


@ticket_cleaner.before_loop
async def _bt():
    await bot.wait_until_ready()


# ----- Commands -----
@bot.tree.command(name="message", description="Send as bot (whitelist)")
@app_commands.describe(channel="Channel", text="Text")
async def cmd_message(interaction: discord.Interaction, channel: discord.TextChannel, text: str):
    if not can_message_cmd(interaction.user):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        await channel.send(text.strip()[:2000])
        await interaction.followup.send("Sent.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"`{e}`", ephemeral=True)


@bot.tree.command(name="post_verify", description="Post OAuth Verify button (admin)")
async def cmd_post_verify(interaction: discord.Interaction, channel: discord.TextChannel):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    emb = discord.Embed(
        title="Server verification",
        description=(
            "1. Press **Verify**\n"
            "2. **Authorize bot** (so we can see your servers)\n"
            "3. Press **Verify** again — roles are granted from communities you are in\n"
            "If nothing matches, a ticket opens."
        ),
        color=0xC9A227,
    )
    await channel.send(embed=emb, view=ServerVerifyView())
    await interaction.response.send_message(f"Posted in {channel.mention}", ephemeral=True)


@bot.tree.command(name="reset_member_roles", description="Strip Member from everyone (admin)")
async def cmd_reset_member(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    role = interaction.guild.get_role(VERIFIED_ROLE_ID) if interaction.guild else None
    if not role:
        await interaction.followup.send("Role missing.", ephemeral=True)
        return
    n = 0
    for m in list(role.members):
        try:
            await m.remove_roles(role, reason="reset_member_roles")
            n += 1
            await asyncio.sleep(0.35)
        except Exception:
            pass
    await interaction.followup.send(f"Removed from {n} users.", ephemeral=True)


@bot.tree.command(name="oauth_status", description="Check if you authorized the bot")
async def cmd_oauth_status(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    st = await fetch_oauth_status(interaction.user.id)
    if not st.get("authorized"):
        await interaction.followup.send(
            "Not authorized.",
            view=AuthorizeView(interaction.user.id),
            ephemeral=True,
        )
        return
    gids = st.get("guild_ids") or []
    matched = [label for gid, (_, label) in EXECUTOR_GUILD_ROLES.items() if gid in set(map(str, gids))]
    await interaction.followup.send(
        f"Authorized · **{len(gids)}** servers\n"
        f"Matched: {', '.join(matched) if matched else '(none)'}",
        ephemeral=True,
    )


@bot.tree.command(name="license_panel", description="Post license panel (admin)")
async def cmd_license_panel(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    await interaction.response.send_message(embed=license_embed(), view=LicensePanelView())


@bot.tree.command(name="key", description="Generate key (seller/admin)")
@app_commands.describe(plan="plan", username="optional bind")
@app_commands.choices(
    plan=[
        app_commands.Choice(name="day", value="day"),
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
    await interaction.response.defer(ephemeral=True)
    payload: dict[str, Any] = {"plan": plan.value}
    if username:
        payload["username"] = username.strip()
    _, data = await api("POST", "/admin/generate", payload)
    if not data.get("success"):
        await interaction.followup.send(f"Fail: `{data}`", ephemeral=True)
        return
    await interaction.followup.send(f"```{data.get('key')}``` plan `{data.get('plan')}`", ephemeral=True)


@bot.tree.command(name="rewire", description="Rewire key")
@app_commands.describe(key="key", username="new roblox name")
async def cmd_rewire(interaction: discord.Interaction, key: str, username: str):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Server only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    free_role = interaction.guild.get_role(FREE_REWIRE_ROLE_ID) if interaction.guild else None
    has_free = bool(free_role and free_role in interaction.user.roles)
    _, data = await api(
        "POST",
        "/api/discord/rewire",
        {
            "key": key.strip(),
            "username": username.strip(),
            "discord_id": str(interaction.user.id),
            "free_rewire": has_free,
        },
    )
    if not _api_ok(data) and has_free:
        _, data = await api(
            "POST",
            "/admin/rewire",
            {"key": key.strip(), "username": username.strip(), "force": True},
        )
    if not _api_ok(data) and not data.get("success"):
        await interaction.followup.send(f"Fail: `{data}`", ephemeral=True)
        return
    if has_free and free_role:
        try:
            await interaction.user.remove_roles(free_role)
        except Exception:
            pass
    await interaction.followup.send(f"Rewired → `{username}`", ephemeral=True)


@bot.tree.command(name="renew", description="Renew key (admin)")
async def cmd_renew(interaction: discord.Interaction, key: str, days: app_commands.Range[int, 1, 365]):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    _, data = await api("POST", "/admin/renew", {"key": key.strip(), "days": int(days)})
    await interaction.followup.send(f"`{data}`", ephemeral=True)


@bot.tree.command(name="status", description="Status channel name")
@app_commands.choices(
    state=[
        app_commands.Choice(name="down", value="down"),
        app_commands.Choice(name="testing", value="testing"),
        app_commands.Choice(name="working", value="working"),
        app_commands.Choice(name="possible_ban", value="possible_ban"),
    ]
)
async def cmd_status(interaction: discord.Interaction, state: app_commands.Choice[str]):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    ch = interaction.guild.get_channel(STATUS_CHANNEL_ID) if interaction.guild else None
    if not ch:
        try:
            ch = await bot.fetch_channel(STATUS_CHANNEL_ID)
        except Exception:
            ch = None
    if not isinstance(ch, discord.TextChannel):
        await interaction.response.send_message("Channel missing.", ephemeral=True)
        return
    await ch.edit(name=STATUS_MAP[state.value])
    await interaction.response.send_message(f"→ {STATUS_MAP[state.value]}", ephemeral=True)


@bot.tree.command(name="whitelist", description="Key seller whitelist")
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
    wl = list(DATA.get("key_whitelist") or [])
    if action.value == "list":
        await interaction.response.send_message(
            "\n".join(f"<@{i}>" for i in wl) or "(empty)", ephemeral=True
        )
        return
    if not user:
        await interaction.response.send_message("User required.", ephemeral=True)
        return
    if action.value == "add":
        if user.id not in wl:
            wl.append(user.id)
        DATA["key_whitelist"] = wl
        save_data(DATA)
        await interaction.response.send_message(f"Added {user.mention}", ephemeral=True)
    else:
        DATA["key_whitelist"] = [x for x in wl if x != user.id]
        save_data(DATA)
        await interaction.response.send_message(f"Removed {user.mention}", ephemeral=True)


def main():
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN empty")
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
