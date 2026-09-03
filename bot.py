"""
Greedy Hudzell Discord bot (updated)
Env:
  DISCORD_TOKEN, ADMIN_SECRET, API_BASE
  KEY_LINK, STATUS_CHANNEL_ID, GUILD_ID (main guild, optional sync)
  FREE_REWIRE_ROLE_ID default 1545088955572158484
  VERIFIED_ROLE_ID, AUTO_ROLE_ID (unverified)
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
KEY_LINK = os.getenv("KEY_LINK", "https://work.ink/28wp/Greedy-hudzell")

STATUS_CHANNEL_ID = int(os.getenv("STATUS_CHANNEL_ID", "1472311662307574025"))
AUTO_ROLE_ID = int(os.getenv("AUTO_ROLE_ID", "1448728578844786978"))  # unverified
VERIFY_CHANNEL_ID = int(os.getenv("VERIFY_CHANNEL_ID", "0") or 0)  # 0 = do not auto-post verify
LICENSE_PANEL_CHANNEL_ID = int(os.getenv("LICENSE_PANEL_CHANNEL_ID", "0") or 0)
VERIFY_CATEGORY_ID = int(os.getenv("VERIFY_CATEGORY_ID", "1453098727253479526"))
VERIFIED_ROLE_ID = int(os.getenv("VERIFIED_ROLE_ID", "1445500571640402052"))  # member
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

# Guild that forces a manual ticket (cannot auto-verify)
FORCE_TICKET_GUILD_ID = int(os.getenv("FORCE_TICKET_GUILD_ID", "1228053668797091904"))

# External guild id -> role id on MAIN server (executor communities)
# Bot must be a member of these guilds to detect users.
EXECUTOR_GUILD_ROLES: dict[int, tuple[int, str]] = {
    1289988589052104846: (1545091882101506048, "Potassium"),
    1483453559692595252: (1545092000116904017, "Madium"),
    1497654383234515131: (1545092121814499369, "Real"),
    1448237723352825984: (1545092381265633340, "Volt"),
    1376842062007111750: (1545092590901395496, "Wave"),
    1329189629466771577: (1545093045555298404, "Synapse Z"),
    1330492468700905472: (1545093326225543188, "Isaeva"),
    1534485185427538022: (1545093448825311292, "Cosmic"),
    943223926509699072: (1545093488251510884, "Velocity"),
    1364170844867399722: (1545093815117811712, "SirHurt"),
    # Solara: no guild id — not auto-detected
    1289659915790450849: (1545094729232941156, "Xeno"),
    1262951163943452723: (1545094956564095046, "MacSploit"),
    1253107828835483679: (1545095111015272488, "OpiumWare"),
    1221935816515911850: (1545095225993855008, "Delta"),
}
SOLARA_ROLE_ID = 1545094564229161020  # no guild mapping

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
MESSAGE_WHITELIST = _parse_ids(os.getenv("MESSAGE_WHITELIST", "")) | OWNER_USER_IDS

# -------------------- Persistence --------------------
_default_data: dict[str, Any] = {
    "key_whitelist": [],
    "verify_message_id": None,
    "react_message_id": None,
    "file_sha": {},
    "pending_tickets": {},
    "discord_claims": {},
    "message_whitelist": [],  # extra user ids for /message
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


def is_verified(member: discord.Member) -> bool:
    if is_admin(member):
        return True
    return VERIFIED_ROLE_ID in _member_role_ids(member)


def is_seller(member: discord.Member) -> bool:
    if is_admin(member):
        return True
    if int(member.id) in set(DATA.get("key_whitelist") or []):
        return True
    roles = _member_role_ids(member)
    if SELLER_ROLE_IDS and roles & SELLER_ROLE_IDS:
        return True
    return False


def can_message_cmd(user: discord.abc.User) -> bool:
    if is_owner(user):
        return True
    if int(user.id) in MESSAGE_WHITELIST:
        return True
    if int(user.id) in set(DATA.get("message_whitelist") or []):
        return True
    if int(user.id) in set(DATA.get("key_whitelist") or []):
        return True
    if isinstance(user, discord.Member) and is_admin(user):
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
                return resp.status, {"success": False, "reason": "Cloudflare blocked the request."}
            try:
                data = json.loads(raw)
            except Exception:
                data = {"success": False, "reason": f"bad_response: {raw[:200]}"}
            if not isinstance(data, dict):
                data = {"success": False, "reason": "invalid_json_body"}
            return resp.status, data


def _api_ok(data: dict) -> bool:
    return bool(data.get("ok") or data.get("success") or data.get("valid"))


async def ensure_no_unverified_if_member(member: discord.Member) -> None:
    """Member (verified) must not keep unverified role."""
    roles = _member_role_ids(member)
    if VERIFIED_ROLE_ID not in roles:
        return
    unverified = member.guild.get_role(AUTO_ROLE_ID)
    if unverified and unverified in member.roles:
        try:
            await member.remove_roles(unverified, reason="Has Member — remove unverified")
        except Exception as e:
            print(f"[GH] strip unverified: {e}")


async def ensure_free_rewire_role(member: discord.Member) -> None:
    role = member.guild.get_role(FREE_REWIRE_ROLE_ID)
    if not role:
        return
    if role not in member.roles:
        try:
            await member.add_roles(role, reason="Free rewire entitlement")
        except Exception as e:
            print(f"[GH] free rewire role: {e}")


async def user_in_guild(guild_id: int, user_id: int) -> bool:
    """Requires bot to be in that guild + Members intent."""
    g = bot.get_guild(guild_id)
    if g is None:
        return False
    m = g.get_member(user_id)
    if m is not None:
        return True
    try:
        await g.fetch_member(user_id)
        return True
    except (discord.NotFound, discord.HTTPException):
        return False


async def detect_executor_roles(main_guild: discord.Guild, user_id: int) -> list[tuple[int, str]]:
    """Return list of (role_id, label) the user qualifies for via mutual guilds."""
    found: list[tuple[int, str]] = []
    for gid, (role_id, label) in EXECUTOR_GUILD_ROLES.items():
        try:
            if await user_in_guild(gid, user_id):
                found.append((role_id, label))
        except Exception as e:
            print(f"[GH] guild check {gid}: {e}")
    return found


async def open_verify_ticket(
    guild: discord.Guild,
    member: discord.Member,
    *,
    force_auto_fail: bool = False,
    note: str = "",
) -> Optional[discord.TextChannel]:
    # existing ticket?
    for ch_id, meta in list((DATA.get("pending_tickets") or {}).items()):
        if int(meta.get("user_id", 0)) == member.id:
            ch = guild.get_channel(int(ch_id))
            if ch:
                return ch  # type: ignore

    category = guild.get_channel(VERIFY_CATEGORY_ID)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_channels=True
        ),
    }
    for role in guild.roles:
        if role.permissions.administrator or role.id in ADMIN_ROLE_IDS:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

    safe_name = re.sub(r"[^a-z0-9\-]", "", member.name.lower())[:20] or "user"
    try:
        channel = await guild.create_text_channel(
            name=f"verify-{safe_name}",
            category=category if isinstance(category, discord.CategoryChannel) else None,
            overwrites=overwrites,
            reason=f"Verify ticket for {member}",
        )
    except discord.Forbidden:
        return None

    DATA.setdefault("pending_tickets", {})[str(channel.id)] = {
        "user_id": member.id,
        "created": int(time.time()),
        "force_auto_fail": force_auto_fail,
    }
    save_data(DATA)

    if force_auto_fail:
        await channel.send(
            f"{member.mention}\n"
            "We couldnt verify you automatically, sorry for that. "
            "Moderators will assist you shortly.\n"
            "P.S. if moderators didnt answer for a long time, you can request a free key."
            + (f"\n\n{note}" if note else "")
        )
    else:
        rules = f"<#{RULES_CHANNEL_ID}>"
        await channel.send(
            f"{member.mention}\n"
            f"Automatic executor-server check found **no** matching communities.\n"
            f"Do you agree to our {rules}, **TOS** and **Privacy Policy**?\n"
            f"Reply with **yes** / **no** (or agree / decline).\n"
            "Moderators can also assist you here."
            + (f"\n\n{note}" if note else "")
        )
    return channel


# -------------------- License modals --------------------
class LicenseVerifyModal(discord.ui.Modal, title="Activate license key"):
    key = discord.ui.TextInput(
        label="License key",
        placeholder="GH-XXXX-XXXX-XXXX",
        min_length=8,
        max_length=64,
        required=True,
    )
    roblox = discord.ui.TextInput(
        label="Roblox username",
        placeholder="Exact account name",
        min_length=3,
        max_length=20,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.followup.send("Use this in the server.", ephemeral=True)
            return
        # Require server Member (verified) before key activate
        if not is_verified(interaction.user):
            await interaction.followup.send(
                "Authorize / verify in this server first (Verify button → executor check or ticket), "
                "then activate your key.",
                ephemeral=True,
            )
            return

        key = str(self.key.value).strip()
        username = str(self.roblox.value).strip()
        if not re.match(r"^[A-Za-z0-9_]+$", username):
            await interaction.followup.send("Invalid Roblox username.", ephemeral=True)
            return

        status, data = await api(
            "POST",
            "/api/discord/verify-key",
            {
                "key": key,
                "roblox_username": username,
                "username": username,
                "discord_id": str(interaction.user.id),
            },
        )
        if not _api_ok(data):
            err = data.get("error") or data.get("reason") or data.get("message") or data
            await interaction.followup.send(f"Activate failed: `{err}`", ephemeral=True)
            return

        role_note = ""
        role = interaction.guild.get_role(VERIFIED_ROLE_ID)
        if role and role not in interaction.user.roles:
            try:
                await interaction.user.add_roles(role, reason="License activated")
                role_note = "\nMember role granted."
            except Exception as e:
                role_note = f"\nRole error: `{e}`"
        await ensure_no_unverified_if_member(interaction.user)
        await ensure_free_rewire_role(interaction.user)

        re_note = "\n_(re-activated)_" if data.get("reactivated") else ""
        await interaction.followup.send(
            f"**Key activated**\n"
            f"Plan: `{data.get('plan', '?')}`\n"
            f"Expires: `{data.get('expires_at', '?')}`\n"
            f"Roblox: `{username}`"
            f"{role_note}{re_note}",
            ephemeral=True,
        )


class LicenseRewireModal(discord.ui.Modal, title="Rewire key"):
    key = discord.ui.TextInput(
        label="License key",
        placeholder="GH-XXXX-XXXX-XXXX",
        min_length=8,
        max_length=64,
        required=True,
    )
    roblox = discord.ui.TextInput(
        label="New Roblox username",
        placeholder="Account to bind",
        min_length=3,
        max_length=20,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.followup.send("Use this in the server.", ephemeral=True)
            return

        key = str(self.key.value).strip()
        username = str(self.roblox.value).strip()
        if not re.match(r"^[A-Za-z0-9_]+$", username):
            await interaction.followup.send("Invalid Roblox username.", ephemeral=True)
            return

        free_role = interaction.guild.get_role(FREE_REWIRE_ROLE_ID)
        has_free = bool(free_role and free_role in interaction.user.roles)

        status, data = await api(
            "POST",
            "/api/discord/rewire",
            {
                "key": key,
                "roblox_username": username,
                "username": username,
                "discord_id": str(interaction.user.id),
                "free_rewire": has_free,
            },
        )

        # If API rejects unpaid but user has free rewire role, force bind via admin renew path is not available.
        # Prefer API success; if failed for paid-only and has free role, call admin rewire if exposed.
        if not _api_ok(data) and has_free:
            status2, data2 = await api(
                "POST",
                "/admin/rewire",
                {
                    "key": key,
                    "username": username,
                    "discord_id": str(interaction.user.id),
                    "force": True,
                },
            )
            if _api_ok(data2) or data2.get("success"):
                data = data2
            else:
                # last resort: admin generate bind not available — report original error
                err = data.get("error") or data.get("reason") or data2.get("reason") or data
                await interaction.followup.send(
                    f"Rewire failed: `{err}`\n"
                    f"_Free rewire role is present; if this keeps failing, staff must enable free rewire on API._",
                    ephemeral=True,
                )
                return
        elif not _api_ok(data):
            err = data.get("error") or data.get("reason") or data.get("message") or data
            await interaction.followup.send(
                f"Rewire failed: `{err}`\n"
                + ("You need the **Free Rewire** role or a paid key." if not has_free else ""),
                ephemeral=True,
            )
            return

        # Consume free rewire role after successful rewire
        if has_free and free_role:
            try:
                await interaction.user.remove_roles(free_role, reason="Used 1 free rewire")
            except Exception as e:
                print(f"[GH] remove free rewire: {e}")

        await interaction.followup.send(
            f"**Rewired** `{data.get('previous_username', '?')}` → `{username}`\n"
            f"Plan: `{data.get('plan', '?')}`\n"
            + ("Free rewire role consumed." if has_free else "Paid rewire."),
            ephemeral=True,
        )


class LicensePanelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Get free key",
                style=discord.ButtonStyle.link,
                url=KEY_LINK,
                row=1,
            )
        )

    @discord.ui.button(
        label="Verify key",
        style=discord.ButtonStyle.success,
        custom_id="clientlink:license:verify",
        row=0,
    )
    async def license_verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LicenseVerifyModal())

    @discord.ui.button(
        label="Rewire",
        style=discord.ButtonStyle.primary,
        custom_id="clientlink:license:rewire",
        row=0,
    )
    async def license_rewire(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LicenseRewireModal())


def license_panel_embed() -> discord.Embed:
    e = discord.Embed(
        title="License panel",
        description=(
            f"**Get free key** — {KEY_LINK}\n\n"
            "**Verify key** — activate license (server Member required first).\n"
            "You can activate again for new keys.\n\n"
            "**Rewire** — paid keys, **or** 1× free if you have the Free Rewire role "
            f"(role id `{FREE_REWIRE_ROLE_ID}`; removed after use).\n\n"
            "1. Server verify (executor communities / ticket)\n"
            "2. Get key\n"
            "3. Verify key + Roblox name\n"
            "4. Loader in-game"
        ),
        color=0xD4AF37,
    )
    e.set_footer(text="Do not share your key")
    return e


# -------------------- Server verify (executor guilds) --------------------
class ServerVerifyView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Verify",
        style=discord.ButtonStyle.green,
        custom_id="gh:server_verify",
        emoji="✅",
    )
    async def verify_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Use this in the server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        member = interaction.user

        # Ensure free rewire role exists on user
        await ensure_free_rewire_role(member)

        force_ticket = await user_in_guild(FORCE_TICKET_GUILD_ID, member.id)
        matches = await detect_executor_roles(interaction.guild, member.id)

        granted: list[str] = []
        for role_id, label in matches:
            role = interaction.guild.get_role(role_id)
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason=f"Executor guild: {label}")
                    granted.append(label)
                except Exception as e:
                    print(f"[GH] grant {label}: {e}")
            elif role and role in member.roles:
                granted.append(f"{label} (had)")

        # Auto member if at least one executor match and not force-ticket guild
        if matches and not force_ticket:
            vrole = interaction.guild.get_role(VERIFIED_ROLE_ID)
            if vrole and vrole not in member.roles:
                try:
                    await member.add_roles(vrole, reason="Auto-verify via executor guild")
                except Exception as e:
                    print(f"[GH] member role: {e}")
            await ensure_no_unverified_if_member(member)
            await interaction.followup.send(
                "**Auto-verified** via executor communities:\n"
                + (", ".join(granted) if granted else "roles already present")
                + "\nYou can use **Verify key** on the license panel.",
                ephemeral=True,
            )
            return

        # Force ticket guild OR no matches → ticket
        ch = await open_verify_ticket(
            interaction.guild,
            member,
            force_auto_fail=force_ticket,
            note=("Detected communities: " + ", ".join(granted)) if granted else "",
        )
        if ch is None:
            await interaction.followup.send(
                "Could not create ticket (bot needs Manage Channels).",
                ephemeral=True,
            )
            return
        await interaction.followup.send(f"Ticket: {ch.mention}", ephemeral=True)


# -------------------- Events --------------------
@bot.event
async def on_ready():
    bot.add_view(ServerVerifyView())
    bot.add_view(LicensePanelView())
    try:
        names = [c.name for c in bot.tree.get_commands()]
        print(f"[GH] tree commands ({len(names)}): {', '.join(names)}")
        only = os.getenv("GUILD_ID", "").strip()
        if only.isdigit():
            guilds = [discord.Object(id=int(only))]
        else:
            guilds = list(bot.guilds)
        for g in guilds:
            try:
                bot.tree.copy_global_to(guild=g)
                synced = await bot.tree.sync(guild=g)
                print(f"[GH] guild sync {getattr(g, 'id', g)}: {[c.name for c in synced]}")
            except Exception as ge:
                print(f"[GH] guild sync fail: {ge}")
        try:
            app_id = bot.application_id or (bot.user.id if bot.user else None)
            if app_id:
                await bot.http.bulk_upsert_global_commands(app_id, [])
        except Exception:
            pass
        print(f"[GH] logged in as {bot.user} | guilds={len(bot.guilds)}")
        missing = [gid for gid in EXECUTOR_GUILD_ROLES if bot.get_guild(gid) is None]
        if missing:
            print(f"[GH] WARNING: bot not in {len(missing)} executor guilds — those checks will fail")
            print(f"[GH] missing sample: {missing[:5]}")
    except Exception as e:
        print(f"[GH] sync error: {e}")

    # Do NOT auto-post verify into 1424116614856441856
    await setup_react_only()
    await setup_license_panel()
    if not github_watcher.is_running():
        github_watcher.start()
    if not ticket_cleaner.is_running():
        ticket_cleaner.start()
    if not member_hygiene.is_running():
        member_hygiene.start()


@bot.event
async def on_member_join(member: discord.Member):
    # Unverified auto role
    role = member.guild.get_role(AUTO_ROLE_ID)
    if role and role not in member.roles:
        try:
            await member.add_roles(role, reason="Auto role on join")
        except Exception as e:
            print(f"[GH] auto-role fail: {e}")
    # Free rewire for everyone
    await ensure_free_rewire_role(member)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    # If gained Member, strip unverified
    await ensure_no_unverified_if_member(after)


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
        if (DATA.get("pending_tickets") or {}).get(str(message.channel.id), {}).get("verified"):
            return
        verified = message.guild.get_role(VERIFIED_ROLE_ID)
        unverified = message.guild.get_role(AUTO_ROLE_ID)
        try:
            if verified and verified not in message.author.roles:
                await message.author.add_roles(verified, reason="Agreed to TOS")
            if unverified and unverified in message.author.roles:
                await message.author.remove_roles(unverified, reason="Verified")
        except Exception as e:
            await message.channel.send(f"Could not update roles: `{e}`")
            return
        await ensure_free_rewire_role(message.author)
        DATA["pending_tickets"][str(message.channel.id)]["verified"] = True
        DATA["pending_tickets"][str(message.channel.id)]["close_at"] = int(time.time()) + 30 * 60
        save_data(DATA)
        await message.channel.send(
            f"{message.author.mention} verified. Ticket closes in **30 minutes**."
        )
        return
    if text in NO_WORDS or any(text.startswith(w + " ") for w in NO_WORDS):
        await message.channel.send("You need to agree to the TOS and rules to get access.")
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
    role_id = ROLE_GH_UPDATES if emoji == "📢" else ROLE_PARKOUR_ANN if emoji == "🎮" else None
    if not role_id:
        return
    role = guild.get_role(role_id)
    if role and role not in member.roles:
        try:
            await member.add_roles(role, reason="Reaction role")
        except Exception as e:
            print(f"[GH] reaction add: {e}")


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
    role_id = ROLE_GH_UPDATES if emoji == "📢" else ROLE_PARKOUR_ANN if emoji == "🎮" else None
    if not role_id:
        return
    role = guild.get_role(role_id)
    if role:
        try:
            await member.remove_roles(role, reason="Reaction role remove")
        except Exception:
            pass


async def setup_license_panel() -> None:
    ch_id = LICENSE_PANEL_CHANNEL_ID or 0
    if not ch_id:
        return
    try:
        channel = bot.get_channel(ch_id) or await bot.fetch_channel(ch_id)
    except Exception as e:
        print(f"[GH] license panel channel: {e}")
        return
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        async for msg in channel.history(limit=25):
            if msg.author == bot.user and msg.embeds:
                title = (msg.embeds[0].title or "") if msg.embeds else ""
                if "License panel" in title:
                    await msg.delete()
    except Exception:
        pass
    try:
        await channel.send(embed=license_panel_embed(), view=LicensePanelView())
        print(f"[GH] license panel posted in {ch_id}")
    except Exception as e:
        print(f"[GH] license panel post: {e}")


async def setup_react_only():
    """Reaction roles only — no verify auto-post to rules channel."""
    try:
        mid = DATA.get("react_message_id")
        if mid:
            try:
                ch = bot.get_channel(REACT_CHANNEL_ID) or await bot.fetch_channel(REACT_CHANNEL_ID)
                if isinstance(ch, discord.TextChannel):
                    msg = await ch.fetch_message(int(mid))
                    await msg.delete()
            except Exception:
                pass
        rch = bot.get_channel(REACT_CHANNEL_ID) or await bot.fetch_channel(REACT_CHANNEL_ID)
        if isinstance(rch, discord.TextChannel):
            content = (
                "React with 📢 if you want to be pinged when **Greedy Hudzell** updates\n"
                "React with 🎮 if you want to be pinged when **Parkour Legacy** updates!"
            )
            msg = await rch.send(content)
            await msg.add_reaction("📢")
            await msg.add_reaction("🎮")
            DATA["react_message_id"] = msg.id
            DATA["verify_message_id"] = None  # never auto-post verify
            save_data(DATA)
            print(f"[GH] react message posted ({msg.id})")
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


@tasks.loop(minutes=15)
async def member_hygiene():
    """Strip unverified from anyone who has Member; top up free rewire role."""
    for guild in bot.guilds:
        vrole = guild.get_role(VERIFIED_ROLE_ID)
        urole = guild.get_role(AUTO_ROLE_ID)
        frole = guild.get_role(FREE_REWIRE_ROLE_ID)
        if not vrole:
            continue
        for member in guild.members:
            if member.bot:
                continue
            try:
                if vrole in member.roles and urole and urole in member.roles:
                    await member.remove_roles(urole, reason="Hygiene: member vs unverified")
                # Do not mass-add free rewire every 15m to all — only if missing and verified?
                # User asked role on everyone — add if missing
                if frole and frole not in member.roles:
                    # Only auto-grant if they never used it: we can't know without data;
                    # grant on join only. Skip mass grant here to avoid re-giving after consume.
                    pass
            except Exception:
                pass


@tasks.loop(minutes=3)
async def github_watcher():
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
                        continue
                    commits = await resp.json()
                if not commits:
                    continue
                sha = commits[0].get("sha")
                if not sha:
                    continue
                prev = (DATA.get("file_sha") or {}).get(path)
                if prev is None:
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
                label = "Loader" if path == "greedyloader.lua" else "Hudzell"
                ping = f"<@&{ROLE_GH_UPDATES}>\n" if is_big else ""
                text = (
                    f"{ping}**Greedy {label} updated!**\n{title_line}\n"
                    f"```\n{(body or message)[:1800]}\n```\n"
                    f"https://github.com/{GH_REPO}/commit/{sha}"
                )
                await channel.send(text)
                DATA.setdefault("file_sha", {})[path] = sha
                save_data(DATA)
            except Exception as e:
                print(f"[GH] watcher {path}: {e}")


@github_watcher.before_loop
async def before_github():
    await bot.wait_until_ready()


@ticket_cleaner.before_loop
async def before_cleaner():
    await bot.wait_until_ready()


@member_hygiene.before_loop
async def before_hygiene():
    await bot.wait_until_ready()


# -------------------- Commands --------------------
@bot.tree.command(name="message", description="Send a message as the bot (whitelist)")
@app_commands.describe(channel="Target channel", text="Message content")
async def cmd_message(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    text: str,
):
    if not can_message_cmd(interaction.user):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    if not text or not text.strip():
        await interaction.response.send_message("Empty message.", ephemeral=True)
        return
    # Ephemeral ack — no public trace of who ran the command
    await interaction.response.defer(ephemeral=True)
    try:
        await channel.send(text.strip()[:2000])
        await interaction.followup.send("Sent.", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("Bot cannot send there.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Failed: `{e}`", ephemeral=True)


@bot.tree.command(name="post_verify", description="Post server Verify button (admin)")
async def cmd_post_verify(interaction: discord.Interaction, channel: discord.TextChannel):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    embed = discord.Embed(
        title="Server verification",
        description=(
            "Click **Verify**.\n"
            "The bot checks mutual executor communities (bot must share those servers with you).\n"
            "Matching roles are granted automatically. Otherwise a ticket is opened."
        ),
        color=0xC9A227,
    )
    await channel.send(embed=embed, view=ServerVerifyView())
    await interaction.response.send_message(f"Posted in {channel.mention}", ephemeral=True)


@bot.tree.command(name="reset_member_roles", description="Remove Member role from everyone (admin)")
async def cmd_reset_member_roles(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    if not interaction.guild:
        await interaction.response.send_message("Guild only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    role = interaction.guild.get_role(VERIFIED_ROLE_ID)
    if not role:
        await interaction.followup.send("Member role not found.", ephemeral=True)
        return
    count = 0
    fail = 0
    for member in list(role.members):
        try:
            await member.remove_roles(role, reason=f"reset_member_roles by {interaction.user}")
            count += 1
            await asyncio.sleep(0.35)
        except Exception:
            fail += 1
    await interaction.followup.send(
        f"Removed Member from **{count}** users (fails: {fail}).",
        ephemeral=True,
    )


@bot.tree.command(name="give_free_rewire", description="Give Free Rewire role to a member (admin)")
async def cmd_give_free_rewire(interaction: discord.Interaction, user: discord.Member):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    role = interaction.guild.get_role(FREE_REWIRE_ROLE_ID) if interaction.guild else None
    if not role:
        await interaction.response.send_message("Free rewire role missing.", ephemeral=True)
        return
    try:
        await user.add_roles(role, reason=f"by {interaction.user}")
        await interaction.response.send_message(f"Gave Free Rewire to {user.mention}", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Failed: `{e}`", ephemeral=True)


@bot.tree.command(name="getkey", description="Get your own key (Discord verified + Roblox username)")
@app_commands.describe(username="Your exact Roblox username", plan="Length")
@app_commands.choices(plan=[app_commands.Choice(name="day (24h)", value="day")])
async def cmd_getkey(
    interaction: discord.Interaction,
    username: str,
    plan: app_commands.Choice[str],
):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Use this in the server.", ephemeral=True)
        return
    if not is_verified(interaction.user):
        await interaction.response.send_message(
            "You must **server-verify** first (Verify button), then `/getkey`.",
            ephemeral=True,
        )
        return
    if not ADMIN_SECRET:
        await interaction.response.send_message("ADMIN_SECRET not set on host.", ephemeral=True)
        return
    uname = (username or "").strip()
    if not uname or len(uname) < 3:
        await interaction.response.send_message("Enter a valid Roblox username.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    status, data = await api("POST", "/admin/generate", {"plan": plan.value, "username": uname})
    if not data.get("success"):
        await interaction.followup.send(f"Failed ({status}): `{data.get('reason', data)}`", ephemeral=True)
        return
    await interaction.followup.send(
        f"**Your key** (Roblox `{uname}`)\n```{data.get('key')}```\n"
        f"Plan: `{data.get('plan')}` · expires `{data.get('expires_at')}`\n"
        f"Activate with **Verify key** on the License panel.",
        ephemeral=True,
    )


@bot.tree.command(name="key", description="Generate a license key (admin/seller)")
@app_commands.describe(plan="Subscription length", username="Optional Roblox username")
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
    await interaction.followup.send(
        f"**Key created**\n```{data.get('key')}```\n"
        f"Plan: `{data.get('plan')}` · expires `{data.get('expires_at')}`\n"
        f"User: `{data.get('username') or 'pending'}` · activated `0`",
        ephemeral=True,
    )


@bot.tree.command(name="rewire", description="Rewire key to another Roblox username")
@app_commands.describe(key="License key", username="New Roblox username")
async def cmd_rewire(interaction: discord.Interaction, key: str, username: str):
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Use this in the server.", ephemeral=True)
        return
    uname = (username or "").strip()
    if not re.match(r"^[A-Za-z0-9_]+$", uname):
        await interaction.response.send_message("Invalid Roblox username.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    free_role = interaction.guild.get_role(FREE_REWIRE_ROLE_ID) if interaction.guild else None
    has_free = bool(free_role and free_role in interaction.user.roles)
    status, data = await api(
        "POST",
        "/api/discord/rewire",
        {
            "key": key.strip(),
            "roblox_username": uname,
            "username": uname,
            "discord_id": str(interaction.user.id),
            "free_rewire": has_free,
        },
    )
    if not _api_ok(data) and has_free:
        status, data = await api(
            "POST",
            "/admin/rewire",
            {"key": key.strip(), "username": uname, "discord_id": str(interaction.user.id), "force": True},
        )
    if not _api_ok(data) and not data.get("success"):
        err = data.get("error") or data.get("reason") or data
        await interaction.followup.send(f"Rewire failed: `{err}`", ephemeral=True)
        return
    if has_free and free_role:
        try:
            await interaction.user.remove_roles(free_role, reason="Used 1 free rewire")
        except Exception:
            pass
    await interaction.followup.send(
        f"**Rewired** → `{uname}` · plan `{data.get('plan', '?')}`"
        + (" · free rewire consumed" if has_free else ""),
        ephemeral=True,
    )


@bot.tree.command(name="renew", description="Extend a key by N days")
@app_commands.describe(key="Full key", days="Days to add (1-365)")
async def cmd_renew(interaction: discord.Interaction, key: str, days: app_commands.Range[int, 1, 365]):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    status, data = await api("POST", "/admin/renew", {"key": key.strip(), "days": int(days)})
    if not data.get("success"):
        await interaction.followup.send(f"Failed: `{data.get('reason', data)}`", ephemeral=True)
        return
    await interaction.followup.send(
        f"**Renewed** `{data.get('key')}` → expires `{data.get('expires_at')}`",
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
        await interaction.response.send_message("Status channel not found.", ephemeral=True)
        return
    new_name = STATUS_MAP[state.value]
    try:
        await channel.edit(name=new_name, reason=f"Status by {interaction.user}")
    except Exception as e:
        await interaction.response.send_message(f"Edit failed: `{e}`", ephemeral=True)
        return
    await interaction.response.send_message(f"Status → **{new_name}**", ephemeral=True)


@bot.tree.command(name="keycheck", description="Check key status")
@app_commands.describe(key="Full key")
async def cmd_keycheck(interaction: discord.Interaction, key: str):
    if not isinstance(interaction.user, discord.Member) or not is_seller(interaction.user):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    status, data = await api("GET", f"/admin/key/{key.strip()}")
    if status == 404 or data.get("error"):
        await interaction.followup.send(f"Not found: `{data.get('error', data)}`", ephemeral=True)
        return
    username = str(data.get("username") or "")
    claimed = "unclaimed" if username.startswith("pending_") else "claimed"
    await interaction.followup.send(
        f"**Key** `{data.get('key')}`\nBind: **{claimed}** · User: `{username}`\n"
        f"Plan: `{data.get('plan')}` · Activated: `{data.get('activated')}`\n"
        f"Discord: `{data.get('discord_id')}` · Expires: `{data.get('expires_at')}`",
        ephemeral=True,
    )


@bot.tree.command(name="whitelist", description="Key /key whitelist")
@app_commands.describe(action="add/remove/list", user="Discord user")
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
        lines = [f"<@{i}> (`{i}`)" for i in wl] or ["(empty)"]
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
        await interaction.response.send_message(f"Added {user.mention}", ephemeral=True)
    else:
        DATA["key_whitelist"] = [x for x in wl if x != uid]
        save_data(DATA)
        await interaction.response.send_message(f"Removed {user.mention}", ephemeral=True)


@bot.tree.command(name="license_panel", description="Post license panel (admin)")
async def cmd_license_panel(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    await interaction.response.send_message(embed=license_panel_embed(), view=LicensePanelView())


def main():
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN env is empty")
    if not ADMIN_SECRET:
        print("[GH] WARNING: ADMIN_SECRET empty")
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
