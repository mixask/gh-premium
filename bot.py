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
import random
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
QUARANTINE_ROLE_ID = int(os.getenv("QUARANTINE_ROLE_ID", "1545461244385828864"))
MOD_ROLE_ID = int(os.getenv("MOD_ROLE_ID", "1445497065177088241"))
WEBHOOKS_CHANNEL_ID = int(os.getenv("WEBHOOKS_CHANNEL_ID", "1546938830333153321"))
JOIN_LOG_CHANNEL_ID = int(os.getenv("JOIN_LOG_CHANNEL_ID", "1438999670075686912"))
DASHBOARD_CHANNEL_ID = int(os.getenv("DASHBOARD_CHANNEL_ID", "1546940370422865930"))
VERIFY_CMD_CHANNEL_ID = int(os.getenv("VERIFY_CMD_CHANNEL_ID", "1544375383338655754"))
BAN_PASSWORD = os.getenv("BAN_PASSWORD", "")
GREETINGS = ["Hey there", "Hi", "Wassup", "Hello", "Yo", "Hey", "Welcome", "Sup"]
RULES_CHANNEL_ID = int(os.getenv("RULES_CHANNEL_ID", "1424116614856441856"))
REACT_CHANNEL_ID = int(os.getenv("REACT_CHANNEL_ID", "1448624840905855037"))
ROLE_PARKOUR_ANN = int(os.getenv("ROLE_PARKOUR_ANN", "1445398639462584450"))
ROLE_GH_UPDATES = int(os.getenv("ROLE_GH_UPDATES", "1443554745481560084"))
UPDATES_CHANNEL_ID = int(os.getenv("UPDATES_CHANNEL_ID", "1428800296926314506"))
GH_REPO = os.getenv("GH_REPO", "mixask/GH")
WATCH_FILES = ("greedy.lua", "greedyloader.lua")
DEFAULT_OWNERS = {1332400034892873761, 1426282728520679454, 1386544747279290459}
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


def is_mod(m: discord.Member) -> bool:
    if is_owner(m) or is_admin(m):
        return True
    return MOD_ROLE_ID in _roles(m)


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
    if status != 200 or not isinstance(data, dict):
        return {"authorized": False, "guild_ids": [], "error": data}
    return data


def oauth_authorize_view(user_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=300)
    view.add_item(
        discord.ui.Button(
            label="Authorize / Verify with Discord",
            style=discord.ButtonStyle.link,
            url=oauth_link_for(user_id),
        )
    )
    return view


async def require_oauth(interaction: discord.Interaction) -> tuple[bool, dict]:
    """Block actions until Discord OAuth (identify+guilds) is completed."""
    st = await fetch_oauth_status(interaction.user.id)
    if st.get("authorized"):
        return True, st
    text = (
        "**You must authorize the bot before Verify key / Rewire.**\n"
        "1. Click **Authorize / Verify with Discord**\n"
        "2. Accept **identify** + **guilds**\n"
        "3. Wait for the **Connected** page, then try again here."
    )
    view = oauth_authorize_view(interaction.user.id)
    if interaction.response.is_done():
        await interaction.followup.send(text, view=view, ephemeral=True)
    else:
        await interaction.response.send_message(text, view=view, ephemeral=True)
    return False, st


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
    kind: str = "auto",
    force_msg: bool = False,
    extra: str = "",
) -> Optional[discord.TextChannel]:
    """
    kind:
      - "auto"  — OAuth / server check failed → classic "couldnt verify automatically"
      - "help"  — user pressed Help ticket → support template
      - other   — legacy fallback
    """
    for ch_id, meta in list((DATA.get("pending_tickets") or {}).items()):
        if int(meta.get("user_id", 0)) == member.id and meta.get("kind", "auto") == kind:
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
    prefix = "help" if kind == "help" else "verify"
    try:
        channel = await guild.create_text_channel(
            name=f"{prefix}-{safe}",
            category=category if isinstance(category, discord.CategoryChannel) else None,
            overwrites=overwrites,
            reason=f"Ticket {kind} for {member}",
        )
    except discord.Forbidden:
        return None
    DATA.setdefault("pending_tickets", {})[str(channel.id)] = {
        "user_id": member.id,
        "created": int(time.time()),
        "kind": kind,
    }
    save_data(DATA)

    # force_msg kept for backward compat → treat as auto
    if force_msg and kind == "auto":
        pass

    if kind == "help":
        text = (
            f"{member.mention}\n"
            "You created a ticket for help in the ticket system / key system.\n"
            "**Please describe the error.**\n\n"
            "**Common errors:**\n"
            "1. **Application didn't respond** — the bot is receiving fixes, or it is temporarily down.\n"
            "2. **We couldn't verify you automatically** — moderators will review the ticket; "
            "this is intentional to prevent abuse."
        )
    elif kind == "auto" or force_msg:
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


async def open_verify_ticket_only(member: discord.Member) -> dict[str, Any]:
    """After OAuth: open staff ticket only — never auto-grant roles from other servers."""
    st = await fetch_oauth_status(member.id)
    if not st.get("authorized"):
        return {"ok": False, "need_oauth": True, "guild_ids": []}
    guild_ids = [str(x) for x in (st.get("guild_ids") or [])]
    ch = await open_ticket(
        member.guild,
        member,
        kind="auto",
        extra=f"OAuth servers seen: {len(guild_ids)}",
    )
    if not ch:
        return {"ok": False, "need_ticket": True, "ticket": None, "guild_ids": guild_ids}
    return {"ok": True, "ticket": ch, "guild_ids": guild_ids}



# ----- License UI -----
class LicenseVerifyModal(discord.ui.Modal, title="Activate license key"):
    key = discord.ui.TextInput(label="License key", min_length=8, max_length=64, required=True)
    roblox = discord.ui.TextInput(label="Roblox username", min_length=3, max_length=20, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.user, discord.Member):
            await interaction.followup.send("Server only.", ephemeral=True)
            return
        ok_oauth, _ = await require_oauth(interaction)
        if not ok_oauth:
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
        # Grant Member after successful key activation
        if interaction.guild:
            vrole = interaction.guild.get_role(VERIFIED_ROLE_ID)
            if vrole and vrole not in interaction.user.roles:
                try:
                    await interaction.user.add_roles(vrole, reason="Key activated")
                except Exception:
                    pass
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
        ok_oauth, _ = await require_oauth(interaction)
        if not ok_oauth:
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

    @discord.ui.button(label="Activate key", style=discord.ButtonStyle.green, custom_id="cl:lic:verify", row=0, emoji="✅")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        One button:
        - not OAuth authorized → Discord authorize link
        - authorized → open key activation modal
        """
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Use in a server.", ephemeral=True)
            return
        st = await fetch_oauth_status(interaction.user.id)
        if not st.get("authorized"):
            await interaction.response.send_message(
                "**Authorize the bot first.**\n"
                "1. Click the button below\n"
                "2. Accept **identify** + **guilds**\n"
                "3. Return here and press **Activate key** again to enter your key",
                view=oauth_authorize_view(interaction.user.id),
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(LicenseVerifyModal())

    @discord.ui.button(label="Rewire", style=discord.ButtonStyle.primary, custom_id="cl:lic:r", row=0)
    async def r(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = await fetch_oauth_status(interaction.user.id)
        if not st.get("authorized"):
            await interaction.response.send_message(
                "**Authorize the bot first** before rewire.",
                view=oauth_authorize_view(interaction.user.id),
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(LicenseRewireModal())

    @discord.ui.button(label="Help ticket", style=discord.ButtonStyle.secondary, custom_id="cl:lic:ticket", row=0)
    async def ticket_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """User-opened support ticket (different message than auto-verify)."""
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Use in a server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        ch = await open_ticket(interaction.guild, interaction.user, kind="help")
        if not ch:
            await interaction.followup.send("Cannot create ticket (permissions / category).", ephemeral=True)
            return
        await interaction.followup.send(f"Help ticket: {ch.mention}", ephemeral=True)



def license_embed() -> discord.Embed:
    return discord.Embed(
        title="License & verification",
        description=(
            "**Verify** — authorize bot (first time) or activate key\n"
            "**Rewire** — move key to another Roblox account\n"
            "**Help ticket** — staff ticket only (no auto roles)\n"
            f"**Get free key** — {KEY_LINK}"
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
    """Legacy: ticket only, no auto roles."""
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify", style=discord.ButtonStyle.green, custom_id="gh:oauth_verify", emoji="✅")
    async def verify_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Use in server.", ephemeral=True)
            return
        st = await fetch_oauth_status(interaction.user.id)
        if not st.get("authorized"):
            await interaction.response.send_message(
                "**Authorize the bot first.**",
                view=oauth_authorize_view(interaction.user.id),
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(LicenseVerifyModal())



# ----- Events -----
@bot.event
async def on_ready():
    bot.add_view(ServerVerifyView())
    bot.add_view(LicensePanelView())
    bot.add_view(SessionModView())
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
    # greet in verify command channel
    try:
        ch = member.guild.get_channel(VERIFY_CMD_CHANNEL_ID)
        if isinstance(ch, discord.TextChannel):
            g = random.choice(GREETINGS)
            await ch.send(
                f"{g} {member.mention}, please use `/verify` in this channel to verify yourself."
            )
    except Exception:
        pass


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
    if not DASHBOARD_CHANNEL_ID or LICENSE_PANEL_CHANNEL_ID:
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
    await channel.send(embed=license_embed(), view=LicensePanelView())
    await interaction.response.send_message(f"Posted in {channel.mention}", ephemeral=True)



def _managed_role_ids() -> set[int]:
    ids = {VERIFIED_ROLE_ID, FREE_REWIRE_ROLE_ID}
    for role_id, _label in EXECUTOR_GUILD_ROLES.values():
        ids.add(int(role_id))
    ids.add(1545094564229161020)  # Solara
    return ids


def _bot_can_manage_role(guild: discord.Guild, role: discord.Role) -> bool:
    me = guild.me
    if me is None:
        return False
    if not me.guild_permissions.manage_roles:
        return False
    # Bot must be strictly above the role
    return me.top_role > role


async def _strip_managed_and_unverify(member: discord.Member) -> tuple[str, str]:
    """Returns (status, detail). status: ok | skip | error"""
    guild = member.guild
    if member.bot:
        return "skip", "bot"
    if is_owner(member):
        return "skip", "owner"
    if member.guild_permissions.administrator and not is_owner(member):
        # still skip true admins, but owners already handled
        if is_admin(member):
            return "skip", "admin"

    managed = _managed_role_ids()
    unverified = guild.get_role(AUTO_ROLE_ID)
    to_remove = [
        r
        for r in member.roles
        if r.id in managed and r.is_assignable and r != guild.default_role
    ]
    details = []
    try:
        for r in to_remove:
            if not _bot_can_manage_role(guild, r):
                details.append(f"cant_remove:{r.name}")
                continue
            try:
                await member.remove_roles(r, reason="reset_roles")
            except Exception as e:
                details.append(f"rm:{r.name}:{e}")
        if unverified is None:
            return "error", "unverified_role_missing"
        if not _bot_can_manage_role(guild, unverified):
            return "error", (
                f"bot_role_too_low (bot={guild.me.top_role.name if guild.me else '?'} "
                f"< unverified={unverified.name})"
            )
        if unverified not in member.roles:
            await member.add_roles(unverified, reason="reset_roles → unverified")
            details.append("added_unverified")
        else:
            details.append("already_unverified")
        return "ok", ",".join(details) or "ok"
    except Exception as e:
        return "error", str(e)


class ResetRolesConfirmView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=90)
        self.author_id = author_id
        self.done = False

    @discord.ui.button(label="Confirm reset", style=discord.ButtonStyle.danger, custom_id="gh:reset_roles:yes")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Not your confirmation.", ephemeral=True)
            return
        if self.done:
            await interaction.response.send_message("Already running/done.", ephemeral=True)
            return
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        if not is_admin(interaction.user):
            await interaction.response.send_message("Admin only.", ephemeral=True)
            return

        self.done = True
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.response.edit_message(content="⏳ Resetting roles…", view=self)

        guild = interaction.guild
        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            await interaction.followup.send(
                "Bot needs **Manage Roles** and its role must be **above** Unverified + Member.",
                ephemeral=True,
            )
            return

        unverified = guild.get_role(AUTO_ROLE_ID)
        if unverified is None:
            await interaction.followup.send(
                f"Unverified role id `{AUTO_ROLE_ID}` not found on this server.",
                ephemeral=True,
            )
            return
        if not _bot_can_manage_role(guild, unverified):
            await interaction.followup.send(
                f"Move bot role **above** `{unverified.name}` in Server Settings → Roles.",
                ephemeral=True,
            )
            return

        # Ensure member cache is as full as possible
        try:
            if not guild.chunked:
                await guild.chunk(cache=True)
        except Exception:
            pass

        ok = skip = err = 0
        err_samples: list[str] = []
        for member in list(guild.members):
            status, detail = await _strip_managed_and_unverify(member)
            if status == "ok":
                ok += 1
            elif status == "skip":
                skip += 1
            else:
                err += 1
                if len(err_samples) < 5:
                    err_samples.append(f"{member}: {detail}")
            await asyncio.sleep(0.3)

        extra = ("\n" + "\n".join(err_samples)) if err_samples else ""
        await interaction.followup.send(
            f"**Reset done**\n"
            f"• updated: `{ok}`\n"
            f"• skipped (bot/owner/admin): `{skip}`\n"
            f"• errors: `{err}`{extra}",
            ephemeral=True,
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="gh:reset_roles:no")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Not your confirmation.", ephemeral=True)
            return
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.response.edit_message(content="Cancelled.", view=self)


@bot.tree.command(name="reset_roles", description="Reset managed roles → Unverified for all (admin)")
async def cmd_reset_roles(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    guild = interaction.guild
    unverified = guild.get_role(AUTO_ROLE_ID) if guild else None
    warn = []
    if unverified is None:
        warn.append(f"⚠ role `{AUTO_ROLE_ID}` missing")
    elif guild and guild.me and not _bot_can_manage_role(guild, unverified):
        warn.append(f"⚠ bot role must be **above** `{unverified.name}`")
    if guild and guild.me and not guild.me.guild_permissions.manage_roles:
        warn.append("⚠ bot missing **Manage Roles**")
    warn_txt = ("\n" + "\n".join(warn)) if warn else ""
    await interaction.response.send_message(
        "⚠️ Removes **Member**, executor roles, free-rewire from non-admins, "
        "then grants **Unverified**.\n"
        "Owners/admins/bots are **skipped**.\n"
        f"Unverified role: `{unverified.name if unverified else AUTO_ROLE_ID}`"
        f"{warn_txt}\n"
        "Press **Confirm reset** within 90s.",
        view=ResetRolesConfirmView(interaction.user.id),
        ephemeral=True,
    )


@bot.tree.command(name="set_unverified", description="Force Unverified on one member (admin)")
@app_commands.describe(member="Target member")
async def cmd_set_unverified(interaction: discord.Interaction, member: discord.Member):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    if is_owner(member) and not is_owner(interaction.user):
        await interaction.followup.send("Cannot modify owner.", ephemeral=True)
        return
    # Allow admin to set unverified even on other admins only if caller is owner
    if is_admin(member) and not is_owner(interaction.user):
        await interaction.followup.send("Only owners can reset admins.", ephemeral=True)
        return
    # Temporarily treat target as non-admin path: strip managed + add unverified
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("Guild only.", ephemeral=True)
        return
    unverified = guild.get_role(AUTO_ROLE_ID)
    if unverified is None:
        await interaction.followup.send(f"Unverified role `{AUTO_ROLE_ID}` missing.", ephemeral=True)
        return
    if not _bot_can_manage_role(guild, unverified):
        await interaction.followup.send(
            f"Move bot role **above** `{unverified.name}`.",
            ephemeral=True,
        )
        return
    managed = _managed_role_ids()
    removed = []
    for r in list(member.roles):
        if r.id in managed and r.is_assignable:
            try:
                await member.remove_roles(r, reason="set_unverified")
                removed.append(r.name)
            except Exception as e:
                removed.append(f"{r.name}?{e}")
    try:
        if unverified not in member.roles:
            await member.add_roles(unverified, reason="set_unverified")
        await interaction.followup.send(
            f"{member.mention} → Unverified. Removed: {', '.join(removed) or '—'}",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.followup.send(f"Failed to add Unverified: `{e}`", ephemeral=True)


@bot.tree.command(name="reset_member_roles", description="Strip Member only (admin)")
async def cmd_reset_member(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    role = interaction.guild.get_role(VERIFIED_ROLE_ID) if interaction.guild else None
    if not role:
        await interaction.followup.send("Member role missing.", ephemeral=True)
        return
    if interaction.guild and not _bot_can_manage_role(interaction.guild, role):
        await interaction.followup.send(
            f"Bot role must be above `{role.name}`.",
            ephemeral=True,
        )
        return
    n = 0
    for m in list(role.members):
        if is_owner(m) or is_admin(m):
            continue
        try:
            await m.remove_roles(role, reason="reset_member_roles")
            n += 1
            await asyncio.sleep(0.3)
        except Exception:
            pass
    await interaction.followup.send(f"Removed Member from {n} users (admins skipped).", ephemeral=True)


@bot.tree.command(name="oauth_status", description="Check if you authorized the bot")
async def cmd_oauth_status(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    st = await fetch_oauth_status(interaction.user.id)
    if not st.get("authorized"):
        await interaction.followup.send(
            "Not authorized.",
            view=oauth_authorize_view(interaction.user.id),
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


@bot.tree.command(name="license_panel", description="Post license panel to dashboard (admin)")
async def cmd_license_panel(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    ch = None
    if interaction.guild:
        ch = interaction.guild.get_channel(DASHBOARD_CHANNEL_ID)
    if not isinstance(ch, discord.TextChannel):
        # fallback: post in current channel
        await interaction.response.send_message(embed=license_embed(), view=LicensePanelView())
        return
    await ch.send(embed=license_embed(), view=LicensePanelView())
    await interaction.response.send_message(f"Posted to {ch.mention}", ephemeral=True)


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



# ----- Moderation helpers -----

@bot.tree.command(name="quarantine", description="Quarantine member: strip managed roles, add quarantine role")
@app_commands.describe(member="User to quarantine", reason="Optional reason")
async def cmd_quarantine(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: Optional[str] = None,
):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    if is_owner(member):
        await interaction.followup.send("Cannot quarantine an owner.", ephemeral=True)
        return
    guild = interaction.guild
    if guild is None:
        return
    qrole = guild.get_role(QUARANTINE_ROLE_ID)
    if qrole is None:
        await interaction.followup.send(f"Quarantine role `{QUARANTINE_ROLE_ID}` not found.", ephemeral=True)
        return
    if not _bot_can_manage_role(guild, qrole):
        await interaction.followup.send(f"Bot role must be above `{qrole.name}`.", ephemeral=True)
        return
    managed = _managed_role_ids() | {VERIFIED_ROLE_ID, FREE_REWIRE_ROLE_ID, AUTO_ROLE_ID}
    removed = []
    for r in list(member.roles):
        if r == guild.default_role or r >= guild.me.top_role:  # type: ignore
            continue
        if r.id in managed or (not r.managed and r != qrole):
            # strip all assignable non-integrated roles except keep none
            if r.is_assignable and r != qrole:
                try:
                    await member.remove_roles(r, reason=f"quarantine by {interaction.user}: {reason or ''}")
                    removed.append(r.name)
                except Exception:
                    pass
    try:
        if qrole not in member.roles:
            await member.add_roles(qrole, reason=f"quarantine: {reason or 'n/a'}")
    except Exception as e:
        await interaction.followup.send(f"Failed to add quarantine: `{e}`", ephemeral=True)
        return
    await interaction.followup.send(
        f"🔒 {member.mention} quarantined.\nRemoved: {', '.join(removed[:15]) or '—'}"
        + (f"\nReason: {reason}" if reason else ""),
        ephemeral=True,
    )


@bot.tree.command(name="unquarantine", description="Remove quarantine role")
@app_commands.describe(member="User", give_unverified="Also give Unverified role")
async def cmd_unquarantine(
    interaction: discord.Interaction,
    member: discord.Member,
    give_unverified: bool = True,
):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if not guild:
        return
    qrole = guild.get_role(QUARANTINE_ROLE_ID)
    if qrole and qrole in member.roles:
        try:
            await member.remove_roles(qrole, reason=f"unquarantine by {interaction.user}")
        except Exception as e:
            await interaction.followup.send(f"Failed: `{e}`", ephemeral=True)
            return
    if give_unverified:
        u = guild.get_role(AUTO_ROLE_ID)
        if u and u not in member.roles:
            try:
                await member.add_roles(u, reason="unquarantine → unverified")
            except Exception:
                pass
    await interaction.followup.send(f"Unlocked {member.mention}.", ephemeral=True)


@bot.tree.command(name="grant_member", description="Manually grant Member role (staff after ticket)")
async def cmd_grant_member(interaction: discord.Interaction, member: discord.Member):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if not guild:
        return
    vrole = guild.get_role(VERIFIED_ROLE_ID)
    if not vrole:
        await interaction.followup.send("Member role missing.", ephemeral=True)
        return
    try:
        if vrole not in member.roles:
            await member.add_roles(vrole, reason=f"grant_member by {interaction.user}")
        await ensure_no_unverified_if_member(member)
        await ensure_free_rewire_role(member)
        await interaction.followup.send(f"Granted Member to {member.mention}.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"`{e}`", ephemeral=True)


@bot.tree.command(name="lookup_key", description="Lookup key status via API (admin)")
@app_commands.describe(key="License key")
async def cmd_lookup_key(interaction: discord.Interaction, key: str):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    key = key.strip()
    status, data = await api("GET", f"/admin/key/{key}")
    if status != 200:
        # try validate shape
        status2, data2 = await api("POST", "/validate", {"key": key, "username": "_lookup_"})
        await interaction.followup.send(
            f"HTTP {status}/{status2}\n```json\n{json.dumps(data or data2, indent=2)[:1500]}\n```",
            ephemeral=True,
        )
        return
    await interaction.followup.send(
        f"```json\n{json.dumps(data, indent=2)[:1800]}\n```",
        ephemeral=True,
    )


@bot.tree.command(name="purge_tickets", description="Delete open verify-* ticket channels (admin)")
async def cmd_purge_tickets(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if not guild:
        return
    n = 0
    pending = dict(DATA.get("pending_tickets") or {})
    for ch_id in list(pending.keys()):
        ch = guild.get_channel(int(ch_id))
        if ch and isinstance(ch, discord.TextChannel):
            try:
                await ch.delete(reason="purge_tickets")
                n += 1
            except Exception:
                pass
        pending.pop(ch_id, None)
    DATA["pending_tickets"] = pending
    save_data(DATA)
    await interaction.followup.send(f"Deleted `{n}` ticket channels.", ephemeral=True)


@bot.tree.command(name="say", description="Send a message as the bot (whitelist/admin)")
@app_commands.describe(channel="Channel", text="Message text")
async def cmd_say(interaction: discord.Interaction, channel: discord.TextChannel, text: str):
    if not can_message_cmd(interaction.user):
        await interaction.response.send_message("Not allowed.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        await channel.send(text[:2000])
        await interaction.followup.send("Sent.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"`{e}`", ephemeral=True)


@bot.tree.command(name="userinfo", description="Show member roles / ids (admin)")
async def cmd_userinfo(interaction: discord.Interaction, member: discord.Member):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    roles = ", ".join(r.mention for r in member.roles if r != interaction.guild.default_role)  # type: ignore
    emb = discord.Embed(title=str(member), color=0xD4AF37)
    emb.add_field(name="ID", value=str(member.id), inline=False)
    emb.add_field(name="Roles", value=roles[:1000] or "—", inline=False)
    emb.add_field(name="Joined", value=str(member.joined_at), inline=False)
    await interaction.response.send_message(embed=emb, ephemeral=True)



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



# ----- GH ban / unban / verify / webhook -----

@bot.tree.command(name="verify", description="Get Discord OAuth verification link")
async def cmd_verify(interaction: discord.Interaction):
    await interaction.response.send_message(
        "Authorize the bot (identify + guilds), then use **Activate key** on the license panel.",
        view=oauth_authorize_view(interaction.user.id),
        ephemeral=True,
    )


@bot.tree.command(name="ban", description="Ban key and/or Roblox username from GH")
@app_commands.describe(key="License key", username="Roblox username", reason="Reason")
async def cmd_ban(
    interaction: discord.Interaction,
    key: str = "",
    username: str = "",
    reason: str = "",
):
    if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
        await interaction.response.send_message("Mod only.", ephemeral=True)
        return
    if not key.strip() and not username.strip():
        await interaction.response.send_message("Need key and/or username.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    _, data = await api(
        "POST",
        "/admin/ban",
        {
            "key": key.strip(),
            "username": username.strip(),
            "reason": reason,
            "by_discord": str(interaction.user.id),
        },
    )
    await interaction.followup.send(
        "Banned." if _api_ok(data) or data.get("success") else f"Fail: `{data}`",
        ephemeral=True,
    )


@bot.tree.command(name="unban", description="Remove GH ban by key and/or username")
@app_commands.describe(key="License key", username="Roblox username")
async def cmd_unban(interaction: discord.Interaction, key: str = "", username: str = ""):
    if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
        await interaction.response.send_message("Mod only.", ephemeral=True)
        return
    if not key.strip() and not username.strip():
        await interaction.response.send_message("Need key and/or username.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    _, data = await api(
        "POST",
        "/admin/unban",
        {
            "key": key.strip(),
            "username": username.strip(),
            "by_discord": str(interaction.user.id),
        },
    )
    await interaction.followup.send(
        "Unbanned." if _api_ok(data) or data.get("success") else f"Fail: `{data}`",
        ephemeral=True,
    )


@bot.tree.command(name="create_webhook", description="Create personal webhook in GH webhooks channel (mod)")
@app_commands.describe(roblox_name="Roblox username for webhook name")
async def cmd_create_webhook(interaction: discord.Interaction, roblox_name: str):
    if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
        await interaction.response.send_message("Mod only (users: hub Create Webhook).", ephemeral=True)
        return
    if not interaction.guild:
        await interaction.response.send_message("Guild only.", ephemeral=True)
        return
    ch = interaction.guild.get_channel(WEBHOOKS_CHANNEL_ID)
    if not isinstance(ch, discord.TextChannel):
        await interaction.response.send_message("Webhooks channel missing.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    name = re.sub(r"[^\w\- ]", "", roblox_name)[:80] or "gh-user"
    try:
        wh = await ch.create_webhook(name=name, reason=f"GH webhook {roblox_name}")
    except Exception as e:
        await interaction.followup.send(f"Fail: `{e}`", ephemeral=True)
        return
    await api(
        "POST",
        "/admin/webhook-register",
        {
            "webhook_id": str(wh.id),
            "url": wh.url,
            "roblox_name": roblox_name,
            "discord_id": str(interaction.user.id),
        },
    )
    await interaction.followup.send(f"Created:\n`{wh.url}`", ephemeral=True)


@bot.tree.command(name="fix_command_scope", description="How to allow slash commands outside threads")
async def cmd_fix_command_scope(interaction: discord.Interaction):
    await interaction.response.send_message(
        "Server Settings → Integrations → this bot → enable slash commands in **text channels** "
        "(not threads-only). Discord UI controls this.",
        ephemeral=True,
    )


class SessionKickModal(discord.ui.Modal, title="Kick player (client)"):
    reason = discord.ui.TextInput(label="Kick message", max_length=200)

    def __init__(self, roblox_id: str, roblox_name: str):
        super().__init__()
        self.roblox_id = roblox_id
        self.roblox_name = roblox_name

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            await interaction.response.send_message("Mod only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        _, data = await api(
            "POST",
            "/admin/kick",
            {"user_id": self.roblox_id, "reason": str(self.reason)},
        )
        await interaction.followup.send(
            f"Kick queued for **{self.roblox_name}**."
            if data.get("success") or _api_ok(data)
            else f"Fail: `{data}`",
            ephemeral=True,
        )


class SessionBanModal(discord.ui.Modal, title="Ban key + username"):
    password = discord.ui.TextInput(label="Confirm password", max_length=64)
    reason = discord.ui.TextInput(label="Reason", required=False, max_length=200)

    def __init__(self, key: str, roblox_name: str):
        super().__init__()
        self.key = key
        self.roblox_name = roblox_name

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            await interaction.response.send_message("Mod only.", ephemeral=True)
            return
        if BAN_PASSWORD and str(self.password) != BAN_PASSWORD:
            await interaction.response.send_message("Wrong password.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        _, data = await api(
            "POST",
            "/admin/ban",
            {
                "key": self.key,
                "username": self.roblox_name,
                "reason": str(self.reason or ""),
                "by_discord": str(interaction.user.id),
            },
        )
        await interaction.followup.send(
            "Banned." if data.get("success") or _api_ok(data) else f"Fail: `{data}`",
            ephemeral=True,
        )


class SessionModView(discord.ui.View):
    """Persistent-ish session controls (custom_id includes payload via short hash optional)."""

    def __init__(self, roblox_name: str = "", roblox_id: str = "", key: str = ""):
        super().__init__(timeout=None)
        self.roblox_name = roblox_name
        self.roblox_id = str(roblox_id)
        self.key = key or ""

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.secondary, custom_id="gh:sess:kick")
    async def kick_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            await interaction.response.send_message("Mod only.", ephemeral=True)
            return
        # Prefer modal; roblox_id may be empty if view restored without state
        await interaction.response.send_modal(
            SessionKickModal(self.roblox_id or "0", self.roblox_name or "player")
        )

    @discord.ui.button(label="Ban", style=discord.ButtonStyle.danger, custom_id="gh:sess:ban")
    async def ban_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not is_mod(interaction.user):
            await interaction.response.send_message("Mod only.", ephemeral=True)
            return
        await interaction.response.send_modal(
            SessionBanModal(self.key, self.roblox_name or "")
        )



def main():
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN empty")
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
