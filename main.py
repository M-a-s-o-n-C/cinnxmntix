
from __future__ import annotations

import html
import io
import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

from database import Database

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GUILD_ID = os.getenv("GUILD_ID", "").strip()
DEFAULT_BRAND = os.getenv("BOT_BRAND", "cinnxmn").strip() or "cinnxmn"

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing.")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("cinnxmn-v2")

db = Database()

# Warm, neutral bakery defaults.
CROISSANT = 0xD7A86E
LATTE = 0xC8A27A
COFFEE = 0x6F4E37
ESPRESSO = 0x4B3621
CREAM = 0xE8D6C0
ROSE = 0xB5838D

intents = discord.Intents.default()
# Needed only for transcript body text. Enable Message Content Intent in Developer Portal.
intents.message_content = True


# -----------------------------
# Helpers / accessibility
# -----------------------------

def slugify(value: str, fallback: str = "ticket") -> str:
    value = re.sub(r"[^a-z0-9-]+", "-", value.lower().strip()).strip("-")
    return value[:40] or fallback


def parse_hex_color(value: str | None) -> int | None:
    if value is None:
        return None
    raw = value.strip().lower().replace("#", "").replace("0x", "")
    if not re.fullmatch(r"[0-9a-f]{6}", raw):
        raise ValueError("Use a 6-digit hex color such as D7A86E.")
    return int(raw, 16)


def color_hex(value: int) -> str:
    return f"#{value:06X}"


def bool_word(value: bool) -> str:
    return "On" if value else "Off"


def has_manage(member: discord.Member) -> bool:
    return member.guild_permissions.manage_guild or member.guild_permissions.administrator


def effective_staff_role(guild: discord.Guild, cfg, ticket=None):
    role_id = None
    if ticket:
        keys = set(ticket.keys())
        if "type_staff_role_id" in keys and ticket["type_staff_role_id"]:
            role_id = ticket["type_staff_role_id"]
        elif "staff_role_id" in keys and ticket["staff_role_id"]:
            role_id = ticket["staff_role_id"]
    if not role_id:
        role_id = cfg["staff_role_id"]
    return guild.get_role(role_id) if role_id else None


def is_staff(member: discord.Member, cfg, ticket=None) -> bool:
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    role = effective_staff_role(member.guild, cfg, ticket)
    return bool(role and role in member.roles)


def decor(cfg, emoji: str, text: str) -> str:
    if cfg and cfg["decorative_emojis"]:
        return f"{emoji} {text}"
    return text


def separator(cfg, text: str) -> str:
    # !*!* is only used in embed/message bodies where Markdown is rendered.
    if cfg and cfg["use_separator"]:
        return f"!*!* {text} !*!*"
    return text


def footer_text(cfg) -> str:
    # Footers do not support Discord Markdown, so no !*!* here.
    return (cfg["footer_text"] if cfg else DEFAULT_BRAND)[:2048]


def make_embed(cfg, title: str, description: str = "", *,
               color: int | None = None, timestamp: bool = True) -> discord.Embed:
    chosen = color if color is not None else (cfg["primary_color"] if cfg else LATTE)
    embed = discord.Embed(
        title=title,
        description=description,
        color=chosen,
        timestamp=datetime.now(timezone.utc) if timestamp else None,
    )
    embed.set_footer(text=footer_text(cfg))
    return embed


async def safe_ephemeral(interaction: discord.Interaction, content=None, *, embed=None, file=None, view=None):
    kwargs = {"ephemeral": True}
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if file is not None:
        kwargs["file"] = file
    if view is not None:
        kwargs["view"] = view
    try:
        if interaction.response.is_done():
            return await interaction.followup.send(**kwargs)
        return await interaction.response.send_message(**kwargs)
    except discord.NotFound:
        log.warning("Interaction expired before response could be sent: %s", interaction.id)
        return None


async def require_ticket(interaction: discord.Interaction):
    if not interaction.guild or not interaction.channel_id:
        await safe_ephemeral(interaction, "This command must be used inside a ticket channel.")
        return None, None
    ticket = await db.ticket_by_channel(interaction.channel_id)
    cfg = await db.config(interaction.guild.id)
    if not ticket:
        await safe_ephemeral(interaction, "This channel is not registered as a ticket.")
        return None, cfg
    return ticket, cfg


async def ticket_type_choices(interaction: discord.Interaction, current: str):
    if not interaction.guild_id:
        return []
    rows = await db.types(interaction.guild_id)
    needle = current.lower().strip()
    result = []
    for row in rows:
        label = f"{row['emoji']} {row['name']} — ID {row['id']}"
        if needle and needle not in label.lower():
            continue
        result.append(app_commands.Choice(name=label[:100], value=row["id"]))
        if len(result) >= 25:
            break
    return result


async def panel_choices(interaction: discord.Interaction, current: str):
    if not interaction.guild_id:
        return []
    rows = await db.panels(interaction.guild_id)
    needle = current.lower().strip()
    result = []
    for row in rows:
        label = f"#{row['id']} • {row['title']}"
        if needle and needle not in label.lower():
            continue
        result.append(app_commands.Choice(name=label[:100], value=row["id"]))
        if len(result) >= 25:
            break
    return result


async def transcript_bytes(channel: discord.TextChannel, ticket, cfg) -> bytes:
    brand = html.escape(cfg["brand_name"])
    chunks = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<style>",
        "body{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        "background:#f8f1e8;color:#3f2f25;padding:24px;max-width:980px;margin:auto;line-height:1.45}",
        ".hero{background:#fffaf4;border:1px solid #d7a86e;border-radius:18px;padding:20px;margin-bottom:20px}",
        ".msg{background:#fffdf9;border:1px solid #ddc4a8;border-radius:14px;padding:12px 14px;margin:10px 0}",
        ".meta{color:#765d49;font-size:12px;margin-bottom:6px}",
        ".content{white-space:pre-wrap;word-break:break-word}",
        ".attachments{margin-top:7px}.attachments a{color:#6f4e37}",
        "</style></head><body>",
        "<div class='hero'>",
        f"<h1>Ticket #{ticket['id']:04d} — {html.escape(ticket['type_name'])}</h1>",
        f"<p><b>Brand:</b> {brand}</p>",
        f"<p><b>Subject:</b> {html.escape(ticket['subject'])}</p>",
        f"<p><b>Customer ID:</b> {ticket['opener_id']}</p>",
        f"<p><b>Status:</b> {html.escape(ticket['status'])}</p>",
        "</div>",
    ]
    async for message in channel.history(limit=None, oldest_first=True):
        author = html.escape(str(message.author))
        when = message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        content = html.escape(message.content or "")
        attachments = "<br>".join(
            f"<a href='{html.escape(a.url)}'>{html.escape(a.filename)}</a>"
            for a in message.attachments
        )
        chunks.extend([
            "<div class='msg'>",
            f"<div class='meta'>{author} • {when}</div>",
            f"<div class='content'>{content}</div>",
            f"<div class='attachments'>{attachments}</div>" if attachments else "",
            "</div>",
        ])
    chunks.append("</body></html>")
    return "\n".join(chunks).encode("utf-8")


def ticket_status_text(ticket) -> str:
    if ticket["status"] == "closed":
        return "Closed"
    if ticket["claimed_by"]:
        return f"Claimed by <@{ticket['claimed_by']}>"
    return "Open — waiting for staff"


def priority_label(priority: str) -> str:
    return {
        "low": "Low",
        "normal": "Normal",
        "high": "High",
        "urgent": "Urgent",
    }.get(priority, priority.title())


async def ticket_embed(ticket, cfg) -> discord.Embed:
    emoji = ticket["type_emoji"] if cfg["decorative_emojis"] else ""
    title = f"{emoji} {ticket['type_name']} • Ticket #{ticket['id']:04d}".strip()
    if ticket["status"] == "closed":
        desc = separator(cfg, "This ticket is closed")
        color = cfg["closed_color"]
    else:
        welcome = ticket["type_welcome_text"] or (
            "Your ticket is open. A staff member can claim it from the private staff queue."
        )
        desc = f"{separator(cfg, 'Welcome to the ' + cfg['brand_name'] + ' help counter')}\n\n{welcome}"
        color = ticket["type_color"] or cfg["primary_color"]

    embed = make_embed(cfg, title, desc, color=color)
    embed.add_field(name="Customer", value=f"<@{ticket['opener_id']}>", inline=True)
    embed.add_field(name="Status", value=ticket_status_text(ticket), inline=True)
    embed.add_field(name="Priority", value=priority_label(ticket["priority"]), inline=True)
    embed.add_field(name="Subject", value=ticket["subject"][:1024], inline=False)
    embed.add_field(name="Details", value=ticket["details"][:1024], inline=False)
    if ticket["locked"]:
        embed.add_field(name="Conversation", value="Locked — customer replies are disabled.", inline=False)
    if ticket["status"] == "closed":
        if ticket["closed_by"]:
            embed.add_field(name="Closed by", value=f"<@{ticket['closed_by']}>", inline=True)
        if ticket["close_reason"]:
            embed.add_field(name="Close reason", value=ticket["close_reason"][:1024], inline=False)
    return embed


async def queue_embed(ticket, cfg) -> discord.Embed:
    if ticket["status"] == "closed":
        color = cfg["closed_color"]
        status = "Closed"
    elif ticket["claimed_by"]:
        color = cfg["accent_color"]
        status = f"Claimed by <@{ticket['claimed_by']}>"
    else:
        color = ticket["type_color"] or cfg["primary_color"]
        status = "Unclaimed — needs a staff member"

    emoji = ticket["type_emoji"] if cfg["decorative_emojis"] else ""
    embed = make_embed(
        cfg,
        f"{emoji} Ticket #{ticket['id']:04d} • {ticket['type_name']}".strip(),
        separator(cfg, "Staff queue"),
        color=color,
    )
    embed.add_field(name="Customer", value=f"<@{ticket['opener_id']}>", inline=True)
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(name="Priority", value=priority_label(ticket["priority"]), inline=True)
    embed.add_field(name="Subject", value=ticket["subject"][:1024], inline=False)
    embed.add_field(name="Details", value=ticket["details"][:1024], inline=False)
    if ticket["channel_id"]:
        embed.add_field(name="Ticket channel", value=f"<#{ticket['channel_id']}>", inline=False)
    return embed


async def refresh_ticket(guild: discord.Guild, ticket_id: int):
    ticket = await db.ticket(ticket_id)
    cfg = await db.config(guild.id)
    if not ticket:
        return
    if ticket["control_message_id"] and ticket["channel_id"]:
        channel = guild.get_channel(ticket["channel_id"])
        if isinstance(channel, discord.TextChannel):
            try:
                msg = await channel.fetch_message(ticket["control_message_id"])
                view = TicketControls(ticket_id) if ticket["status"] == "open" else ClosedControls(ticket_id)
                await msg.edit(embed=await ticket_embed(ticket, cfg), view=view)
            except discord.HTTPException:
                pass
    if ticket["queue_message_id"]:
        queue = guild.get_channel(cfg["staff_queue_channel_id"]) if cfg["staff_queue_channel_id"] else None
        if isinstance(queue, discord.TextChannel):
            try:
                msg = await queue.fetch_message(ticket["queue_message_id"])
                await msg.edit(
                    embed=await queue_embed(ticket, cfg),
                    view=QueueControls(ticket_id) if ticket["status"] == "open" else None,
                )
            except discord.HTTPException:
                pass


def format_ticket_channel(cfg, ticket_type, ticket_id: int, member: discord.Member) -> str:
    template = cfg["ticket_name_format"] or "{type}-{id}-{user}"
    data = {
        "type": slugify(ticket_type["slug"] or ticket_type["name"]),
        "id": f"{ticket_id:04d}",
        "user": slugify(member.display_name, "user"),
        "username": slugify(member.name, "user"),
    }
    try:
        raw = template.format(**data)
    except Exception:
        raw = f"{data['type']}-{data['id']}-{data['user']}"
    return slugify(raw, f"ticket-{ticket_id:04d}")[:100]


# -----------------------------
# Ticket actions
# -----------------------------

async def do_claim(interaction: discord.Interaction, ticket_id: int):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return
    cfg = await db.config(interaction.guild.id)
    ticket = await db.ticket(ticket_id)
    if not ticket:
        return await safe_ephemeral(interaction, "Ticket not found.")
    if not is_staff(interaction.user, cfg, ticket):
        return await safe_ephemeral(interaction, "Only authorized staff can claim this ticket.")
    if ticket["status"] != "open":
        return await safe_ephemeral(interaction, "This ticket is already closed.")
    if ticket["claimed_by"] == interaction.user.id:
        return await safe_ephemeral(interaction, "You already have this ticket.")
    if ticket["claimed_by"]:
        return await safe_ephemeral(interaction, f"This ticket is already claimed by <@{ticket['claimed_by']}>.")

    await interaction.response.defer(ephemeral=True)

    if not await db.claim(ticket_id, interaction.user.id):
        fresh = await db.ticket(ticket_id)
        who = f"<@{fresh['claimed_by']}>" if fresh and fresh["claimed_by"] else "another staff member"
        return await safe_ephemeral(interaction, f"{who} claimed it first.")

    channel = interaction.guild.get_channel(ticket["channel_id"])
    if isinstance(channel, discord.TextChannel):
        await channel.set_permissions(
            interaction.user,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
        )
    await db.audit(interaction.guild.id, "claimed", ticket_id, interaction.user.id, str(interaction.user))
    await refresh_ticket(interaction.guild, ticket_id)
    await safe_ephemeral(interaction, f"Ticket #{ticket_id:04d} is now assigned to you.")
    if isinstance(channel, discord.TextChannel):
        await channel.send(
            embed=make_embed(
                cfg,
                decor(cfg, "☕", "Ticket claimed"),
                f"<@{interaction.user.id}> is now handling this ticket.",
                color=cfg["accent_color"],
            )
        )


async def do_unclaim(interaction: discord.Interaction, ticket_id: int):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return
    cfg = await db.config(interaction.guild.id)
    ticket = await db.ticket(ticket_id)
    if not ticket:
        return await safe_ephemeral(interaction, "Ticket not found.")
    if not is_staff(interaction.user, cfg, ticket):
        return await safe_ephemeral(interaction, "Only authorized staff can unclaim tickets.")
    if not ticket["claimed_by"]:
        return await safe_ephemeral(interaction, "This ticket is already unclaimed.")

    override = has_manage(interaction.user)
    if ticket["claimed_by"] != interaction.user.id and not override:
        return await safe_ephemeral(interaction, "Only the current claimer or a server manager can unclaim this ticket.")

    await interaction.response.defer(ephemeral=True)

    old_id = ticket["claimed_by"]
    if not await db.unclaim(ticket_id, None if override else interaction.user.id):
        return await safe_ephemeral(interaction, "The ticket changed before I could update it.")

    channel = interaction.guild.get_channel(ticket["channel_id"])
    old_member = interaction.guild.get_member(old_id)
    if isinstance(channel, discord.TextChannel) and old_member:
        await channel.set_permissions(old_member, overwrite=None)

    await db.audit(interaction.guild.id, "unclaimed", ticket_id, interaction.user.id, f"Previous claimer {old_id}")
    await refresh_ticket(interaction.guild, ticket_id)

    queue = interaction.guild.get_channel(cfg["staff_queue_channel_id"]) if cfg["staff_queue_channel_id"] else None
    role = effective_staff_role(interaction.guild, cfg, ticket)
    if cfg["ping_staff_on_unclaim"] and isinstance(queue, discord.TextChannel):
        await queue.send(
            content=role.mention if role else None,
            embed=make_embed(
                cfg,
                decor(cfg, "🥐", "Ticket returned to queue"),
                f"Ticket **#{ticket_id:04d}** was unclaimed and needs another staff member.",
                color=cfg["primary_color"],
            ),
            allowed_mentions=discord.AllowedMentions(roles=True),
        )
    await safe_ephemeral(interaction, f"Ticket #{ticket_id:04d} is unclaimed again.")


async def do_transfer(interaction: discord.Interaction, ticket_id: int, target: discord.Member):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return
    cfg = await db.config(interaction.guild.id)
    ticket = await db.ticket(ticket_id)
    if not ticket:
        return await safe_ephemeral(interaction, "Ticket not found.")
    if not is_staff(interaction.user, cfg, ticket):
        return await safe_ephemeral(interaction, "Only authorized staff can transfer tickets.")
    if not is_staff(target, cfg, ticket):
        return await safe_ephemeral(interaction, "That member is not part of the staff team for this ticket type.")

    await interaction.response.defer(ephemeral=True)

    old_id = ticket["claimed_by"]
    channel = interaction.guild.get_channel(ticket["channel_id"])
    if isinstance(channel, discord.TextChannel):
        if old_id:
            old = interaction.guild.get_member(old_id)
            if old and old.id != target.id:
                await channel.set_permissions(old, overwrite=None)
        await channel.set_permissions(
            target,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
        )
    await db.transfer(ticket_id, target.id)
    await db.audit(interaction.guild.id, "transferred", ticket_id, interaction.user.id, f"to {target.id}")
    await refresh_ticket(interaction.guild, ticket_id)
    await safe_ephemeral(interaction, f"Ticket #{ticket_id:04d} transferred to {target.mention}.")
    if isinstance(channel, discord.TextChannel):
        await channel.send(
            embed=make_embed(
                cfg,
                decor(cfg, "☕", "Ticket transferred"),
                f"This ticket is now being handled by {target.mention}.",
                color=cfg["accent_color"],
            )
        )


async def send_close_dm(user, ticket, cfg, closer: discord.Member, reason: str, transcript: bytes | None):
    if not cfg["dm_on_close"]:
        return False
    embed = make_embed(
        cfg,
        decor(cfg, "🍪", f"Your {cfg['brand_name']} ticket has been closed"),
        f"{separator(cfg, 'Thanks for stopping by')}\n\n"
        "Your ticket has been wrapped up. Here is your closure receipt.",
        color=cfg["primary_color"],
    )
    embed.add_field(name="Ticket", value=f"#{ticket['id']:04d} • {ticket['type_name']}", inline=False)
    embed.add_field(name="Subject", value=ticket["subject"][:1024], inline=False)
    embed.add_field(name="Closed by", value=closer.mention, inline=True)
    embed.add_field(name="Reason", value=reason[:1024], inline=False)
    if transcript:
        embed.add_field(name="Transcript", value="Attached as an HTML file below.", inline=False)
    files = []
    if transcript:
        files.append(discord.File(io.BytesIO(transcript), filename=f"{cfg['brand_name']}-ticket-{ticket['id']:04d}.html"))
    try:
        await user.send(embed=embed, files=files)
        log.info("Close DM delivered for ticket %s to user %s", ticket["id"], user.id)
        return True
    except discord.Forbidden as exc:
        log.warning("Close DM forbidden for ticket %s to user %s: %s", ticket["id"], user.id, exc)
        return False
    except discord.HTTPException as exc:
        log.warning("Close DM HTTP error for ticket %s to user %s: %s", ticket["id"], user.id, exc)
        return False


async def do_close(interaction: discord.Interaction, ticket_id: int, reason: str):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return
    cfg = await db.config(interaction.guild.id)
    ticket = await db.ticket(ticket_id)
    if not ticket:
        return await safe_ephemeral(interaction, "Ticket not found.")
    allowed = is_staff(interaction.user, cfg, ticket) or (
        cfg["allow_user_close"] and interaction.user.id == ticket["opener_id"]
    )
    if not allowed:
        return await safe_ephemeral(interaction, "You do not have permission to close this ticket.")
    if ticket["status"] != "open":
        return await safe_ephemeral(interaction, "This ticket is already closed.")

    await interaction.response.defer(ephemeral=True)
    channel = interaction.guild.get_channel(ticket["channel_id"])
    transcript = None
    if cfg["transcript_on_close"] and isinstance(channel, discord.TextChannel):
        try:
            transcript = await transcript_bytes(channel, ticket, cfg)
        except discord.HTTPException:
            transcript = None

    await db.close(ticket_id, interaction.user.id, reason)
    await db.audit(interaction.guild.id, "closed", ticket_id, interaction.user.id, reason)

    opener = interaction.guild.get_member(ticket["opener_id"]) or interaction.client.get_user(ticket["opener_id"])
    if opener is None:
        try:
            opener = await interaction.client.fetch_user(ticket["opener_id"])
        except discord.HTTPException as exc:
            log.warning("Could not fetch opener %s for close DM: %s", ticket["opener_id"], exc)
            opener = None

    dm_ok = await send_close_dm(opener, ticket, cfg, interaction.user, reason, transcript) if opener else False

    log_channel = interaction.guild.get_channel(cfg["log_channel_id"]) if cfg["log_channel_id"] else None
    if isinstance(log_channel, discord.TextChannel):
        e = make_embed(
            cfg,
            decor(cfg, "📜", f"Ticket #{ticket_id:04d} closed"),
            separator(cfg, "Ticket record"),
            color=cfg["closed_color"],
        )
        e.add_field(name="Customer", value=f"<@{ticket['opener_id']}>", inline=True)
        e.add_field(name="Closed by", value=interaction.user.mention, inline=True)
        e.add_field(name="Reason", value=reason[:1024], inline=False)
        e.add_field(name="Close DM", value="Delivered" if dm_ok else "Not delivered / disabled", inline=False)
        files = []
        if transcript:
            files.append(discord.File(io.BytesIO(transcript), filename=f"{cfg['brand_name']}-ticket-{ticket_id:04d}.html"))
        await log_channel.send(embed=e, files=files)

    if isinstance(channel, discord.TextChannel):
        opener_member = interaction.guild.get_member(ticket["opener_id"])
        if opener_member:
            await channel.set_permissions(opener_member, view_channel=False, send_messages=False)
        for row in await db.members(ticket_id):
            member = interaction.guild.get_member(row["user_id"])
            if member:
                await channel.set_permissions(member, overwrite=None)

        archive_id = ticket["type_archive_category_id"] or cfg["archive_category_id"]
        archive = interaction.guild.get_channel(archive_id) if archive_id else None
        kwargs = {
            "name": f"closed-{ticket_id:04d}-{slugify(ticket['type_name'])}"[:100],
            "reason": f"Ticket closed by {interaction.user}: {reason[:250]}",
        }
        if cfg["auto_archive"] and isinstance(archive, discord.CategoryChannel):
            kwargs["category"] = archive
        try:
            await channel.edit(**kwargs)
        except discord.HTTPException:
            pass

    await refresh_ticket(interaction.guild, ticket_id)
    await interaction.followup.send(
        f"Ticket #{ticket_id:04d} closed. "
        + ("The customer received the closure DM." if dm_ok else "The closure DM was disabled or could not be delivered."),
        ephemeral=True,
    )


# -----------------------------
# Modals / Views
# -----------------------------

class CloseModal(discord.ui.Modal):
    def __init__(self, ticket_id: int):
        super().__init__(title="Close ticket")
        self.ticket_id = ticket_id
        self.reason = discord.ui.TextInput(
            label="Reason for closing",
            placeholder="Explain clearly why this ticket is being closed.",
            style=discord.TextStyle.paragraph,
            min_length=2,
            max_length=800,
            required=True,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await do_close(interaction, self.ticket_id, str(self.reason).strip())


class TicketCreateModal(discord.ui.Modal):
    def __init__(self, type_row, cfg):
        super().__init__(title=f"Open {type_row['name']}"[:45])
        self.type_id = type_row["id"]
        self.subject = discord.ui.TextInput(
            label=(type_row["form_label_subject"] or "What can we help with?")[:45],
            placeholder="A short summary",
            min_length=3,
            max_length=80,
        )
        self.details = discord.ui.TextInput(
            label=(type_row["form_label_details"] or "Tell us the details")[:45],
            placeholder="Include the details staff will need to help you.",
            style=discord.TextStyle.paragraph,
            min_length=5,
            max_length=1800,
        )
        self.add_item(self.subject)
        self.add_item(self.details)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return
        cfg = await db.config(interaction.guild.id)
        blocked = await db.blocked(interaction.guild.id, interaction.user.id)
        if blocked:
            reason = blocked["reason"] or "No reason provided."
            return await safe_ephemeral(
                interaction,
                embed=make_embed(
                    cfg,
                    "Ticket access unavailable",
                    f"You cannot open tickets in this server.\n\n**Reason:** {reason}",
                    color=cfg["closed_color"],
                ),
            )

        type_row = await db.type_by_id(interaction.guild.id, self.type_id)
        if not type_row or not type_row["enabled"]:
            return await safe_ephemeral(interaction, "That ticket type is no longer available.")

        existing = await db.open_tickets_for_user(interaction.guild.id, interaction.user.id)
        if len(existing) >= cfg["max_open_per_user"]:
            return await safe_ephemeral(
                interaction,
                f"You already have {len(existing)} open ticket(s). The limit is {cfg['max_open_per_user']}.",
            )

        if not cfg["staff_role_id"] or not cfg["staff_queue_channel_id"] or not cfg["ticket_category_id"]:
            return await safe_ephemeral(interaction, "Ticket setup is incomplete. Please contact a server administrator.")

        await interaction.response.defer(ephemeral=True)
        ticket_id = await db.create_ticket(
            interaction.guild.id,
            interaction.user.id,
            self.type_id,
            str(self.subject).strip(),
            str(self.details).strip(),
        )

        category_id = type_row["category_id"] or cfg["ticket_category_id"]
        category = interaction.guild.get_channel(category_id)
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.followup.send(
                "The configured ticket category is missing. Ask an administrator to run /setup again.",
                ephemeral=True,
            )

        staff_role = effective_staff_role(interaction.guild, cfg, type_row)
        me = interaction.guild.me
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True,
                read_message_history=True, attach_files=True
            ),
        }
        if staff_role:
            # Staff cannot see the ticket until individually claimed.
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=False)
        if me:
            overwrites[me] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                manage_channels=True, manage_messages=True, attach_files=True
            )

        channel = await interaction.guild.create_text_channel(
            format_ticket_channel(cfg, type_row, ticket_id, interaction.user),
            category=category,
            overwrites=overwrites,
            topic=f"{cfg['brand_name']} ticket #{ticket_id:04d} • opener={interaction.user.id} • type={type_row['name']}",
            reason=f"Ticket opened by {interaction.user}",
        )
        await db.attach_ticket_channel(ticket_id, channel.id)
        ticket = await db.ticket(ticket_id)

        control = await channel.send(
            content=interaction.user.mention,
            embed=await ticket_embed(ticket, cfg),
            view=TicketControls(ticket_id),
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        await db.set_control_message(ticket_id, control.id)

        queue = interaction.guild.get_channel(cfg["staff_queue_channel_id"])
        if isinstance(queue, discord.TextChannel):
            content = staff_role.mention if (staff_role and cfg["ping_staff_on_create"]) else None
            qmsg = await queue.send(
                content=content,
                embed=await queue_embed(ticket, cfg),
                view=QueueControls(ticket_id),
                allowed_mentions=discord.AllowedMentions(roles=True),
            )
            await db.set_queue_message(ticket_id, qmsg.id)

        await db.audit(interaction.guild.id, "created", ticket_id, interaction.user.id, type_row["name"])
        await interaction.followup.send(
            f"Your ticket is ready: {channel.mention}",
            ephemeral=True,
        )


class PanelSelect(discord.ui.Select):
    def __init__(self, panel_id: int, type_rows, cfg, placeholder: str | None = None):
        options = []
        for row in type_rows[:25]:
            options.append(
                discord.SelectOption(
                    label=row["name"][:100],
                    value=str(row["id"]),
                    description=row["description"][:100],
                    emoji=discord.PartialEmoji.from_str(row["emoji"]) if row["emoji"] else None,
                )
            )
        chosen_placeholder = placeholder or cfg["panel_placeholder"]
        super().__init__(
            placeholder=(chosen_placeholder or "Choose what you need help with…")[:150],
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"cx:panel:{panel_id}",
        )

    async def callback(self, interaction: discord.Interaction):
        cfg = await db.config(interaction.guild_id)
        row = await db.type_by_id(interaction.guild_id, int(self.values[0]))
        if not row:
            return await safe_ephemeral(interaction, "That ticket type is unavailable.")
        await interaction.response.send_modal(TicketCreateModal(row, cfg))


class PanelView(discord.ui.View):
    def __init__(self, panel_id: int, type_rows, cfg, placeholder: str | None = None):
        super().__init__(timeout=None)
        self.add_item(PanelSelect(panel_id, type_rows, cfg, placeholder))


class QueueControls(discord.ui.View):
    def __init__(self, ticket_id: int):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id

        claim = discord.ui.Button(
            label="Claim ticket", emoji="☕",
            style=discord.ButtonStyle.success,
            custom_id=f"cx:q:claim:{ticket_id}"
        )
        claim.callback = self.claim
        self.add_item(claim)

        unclaim = discord.ui.Button(
            label="Unclaim ticket", emoji="🥐",
            style=discord.ButtonStyle.secondary,
            custom_id=f"cx:q:unclaim:{ticket_id}"
        )
        unclaim.callback = self.unclaim
        self.add_item(unclaim)

    async def claim(self, interaction):
        await do_claim(interaction, self.ticket_id)

    async def unclaim(self, interaction):
        await do_unclaim(interaction, self.ticket_id)


class TicketControls(discord.ui.View):
    def __init__(self, ticket_id: int):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id

        buttons = [
            ("Claim", "☕", discord.ButtonStyle.success, "claim", self.claim),
            ("Unclaim", "🥐", discord.ButtonStyle.secondary, "unclaim", self.unclaim),
            ("Transcript", "📜", discord.ButtonStyle.secondary, "transcript", self.transcript),
            ("Close", "🍪", discord.ButtonStyle.danger, "close", self.close),
        ]
        for label, emoji, style, key, callback in buttons:
            btn = discord.ui.Button(
                label=label, emoji=emoji, style=style,
                custom_id=f"cx:t:{key}:{ticket_id}"
            )
            btn.callback = callback
            self.add_item(btn)

    async def claim(self, interaction):
        await do_claim(interaction, self.ticket_id)

    async def unclaim(self, interaction):
        await do_unclaim(interaction, self.ticket_id)

    async def transcript(self, interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return
        cfg = await db.config(interaction.guild.id)
        ticket = await db.ticket(self.ticket_id)
        if not ticket:
            return await safe_ephemeral(interaction, "Ticket not found.")
        if interaction.user.id != ticket["opener_id"] and not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "You do not have access to this transcript.")
        channel = interaction.guild.get_channel(ticket["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return await safe_ephemeral(interaction, "Ticket channel not found.")
        await interaction.response.defer(ephemeral=True)
        data = await transcript_bytes(channel, ticket, cfg)
        await interaction.followup.send(
            "Transcript:",
            file=discord.File(io.BytesIO(data), filename=f"{cfg['brand_name']}-ticket-{self.ticket_id:04d}.html"),
            ephemeral=True,
        )

    async def close(self, interaction):
        await interaction.response.send_modal(CloseModal(self.ticket_id))


class DeleteConfirm(discord.ui.View):
    def __init__(self, ticket_id: int, user_id: int):
        super().__init__(timeout=60)
        self.ticket_id = ticket_id
        self.user_id = user_id

    @discord.ui.button(label="Delete permanently", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await safe_ephemeral(interaction, "Only the person who opened this confirmation can use it.")
        ticket = await db.ticket(self.ticket_id)
        cfg = await db.config(interaction.guild_id)
        if not ticket or not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "You cannot delete this ticket.")
        channel = interaction.guild.get_channel(ticket["channel_id"])
        await db.mark_deleted(self.ticket_id)
        await db.audit(interaction.guild_id, "deleted", self.ticket_id, interaction.user.id)
        await interaction.response.edit_message(content="Deleting ticket permanently…", embed=None, view=None)
        if isinstance(channel, discord.TextChannel):
            await channel.delete(reason=f"Ticket permanently deleted by {interaction.user}")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await safe_ephemeral(interaction, "Only the person who opened this confirmation can use it.")
        await interaction.response.edit_message(content="Deletion cancelled.", embed=None, view=None)


class ClosedControls(discord.ui.View):
    def __init__(self, ticket_id: int):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id

        reopen = discord.ui.Button(
            label="Reopen", emoji="🥐", style=discord.ButtonStyle.success,
            custom_id=f"cx:c:reopen:{ticket_id}"
        )
        reopen.callback = self.reopen
        self.add_item(reopen)

        transcript = discord.ui.Button(
            label="Transcript", emoji="📜", style=discord.ButtonStyle.secondary,
            custom_id=f"cx:c:transcript:{ticket_id}"
        )
        transcript.callback = self.transcript
        self.add_item(transcript)

        delete = discord.ui.Button(
            label="Delete", emoji="🗑️", style=discord.ButtonStyle.danger,
            custom_id=f"cx:c:delete:{ticket_id}"
        )
        delete.callback = self.delete
        self.add_item(delete)

    async def reopen(self, interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return
        cfg = await db.config(interaction.guild.id)
        ticket = await db.ticket(self.ticket_id)
        if not ticket or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Only authorized staff can reopen this ticket.")
        if ticket["status"] != "closed":
            return await safe_ephemeral(interaction, "This ticket is not closed.")
        channel = interaction.guild.get_channel(ticket["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return await safe_ephemeral(interaction, "Ticket channel not found.")

        opener = interaction.guild.get_member(ticket["opener_id"])
        if opener:
            await channel.set_permissions(
                opener, view_channel=True, send_messages=True,
                read_message_history=True, attach_files=True
            )
        if ticket["claimed_by"]:
            old = interaction.guild.get_member(ticket["claimed_by"])
            if old:
                await channel.set_permissions(old, overwrite=None)

        open_category_id = ticket["type_category_id"] or cfg["ticket_category_id"]
        open_category = interaction.guild.get_channel(open_category_id) if open_category_id else None
        kwargs = {}
        if isinstance(open_category, discord.CategoryChannel):
            kwargs["category"] = open_category
        if opener:
            type_row = await db.type_by_id(interaction.guild.id, ticket["type_id"])
            kwargs["name"] = format_ticket_channel(cfg, type_row, self.ticket_id, opener)
        if kwargs:
            await channel.edit(**kwargs)

        await db.reopen(self.ticket_id)
        await db.audit(interaction.guild.id, "reopened", self.ticket_id, interaction.user.id)

        fresh = await db.ticket(self.ticket_id)
        queue = interaction.guild.get_channel(cfg["staff_queue_channel_id"]) if cfg["staff_queue_channel_id"] else None
        staff_role = effective_staff_role(interaction.guild, cfg, fresh)
        if isinstance(queue, discord.TextChannel):
            qmsg = await queue.send(
                content=staff_role.mention if (staff_role and cfg["ping_staff_on_create"]) else None,
                embed=await queue_embed(fresh, cfg),
                view=QueueControls(self.ticket_id),
                allowed_mentions=discord.AllowedMentions(roles=True),
            )
            await db.set_queue_message(self.ticket_id, qmsg.id)
        await refresh_ticket(interaction.guild, self.ticket_id)
        await safe_ephemeral(interaction, f"Ticket #{self.ticket_id:04d} reopened.")

    async def transcript(self, interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return
        cfg = await db.config(interaction.guild.id)
        ticket = await db.ticket(self.ticket_id)
        if not ticket or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        channel = interaction.guild.get_channel(ticket["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return await safe_ephemeral(interaction, "Ticket channel not found.")
        await interaction.response.defer(ephemeral=True)
        data = await transcript_bytes(channel, ticket, cfg)
        await interaction.followup.send(
            file=discord.File(io.BytesIO(data), filename=f"{cfg['brand_name']}-ticket-{self.ticket_id:04d}.html"),
            ephemeral=True,
        )

    async def delete(self, interaction):
        await safe_ephemeral(
            interaction,
            "This permanently deletes the Discord ticket channel. The database record remains marked deleted for auditing.",
            view=DeleteConfirm(self.ticket_id, interaction.user.id),
        )



# -----------------------------
# Moderation helpers
# -----------------------------

_DURATION_RE = re.compile(r"^\s*(\d+)\s*([smhdw])\s*$", re.I)

def parse_duration(value: str) -> int:
    match = _DURATION_RE.match(value or "")
    if not match:
        raise ValueError("Use a duration like `30m`, `2h`, `3d`, or `1w`.")
    amount = int(match.group(1))
    unit = match.group(2).lower()
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
    seconds = amount * mult
    if seconds <= 0:
        raise ValueError("Duration must be greater than zero.")
    return seconds

def human_duration(seconds: int | None) -> str:
    if not seconds:
        return "No duration"
    units = [
        ("week", 604800), ("day", 86400), ("hour", 3600),
        ("minute", 60), ("second", 1),
    ]
    parts = []
    remaining = seconds
    for name, size in units:
        count, remaining = divmod(remaining, size)
        if count:
            parts.append(f"{count} {name}{'' if count == 1 else 's'}")
        if len(parts) == 2:
            break
    return ", ".join(parts) or f"{seconds} seconds"

def mod_is_authorized(member: discord.Member, mod_cfg) -> bool:
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    role_id = mod_cfg["moderator_role_id"] if mod_cfg else None
    role = member.guild.get_role(role_id) if role_id else None
    return bool(role and role in member.roles)

def hierarchy_ok(actor: discord.Member, target: discord.Member, bot_member: discord.Member | None) -> tuple[bool, str]:
    if target.id == actor.id:
        return False, "You cannot use that moderation action on yourself."
    if target.id == target.guild.owner_id:
        return False, "The server owner cannot be moderated by the bot."
    if actor.id != target.guild.owner_id and target.top_role >= actor.top_role:
        return False, "That member's highest role is equal to or above yours."
    if bot_member and target.top_role >= bot_member.top_role:
        return False, "My bot role must be above that member's highest role."
    return True, ""

async def moderation_log(guild: discord.Guild, title: str, description: str, *,
                         target_id: int | None = None, moderator_id: int | None = None,
                         case_id: int | None = None, color: int = COFFEE):
    cfg = await db.config(guild.id)
    mod_cfg = await db.mod_config(guild.id)
    channel_id = mod_cfg["mod_log_channel_id"] if mod_cfg else None
    channel = guild.get_channel(channel_id) if channel_id else None
    if not isinstance(channel, discord.TextChannel):
        return
    e = make_embed(cfg, title, description, color=color)
    if case_id is not None:
        e.add_field(name="Case", value=f"`#{case_id}`", inline=True)
    if target_id is not None:
        e.add_field(name="Member", value=f"<@{target_id}> (`{target_id}`)", inline=True)
    if moderator_id is not None:
        e.add_field(name="Moderator", value=f"<@{moderator_id}>", inline=True)
    try:
        await channel.send(embed=e)
    except discord.HTTPException:
        pass

async def send_moderation_dm(user, guild: discord.Guild, action: str, reason: str,
                             case_id: int, *, duration: int | None = None,
                             points: int | None = None):
    cfg = await db.config(guild.id)
    e = make_embed(
        cfg,
        decor(cfg, "🍪", f"Moderation notice from {guild.name}"),
        "A moderation action was recorded on your account.",
        color=cfg["closed_color"],
    )
    e.add_field(name="Action", value=action, inline=True)
    e.add_field(name="Case", value=f"#{case_id}", inline=True)
    if duration:
        e.add_field(name="Duration", value=human_duration(duration), inline=True)
    if points is not None:
        e.add_field(name="Warning points", value=str(points), inline=True)
    e.add_field(name="Reason", value=reason[:1024], inline=False)
    e.add_field(
        name="Need to appeal?",
        value="If you still have access to the server, use `/appeal submit` and reference this case number.",
        inline=False,
    )
    try:
        await user.send(embed=e)
        return True
    except discord.HTTPException as exc:
        log.warning("Moderation DM failed for user %s: %s", getattr(user, "id", "?"), exc)
        return False

async def apply_jail(guild: discord.Guild, member: discord.Member, moderator: discord.Member,
                     reason: str, case_id: int | None = None) -> tuple[bool, str]:
    mod_cfg = await db.mod_config(guild.id)
    if not mod_cfg or not mod_cfg["jail_role_id"]:
        return False, "No jail role is configured. Run `/mod setup` first."
    jail_role = guild.get_role(mod_cfg["jail_role_id"])
    if not jail_role:
        return False, "The configured jail role no longer exists."

    bot_member = guild.me
    if not bot_member or jail_role >= bot_member.top_role:
        return False, "My bot role must be above the jail role."

    existing = await db.jail_snapshot(guild.id, member.id)
    if existing:
        if jail_role not in member.roles:
            try:
                await member.add_roles(jail_role, reason=f"Re-applying jail role: {reason}")
            except discord.HTTPException as exc:
                return False, f"Could not add the jail role: {exc}"
        return True, "Member was already jailed; the jail role was refreshed."

    removable = []
    for role in member.roles:
        if role.is_default() or role.managed or role == jail_role:
            continue
        if role < bot_member.top_role:
            removable.append(role)

    await db.save_jail_snapshot(
        guild.id, member.id, [r.id for r in removable],
        moderator.id, reason, case_id
    )

    try:
        if removable:
            await member.remove_roles(*removable, reason=f"Jailed by {moderator}: {reason}")
        await member.add_roles(jail_role, reason=f"Jailed by {moderator}: {reason}")
    except discord.HTTPException as exc:
        return False, f"Discord rejected the role change: {exc}"
    return True, f"Removed {len(removable)} role(s) and applied {jail_role.mention}."

async def restore_from_jail(guild: discord.Guild, member: discord.Member, moderator: discord.Member,
                            reason: str) -> tuple[bool, str]:
    mod_cfg = await db.mod_config(guild.id)
    jail_role = guild.get_role(mod_cfg["jail_role_id"]) if mod_cfg and mod_cfg["jail_role_id"] else None
    snapshot = await db.jail_snapshot(guild.id, member.id)
    bot_member = guild.me
    restored = []
    skipped = []

    if jail_role and jail_role in member.roles:
        try:
            await member.remove_roles(jail_role, reason=f"Unjailed by {moderator}: {reason}")
        except discord.HTTPException as exc:
            return False, f"Could not remove the jail role: {exc}"

    if snapshot and bot_member:
        for raw in (snapshot["role_ids"] or "").split(","):
            if not raw.strip():
                continue
            role = guild.get_role(int(raw))
            if not role:
                skipped.append(raw)
                continue
            if role.managed or role >= bot_member.top_role:
                skipped.append(role.name)
                continue
            restored.append(role)
        if restored:
            try:
                await member.add_roles(*restored, reason=f"Restoring roles after jail: {reason}")
            except discord.HTTPException as exc:
                return False, f"Jail role removed, but some roles could not be restored: {exc}"
        await db.delete_jail_snapshot(guild.id, member.id)

    details = f"Restored {len(restored)} role(s)."
    if skipped:
        details += f" Skipped {len(skipped)} unavailable/unassignable role(s)."
    return True, details

async def case_embed(guild: discord.Guild, row) -> discord.Embed:
    cfg = await db.config(guild.id)
    active = "Active" if row["active"] else "Inactive / cleared"
    e = make_embed(
        cfg,
        f"Moderation case #{row['id']}",
        separator(cfg, "Case record"),
        color=cfg["closed_color"] if row["active"] else cfg["accent_color"],
    )
    e.add_field(name="Member", value=f"<@{row['target_id']}> (`{row['target_id']}`)", inline=False)
    e.add_field(name="Action", value=row["action"].replace("_", " ").title(), inline=True)
    e.add_field(name="Status", value=active, inline=True)
    if row["points"]:
        e.add_field(name="Points", value=str(row["points"]), inline=True)
    if row["duration_seconds"]:
        e.add_field(name="Duration", value=human_duration(row["duration_seconds"]), inline=True)
    e.add_field(name="Moderator", value=f"<@{row['moderator_id']}>", inline=True)
    e.add_field(name="Created", value=row["created_at"], inline=True)
    e.add_field(name="Reason", value=row["reason"][:1024], inline=False)
    if row["related_ticket_id"]:
        e.add_field(name="Linked ticket", value=f"#{row['related_ticket_id']:04d}", inline=True)
    notes = await db.case_notes(row["id"])
    if notes:
        preview = "\n".join(
            f"• <@{n['author_id']}>: {n['note'][:180]}"
            for n in notes[-5:]
        )
        e.add_field(name="Recent private case notes", value=preview[:1024], inline=False)
    return e

# -----------------------------
# Main slash-command Cog
# -----------------------------

class TicketCog(commands.Cog):
    category_group = app_commands.Group(name="category", description="Manage ticket categories.")
    form_group = app_commands.Group(name="form", description="Customize ticket forms.")
    panel_group = app_commands.Group(name="panel", description="Manage ticket panels.")
    my_group = app_commands.Group(name="my", description="View your ticket information.")
    user_group = app_commands.Group(name="user", description="Manage users in the current ticket.")
    blacklist_group = app_commands.Group(name="blacklist", description="Manage the ticket blacklist.")
    config_group = app_commands.Group(name="config", description="Import/export bot configuration.")
    dm_group = app_commands.Group(name="dm", description="Direct-message tools.")

    def __init__(self, bot):
        self.bot = bot

    # ---- Admin / setup ----

    @app_commands.command(name="setup", description="Configure the ticket system.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup(
        self,
        interaction: discord.Interaction,
        staff_role: discord.Role,
        staff_queue: discord.TextChannel,
        open_category: discord.CategoryChannel,
        archive_category: discord.CategoryChannel | None = None,
        log_channel: discord.TextChannel | None = None,
        max_open_per_user: app_commands.Range[int, 1, 10] = 2,
    ):
        await db.update_config(
            interaction.guild_id,
            staff_role_id=staff_role.id,
            staff_queue_channel_id=staff_queue.id,
            ticket_category_id=open_category.id,
            archive_category_id=archive_category.id if archive_category else None,
            log_channel_id=log_channel.id if log_channel else None,
            max_open_per_user=int(max_open_per_user),
            brand_name=DEFAULT_BRAND,
            footer_text=DEFAULT_BRAND,
        )
        cfg = await db.config(interaction.guild_id)
        e = make_embed(cfg, decor(cfg, "🥐", "Ticket system configured"), separator(cfg, "Setup complete"))
        e.add_field(name="Staff role", value=staff_role.mention, inline=False)
        e.add_field(name="Staff queue", value=staff_queue.mention, inline=False)
        e.add_field(name="Open category", value=open_category.name, inline=False)
        e.add_field(name="Archive", value=archive_category.name if archive_category else "Not set", inline=False)
        e.add_field(name="Logs", value=log_channel.mention if log_channel else "Not set", inline=False)
        e.add_field(name="Privacy model", value="Staff cannot see ticket channels until individually claimed.", inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="settings", description="View the current ticket configuration.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def settings(self, interaction: discord.Interaction):
        cfg = await db.config(interaction.guild_id)
        e = make_embed(cfg, decor(cfg, "☕", "Current settings"), separator(cfg, "Configuration overview"), color=cfg["accent_color"])
        fields = [
            ("Brand", cfg["brand_name"]),
            ("Staff role", f"<@&{cfg['staff_role_id']}>" if cfg["staff_role_id"] else "Not set"),
            ("Staff queue", f"<#{cfg['staff_queue_channel_id']}>" if cfg["staff_queue_channel_id"] else "Not set"),
            ("Open category", f"<#{cfg['ticket_category_id']}>" if cfg["ticket_category_id"] else "Not set"),
            ("Archive category", f"<#{cfg['archive_category_id']}>" if cfg["archive_category_id"] else "Not set"),
            ("Log channel", f"<#{cfg['log_channel_id']}>" if cfg["log_channel_id"] else "Not set"),
            ("Max open / user", str(cfg["max_open_per_user"])),
            ("Accessibility mode", bool_word(bool(cfg["accessibility_mode"]))),
            ("Decorative emoji", bool_word(bool(cfg["decorative_emojis"]))),
            ("Separator styling", bool_word(bool(cfg["use_separator"]))),
            ("Close DMs", bool_word(bool(cfg["dm_on_close"]))),
            ("Close transcripts", bool_word(bool(cfg["transcript_on_close"]))),
        ]
        for n, v in fields:
            e.add_field(name=n, value=v, inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="appearance", description="Customize brand text, colors, footer, and ticket naming.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def appearance(
        self,
        interaction: discord.Interaction,
        brand_name: str | None = None,
        primary_color: str | None = None,
        accent_color: str | None = None,
        closed_color: str | None = None,
        footer: str | None = None,
        dropdown_placeholder: str | None = None,
        ticket_name_format: str | None = None,
    ):
        changes = {}
        try:
            if primary_color is not None:
                changes["primary_color"] = parse_hex_color(primary_color)
            if accent_color is not None:
                changes["accent_color"] = parse_hex_color(accent_color)
            if closed_color is not None:
                changes["closed_color"] = parse_hex_color(closed_color)
        except ValueError as exc:
            return await safe_ephemeral(interaction, str(exc))
        if brand_name is not None:
            changes["brand_name"] = brand_name.strip()[:80]
        if footer is not None:
            changes["footer_text"] = footer.strip()[:200]
        if dropdown_placeholder is not None:
            changes["panel_placeholder"] = dropdown_placeholder.strip()[:150]
        if ticket_name_format is not None:
            allowed_tokens = {"{type}", "{id}", "{user}", "{username}"}
            # Allow any combination of supported tokens plus literal text.
            changes["ticket_name_format"] = ticket_name_format.strip()[:100]
        if not changes:
            return await safe_ephemeral(interaction, "Provide at least one appearance setting to change.")
        await db.update_config(interaction.guild_id, **changes)
        cfg = await db.config(interaction.guild_id)
        e = make_embed(cfg, decor(cfg, "🧁", "Appearance updated"), separator(cfg, "Customization saved"))
        e.add_field(name="Primary", value=color_hex(cfg["primary_color"]), inline=True)
        e.add_field(name="Accent", value=color_hex(cfg["accent_color"]), inline=True)
        e.add_field(name="Closed", value=color_hex(cfg["closed_color"]), inline=True)
        e.add_field(name="Footer", value=cfg["footer_text"], inline=False)
        e.add_field(name="Channel format", value=f"`{cfg['ticket_name_format']}`", inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="accessibility", description="Configure accessibility and reduced-decoration options.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def accessibility(
        self,
        interaction: discord.Interaction,
        accessibility_mode: bool | None = None,
        decorative_emojis: bool | None = None,
        separator_styling: bool | None = None,
    ):
        changes = {}
        if accessibility_mode is not None:
            changes["accessibility_mode"] = int(accessibility_mode)
        if decorative_emojis is not None:
            changes["decorative_emojis"] = int(decorative_emojis)
        if separator_styling is not None:
            changes["use_separator"] = int(separator_styling)
        if not changes:
            return await safe_ephemeral(interaction, "Choose at least one accessibility setting.")
        await db.update_config(interaction.guild_id, **changes)
        cfg = await db.config(interaction.guild_id)
        e = make_embed(
            cfg,
            "Accessibility settings updated",
            "Core actions always use readable text labels. Color and emoji are never the only indicators of state.",
            color=cfg["accent_color"],
        )
        e.add_field(name="Accessibility mode", value=bool_word(bool(cfg["accessibility_mode"])), inline=True)
        e.add_field(name="Decorative emoji", value=bool_word(bool(cfg["decorative_emojis"])), inline=True)
        e.add_field(name="Decorative separators", value=bool_word(bool(cfg["use_separator"])), inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="automation", description="Configure ticket notifications, DMs, transcripts, and archiving.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def automation(
        self,
        interaction: discord.Interaction,
        dm_on_close: bool | None = None,
        transcript_on_close: bool | None = None,
        ping_staff_on_create: bool | None = None,
        ping_staff_on_unclaim: bool | None = None,
        allow_user_close: bool | None = None,
        auto_archive: bool | None = None,
    ):
        mapping = {
            "dm_on_close": dm_on_close,
            "transcript_on_close": transcript_on_close,
            "ping_staff_on_create": ping_staff_on_create,
            "ping_staff_on_unclaim": ping_staff_on_unclaim,
            "allow_user_close": allow_user_close,
            "auto_archive": auto_archive,
        }
        changes = {k: int(v) for k, v in mapping.items() if v is not None}
        if not changes:
            return await safe_ephemeral(interaction, "Choose at least one automation setting.")
        await db.update_config(interaction.guild_id, **changes)
        cfg = await db.config(interaction.guild_id)
        e = make_embed(cfg, "Automation settings updated", "Your workflow preferences were saved.")
        for key, label in [
            ("dm_on_close", "DM customer on close"),
            ("transcript_on_close", "Transcript on close"),
            ("ping_staff_on_create", "Ping on creation"),
            ("ping_staff_on_unclaim", "Ping on unclaim"),
            ("allow_user_close", "Customers may close"),
            ("auto_archive", "Move closed tickets to archive"),
        ]:
            e.add_field(name=label, value=bool_word(bool(cfg[key])), inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ---- Category management ----

    @category_group.command(name="add", description="Create a customizable ticket category.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def category_add(
        self,
        interaction: discord.Interaction,
        name: str,
        description: str,
        emoji: str = "🥐",
        color: str | None = None,
        staff_role: discord.Role | None = None,
        open_category: discord.CategoryChannel | None = None,
        archive_category: discord.CategoryChannel | None = None,
        welcome_text: str | None = None,
    ):
        if not 1 <= len(name.strip()) <= 80:
            return await safe_ephemeral(interaction, "Category names must be 1–80 characters.")
        if not 1 <= len(description.strip()) <= 100:
            return await safe_ephemeral(interaction, "Descriptions must be 1–100 characters.")
        try:
            color_int = parse_hex_color(color)
        except ValueError as exc:
            return await safe_ephemeral(interaction, str(exc))
        try:
            type_id = await db.add_type(
                interaction.guild_id, name.strip(), emoji.strip() or "🥐",
                description.strip(), slugify(name), color_int,
                staff_role.id if staff_role else None,
                open_category.id if open_category else None,
                archive_category.id if archive_category else None,
                welcome_text.strip()[:1000] if welcome_text else None,
            )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                return await safe_ephemeral(interaction, "A ticket category with that name already exists.")
            raise
        cfg = await db.config(interaction.guild_id)
        e = make_embed(cfg, "Ticket category created", f"**ID:** `{type_id}`\n**Name:** {emoji} {name}")
        e.add_field(name="Description", value=description[:1024], inline=False)
        if color_int:
            e.add_field(name="Color", value=color_hex(color_int), inline=True)
        if staff_role:
            e.add_field(name="Dedicated staff role", value=staff_role.mention, inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @category_group.command(name="edit", description="Edit a ticket category.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.autocomplete(type_id=ticket_type_choices)
    async def category_edit(
        self,
        interaction: discord.Interaction,
        type_id: int,
        name: str | None = None,
        description: str | None = None,
        emoji: str | None = None,
        color: str | None = None,
        staff_role: discord.Role | None = None,
        open_category: discord.CategoryChannel | None = None,
        archive_category: discord.CategoryChannel | None = None,
        welcome_text: str | None = None,
        enabled: bool | None = None,
    ):
        row = await db.type_by_id(interaction.guild_id, type_id)
        if not row:
            return await safe_ephemeral(interaction, "Ticket category not found.")
        changes = {}
        if name is not None:
            changes["name"] = name.strip()[:80]
            changes["slug"] = slugify(name)
        if description is not None:
            changes["description"] = description.strip()[:100]
        if emoji is not None:
            changes["emoji"] = emoji.strip()[:100]
        if color is not None:
            try:
                changes["color"] = parse_hex_color(color)
            except ValueError as exc:
                return await safe_ephemeral(interaction, str(exc))
        if staff_role is not None:
            changes["staff_role_id"] = staff_role.id
        if open_category is not None:
            changes["category_id"] = open_category.id
        if archive_category is not None:
            changes["archive_category_id"] = archive_category.id
        if welcome_text is not None:
            changes["welcome_text"] = welcome_text.strip()[:1000]
        if enabled is not None:
            changes["enabled"] = int(enabled)
        if not changes:
            return await safe_ephemeral(interaction, "Provide at least one field to change.")
        await db.edit_type(interaction.guild_id, type_id, **changes)
        cfg = await db.config(interaction.guild_id)
        fresh = await db.type_by_id(interaction.guild_id, type_id)
        await interaction.response.send_message(
            embed=make_embed(
                cfg, "Ticket category updated",
                f"`{type_id}` • {fresh['emoji']} **{fresh['name']}**\n{fresh['description']}"
            ),
            ephemeral=True,
        )

    @category_group.command(name="remove", description="Disable a ticket category without deleting its history.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.autocomplete(type_id=ticket_type_choices)
    async def category_remove(self, interaction: discord.Interaction, type_id: int):
        changed = await db.edit_type(interaction.guild_id, type_id, enabled=0)
        await safe_ephemeral(interaction, "Ticket category disabled." if changed else "Ticket category not found.")

    @category_group.command(name="list", description="List all ticket categories and IDs.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def category_list(self, interaction: discord.Interaction):
        cfg = await db.config(interaction.guild_id)
        rows = await db.types(interaction.guild_id, enabled_only=False)
        if not rows:
            return await safe_ephemeral(interaction, "No ticket categories exist yet.")
        lines = []
        for r in rows:
            status = "Enabled" if r["enabled"] else "Disabled"
            lines.append(f"`{r['id']}` {r['emoji']} **{r['name']}** — {r['description']} • {status}")
        e = make_embed(cfg, "Ticket categories", "\n".join(lines)[:4000])
        await interaction.response.send_message(embed=e, ephemeral=True)

    @form_group.command(name="customize", description="Customize the two questions shown when a ticket opens.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.autocomplete(type_id=ticket_type_choices)
    async def form_customize(
        self,
        interaction: discord.Interaction,
        type_id: int,
        subject_label: str | None = None,
        details_label: str | None = None,
    ):
        row = await db.type_by_id(interaction.guild_id, type_id)
        if not row:
            return await safe_ephemeral(interaction, "Ticket category not found.")
        changes = {}
        if subject_label is not None:
            if not 1 <= len(subject_label.strip()) <= 45:
                return await safe_ephemeral(interaction, "The subject label must be 1–45 characters.")
            changes["form_label_subject"] = subject_label.strip()
        if details_label is not None:
            if not 1 <= len(details_label.strip()) <= 45:
                return await safe_ephemeral(interaction, "The details label must be 1–45 characters.")
            changes["form_label_details"] = details_label.strip()
        if not changes:
            return await safe_ephemeral(interaction, "Provide at least one form label to change.")
        await db.edit_type(interaction.guild_id, type_id, **changes)
        cfg = await db.config(interaction.guild_id)
        fresh = await db.type_by_id(interaction.guild_id, type_id)
        e = make_embed(
            cfg,
            "Ticket form updated",
            f"**{fresh['name']}** now uses these accessible field labels:"
        )
        e.add_field(name="Short-answer field", value=fresh["form_label_subject"], inline=False)
        e.add_field(name="Long-answer field", value=fresh["form_label_details"], inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @category_group.command(name="inherit", description="Reset category routing/colors so it inherits the server defaults.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.autocomplete(type_id=ticket_type_choices)
    async def category_inherit(
        self,
        interaction: discord.Interaction,
        type_id: int,
        reset_staff_role: bool = True,
        reset_open_category: bool = True,
        reset_archive_category: bool = True,
        reset_color: bool = False,
    ):
        row = await db.type_by_id(interaction.guild_id, type_id)
        if not row:
            return await safe_ephemeral(interaction, "Ticket category not found.")
        changes = {}
        if reset_staff_role:
            changes["staff_role_id"] = None
        if reset_open_category:
            changes["category_id"] = None
        if reset_archive_category:
            changes["archive_category_id"] = None
        if reset_color:
            changes["color"] = None
        await db.edit_type(interaction.guild_id, type_id, **changes)
        await safe_ephemeral(interaction, "Selected category overrides were reset to server defaults.")

    # ---- Panels ----

    async def _render_panel(self, interaction, panel_row):
        cfg = await db.config(interaction.guild_id)
        rows = []
        for raw in panel_row["type_ids"].split(","):
            if not raw.strip():
                continue
            row = await db.type_by_id(interaction.guild_id, int(raw))
            if row and row["enabled"]:
                rows.append(row)
        if not rows:
            raise ValueError("This panel has no enabled ticket categories.")
        color = panel_row["color"] or cfg["primary_color"]
        e = make_embed(
            cfg,
            panel_row["title"],
            f"{panel_row['description']}\n\n{separator(cfg, 'Choose an option from the menu below')}",
            color=color,
        )
        preview = "\n".join(
            f"{r['emoji']} **{r['name']}** — {r['description']}"
            if cfg["decorative_emojis"]
            else f"**{r['name']}** — {r['description']}"
            for r in rows
        )
        e.add_field(name="Available ticket types", value=preview[:1024], inline=False)
        if panel_row["image_url"]:
            e.set_image(url=panel_row["image_url"])
        if panel_row["thumbnail_url"]:
            e.set_thumbnail(url=panel_row["thumbnail_url"])
        return e, PanelView(panel_row["id"], rows, cfg, panel_row["placeholder"])

    @panel_group.command(name="create", description="Create a modern multi-category dropdown panel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def panel_create(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        category_ids: str,
        title: str = "🧁 cinnxmn help counter",
        description: str = "Choose what you need help with and we’ll get the right ticket started.",
        color: str | None = None,
        image_url: str | None = None,
        thumbnail_url: str | None = None,
        placeholder: str | None = None,
    ):
        try:
            ids = list(dict.fromkeys(int(x.strip()) for x in category_ids.split(",") if x.strip()))
        except ValueError:
            return await safe_ephemeral(interaction, "Category IDs must be comma-separated numbers, such as `1,2,4`.")
        if not 1 <= len(ids) <= 25:
            return await safe_ephemeral(interaction, "Panels must contain between 1 and 25 ticket categories.")
        valid = []
        for type_id in ids:
            row = await db.type_by_id(interaction.guild_id, type_id)
            if row and row["enabled"]:
                valid.append(type_id)
        if len(valid) != len(ids):
            return await safe_ephemeral(interaction, "One or more category IDs are invalid or disabled.")
        try:
            color_int = parse_hex_color(color)
        except ValueError as exc:
            return await safe_ephemeral(interaction, str(exc))

        panel_id = await db.create_panel(
            interaction.guild_id, channel.id, title[:256], description[:3500],
            valid, interaction.user.id, image_url, thumbnail_url, color_int, placeholder
        )
        panel = await db.panel(interaction.guild_id, panel_id)
        e, view = await self._render_panel(interaction, panel)
        msg = await channel.send(embed=e, view=view)
        await db.edit_panel(interaction.guild_id, panel_id, message_id=msg.id)
        self.bot.add_view(view, message_id=msg.id)
        await safe_ephemeral(interaction, f"Panel #{panel_id} created in {channel.mention}.")

    @panel_group.command(name="edit", description="Edit an existing ticket panel and refresh its message.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.autocomplete(panel_id=panel_choices)
    async def panel_edit(
        self,
        interaction: discord.Interaction,
        panel_id: int,
        title: str | None = None,
        description: str | None = None,
        category_ids: str | None = None,
        color: str | None = None,
        image_url: str | None = None,
        thumbnail_url: str | None = None,
        placeholder: str | None = None,
    ):
        panel = await db.panel(interaction.guild_id, panel_id)
        if not panel:
            return await safe_ephemeral(interaction, "Panel not found.")
        changes = {}
        if title is not None:
            changes["title"] = title[:256]
        if description is not None:
            changes["description"] = description[:3500]
        if category_ids is not None:
            try:
                ids = list(dict.fromkeys(int(x.strip()) for x in category_ids.split(",") if x.strip()))
            except ValueError:
                return await safe_ephemeral(interaction, "Category IDs must be comma-separated numbers.")
            if not 1 <= len(ids) <= 25:
                return await safe_ephemeral(interaction, "Panels must contain 1–25 categories.")
            for tid in ids:
                if not await db.type_by_id(interaction.guild_id, tid):
                    return await safe_ephemeral(interaction, f"Category ID `{tid}` does not exist.")
            changes["type_ids"] = ids
        if color is not None:
            try:
                changes["color"] = parse_hex_color(color)
            except ValueError as exc:
                return await safe_ephemeral(interaction, str(exc))
        if image_url is not None:
            changes["image_url"] = image_url or None
        if thumbnail_url is not None:
            changes["thumbnail_url"] = thumbnail_url or None
        if placeholder is not None:
            changes["placeholder"] = placeholder[:150]
        if not changes:
            return await safe_ephemeral(interaction, "Provide at least one panel setting to change.")

        await db.edit_panel(interaction.guild_id, panel_id, **changes)
        fresh = await db.panel(interaction.guild_id, panel_id)
        e, view = await self._render_panel(interaction, fresh)
        channel = interaction.guild.get_channel(fresh["channel_id"])
        if isinstance(channel, discord.TextChannel) and fresh["message_id"]:
            try:
                msg = await channel.fetch_message(fresh["message_id"])
                await msg.edit(embed=e, view=view)
                self.bot.add_view(view, message_id=fresh["message_id"])
            except discord.HTTPException:
                pass
        await safe_ephemeral(interaction, f"Panel #{panel_id} updated.")

    @panel_group.command(name="preview", description="Preview a panel privately without posting it.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.autocomplete(panel_id=panel_choices)
    async def panel_preview(self, interaction: discord.Interaction, panel_id: int):
        panel = await db.panel(interaction.guild_id, panel_id)
        if not panel:
            return await safe_ephemeral(interaction, "Panel not found.")
        try:
            e, view = await self._render_panel(interaction, panel)
        except ValueError as exc:
            return await safe_ephemeral(interaction, str(exc))
        await interaction.response.send_message(embed=e, view=view, ephemeral=True)

    @panel_group.command(name="list", description="List configured ticket panels.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def panel_list(self, interaction: discord.Interaction):
        cfg = await db.config(interaction.guild_id)
        rows = await db.panels(interaction.guild_id)
        if not rows:
            return await safe_ephemeral(interaction, "No panels are configured.")
        lines = [
            f"`#{r['id']}` **{r['title']}** • <#{r['channel_id']}> • {'Enabled' if r['enabled'] else 'Disabled'}"
            for r in rows
        ]
        await interaction.response.send_message(
            embed=make_embed(cfg, "Ticket panels", "\n".join(lines)[:4000]),
            ephemeral=True,
        )

    @panel_group.command(name="delete", description="Disable a panel and remove its Discord message.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.autocomplete(panel_id=panel_choices)
    async def panel_delete(self, interaction: discord.Interaction, panel_id: int):
        panel = await db.panel(interaction.guild_id, panel_id)
        if not panel:
            return await safe_ephemeral(interaction, "Panel not found.")
        channel = interaction.guild.get_channel(panel["channel_id"])
        if isinstance(channel, discord.TextChannel) and panel["message_id"]:
            try:
                msg = await channel.fetch_message(panel["message_id"])
                await msg.delete()
            except discord.HTTPException:
                pass
        await db.edit_panel(interaction.guild_id, panel_id, enabled=0)
        await safe_ephemeral(interaction, f"Panel #{panel_id} disabled and its message removed.")

    # ---- User / staff ticket commands ----

    @my_group.command(name="tickets", description="See your currently open tickets.")
    async def my_tickets(self, interaction: discord.Interaction):
        cfg = await db.config(interaction.guild_id)
        rows = await db.open_tickets_for_user(interaction.guild_id, interaction.user.id)
        if not rows:
            return await safe_ephemeral(interaction, "You do not have any open tickets.")
        lines = [
            f"**#{r['id']:04d}** • {r['type_emoji']} {r['type_name']} • <#{r['channel_id']}>"
            for r in rows
        ]
        await interaction.response.send_message(
            embed=make_embed(cfg, "Your open tickets", "\n".join(lines)),
            ephemeral=True,
        )

    @app_commands.command(name="info", description="Show details about the current ticket.")
    async def info(self, interaction: discord.Interaction):
        ticket, cfg = await require_ticket(interaction)
        if ticket:
            await interaction.response.send_message(embed=await ticket_embed(ticket, cfg), ephemeral=True)

    @app_commands.command(name="claim", description="Claim the current ticket.")
    async def claim(self, interaction: discord.Interaction):
        ticket, _ = await require_ticket(interaction)
        if ticket:
            await do_claim(interaction, ticket["id"])

    @app_commands.command(name="unclaim", description="Return the current ticket to the staff queue.")
    async def unclaim(self, interaction: discord.Interaction):
        ticket, _ = await require_ticket(interaction)
        if ticket:
            await do_unclaim(interaction, ticket["id"])

    @app_commands.command(name="transfer", description="Transfer the current ticket to another staff member.")
    async def transfer(self, interaction: discord.Interaction, staff_member: discord.Member):
        ticket, _ = await require_ticket(interaction)
        if ticket:
            await do_transfer(interaction, ticket["id"], staff_member)

    @app_commands.command(name="close", description="Close the current ticket with a reason.")
    async def close(self, interaction: discord.Interaction):
        ticket, _ = await require_ticket(interaction)
        if ticket:
            await interaction.response.send_modal(CloseModal(ticket["id"]))

    @app_commands.command(name="reopen", description="Reopen the current closed ticket.")
    async def reopen(self, interaction: discord.Interaction):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        if ticket["status"] != "closed":
            return await safe_ephemeral(interaction, "This ticket is already open.")
        # Re-use the persistent control implementation.
        view = ClosedControls(ticket["id"])
        await view.reopen(interaction)

    @app_commands.command(name="delete", description="Permanently delete the current closed ticket channel.")
    async def delete(self, interaction: discord.Interaction):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        if ticket["status"] != "closed":
            return await safe_ephemeral(interaction, "Close the ticket before deleting it.")
        await safe_ephemeral(
            interaction,
            "This permanently deletes the Discord channel. Continue?",
            view=DeleteConfirm(ticket["id"], interaction.user.id),
        )

    @app_commands.command(name="transcript", description="Export the current ticket conversation as HTML.")
    async def transcript(self, interaction: discord.Interaction):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member):
            return
        if interaction.user.id != ticket["opener_id"] and not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "You do not have permission to export this transcript.")
        await interaction.response.defer(ephemeral=True)
        data = await transcript_bytes(interaction.channel, ticket, cfg)
        await interaction.followup.send(
            file=discord.File(io.BytesIO(data), filename=f"{cfg['brand_name']}-ticket-{ticket['id']:04d}.html"),
            ephemeral=True,
        )

    @user_group.command(name="add", description="Give another member access to the current ticket.")
    async def add_user(self, interaction: discord.Interaction, member: discord.Member):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        await interaction.channel.set_permissions(
            member, view_channel=True, send_messages=True,
            read_message_history=True, attach_files=True
        )
        await db.add_member(ticket["id"], member.id, interaction.user.id)
        await db.audit(interaction.guild_id, "user_added", ticket["id"], interaction.user.id, str(member.id))
        await safe_ephemeral(interaction, f"{member.mention} can now access this ticket.")

    @user_group.command(name="remove", description="Remove an added member from the current ticket.")
    async def remove_user(self, interaction: discord.Interaction, member: discord.Member):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        if member.id == ticket["opener_id"]:
            return await safe_ephemeral(interaction, "The ticket opener cannot be removed this way.")
        if member.id == ticket["claimed_by"]:
            return await safe_ephemeral(interaction, "Use /transfer or /unclaim for the assigned staff member.")
        await interaction.channel.set_permissions(member, overwrite=None)
        await db.remove_member(ticket["id"], member.id)
        await db.audit(interaction.guild_id, "user_removed", ticket["id"], interaction.user.id, str(member.id))
        await safe_ephemeral(interaction, f"{member.mention} was removed from this ticket.")

    @app_commands.command(name="rename", description="Rename the current ticket channel.")
    async def rename(self, interaction: discord.Interaction, name: str):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        new_name = f"{ticket['id']:04d}-{slugify(name)}"[:100]
        await interaction.channel.edit(name=new_name, reason=f"Ticket renamed by {interaction.user}")
        await db.audit(interaction.guild_id, "renamed", ticket["id"], interaction.user.id, new_name)
        await safe_ephemeral(interaction, f"Ticket renamed to `{new_name}`.")

    @app_commands.command(name="priority", description="Set the priority of the current ticket.")
    @app_commands.choices(level=[
        app_commands.Choice(name="Low", value="low"),
        app_commands.Choice(name="Normal", value="normal"),
        app_commands.Choice(name="High", value="high"),
        app_commands.Choice(name="Urgent", value="urgent"),
    ])
    async def priority(self, interaction: discord.Interaction, level: app_commands.Choice[str]):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        await db.set_priority(ticket["id"], level.value)
        await db.audit(interaction.guild_id, "priority_changed", ticket["id"], interaction.user.id, level.value)
        await refresh_ticket(interaction.guild, ticket["id"])
        await safe_ephemeral(interaction, f"Priority set to **{level.name}**.")

    @app_commands.command(name="note", description="Add a private internal note to the ticket record.")
    async def note(self, interaction: discord.Interaction, note: str):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        await db.add_note(ticket["id"], interaction.user.id, note[:1500])
        await db.audit(interaction.guild_id, "note_added", ticket["id"], interaction.user.id, note[:250])
        await safe_ephemeral(interaction, "Private staff note saved. It is not posted in the ticket channel.")

    @app_commands.command(name="notes", description="View private internal notes for this ticket.")
    async def notes(self, interaction: discord.Interaction):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        rows = await db.notes(ticket["id"])
        if not rows:
            return await safe_ephemeral(interaction, "No internal notes have been added.")
        text = "\n\n".join(
            f"**Note #{r['id']}** • <@{r['author_id']}> • {r['created_at']}\n{r['note']}"
            for r in rows
        )
        await interaction.response.send_message(
            embed=make_embed(cfg, "Internal ticket notes", text[:4000], color=cfg["accent_color"]),
            ephemeral=True,
        )

    @app_commands.command(name="lock", description="Prevent the customer from sending messages in this ticket.")
    async def lock(self, interaction: discord.Interaction):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        opener = interaction.guild.get_member(ticket["opener_id"])
        if opener:
            await interaction.channel.set_permissions(
                opener, view_channel=True, send_messages=False, read_message_history=True
            )
        await db.set_locked(ticket["id"], True)
        await db.audit(interaction.guild_id, "locked", ticket["id"], interaction.user.id)
        await refresh_ticket(interaction.guild, ticket["id"])
        await safe_ephemeral(interaction, "Customer replies are now locked.")

    @app_commands.command(name="unlock", description="Allow the customer to send messages again.")
    async def unlock(self, interaction: discord.Interaction):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        opener = interaction.guild.get_member(ticket["opener_id"])
        if opener:
            await interaction.channel.set_permissions(
                opener, view_channel=True, send_messages=True,
                read_message_history=True, attach_files=True
            )
        await db.set_locked(ticket["id"], False)
        await db.audit(interaction.guild_id, "unlocked", ticket["id"], interaction.user.id)
        await refresh_ticket(interaction.guild, ticket["id"])
        await safe_ephemeral(interaction, "Customer replies are unlocked.")

    # ---- Moderation / analytics ----

    @blacklist_group.command(name="add", description="Prevent a member from opening tickets.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def blacklist(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        await db.block_user(interaction.guild_id, member.id, reason[:1000], interaction.user.id)
        await safe_ephemeral(interaction, f"{member.mention} can no longer open tickets.\n**Reason:** {reason}")

    @blacklist_group.command(name="remove", description="Allow a member to open tickets again.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def unblacklist(self, interaction: discord.Interaction, member: discord.Member):
        changed = await db.unblock_user(interaction.guild_id, member.id)
        await safe_ephemeral(interaction, f"{member.mention} was removed from the blacklist." if changed else "That member was not blacklisted.")

    @blacklist_group.command(name="list", description="List members blocked from opening tickets.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def blacklist_list(self, interaction: discord.Interaction):
        cfg = await db.config(interaction.guild_id)
        rows = await db.blocked_list(interaction.guild_id)
        if not rows:
            return await safe_ephemeral(interaction, "The ticket blacklist is empty.")
        text = "\n".join(
            f"<@{r['user_id']}> — {r['reason'] or 'No reason provided'}"
            for r in rows
        )
        await interaction.response.send_message(
            embed=make_embed(cfg, "Ticket blacklist", text[:4000]),
            ephemeral=True,
        )

    @app_commands.command(name="stats", description="View ticket-system statistics.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def stats(self, interaction: discord.Interaction):
        cfg = await db.config(interaction.guild_id)
        s = await db.stats(interaction.guild_id)
        e = make_embed(cfg, "Ticket statistics", separator(cfg, "Current ticket activity"), color=cfg["accent_color"])
        e.add_field(name="All tickets", value=str(s["total"]), inline=True)
        e.add_field(name="Open", value=str(s["open"]), inline=True)
        e.add_field(name="Claimed open", value=str(s["claimed"]), inline=True)
        e.add_field(name="Closed", value=str(s["closed"]), inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @config_group.command(name="export", description="Export the ticket setup as a JSON backup.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def export_config(self, interaction: discord.Interaction):
        payload = await db.export_config(interaction.guild_id)
        data = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        await interaction.response.send_message(
            "Configuration backup:",
            file=discord.File(io.BytesIO(data), filename=f"{DEFAULT_BRAND}-ticket-config.json"),
            ephemeral=True,
        )

    @dm_group.command(name="test", description="Send yourself a test DM to verify bot DM delivery.")
    async def dm_test(self, interaction: discord.Interaction):
        cfg = await db.config(interaction.guild_id)
        e = make_embed(
            cfg,
            decor(cfg, "🍪", f"{cfg['brand_name']} DM test"),
            f"{separator(cfg, 'DM delivery test')}\n\n"
            "If you can read this, direct messages from the ticket bot are working.",
            color=cfg["primary_color"],
        )
        try:
            await interaction.user.send(embed=e)
            await safe_ephemeral(interaction, "Test DM sent successfully.")
        except discord.Forbidden:
            await safe_ephemeral(
                interaction,
                "Discord rejected the DM. Check server privacy settings and whether the bot is blocked."
            )
        except discord.HTTPException as exc:
            log.warning("DM test failed for user %s: %s", interaction.user.id, exc)
            await safe_ephemeral(interaction, f"Discord returned an error while sending the DM: `{exc}`")

    @app_commands.command(name="help", description="Show the ticket bot command guide.")
    async def help_cmd(self, interaction: discord.Interaction):
        cfg = await db.config(interaction.guild_id)
        e = make_embed(
            cfg,
            decor(cfg, "🥐", f"{cfg['brand_name']} ticket help"),
            "Commands are grouped below by purpose. Buttons also include readable text labels for accessibility.",
        )
        e.add_field(
            name="Customer",
            value="`/my tickets` • `/info` • `/transcript` • `/close` • `/dm test`",
            inline=False,
        )
        e.add_field(
            name="Staff workflow",
            value="`/claim` • `/unclaim` • `/transfer` • `/priority` • `/note` • `/notes` • `/lock` • `/unlock` • `/rename` • `/user add` • `/user remove` • `/reopen` • `/delete`",
            inline=False,
        )
        e.add_field(
            name="Configuration",
            value="`/setup` • `/settings` • `/appearance` • `/accessibility` • `/automation` • `/category add` • `/category edit` • `/category remove` • `/category list` • `/category inherit` • `/form customize` • `/panel create` • `/panel edit` • `/panel preview` • `/panel list` • `/panel delete`",
            inline=False,
        )
        e.add_field(
            name="Management",
            value="`/blacklist add` • `/blacklist remove` • `/blacklist list` • `/stats` • `/config export`",
            inline=False,
        )
        e.add_field(
            name="Moderation",
            value="`/warn add` • `/warn list` • `/warn remove` • `/case view` • `/case note` • `/case link ticket` • `/mod context` • `/kick` • `/ban` • `/unban` • `/timeout` • `/untimeout` • `/jail add` • `/jail remove` • `/purge` • `/slowmode`",
            inline=False,
        )
        e.add_field(
            name="Reports & appeals",
            value="`/report submit` • `/report claim` • `/report resolve` • `/appeal submit` • `/appeal claim` • `/appeal resolve`",
            inline=False,
        )
        e.add_field(
            name="Moderation setup",
            value="`/mod setup` • `/jail channel add` • `/jail channel remove` • `/jail channel list` • `/jail sync`",
            inline=False,
        )
        await interaction.response.send_message(embed=e, ephemeral=True)



class ModerationCog(commands.Cog):
    mod_group = app_commands.Group(name="mod", description="Moderation configuration and context.")
    jail_group = app_commands.Group(name="jail", description="Jail members and manage jail access.")
    jail_channel_group = app_commands.Group(name="channel", description="Manage jail-safe channels.", parent=jail_group)
    warn_group = app_commands.Group(name="warn", description="Issue and manage warnings.")
    case_group = app_commands.Group(name="case", description="View and manage moderation cases.")
    case_link_group = app_commands.Group(name="link", description="Link moderation cases to other records.", parent=case_group)
    report_group = app_commands.Group(name="report", description="Submit and manage member reports.")
    appeal_group = app_commands.Group(name="appeal", description="Submit and manage moderation appeals.")

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        if not self.timeout_cleanup_loop.is_running():
            self.timeout_cleanup_loop.start()

    def cog_unload(self):
        self.timeout_cleanup_loop.cancel()

    @tasks.loop(seconds=60)
    async def timeout_cleanup_loop(self):
        now = datetime.now(timezone.utc)
        rows = await db.active_timeout_cases()
        for row in rows:
            try:
                expires = datetime.fromisoformat(row["expires_at"])
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
            if expires > now:
                continue

            guild = self.bot.get_guild(row["guild_id"])
            if not guild:
                continue
            try:
                member = guild.get_member(row["target_id"]) or await guild.fetch_member(row["target_id"])
            except discord.HTTPException:
                await db.deactivate_case(row["guild_id"], row["id"])
                continue

            bot_member = guild.me
            if not bot_member:
                continue
            success, detail = await restore_from_jail(
                guild, member, bot_member, "Discord timeout expired automatically"
            )
            if success:
                await db.deactivate_case(row["guild_id"], row["id"])
                await moderation_log(
                    guild,
                    "Timeout expired — roles restored",
                    detail,
                    target_id=member.id,
                    moderator_id=bot_member.id,
                    case_id=row["id"],
                    color=LATTE,
                )

    @timeout_cleanup_loop.before_loop
    async def before_timeout_cleanup(self):
        await self.bot.wait_until_ready()

    async def _require_mod(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await safe_ephemeral(interaction, "This command must be used in a server.")
            return None
        cfg = await db.mod_config(interaction.guild.id)
        if not mod_is_authorized(interaction.user, cfg):
            await safe_ephemeral(interaction, "You are not authorized to use moderation commands.")
            return None
        return cfg

    @mod_group.command(name="setup", description="Configure moderation roles, logs, reports, appeals, and jail.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def mod_setup(
        self,
        interaction: discord.Interaction,
        moderator_role: discord.Role,
        jail_role: discord.Role,
        mod_log: discord.TextChannel,
        reports_category: discord.CategoryChannel,
        appeals_category: discord.CategoryChannel,
        report_queue: discord.TextChannel,
        appeal_queue: discord.TextChannel,
        warning_threshold_points: app_commands.Range[int, 1, 50] = 6,
        auto_jail_on_threshold: bool = False,
    ):
        await db.update_mod_config(
            interaction.guild_id,
            moderator_role_id=moderator_role.id,
            jail_role_id=jail_role.id,
            mod_log_channel_id=mod_log.id,
            reports_category_id=reports_category.id,
            appeals_category_id=appeals_category.id,
            report_queue_channel_id=report_queue.id,
            appeal_queue_channel_id=appeal_queue.id,
            warning_threshold_points=int(warning_threshold_points),
            auto_jail_on_threshold=int(auto_jail_on_threshold),
        )
        cfg = await db.config(interaction.guild_id)
        e = make_embed(cfg, "Moderation system configured", separator(cfg, "Moderation setup complete"), color=cfg["accent_color"])
        e.add_field(name="Moderator role", value=moderator_role.mention, inline=False)
        e.add_field(name="Jail role", value=jail_role.mention, inline=False)
        e.add_field(name="Moderation log", value=mod_log.mention, inline=False)
        e.add_field(name="Report queue", value=report_queue.mention, inline=False)
        e.add_field(name="Appeal queue", value=appeal_queue.mention, inline=False)
        e.add_field(name="Warning threshold", value=str(warning_threshold_points), inline=True)
        e.add_field(name="Auto-jail at threshold", value=bool_word(auto_jail_on_threshold), inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @jail_channel_group.command(name="add", description="Allow jailed members to access a specific channel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def jail_channel_add(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        can_send: bool = True,
    ):
        await db.add_jail_channel(interaction.guild_id, channel.id, can_send)
        await safe_ephemeral(
            interaction,
            f"{channel.mention} added to the jail-safe list. "
            f"Jailed users may {'read and send messages' if can_send else 'read only'}. "
            "Run `/jail sync` after changing the list."
        )

    @jail_channel_group.command(name="remove", description="Remove a channel from the jail-safe list.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def jail_channel_remove(self, interaction: discord.Interaction, channel: discord.TextChannel):
        changed = await db.remove_jail_channel(interaction.guild_id, channel.id)
        await safe_ephemeral(interaction, "Channel removed. Run `/jail sync`." if changed else "That channel was not on the jail-safe list.")

    @jail_channel_group.command(name="list", description="List channels jailed users are allowed to access.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def jail_channel_list(self, interaction: discord.Interaction):
        cfg = await db.config(interaction.guild_id)
        rows = await db.jail_channels(interaction.guild_id)
        if not rows:
            return await safe_ephemeral(interaction, "No jail-safe channels are configured.")
        lines = [
            f"<#{r['channel_id']}> — {'read/write' if r['can_send'] else 'read-only'}"
            for r in rows
        ]
        await interaction.response.send_message(
            embed=make_embed(cfg, "Jail-safe channels", "\n".join(lines), color=cfg["accent_color"]),
            ephemeral=True,
        )

    @jail_group.command(name="sync", description="Apply jail-role visibility restrictions across the server.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def jail_sync(self, interaction: discord.Interaction):
        mod_cfg = await db.mod_config(interaction.guild_id)
        jail_role = interaction.guild.get_role(mod_cfg["jail_role_id"]) if mod_cfg["jail_role_id"] else None
        if not jail_role:
            return await safe_ephemeral(interaction, "Configure a valid jail role with `/mod setup` first.")

        rows = await db.jail_channels(interaction.guild_id)
        safe = {r["channel_id"]: bool(r["can_send"]) for r in rows}
        await interaction.response.defer(ephemeral=True)

        changed = 0
        failed = 0
        for channel in interaction.guild.channels:
            if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.ForumChannel)):
                continue
            try:
                if channel.id in safe:
                    perms = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=safe[channel.id] if isinstance(channel, (discord.TextChannel, discord.ForumChannel)) else None,
                        read_message_history=True if isinstance(channel, (discord.TextChannel, discord.ForumChannel)) else None,
                        connect=True if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)) else None,
                    )
                else:
                    perms = discord.PermissionOverwrite(view_channel=False, connect=False)
                await channel.set_permissions(jail_role, overwrite=perms, reason=f"Jail sync by {interaction.user}")
                changed += 1
            except discord.HTTPException:
                failed += 1

        await interaction.followup.send(
            f"Jail permissions synchronized across **{changed}** channels."
            + (f" **{failed}** channel(s) could not be updated." if failed else ""),
            ephemeral=True,
        )

    @warn_group.command(name="add", description="Issue a persistent warning with points and a case number.")
    async def warn(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
        points: app_commands.Range[int, 0, 10] = 1,
    ):
        mod_cfg = await self._require_mod(interaction)
        if not mod_cfg:
            return
        ok, why = hierarchy_ok(interaction.user, member, interaction.guild.me)
        if not ok:
            return await safe_ephemeral(interaction, why)

        case_id = await db.create_case(
            interaction.guild_id, member.id, interaction.user.id,
            "warning", reason[:1500], points=int(points)
        )
        total = await db.active_warning_points(interaction.guild_id, member.id)
        await send_moderation_dm(member, interaction.guild, "Warning", reason, case_id, points=int(points))
        await moderation_log(
            interaction.guild, "Warning issued",
            f"**Reason:** {reason}\n**Current active warning points:** {total}",
            target_id=member.id, moderator_id=interaction.user.id,
            case_id=case_id, color=CROISSANT
        )

        auto_text = ""
        if mod_cfg["auto_jail_on_threshold"] and total >= mod_cfg["warning_threshold_points"]:
            jail_case = await db.create_case(
                interaction.guild_id, member.id, interaction.user.id,
                "automatic_jail", f"Warning threshold reached ({total} points).",
                metadata=json.dumps({"trigger_case": case_id})
            )
            success, detail = await apply_jail(
                interaction.guild, member, interaction.user,
                f"Automatic jail: warning threshold reached ({total} points).",
                jail_case
            )
            auto_text = f"\n\nAuto-jail: {'applied' if success else 'failed'} — {detail}"

        await safe_ephemeral(
            interaction,
            f"Warning case **#{case_id}** created for {member.mention}. "
            f"They now have **{total}** active warning point(s).{auto_text}"
        )

    @warn_group.command(name="list", description="View a member's warning and moderation history.")
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        mod_cfg = await self._require_mod(interaction)
        if not mod_cfg:
            return
        cfg = await db.config(interaction.guild_id)
        cases = await db.cases_for_user(interaction.guild_id, member.id, 25)
        points = await db.active_warning_points(interaction.guild_id, member.id)
        if not cases:
            return await safe_ephemeral(interaction, f"{member.mention} has no moderation cases.")
        lines = []
        for row in cases:
            status = "active" if row["active"] else "cleared"
            p = f" • {row['points']}pt" if row["points"] else ""
            lines.append(f"`#{row['id']}` **{row['action'].replace('_',' ').title()}**{p} • {status}\n{row['reason'][:180]}")
        e = make_embed(
            cfg,
            f"Moderation history • {member}",
            f"**Active warning points:** {points}\n\n" + "\n\n".join(lines)[:3600],
            color=cfg["closed_color"],
        )
        await interaction.response.send_message(embed=e, ephemeral=True)

    @warn_group.command(name="remove", description="Clear a warning case without deleting its history.")
    async def warn_remove(self, interaction: discord.Interaction, case_id: int, reason: str = "Warning cleared"):
        mod_cfg = await self._require_mod(interaction)
        if not mod_cfg:
            return
        row = await db.case(interaction.guild_id, case_id)
        if not row or row["action"] != "warning":
            return await safe_ephemeral(interaction, "That is not a warning case.")
        await db.deactivate_case(interaction.guild_id, case_id)
        await db.add_case_note(case_id, interaction.user.id, reason[:1000])
        await moderation_log(
            interaction.guild, "Warning cleared", reason,
            target_id=row["target_id"], moderator_id=interaction.user.id,
            case_id=case_id, color=LATTE
        )
        await safe_ephemeral(interaction, f"Warning case #{case_id} is now inactive.")

    @case_group.command(name="view", description="View a moderation case by case number.")
    async def case_cmd(self, interaction: discord.Interaction, case_id: int):
        mod_cfg = await self._require_mod(interaction)
        if not mod_cfg:
            return
        row = await db.case(interaction.guild_id, case_id)
        if not row:
            return await safe_ephemeral(interaction, "Case not found.")
        await interaction.response.send_message(embed=await case_embed(interaction.guild, row), ephemeral=True)

    @case_group.command(name="note", description="Add a private note to a moderation case.")
    async def case_note(self, interaction: discord.Interaction, case_id: int, note: str):
        mod_cfg = await self._require_mod(interaction)
        if not mod_cfg:
            return
        row = await db.case(interaction.guild_id, case_id)
        if not row:
            return await safe_ephemeral(interaction, "Case not found.")
        await db.add_case_note(case_id, interaction.user.id, note[:1500])
        await safe_ephemeral(interaction, f"Private note added to case #{case_id}.")

    @case_link_group.command(name="ticket", description="Link a moderation case to a support ticket.")
    async def case_link_ticket(self, interaction: discord.Interaction, case_id: int, ticket_id: int):
        mod_cfg = await self._require_mod(interaction)
        if not mod_cfg:
            return
        row = await db.case(interaction.guild_id, case_id)
        ticket = await db.ticket(ticket_id)
        if not row or not ticket or ticket["guild_id"] != interaction.guild_id:
            return await safe_ephemeral(interaction, "Case or ticket not found in this server.")
        await db.execute(
            "UPDATE moderation_cases SET related_ticket_id=? WHERE guild_id=? AND id=?",
            (ticket_id, interaction.guild_id, case_id),
        )
        await safe_ephemeral(interaction, f"Case #{case_id} linked to ticket #{ticket_id:04d}.")

    @mod_group.command(name="context", description="Show a compact moderation context summary for a member.")
    async def mod_context(self, interaction: discord.Interaction, member: discord.Member):
        mod_cfg = await self._require_mod(interaction)
        if not mod_cfg:
            return
        cfg = await db.config(interaction.guild_id)
        cases = await db.cases_for_user(interaction.guild_id, member.id, 50)
        points = await db.active_warning_points(interaction.guild_id, member.id)
        jail = await db.jail_snapshot(interaction.guild_id, member.id)
        reports = await db.all(
            "SELECT COUNT(*) c FROM reports WHERE guild_id=? AND target_id=? AND status!='resolved'",
            (interaction.guild_id, member.id),
        )
        actions = {}
        for row in cases:
            actions[row["action"]] = actions.get(row["action"], 0) + 1
        action_text = ", ".join(f"{k.replace('_',' ')}: {v}" for k, v in sorted(actions.items())) or "None"
        report_count = int(reports[0]["c"]) if reports else 0
        e = make_embed(
            cfg,
            f"Moderation context • {member}",
            "A quick cross-system summary for staff. This is descriptive data, not an automated punishment recommendation.",
            color=cfg["accent_color"],
        )
        e.add_field(name="Active warning points", value=str(points), inline=True)
        e.add_field(name="Jailed", value="Yes" if jail else "No", inline=True)
        e.add_field(name="Open reports naming member", value=str(report_count), inline=True)
        e.add_field(name="Case counts", value=action_text[:1024], inline=False)
        recent = "\n".join(f"`#{r['id']}` {r['action'].replace('_',' ').title()} — {r['reason'][:120]}" for r in cases[:5]) or "No cases."
        e.add_field(name="Recent cases", value=recent[:1024], inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="kick", description="Kick a member and create a moderation case.")
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        mod_cfg = await self._require_mod(interaction)
        if not mod_cfg:
            return
        ok, why = hierarchy_ok(interaction.user, member, interaction.guild.me)
        if not ok:
            return await safe_ephemeral(interaction, why)
        case_id = await db.create_case(
            interaction.guild_id, member.id, interaction.user.id, "kick", reason[:1500], active=False
        )
        await send_moderation_dm(member, interaction.guild, "Kick", reason, case_id)
        try:
            await member.kick(reason=f"Case #{case_id}: {reason}")
        except discord.HTTPException as exc:
            return await safe_ephemeral(interaction, f"Kick failed: `{exc}`")
        await moderation_log(
            interaction.guild, "Member kicked", reason,
            target_id=member.id, moderator_id=interaction.user.id, case_id=case_id
        )
        await safe_ephemeral(interaction, f"{member} was kicked. Case #{case_id}.")

    @app_commands.command(name="ban", description="Ban a member and create a moderation case.")
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
        delete_message_days: app_commands.Range[int, 0, 7] = 0,
    ):
        mod_cfg = await self._require_mod(interaction)
        if not mod_cfg:
            return
        ok, why = hierarchy_ok(interaction.user, member, interaction.guild.me)
        if not ok:
            return await safe_ephemeral(interaction, why)
        case_id = await db.create_case(
            interaction.guild_id, member.id, interaction.user.id, "ban", reason[:1500]
        )
        await send_moderation_dm(member, interaction.guild, "Ban", reason, case_id)
        try:
            await interaction.guild.ban(
                member,
                reason=f"Case #{case_id}: {reason}",
                delete_message_seconds=int(delete_message_days) * 86400,
            )
        except discord.HTTPException as exc:
            await db.deactivate_case(interaction.guild_id, case_id)
            return await safe_ephemeral(interaction, f"Ban failed: `{exc}`")
        await moderation_log(
            interaction.guild, "Member banned", reason,
            target_id=member.id, moderator_id=interaction.user.id, case_id=case_id,
            color=ESPRESSO
        )
        await safe_ephemeral(interaction, f"{member} was banned. Case #{case_id}.")

    @app_commands.command(name="unban", description="Unban a user by Discord user ID.")
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "Ban lifted"):
        mod_cfg = await self._require_mod(interaction)
        if not mod_cfg:
            return
        try:
            uid = int(user_id)
        except ValueError:
            return await safe_ephemeral(interaction, "Enter a numeric Discord user ID.")
        case_id = await db.create_case(
            interaction.guild_id, uid, interaction.user.id, "unban", reason[:1500], active=False
        )
        try:
            await interaction.guild.unban(discord.Object(id=uid), reason=f"Case #{case_id}: {reason}")
        except discord.HTTPException as exc:
            return await safe_ephemeral(interaction, f"Unban failed: `{exc}`")
        await moderation_log(
            interaction.guild, "User unbanned", reason,
            target_id=uid, moderator_id=interaction.user.id, case_id=case_id,
            color=LATTE
        )
        await safe_ephemeral(interaction, f"User `{uid}` was unbanned. Case #{case_id}.")

    @app_commands.command(name="timeout", description="Timeout a member and place them in jail with role restoration.")
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: str):
        mod_cfg = await self._require_mod(interaction)
        if not mod_cfg:
            return
        ok, why = hierarchy_ok(interaction.user, member, interaction.guild.me)
        if not ok:
            return await safe_ephemeral(interaction, why)
        try:
            seconds = parse_duration(duration)
        except ValueError as exc:
            return await safe_ephemeral(interaction, str(exc))
        if seconds > 28 * 86400:
            return await safe_ephemeral(interaction, "Discord timeouts cannot exceed 28 days.")

        case_id = await db.create_case(
            interaction.guild_id, member.id, interaction.user.id,
            "timeout_jail", reason[:1500], duration_seconds=seconds,
            expires_at=(datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
        )
        await interaction.response.defer(ephemeral=True)
        try:
            await member.timeout(timedelta(seconds=seconds), reason=f"Case #{case_id}: {reason}")
        except discord.HTTPException as exc:
            await db.deactivate_case(interaction.guild_id, case_id)
            return await interaction.followup.send(f"Timeout failed: `{exc}`", ephemeral=True)

        jailed, detail = await apply_jail(interaction.guild, member, interaction.user, reason, case_id)
        await send_moderation_dm(member, interaction.guild, "Timeout + jail", reason, case_id, duration=seconds)
        await moderation_log(
            interaction.guild, "Member timed out and jailed",
            f"**Duration:** {human_duration(seconds)}\n**Reason:** {reason}\n**Jail:** {detail}",
            target_id=member.id, moderator_id=interaction.user.id,
            case_id=case_id, color=ESPRESSO
        )
        await interaction.followup.send(
            f"{member.mention} was timed out for **{human_duration(seconds)}**. "
            f"Jail status: {'applied' if jailed else 'failed'} — {detail}",
            ephemeral=True,
        )

    @app_commands.command(name="untimeout", description="Remove a Discord timeout and restore roles from jail.")
    async def untimeout(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Timeout ended early"):
        mod_cfg = await self._require_mod(interaction)
        if not mod_cfg:
            return
        ok, why = hierarchy_ok(interaction.user, member, interaction.guild.me)
        if not ok:
            return await safe_ephemeral(interaction, why)
        await interaction.response.defer(ephemeral=True)
        try:
            await member.timeout(None, reason=reason)
        except discord.HTTPException as exc:
            return await interaction.followup.send(f"Could not clear timeout: `{exc}`", ephemeral=True)
        restored, detail = await restore_from_jail(interaction.guild, member, interaction.user, reason)
        case_id = await db.create_case(
            interaction.guild_id, member.id, interaction.user.id,
            "untimeout_unjail", reason[:1500], active=False
        )
        await moderation_log(
            interaction.guild, "Timeout removed", f"{reason}\n{detail}",
            target_id=member.id, moderator_id=interaction.user.id, case_id=case_id,
            color=LATTE
        )
        await interaction.followup.send(
            f"Timeout removed. Role restoration: {'complete' if restored else 'problem'} — {detail}",
            ephemeral=True,
        )

    @jail_group.command(name="add", description="Remove removable roles and place a member in the configured jail role.")
    async def jail(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        mod_cfg = await self._require_mod(interaction)
        if not mod_cfg:
            return
        ok, why = hierarchy_ok(interaction.user, member, interaction.guild.me)
        if not ok:
            return await safe_ephemeral(interaction, why)
        case_id = await db.create_case(
            interaction.guild_id, member.id, interaction.user.id, "jail", reason[:1500]
        )
        await interaction.response.defer(ephemeral=True)
        success, detail = await apply_jail(interaction.guild, member, interaction.user, reason, case_id)
        if not success:
            await db.deactivate_case(interaction.guild_id, case_id)
        else:
            await send_moderation_dm(member, interaction.guild, "Jail", reason, case_id)
            await moderation_log(
                interaction.guild, "Member jailed", f"{reason}\n{detail}",
                target_id=member.id, moderator_id=interaction.user.id, case_id=case_id,
                color=ESPRESSO
            )
        await interaction.followup.send(
            f"Jail {'applied' if success else 'failed'} — {detail}",
            ephemeral=True,
        )

    @jail_group.command(name="remove", description="Remove jail and restore the roles saved when the member was jailed.")
    async def unjail(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Jail ended"):
        mod_cfg = await self._require_mod(interaction)
        if not mod_cfg:
            return
        ok, why = hierarchy_ok(interaction.user, member, interaction.guild.me)
        if not ok:
            return await safe_ephemeral(interaction, why)
        await interaction.response.defer(ephemeral=True)
        success, detail = await restore_from_jail(interaction.guild, member, interaction.user, reason)
        case_id = await db.create_case(
            interaction.guild_id, member.id, interaction.user.id, "unjail", reason[:1500], active=False
        )
        await moderation_log(
            interaction.guild, "Member unjailed", f"{reason}\n{detail}",
            target_id=member.id, moderator_id=interaction.user.id, case_id=case_id,
            color=LATTE
        )
        await interaction.followup.send(
            f"Unjail {'completed' if success else 'had a problem'} — {detail}",
            ephemeral=True,
        )

    @app_commands.command(name="purge", description="Delete a batch of recent messages from the current channel.")
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100], member: discord.Member | None = None):
        mod_cfg = await self._require_mod(interaction)
        if not mod_cfg:
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            return await safe_ephemeral(interaction, "This command only works in text channels.")
        await interaction.response.defer(ephemeral=True)
        check = (lambda m: m.author.id == member.id) if member else None
        deleted = await interaction.channel.purge(limit=int(amount), check=check, reason=f"Purge by {interaction.user}")
        case_id = await db.create_case(
            interaction.guild_id,
            member.id if member else interaction.user.id,
            interaction.user.id,
            "message_purge",
            f"Purged {len(deleted)} messages in #{interaction.channel.name}",
            active=False,
            metadata=json.dumps({"channel_id": interaction.channel.id, "requested": int(amount)})
        )
        await moderation_log(
            interaction.guild, "Messages purged",
            f"Deleted **{len(deleted)}** message(s) in {interaction.channel.mention}.",
            target_id=member.id if member else None,
            moderator_id=interaction.user.id, case_id=case_id
        )
        await interaction.followup.send(f"Deleted **{len(deleted)}** message(s).", ephemeral=True)

    @app_commands.command(name="slowmode", description="Set slowmode on the current text channel.")
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
        mod_cfg = await self._require_mod(interaction)
        if not mod_cfg:
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            return await safe_ephemeral(interaction, "This command only works in text channels.")
        await interaction.channel.edit(slowmode_delay=int(seconds), reason=f"Slowmode changed by {interaction.user}")
        await safe_ephemeral(interaction, f"Slowmode set to **{seconds} seconds**.")

    @report_group.command(name="submit", description="Submit a detailed private report about a member.")
    async def report(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
        details: str,
        evidence: str | None = None,
    ):
        mod_cfg = await db.mod_config(interaction.guild_id)
        if not mod_cfg["reports_category_id"] or not mod_cfg["moderator_role_id"]:
            return await safe_ephemeral(interaction, "The report system is not configured yet.")
        if member.id == interaction.user.id:
            return await safe_ephemeral(interaction, "Use `/appeal submit` for moderation actions involving yourself.")

        report_id = await db.create_report(
            interaction.guild_id, interaction.user.id, member.id,
            reason[:500], details[:1800], evidence[:1000] if evidence else None
        )
        category = interaction.guild.get_channel(mod_cfg["reports_category_id"])
        mod_role = interaction.guild.get_role(mod_cfg["moderator_role_id"])
        me = interaction.guild.me
        if not isinstance(category, discord.CategoryChannel) or not mod_role:
            return await safe_ephemeral(interaction, "Report configuration is incomplete.")

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            mod_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        if me:
            overwrites[me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True)

        channel = await interaction.guild.create_text_channel(
            f"report-{report_id:04d}-{slugify(member.display_name)}"[:100],
            category=category, overwrites=overwrites,
            topic=f"Report #{report_id} • reporter={interaction.user.id} • target={member.id}"
        )
        await db.set_report_channel(report_id, channel.id)
        cfg = await db.config(interaction.guild_id)
        e = make_embed(cfg, f"Member report #{report_id}", separator(cfg, "Private report record"), color=cfg["closed_color"])
        e.add_field(name="Reporter", value=interaction.user.mention, inline=True)
        e.add_field(name="Reported member", value=f"{member.mention} (`{member.id}`)", inline=True)
        e.add_field(name="Reason", value=reason[:1024], inline=False)
        e.add_field(name="Details", value=details[:1024], inline=False)
        if evidence:
            e.add_field(name="Evidence / links", value=evidence[:1024], inline=False)
        await channel.send(embed=e)

        queue = interaction.guild.get_channel(mod_cfg["report_queue_channel_id"]) if mod_cfg["report_queue_channel_id"] else None
        if isinstance(queue, discord.TextChannel):
            qe = make_embed(cfg, f"New report #{report_id}", f"{interaction.user.mention} reported {member.mention}.", color=cfg["closed_color"])
            qe.add_field(name="Reason", value=reason[:1024], inline=False)
            qe.add_field(name="Report channel", value=channel.mention, inline=False)
            await queue.send(content=mod_role.mention, embed=qe, allowed_mentions=discord.AllowedMentions(roles=True))

        await safe_ephemeral(interaction, f"Your report was submitted privately as **Report #{report_id}**: {channel.mention}")

    @report_group.command(name="claim", description="Claim a report for staff review.")
    async def report_claim(self, interaction: discord.Interaction, report_id: int):
        mod_cfg = await self._require_mod(interaction)
        if not mod_cfg:
            return
        row = await db.report(interaction.guild_id, report_id)
        if not row:
            return await safe_ephemeral(interaction, "Report not found.")
        await db.claim_report(report_id, interaction.user.id)
        channel = interaction.guild.get_channel(row["channel_id"]) if row["channel_id"] else None
        if isinstance(channel, discord.TextChannel):
            await channel.send(embed=make_embed(
                await db.config(interaction.guild_id),
                "Report claimed",
                f"{interaction.user.mention} is reviewing this report.",
                color=COFFEE
            ))
        await safe_ephemeral(interaction, f"Report #{report_id} assigned to you.")

    @report_group.command(name="resolve", description="Resolve a report with a documented outcome.")
    async def report_resolve(self, interaction: discord.Interaction, report_id: int, resolution: str):
        mod_cfg = await self._require_mod(interaction)
        if not mod_cfg:
            return
        row = await db.report(interaction.guild_id, report_id)
        if not row:
            return await safe_ephemeral(interaction, "Report not found.")
        await db.resolve_report(report_id, resolution[:1500])
        channel = interaction.guild.get_channel(row["channel_id"]) if row["channel_id"] else None
        cfg = await db.config(interaction.guild_id)
        if isinstance(channel, discord.TextChannel):
            await channel.send(embed=make_embed(
                cfg, "Report resolved",
                f"**Resolution:** {resolution}\n\nReviewed by {interaction.user.mention}.",
                color=cfg["accent_color"]
            ))
        await moderation_log(
            interaction.guild, "Report resolved",
            f"Report #{report_id}\n**Resolution:** {resolution}",
            target_id=row["target_id"], moderator_id=interaction.user.id
        )
        await safe_ephemeral(interaction, f"Report #{report_id} marked resolved.")

    @appeal_group.command(name="submit", description="Submit a private appeal for one of your moderation cases.")
    async def appeal(
        self,
        interaction: discord.Interaction,
        case_id: int,
        reason: str,
        details: str,
    ):
        mod_cfg = await db.mod_config(interaction.guild_id)
        if not mod_cfg["appeals_category_id"] or not mod_cfg["moderator_role_id"]:
            return await safe_ephemeral(interaction, "The appeal system is not configured yet.")
        case = await db.case(interaction.guild_id, case_id)
        if not case or case["target_id"] != interaction.user.id:
            return await safe_ephemeral(interaction, "That case does not exist or does not belong to you.")

        appeal_id = await db.create_appeal(
            interaction.guild_id, interaction.user.id, case_id,
            reason[:500], details[:1800]
        )
        category = interaction.guild.get_channel(mod_cfg["appeals_category_id"])
        mod_role = interaction.guild.get_role(mod_cfg["moderator_role_id"])
        me = interaction.guild.me
        if not isinstance(category, discord.CategoryChannel) or not mod_role:
            return await safe_ephemeral(interaction, "Appeal configuration is incomplete.")

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            mod_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        if me:
            overwrites[me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True)

        channel = await interaction.guild.create_text_channel(
            f"appeal-{appeal_id:04d}-{slugify(interaction.user.display_name)}"[:100],
            category=category, overwrites=overwrites,
            topic=f"Appeal #{appeal_id} • user={interaction.user.id} • case={case_id}"
        )
        await db.set_appeal_channel(appeal_id, channel.id)

        cfg = await db.config(interaction.guild_id)
        e = make_embed(cfg, f"Appeal #{appeal_id}", separator(cfg, f"Appeal for case #{case_id}"), color=cfg["primary_color"])
        e.add_field(name="Appealing member", value=interaction.user.mention, inline=True)
        e.add_field(name="Original action", value=case["action"].replace("_"," ").title(), inline=True)
        e.add_field(name="Original reason", value=case["reason"][:1024], inline=False)
        e.add_field(name="Appeal reason", value=reason[:1024], inline=False)
        e.add_field(name="Appeal details", value=details[:1024], inline=False)
        await channel.send(embed=e)

        queue = interaction.guild.get_channel(mod_cfg["appeal_queue_channel_id"]) if mod_cfg["appeal_queue_channel_id"] else None
        if isinstance(queue, discord.TextChannel):
            qe = make_embed(cfg, f"New appeal #{appeal_id}", f"{interaction.user.mention} appealed case **#{case_id}**.", color=cfg["primary_color"])
            qe.add_field(name="Appeal channel", value=channel.mention, inline=False)
            await queue.send(content=mod_role.mention, embed=qe, allowed_mentions=discord.AllowedMentions(roles=True))

        await safe_ephemeral(interaction, f"Appeal **#{appeal_id}** was submitted privately: {channel.mention}")

    @appeal_group.command(name="claim", description="Claim an appeal for staff review.")
    async def appeal_claim(self, interaction: discord.Interaction, appeal_id: int):
        mod_cfg = await self._require_mod(interaction)
        if not mod_cfg:
            return
        row = await db.appeal(interaction.guild_id, appeal_id)
        if not row:
            return await safe_ephemeral(interaction, "Appeal not found.")
        await db.claim_appeal(appeal_id, interaction.user.id)
        channel = interaction.guild.get_channel(row["channel_id"]) if row["channel_id"] else None
        if isinstance(channel, discord.TextChannel):
            await channel.send(embed=make_embed(
                await db.config(interaction.guild_id),
                "Appeal claimed",
                f"{interaction.user.mention} is reviewing this appeal.",
                color=COFFEE
            ))
        await safe_ephemeral(interaction, f"Appeal #{appeal_id} assigned to you.")

    @appeal_group.command(name="resolve", description="Resolve an appeal and document the outcome.")
    async def appeal_resolve(
        self,
        interaction: discord.Interaction,
        appeal_id: int,
        outcome: str,
        clear_case: bool = False,
    ):
        mod_cfg = await self._require_mod(interaction)
        if not mod_cfg:
            return
        row = await db.appeal(interaction.guild_id, appeal_id)
        if not row:
            return await safe_ephemeral(interaction, "Appeal not found.")
        await db.resolve_appeal(appeal_id, outcome[:1500])
        if clear_case and row["case_id"]:
            await db.deactivate_case(interaction.guild_id, row["case_id"])
            await db.add_case_note(row["case_id"], interaction.user.id, f"Cleared through appeal #{appeal_id}: {outcome[:900]}")
        channel = interaction.guild.get_channel(row["channel_id"]) if row["channel_id"] else None
        cfg = await db.config(interaction.guild_id)
        if isinstance(channel, discord.TextChannel):
            e = make_embed(cfg, "Appeal resolved", f"**Outcome:** {outcome}", color=cfg["accent_color"])
            e.add_field(name="Original case cleared", value="Yes" if clear_case else "No", inline=True)
            await channel.send(embed=e)
        user = interaction.client.get_user(row["user_id"])
        if not user:
            try:
                user = await interaction.client.fetch_user(row["user_id"])
            except discord.HTTPException:
                user = None
        if user:
            try:
                e = make_embed(cfg, f"Appeal #{appeal_id} resolved", outcome[:3500], color=cfg["accent_color"])
                e.add_field(name="Original case cleared", value="Yes" if clear_case else "No", inline=True)
                await user.send(embed=e)
            except discord.HTTPException:
                pass
        await moderation_log(
            interaction.guild, "Appeal resolved",
            f"Appeal #{appeal_id}\n**Outcome:** {outcome}\n**Original case cleared:** {'Yes' if clear_case else 'No'}",
            target_id=row["user_id"], moderator_id=interaction.user.id
        )
        await safe_ephemeral(interaction, f"Appeal #{appeal_id} resolved.")

class CinnxmnBot(commands.Bot):
    async def setup_hook(self):
        await db.init()
        await self.add_cog(TicketCog(self))
        await self.add_cog(ModerationCog(self))

        # Restore persistent panels.
        for panel in await db.panels():
            cfg = await db.config(panel["guild_id"])
            rows = []
            for raw in panel["type_ids"].split(","):
                try:
                    tid = int(raw)
                except ValueError:
                    continue
                row = await db.type_by_id(panel["guild_id"], tid)
                if row and row["enabled"]:
                    rows.append(row)
            if rows and panel["message_id"]:
                self.add_view(PanelView(panel["id"], rows, cfg, panel["placeholder"]), message_id=panel["message_id"])

        # Restore persistent ticket buttons.
        for ticket in await db.persistent_tickets():
            if ticket["status"] == "open":
                if ticket["control_message_id"]:
                    self.add_view(TicketControls(ticket["id"]), message_id=ticket["control_message_id"])
                if ticket["queue_message_id"]:
                    self.add_view(QueueControls(ticket["id"]), message_id=ticket["queue_message_id"])
            elif ticket["status"] == "closed" and ticket["control_message_id"]:
                self.add_view(ClosedControls(ticket["id"]), message_id=ticket["control_message_id"])

        if GUILD_ID.isdigit():
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Synced commands to guild %s", GUILD_ID)
        else:
            await self.tree.sync()
            log.info("Synced commands globally")


bot = CinnxmnBot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    log.info("Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "?")


@bot.tree.error
async def app_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "You do not have permission to use that command."
    else:
        log.exception("Application command error", exc_info=error)
        msg = f"Something went wrong: `{error}`"
    try:
        await safe_ephemeral(interaction, msg)
    except discord.HTTPException:
        pass


bot.run(TOKEN)
CROISSANT = 0xD7A86E
LATTE = 0xC8A27A
COFFEE = 0x6F4E37
ESPRESSO = 0x4B3621
CREAM = 0xE8D6C0
ROSE = 0xB5838D

intents = discord.Intents.default()
# Needed only for transcript body text. Enable Message Content Intent in Developer Portal.
intents.message_content = True


# -----------------------------
# Helpers / accessibility
# -----------------------------

def slugify(value: str, fallback: str = "ticket") -> str:
    value = re.sub(r"[^a-z0-9-]+", "-", value.lower().strip()).strip("-")
    return value[:40] or fallback


def parse_hex_color(value: str | None) -> int | None:
    if value is None:
        return None
    raw = value.strip().lower().replace("#", "").replace("0x", "")
    if not re.fullmatch(r"[0-9a-f]{6}", raw):
        raise ValueError("Use a 6-digit hex color such as D7A86E.")
    return int(raw, 16)


def color_hex(value: int) -> str:
    return f"#{value:06X}"


def bool_word(value: bool) -> str:
    return "On" if value else "Off"


def has_manage(member: discord.Member) -> bool:
    return member.guild_permissions.manage_guild or member.guild_permissions.administrator


def effective_staff_role(guild: discord.Guild, cfg, ticket=None):
    role_id = None
    if ticket:
        keys = set(ticket.keys())
        if "type_staff_role_id" in keys and ticket["type_staff_role_id"]:
            role_id = ticket["type_staff_role_id"]
        elif "staff_role_id" in keys and ticket["staff_role_id"]:
            role_id = ticket["staff_role_id"]
    if not role_id:
        role_id = cfg["staff_role_id"]
    return guild.get_role(role_id) if role_id else None


def is_staff(member: discord.Member, cfg, ticket=None) -> bool:
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    role = effective_staff_role(member.guild, cfg, ticket)
    return bool(role and role in member.roles)


def decor(cfg, emoji: str, text: str) -> str:
    if cfg and cfg["decorative_emojis"]:
        return f"{emoji} {text}"
    return text


def separator(cfg, text: str) -> str:
    # !*!* is only used in embed/message bodies where Markdown is rendered.
    if cfg and cfg["use_separator"]:
        return f"!*!* {text} !*!*"
    return text


def footer_text(cfg) -> str:
    # Footers do not support Discord Markdown, so no !*!* here.
    return (cfg["footer_text"] if cfg else DEFAULT_BRAND)[:2048]


def make_embed(cfg, title: str, description: str = "", *,
               color: int | None = None, timestamp: bool = True) -> discord.Embed:
    chosen = color if color is not None else (cfg["primary_color"] if cfg else LATTE)
    embed = discord.Embed(
        title=title,
        description=description,
        color=chosen,
        timestamp=datetime.now(timezone.utc) if timestamp else None,
    )
    embed.set_footer(text=footer_text(cfg))
    return embed


async def safe_ephemeral(interaction: discord.Interaction, content=None, *, embed=None, file=None, view=None):
    kwargs = {"ephemeral": True}
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if file is not None:
        kwargs["file"] = file
    if view is not None:
        kwargs["view"] = view
    try:
        if interaction.response.is_done():
            return await interaction.followup.send(**kwargs)
        return await interaction.response.send_message(**kwargs)
    except discord.NotFound:
        log.warning("Interaction expired before response could be sent: %s", interaction.id)
        return None


async def require_ticket(interaction: discord.Interaction):
    if not interaction.guild or not interaction.channel_id:
        await safe_ephemeral(interaction, "This command must be used inside a ticket channel.")
        return None, None
    ticket = await db.ticket_by_channel(interaction.channel_id)
    cfg = await db.config(interaction.guild.id)
    if not ticket:
        await safe_ephemeral(interaction, "This channel is not registered as a ticket.")
        return None, cfg
    return ticket, cfg


async def ticket_type_choices(interaction: discord.Interaction, current: str):
    if not interaction.guild_id:
        return []
    rows = await db.types(interaction.guild_id)
    needle = current.lower().strip()
    result = []
    for row in rows:
        label = f"{row['emoji']} {row['name']} — ID {row['id']}"
        if needle and needle not in label.lower():
            continue
        result.append(app_commands.Choice(name=label[:100], value=row["id"]))
        if len(result) >= 25:
            break
    return result


async def panel_choices(interaction: discord.Interaction, current: str):
    if not interaction.guild_id:
        return []
    rows = await db.panels(interaction.guild_id)
    needle = current.lower().strip()
    result = []
    for row in rows:
        label = f"#{row['id']} • {row['title']}"
        if needle and needle not in label.lower():
            continue
        result.append(app_commands.Choice(name=label[:100], value=row["id"]))
        if len(result) >= 25:
            break
    return result


async def transcript_bytes(channel: discord.TextChannel, ticket, cfg) -> bytes:
    brand = html.escape(cfg["brand_name"])
    chunks = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<style>",
        "body{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        "background:#f8f1e8;color:#3f2f25;padding:24px;max-width:980px;margin:auto;line-height:1.45}",
        ".hero{background:#fffaf4;border:1px solid #d7a86e;border-radius:18px;padding:20px;margin-bottom:20px}",
        ".msg{background:#fffdf9;border:1px solid #ddc4a8;border-radius:14px;padding:12px 14px;margin:10px 0}",
        ".meta{color:#765d49;font-size:12px;margin-bottom:6px}",
        ".content{white-space:pre-wrap;word-break:break-word}",
        ".attachments{margin-top:7px}.attachments a{color:#6f4e37}",
        "</style></head><body>",
        "<div class='hero'>",
        f"<h1>Ticket #{ticket['id']:04d} — {html.escape(ticket['type_name'])}</h1>",
        f"<p><b>Brand:</b> {brand}</p>",
        f"<p><b>Subject:</b> {html.escape(ticket['subject'])}</p>",
        f"<p><b>Customer ID:</b> {ticket['opener_id']}</p>",
        f"<p><b>Status:</b> {html.escape(ticket['status'])}</p>",
        "</div>",
    ]
    async for message in channel.history(limit=None, oldest_first=True):
        author = html.escape(str(message.author))
        when = message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        content = html.escape(message.content or "")
        attachments = "<br>".join(
            f"<a href='{html.escape(a.url)}'>{html.escape(a.filename)}</a>"
            for a in message.attachments
        )
        chunks.extend([
            "<div class='msg'>",
            f"<div class='meta'>{author} • {when}</div>",
            f"<div class='content'>{content}</div>",
            f"<div class='attachments'>{attachments}</div>" if attachments else "",
            "</div>",
        ])
    chunks.append("</body></html>")
    return "\n".join(chunks).encode("utf-8")


def ticket_status_text(ticket) -> str:
    if ticket["status"] == "closed":
        return "Closed"
    if ticket["claimed_by"]:
        return f"Claimed by <@{ticket['claimed_by']}>"
    return "Open — waiting for staff"


def priority_label(priority: str) -> str:
    return {
        "low": "Low",
        "normal": "Normal",
        "high": "High",
        "urgent": "Urgent",
    }.get(priority, priority.title())


async def ticket_embed(ticket, cfg) -> discord.Embed:
    emoji = ticket["type_emoji"] if cfg["decorative_emojis"] else ""
    title = f"{emoji} {ticket['type_name']} • Ticket #{ticket['id']:04d}".strip()
    if ticket["status"] == "closed":
        desc = separator(cfg, "This ticket is closed")
        color = cfg["closed_color"]
    else:
        welcome = ticket["type_welcome_text"] or (
            "Your ticket is open. A staff member can claim it from the private staff queue."
        )
        desc = f"{separator(cfg, 'Welcome to the ' + cfg['brand_name'] + ' help counter')}\n\n{welcome}"
        color = ticket["type_color"] or cfg["primary_color"]

    embed = make_embed(cfg, title, desc, color=color)
    embed.add_field(name="Customer", value=f"<@{ticket['opener_id']}>", inline=True)
    embed.add_field(name="Status", value=ticket_status_text(ticket), inline=True)
    embed.add_field(name="Priority", value=priority_label(ticket["priority"]), inline=True)
    embed.add_field(name="Subject", value=ticket["subject"][:1024], inline=False)
    embed.add_field(name="Details", value=ticket["details"][:1024], inline=False)
    if ticket["locked"]:
        embed.add_field(name="Conversation", value="Locked — customer replies are disabled.", inline=False)
    if ticket["status"] == "closed":
        if ticket["closed_by"]:
            embed.add_field(name="Closed by", value=f"<@{ticket['closed_by']}>", inline=True)
        if ticket["close_reason"]:
            embed.add_field(name="Close reason", value=ticket["close_reason"][:1024], inline=False)
    return embed


async def queue_embed(ticket, cfg) -> discord.Embed:
    if ticket["status"] == "closed":
        color = cfg["closed_color"]
        status = "Closed"
    elif ticket["claimed_by"]:
        color = cfg["accent_color"]
        status = f"Claimed by <@{ticket['claimed_by']}>"
    else:
        color = ticket["type_color"] or cfg["primary_color"]
        status = "Unclaimed — needs a staff member"

    emoji = ticket["type_emoji"] if cfg["decorative_emojis"] else ""
    embed = make_embed(
        cfg,
        f"{emoji} Ticket #{ticket['id']:04d} • {ticket['type_name']}".strip(),
        separator(cfg, "Staff queue"),
        color=color,
    )
    embed.add_field(name="Customer", value=f"<@{ticket['opener_id']}>", inline=True)
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(name="Priority", value=priority_label(ticket["priority"]), inline=True)
    embed.add_field(name="Subject", value=ticket["subject"][:1024], inline=False)
    embed.add_field(name="Details", value=ticket["details"][:1024], inline=False)
    if ticket["channel_id"]:
        embed.add_field(name="Ticket channel", value=f"<#{ticket['channel_id']}>", inline=False)
    return embed


async def refresh_ticket(guild: discord.Guild, ticket_id: int):
    ticket = await db.ticket(ticket_id)
    cfg = await db.config(guild.id)
    if not ticket:
        return
    if ticket["control_message_id"] and ticket["channel_id"]:
        channel = guild.get_channel(ticket["channel_id"])
        if isinstance(channel, discord.TextChannel):
            try:
                msg = await channel.fetch_message(ticket["control_message_id"])
                view = TicketControls(ticket_id) if ticket["status"] == "open" else ClosedControls(ticket_id)
                await msg.edit(embed=await ticket_embed(ticket, cfg), view=view)
            except discord.HTTPException:
                pass
    if ticket["queue_message_id"]:
        queue = guild.get_channel(cfg["staff_queue_channel_id"]) if cfg["staff_queue_channel_id"] else None
        if isinstance(queue, discord.TextChannel):
            try:
                msg = await queue.fetch_message(ticket["queue_message_id"])
                await msg.edit(
                    embed=await queue_embed(ticket, cfg),
                    view=QueueControls(ticket_id) if ticket["status"] == "open" else None,
                )
            except discord.HTTPException:
                pass


def format_ticket_channel(cfg, ticket_type, ticket_id: int, member: discord.Member) -> str:
    template = cfg["ticket_name_format"] or "{type}-{id}-{user}"
    data = {
        "type": slugify(ticket_type["slug"] or ticket_type["name"]),
        "id": f"{ticket_id:04d}",
        "user": slugify(member.display_name, "user"),
        "username": slugify(member.name, "user"),
    }
    try:
        raw = template.format(**data)
    except Exception:
        raw = f"{data['type']}-{data['id']}-{data['user']}"
    return slugify(raw, f"ticket-{ticket_id:04d}")[:100]


# -----------------------------
# Ticket actions
# -----------------------------

async def do_claim(interaction: discord.Interaction, ticket_id: int):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return
    cfg = await db.config(interaction.guild.id)
    ticket = await db.ticket(ticket_id)
    if not ticket:
        return await safe_ephemeral(interaction, "Ticket not found.")
    if not is_staff(interaction.user, cfg, ticket):
        return await safe_ephemeral(interaction, "Only authorized staff can claim this ticket.")
    if ticket["status"] != "open":
        return await safe_ephemeral(interaction, "This ticket is already closed.")
    if ticket["claimed_by"] == interaction.user.id:
        return await safe_ephemeral(interaction, "You already have this ticket.")
    if ticket["claimed_by"]:
        return await safe_ephemeral(interaction, f"This ticket is already claimed by <@{ticket['claimed_by']}>.")

    await interaction.response.defer(ephemeral=True)

    if not await db.claim(ticket_id, interaction.user.id):
        fresh = await db.ticket(ticket_id)
        who = f"<@{fresh['claimed_by']}>" if fresh and fresh["claimed_by"] else "another staff member"
        return await safe_ephemeral(interaction, f"{who} claimed it first.")

    channel = interaction.guild.get_channel(ticket["channel_id"])
    if isinstance(channel, discord.TextChannel):
        await channel.set_permissions(
            interaction.user,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
        )
    await db.audit(interaction.guild.id, "claimed", ticket_id, interaction.user.id, str(interaction.user))
    await refresh_ticket(interaction.guild, ticket_id)
    await safe_ephemeral(interaction, f"Ticket #{ticket_id:04d} is now assigned to you.")
    if isinstance(channel, discord.TextChannel):
        await channel.send(
            embed=make_embed(
                cfg,
                decor(cfg, "☕", "Ticket claimed"),
                f"<@{interaction.user.id}> is now handling this ticket.",
                color=cfg["accent_color"],
            )
        )


async def do_unclaim(interaction: discord.Interaction, ticket_id: int):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return
    cfg = await db.config(interaction.guild.id)
    ticket = await db.ticket(ticket_id)
    if not ticket:
        return await safe_ephemeral(interaction, "Ticket not found.")
    if not is_staff(interaction.user, cfg, ticket):
        return await safe_ephemeral(interaction, "Only authorized staff can unclaim tickets.")
    if not ticket["claimed_by"]:
        return await safe_ephemeral(interaction, "This ticket is already unclaimed.")

    override = has_manage(interaction.user)
    if ticket["claimed_by"] != interaction.user.id and not override:
        return await safe_ephemeral(interaction, "Only the current claimer or a server manager can unclaim this ticket.")

    await interaction.response.defer(ephemeral=True)

    old_id = ticket["claimed_by"]
    if not await db.unclaim(ticket_id, None if override else interaction.user.id):
        return await safe_ephemeral(interaction, "The ticket changed before I could update it.")

    channel = interaction.guild.get_channel(ticket["channel_id"])
    old_member = interaction.guild.get_member(old_id)
    if isinstance(channel, discord.TextChannel) and old_member:
        await channel.set_permissions(old_member, overwrite=None)

    await db.audit(interaction.guild.id, "unclaimed", ticket_id, interaction.user.id, f"Previous claimer {old_id}")
    await refresh_ticket(interaction.guild, ticket_id)

    queue = interaction.guild.get_channel(cfg["staff_queue_channel_id"]) if cfg["staff_queue_channel_id"] else None
    role = effective_staff_role(interaction.guild, cfg, ticket)
    if cfg["ping_staff_on_unclaim"] and isinstance(queue, discord.TextChannel):
        await queue.send(
            content=role.mention if role else None,
            embed=make_embed(
                cfg,
                decor(cfg, "🥐", "Ticket returned to queue"),
                f"Ticket **#{ticket_id:04d}** was unclaimed and needs another staff member.",
                color=cfg["primary_color"],
            ),
            allowed_mentions=discord.AllowedMentions(roles=True),
        )
    await safe_ephemeral(interaction, f"Ticket #{ticket_id:04d} is unclaimed again.")


async def do_transfer(interaction: discord.Interaction, ticket_id: int, target: discord.Member):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return
    cfg = await db.config(interaction.guild.id)
    ticket = await db.ticket(ticket_id)
    if not ticket:
        return await safe_ephemeral(interaction, "Ticket not found.")
    if not is_staff(interaction.user, cfg, ticket):
        return await safe_ephemeral(interaction, "Only authorized staff can transfer tickets.")
    if not is_staff(target, cfg, ticket):
        return await safe_ephemeral(interaction, "That member is not part of the staff team for this ticket type.")

    await interaction.response.defer(ephemeral=True)

    old_id = ticket["claimed_by"]
    channel = interaction.guild.get_channel(ticket["channel_id"])
    if isinstance(channel, discord.TextChannel):
        if old_id:
            old = interaction.guild.get_member(old_id)
            if old and old.id != target.id:
                await channel.set_permissions(old, overwrite=None)
        await channel.set_permissions(
            target,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
        )
    await db.transfer(ticket_id, target.id)
    await db.audit(interaction.guild.id, "transferred", ticket_id, interaction.user.id, f"to {target.id}")
    await refresh_ticket(interaction.guild, ticket_id)
    await safe_ephemeral(interaction, f"Ticket #{ticket_id:04d} transferred to {target.mention}.")
    if isinstance(channel, discord.TextChannel):
        await channel.send(
            embed=make_embed(
                cfg,
                decor(cfg, "☕", "Ticket transferred"),
                f"This ticket is now being handled by {target.mention}.",
                color=cfg["accent_color"],
            )
        )


async def send_close_dm(user, ticket, cfg, closer: discord.Member, reason: str, transcript: bytes | None):
    if not cfg["dm_on_close"]:
        return False
    embed = make_embed(
        cfg,
        decor(cfg, "🍪", f"Your {cfg['brand_name']} ticket has been closed"),
        f"{separator(cfg, 'Thanks for stopping by')}\n\n"
        "Your ticket has been wrapped up. Here is your closure receipt.",
        color=cfg["primary_color"],
    )
    embed.add_field(name="Ticket", value=f"#{ticket['id']:04d} • {ticket['type_name']}", inline=False)
    embed.add_field(name="Subject", value=ticket["subject"][:1024], inline=False)
    embed.add_field(name="Closed by", value=closer.mention, inline=True)
    embed.add_field(name="Reason", value=reason[:1024], inline=False)
    if transcript:
        embed.add_field(name="Transcript", value="Attached as an HTML file below.", inline=False)
    files = []
    if transcript:
        files.append(discord.File(io.BytesIO(transcript), filename=f"{cfg['brand_name']}-ticket-{ticket['id']:04d}.html"))
    try:
        await user.send(embed=embed, files=files)
        log.info("Close DM delivered for ticket %s to user %s", ticket["id"], user.id)
        return True
    except discord.Forbidden as exc:
        log.warning("Close DM forbidden for ticket %s to user %s: %s", ticket["id"], user.id, exc)
        return False
    except discord.HTTPException as exc:
        log.warning("Close DM HTTP error for ticket %s to user %s: %s", ticket["id"], user.id, exc)
        return False


async def do_close(interaction: discord.Interaction, ticket_id: int, reason: str):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return
    cfg = await db.config(interaction.guild.id)
    ticket = await db.ticket(ticket_id)
    if not ticket:
        return await safe_ephemeral(interaction, "Ticket not found.")
    allowed = is_staff(interaction.user, cfg, ticket) or (
        cfg["allow_user_close"] and interaction.user.id == ticket["opener_id"]
    )
    if not allowed:
        return await safe_ephemeral(interaction, "You do not have permission to close this ticket.")
    if ticket["status"] != "open":
        return await safe_ephemeral(interaction, "This ticket is already closed.")

    await interaction.response.defer(ephemeral=True)
    channel = interaction.guild.get_channel(ticket["channel_id"])
    transcript = None
    if cfg["transcript_on_close"] and isinstance(channel, discord.TextChannel):
        try:
            transcript = await transcript_bytes(channel, ticket, cfg)
        except discord.HTTPException:
            transcript = None

    await db.close(ticket_id, interaction.user.id, reason)
    await db.audit(interaction.guild.id, "closed", ticket_id, interaction.user.id, reason)

    opener = interaction.guild.get_member(ticket["opener_id"]) or interaction.client.get_user(ticket["opener_id"])
    if opener is None:
        try:
            opener = await interaction.client.fetch_user(ticket["opener_id"])
        except discord.HTTPException as exc:
            log.warning("Could not fetch opener %s for close DM: %s", ticket["opener_id"], exc)
            opener = None

    dm_ok = await send_close_dm(opener, ticket, cfg, interaction.user, reason, transcript) if opener else False

    log_channel = interaction.guild.get_channel(cfg["log_channel_id"]) if cfg["log_channel_id"] else None
    if isinstance(log_channel, discord.TextChannel):
        e = make_embed(
            cfg,
            decor(cfg, "📜", f"Ticket #{ticket_id:04d} closed"),
            separator(cfg, "Ticket record"),
            color=cfg["closed_color"],
        )
        e.add_field(name="Customer", value=f"<@{ticket['opener_id']}>", inline=True)
        e.add_field(name="Closed by", value=interaction.user.mention, inline=True)
        e.add_field(name="Reason", value=reason[:1024], inline=False)
        e.add_field(name="Close DM", value="Delivered" if dm_ok else "Not delivered / disabled", inline=False)
        files = []
        if transcript:
            files.append(discord.File(io.BytesIO(transcript), filename=f"{cfg['brand_name']}-ticket-{ticket_id:04d}.html"))
        await log_channel.send(embed=e, files=files)

    if isinstance(channel, discord.TextChannel):
        opener_member = interaction.guild.get_member(ticket["opener_id"])
        if opener_member:
            await channel.set_permissions(opener_member, view_channel=False, send_messages=False)
        for row in await db.members(ticket_id):
            member = interaction.guild.get_member(row["user_id"])
            if member:
                await channel.set_permissions(member, overwrite=None)

        archive_id = ticket["type_archive_category_id"] or cfg["archive_category_id"]
        archive = interaction.guild.get_channel(archive_id) if archive_id else None
        kwargs = {
            "name": f"closed-{ticket_id:04d}-{slugify(ticket['type_name'])}"[:100],
            "reason": f"Ticket closed by {interaction.user}: {reason[:250]}",
        }
        if cfg["auto_archive"] and isinstance(archive, discord.CategoryChannel):
            kwargs["category"] = archive
        try:
            await channel.edit(**kwargs)
        except discord.HTTPException:
            pass

    await refresh_ticket(interaction.guild, ticket_id)
    await interaction.followup.send(
        f"Ticket #{ticket_id:04d} closed. "
        + ("The customer received the closure DM." if dm_ok else "The closure DM was disabled or could not be delivered."),
        ephemeral=True,
    )


# -----------------------------
# Modals / Views
# -----------------------------

class CloseModal(discord.ui.Modal):
    def __init__(self, ticket_id: int):
        super().__init__(title="Close ticket")
        self.ticket_id = ticket_id
        self.reason = discord.ui.TextInput(
            label="Reason for closing",
            placeholder="Explain clearly why this ticket is being closed.",
            style=discord.TextStyle.paragraph,
            min_length=2,
            max_length=800,
            required=True,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await do_close(interaction, self.ticket_id, str(self.reason).strip())


class TicketCreateModal(discord.ui.Modal):
    def __init__(self, type_row, cfg):
        super().__init__(title=f"Open {type_row['name']}"[:45])
        self.type_id = type_row["id"]
        self.subject = discord.ui.TextInput(
            label=(type_row["form_label_subject"] or "What can we help with?")[:45],
            placeholder="A short summary",
            min_length=3,
            max_length=80,
        )
        self.details = discord.ui.TextInput(
            label=(type_row["form_label_details"] or "Tell us the details")[:45],
            placeholder="Include the details staff will need to help you.",
            style=discord.TextStyle.paragraph,
            min_length=5,
            max_length=1800,
        )
        self.add_item(self.subject)
        self.add_item(self.details)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return
        cfg = await db.config(interaction.guild.id)
        blocked = await db.blocked(interaction.guild.id, interaction.user.id)
        if blocked:
            reason = blocked["reason"] or "No reason provided."
            return await safe_ephemeral(
                interaction,
                embed=make_embed(
                    cfg,
                    "Ticket access unavailable",
                    f"You cannot open tickets in this server.\n\n**Reason:** {reason}",
                    color=cfg["closed_color"],
                ),
            )

        type_row = await db.type_by_id(interaction.guild.id, self.type_id)
        if not type_row or not type_row["enabled"]:
            return await safe_ephemeral(interaction, "That ticket type is no longer available.")

        existing = await db.open_tickets_for_user(interaction.guild.id, interaction.user.id)
        if len(existing) >= cfg["max_open_per_user"]:
            return await safe_ephemeral(
                interaction,
                f"You already have {len(existing)} open ticket(s). The limit is {cfg['max_open_per_user']}.",
            )

        if not cfg["staff_role_id"] or not cfg["staff_queue_channel_id"] or not cfg["ticket_category_id"]:
            return await safe_ephemeral(interaction, "Ticket setup is incomplete. Please contact a server administrator.")

        await interaction.response.defer(ephemeral=True)
        ticket_id = await db.create_ticket(
            interaction.guild.id,
            interaction.user.id,
            self.type_id,
            str(self.subject).strip(),
            str(self.details).strip(),
        )

        category_id = type_row["category_id"] or cfg["ticket_category_id"]
        category = interaction.guild.get_channel(category_id)
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.followup.send(
                "The configured ticket category is missing. Ask an administrator to run /setup again.",
                ephemeral=True,
            )

        staff_role = effective_staff_role(interaction.guild, cfg, type_row)
        me = interaction.guild.me
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True,
                read_message_history=True, attach_files=True
            ),
        }
        if staff_role:
            # Staff cannot see the ticket until individually claimed.
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=False)
        if me:
            overwrites[me] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                manage_channels=True, manage_messages=True, attach_files=True
            )

        channel = await interaction.guild.create_text_channel(
            format_ticket_channel(cfg, type_row, ticket_id, interaction.user),
            category=category,
            overwrites=overwrites,
            topic=f"{cfg['brand_name']} ticket #{ticket_id:04d} • opener={interaction.user.id} • type={type_row['name']}",
            reason=f"Ticket opened by {interaction.user}",
        )
        await db.attach_ticket_channel(ticket_id, channel.id)
        ticket = await db.ticket(ticket_id)

        control = await channel.send(
            content=interaction.user.mention,
            embed=await ticket_embed(ticket, cfg),
            view=TicketControls(ticket_id),
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        await db.set_control_message(ticket_id, control.id)

        queue = interaction.guild.get_channel(cfg["staff_queue_channel_id"])
        if isinstance(queue, discord.TextChannel):
            content = staff_role.mention if (staff_role and cfg["ping_staff_on_create"]) else None
            qmsg = await queue.send(
                content=content,
                embed=await queue_embed(ticket, cfg),
                view=QueueControls(ticket_id),
                allowed_mentions=discord.AllowedMentions(roles=True),
            )
            await db.set_queue_message(ticket_id, qmsg.id)

        await db.audit(interaction.guild.id, "created", ticket_id, interaction.user.id, type_row["name"])
        await interaction.followup.send(
            f"Your ticket is ready: {channel.mention}",
            ephemeral=True,
        )


class PanelSelect(discord.ui.Select):
    def __init__(self, panel_id: int, type_rows, cfg, placeholder: str | None = None):
        options = []
        for row in type_rows[:25]:
            options.append(
                discord.SelectOption(
                    label=row["name"][:100],
                    value=str(row["id"]),
                    description=row["description"][:100],
                    emoji=discord.PartialEmoji.from_str(row["emoji"]) if row["emoji"] else None,
                )
            )
        chosen_placeholder = placeholder or cfg["panel_placeholder"]
        super().__init__(
            placeholder=(chosen_placeholder or "Choose what you need help with…")[:150],
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"cx:panel:{panel_id}",
        )

    async def callback(self, interaction: discord.Interaction):
        cfg = await db.config(interaction.guild_id)
        row = await db.type_by_id(interaction.guild_id, int(self.values[0]))
        if not row:
            return await safe_ephemeral(interaction, "That ticket type is unavailable.")
        await interaction.response.send_modal(TicketCreateModal(row, cfg))


class PanelView(discord.ui.View):
    def __init__(self, panel_id: int, type_rows, cfg, placeholder: str | None = None):
        super().__init__(timeout=None)
        self.add_item(PanelSelect(panel_id, type_rows, cfg, placeholder))


class QueueControls(discord.ui.View):
    def __init__(self, ticket_id: int):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id

        claim = discord.ui.Button(
            label="Claim ticket", emoji="☕",
            style=discord.ButtonStyle.success,
            custom_id=f"cx:q:claim:{ticket_id}"
        )
        claim.callback = self.claim
        self.add_item(claim)

        unclaim = discord.ui.Button(
            label="Unclaim ticket", emoji="🥐",
            style=discord.ButtonStyle.secondary,
            custom_id=f"cx:q:unclaim:{ticket_id}"
        )
        unclaim.callback = self.unclaim
        self.add_item(unclaim)

    async def claim(self, interaction):
        await do_claim(interaction, self.ticket_id)

    async def unclaim(self, interaction):
        await do_unclaim(interaction, self.ticket_id)


class TicketControls(discord.ui.View):
    def __init__(self, ticket_id: int):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id

        buttons = [
            ("Claim", "☕", discord.ButtonStyle.success, "claim", self.claim),
            ("Unclaim", "🥐", discord.ButtonStyle.secondary, "unclaim", self.unclaim),
            ("Transcript", "📜", discord.ButtonStyle.secondary, "transcript", self.transcript),
            ("Close", "🍪", discord.ButtonStyle.danger, "close", self.close),
        ]
        for label, emoji, style, key, callback in buttons:
            btn = discord.ui.Button(
                label=label, emoji=emoji, style=style,
                custom_id=f"cx:t:{key}:{ticket_id}"
            )
            btn.callback = callback
            self.add_item(btn)

    async def claim(self, interaction):
        await do_claim(interaction, self.ticket_id)

    async def unclaim(self, interaction):
        await do_unclaim(interaction, self.ticket_id)

    async def transcript(self, interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return
        cfg = await db.config(interaction.guild.id)
        ticket = await db.ticket(self.ticket_id)
        if not ticket:
            return await safe_ephemeral(interaction, "Ticket not found.")
        if interaction.user.id != ticket["opener_id"] and not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "You do not have access to this transcript.")
        channel = interaction.guild.get_channel(ticket["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return await safe_ephemeral(interaction, "Ticket channel not found.")
        await interaction.response.defer(ephemeral=True)
        data = await transcript_bytes(channel, ticket, cfg)
        await interaction.followup.send(
            "Transcript:",
            file=discord.File(io.BytesIO(data), filename=f"{cfg['brand_name']}-ticket-{self.ticket_id:04d}.html"),
            ephemeral=True,
        )

    async def close(self, interaction):
        await interaction.response.send_modal(CloseModal(self.ticket_id))


class DeleteConfirm(discord.ui.View):
    def __init__(self, ticket_id: int, user_id: int):
        super().__init__(timeout=60)
        self.ticket_id = ticket_id
        self.user_id = user_id

    @discord.ui.button(label="Delete permanently", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await safe_ephemeral(interaction, "Only the person who opened this confirmation can use it.")
        ticket = await db.ticket(self.ticket_id)
        cfg = await db.config(interaction.guild_id)
        if not ticket or not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "You cannot delete this ticket.")
        channel = interaction.guild.get_channel(ticket["channel_id"])
        await db.mark_deleted(self.ticket_id)
        await db.audit(interaction.guild_id, "deleted", self.ticket_id, interaction.user.id)
        await interaction.response.edit_message(content="Deleting ticket permanently…", embed=None, view=None)
        if isinstance(channel, discord.TextChannel):
            await channel.delete(reason=f"Ticket permanently deleted by {interaction.user}")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await safe_ephemeral(interaction, "Only the person who opened this confirmation can use it.")
        await interaction.response.edit_message(content="Deletion cancelled.", embed=None, view=None)


class ClosedControls(discord.ui.View):
    def __init__(self, ticket_id: int):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id

        reopen = discord.ui.Button(
            label="Reopen", emoji="🥐", style=discord.ButtonStyle.success,
            custom_id=f"cx:c:reopen:{ticket_id}"
        )
        reopen.callback = self.reopen
        self.add_item(reopen)

        transcript = discord.ui.Button(
            label="Transcript", emoji="📜", style=discord.ButtonStyle.secondary,
            custom_id=f"cx:c:transcript:{ticket_id}"
        )
        transcript.callback = self.transcript
        self.add_item(transcript)

        delete = discord.ui.Button(
            label="Delete", emoji="🗑️", style=discord.ButtonStyle.danger,
            custom_id=f"cx:c:delete:{ticket_id}"
        )
        delete.callback = self.delete
        self.add_item(delete)

    async def reopen(self, interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return
        cfg = await db.config(interaction.guild.id)
        ticket = await db.ticket(self.ticket_id)
        if not ticket or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Only authorized staff can reopen this ticket.")
        if ticket["status"] != "closed":
            return await safe_ephemeral(interaction, "This ticket is not closed.")
        channel = interaction.guild.get_channel(ticket["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return await safe_ephemeral(interaction, "Ticket channel not found.")

        opener = interaction.guild.get_member(ticket["opener_id"])
        if opener:
            await channel.set_permissions(
                opener, view_channel=True, send_messages=True,
                read_message_history=True, attach_files=True
            )
        if ticket["claimed_by"]:
            old = interaction.guild.get_member(ticket["claimed_by"])
            if old:
                await channel.set_permissions(old, overwrite=None)

        open_category_id = ticket["type_category_id"] or cfg["ticket_category_id"]
        open_category = interaction.guild.get_channel(open_category_id) if open_category_id else None
        kwargs = {}
        if isinstance(open_category, discord.CategoryChannel):
            kwargs["category"] = open_category
        if opener:
            type_row = await db.type_by_id(interaction.guild.id, ticket["type_id"])
            kwargs["name"] = format_ticket_channel(cfg, type_row, self.ticket_id, opener)
        if kwargs:
            await channel.edit(**kwargs)

        await db.reopen(self.ticket_id)
        await db.audit(interaction.guild.id, "reopened", self.ticket_id, interaction.user.id)

        fresh = await db.ticket(self.ticket_id)
        queue = interaction.guild.get_channel(cfg["staff_queue_channel_id"]) if cfg["staff_queue_channel_id"] else None
        staff_role = effective_staff_role(interaction.guild, cfg, fresh)
        if isinstance(queue, discord.TextChannel):
            qmsg = await queue.send(
                content=staff_role.mention if (staff_role and cfg["ping_staff_on_create"]) else None,
                embed=await queue_embed(fresh, cfg),
                view=QueueControls(self.ticket_id),
                allowed_mentions=discord.AllowedMentions(roles=True),
            )
            await db.set_queue_message(self.ticket_id, qmsg.id)
        await refresh_ticket(interaction.guild, self.ticket_id)
        await safe_ephemeral(interaction, f"Ticket #{self.ticket_id:04d} reopened.")

    async def transcript(self, interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return
        cfg = await db.config(interaction.guild.id)
        ticket = await db.ticket(self.ticket_id)
        if not ticket or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        channel = interaction.guild.get_channel(ticket["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return await safe_ephemeral(interaction, "Ticket channel not found.")
        await interaction.response.defer(ephemeral=True)
        data = await transcript_bytes(channel, ticket, cfg)
        await interaction.followup.send(
            file=discord.File(io.BytesIO(data), filename=f"{cfg['brand_name']}-ticket-{self.ticket_id:04d}.html"),
            ephemeral=True,
        )

    async def delete(self, interaction):
        await safe_ephemeral(
            interaction,
            "This permanently deletes the Discord ticket channel. The database record remains marked deleted for auditing.",
            view=DeleteConfirm(self.ticket_id, interaction.user.id),
        )


# -----------------------------
# Main slash-command Cog
# -----------------------------

class TicketCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---- Admin / setup ----

    @app_commands.command(name="setup", description="Configure the ticket system.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup(
        self,
        interaction: discord.Interaction,
        staff_role: discord.Role,
        staff_queue: discord.TextChannel,
        open_category: discord.CategoryChannel,
        archive_category: discord.CategoryChannel | None = None,
        log_channel: discord.TextChannel | None = None,
        max_open_per_user: app_commands.Range[int, 1, 10] = 2,
    ):
        await db.update_config(
            interaction.guild_id,
            staff_role_id=staff_role.id,
            staff_queue_channel_id=staff_queue.id,
            ticket_category_id=open_category.id,
            archive_category_id=archive_category.id if archive_category else None,
            log_channel_id=log_channel.id if log_channel else None,
            max_open_per_user=int(max_open_per_user),
            brand_name=DEFAULT_BRAND,
            footer_text=DEFAULT_BRAND,
        )
        cfg = await db.config(interaction.guild_id)
        e = make_embed(cfg, decor(cfg, "🥐", "Ticket system configured"), separator(cfg, "Setup complete"))
        e.add_field(name="Staff role", value=staff_role.mention, inline=False)
        e.add_field(name="Staff queue", value=staff_queue.mention, inline=False)
        e.add_field(name="Open category", value=open_category.name, inline=False)
        e.add_field(name="Archive", value=archive_category.name if archive_category else "Not set", inline=False)
        e.add_field(name="Logs", value=log_channel.mention if log_channel else "Not set", inline=False)
        e.add_field(name="Privacy model", value="Staff cannot see ticket channels until individually claimed.", inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="settings", description="View the current ticket configuration.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def settings(self, interaction: discord.Interaction):
        cfg = await db.config(interaction.guild_id)
        e = make_embed(cfg, decor(cfg, "☕", "Current settings"), separator(cfg, "Configuration overview"), color=cfg["accent_color"])
        fields = [
            ("Brand", cfg["brand_name"]),
            ("Staff role", f"<@&{cfg['staff_role_id']}>" if cfg["staff_role_id"] else "Not set"),
            ("Staff queue", f"<#{cfg['staff_queue_channel_id']}>" if cfg["staff_queue_channel_id"] else "Not set"),
            ("Open category", f"<#{cfg['ticket_category_id']}>" if cfg["ticket_category_id"] else "Not set"),
            ("Archive category", f"<#{cfg['archive_category_id']}>" if cfg["archive_category_id"] else "Not set"),
            ("Log channel", f"<#{cfg['log_channel_id']}>" if cfg["log_channel_id"] else "Not set"),
            ("Max open / user", str(cfg["max_open_per_user"])),
            ("Accessibility mode", bool_word(bool(cfg["accessibility_mode"]))),
            ("Decorative emoji", bool_word(bool(cfg["decorative_emojis"]))),
            ("Separator styling", bool_word(bool(cfg["use_separator"]))),
            ("Close DMs", bool_word(bool(cfg["dm_on_close"]))),
            ("Close transcripts", bool_word(bool(cfg["transcript_on_close"]))),
        ]
        for n, v in fields:
            e.add_field(name=n, value=v, inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="appearance", description="Customize brand text, colors, footer, and ticket naming.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def appearance(
        self,
        interaction: discord.Interaction,
        brand_name: str | None = None,
        primary_color: str | None = None,
        accent_color: str | None = None,
        closed_color: str | None = None,
        footer: str | None = None,
        dropdown_placeholder: str | None = None,
        ticket_name_format: str | None = None,
    ):
        changes = {}
        try:
            if primary_color is not None:
                changes["primary_color"] = parse_hex_color(primary_color)
            if accent_color is not None:
                changes["accent_color"] = parse_hex_color(accent_color)
            if closed_color is not None:
                changes["closed_color"] = parse_hex_color(closed_color)
        except ValueError as exc:
            return await safe_ephemeral(interaction, str(exc))
        if brand_name is not None:
            changes["brand_name"] = brand_name.strip()[:80]
        if footer is not None:
            changes["footer_text"] = footer.strip()[:200]
        if dropdown_placeholder is not None:
            changes["panel_placeholder"] = dropdown_placeholder.strip()[:150]
        if ticket_name_format is not None:
            allowed_tokens = {"{type}", "{id}", "{user}", "{username}"}
            # Allow any combination of supported tokens plus literal text.
            changes["ticket_name_format"] = ticket_name_format.strip()[:100]
        if not changes:
            return await safe_ephemeral(interaction, "Provide at least one appearance setting to change.")
        await db.update_config(interaction.guild_id, **changes)
        cfg = await db.config(interaction.guild_id)
        e = make_embed(cfg, decor(cfg, "🧁", "Appearance updated"), separator(cfg, "Customization saved"))
        e.add_field(name="Primary", value=color_hex(cfg["primary_color"]), inline=True)
        e.add_field(name="Accent", value=color_hex(cfg["accent_color"]), inline=True)
        e.add_field(name="Closed", value=color_hex(cfg["closed_color"]), inline=True)
        e.add_field(name="Footer", value=cfg["footer_text"], inline=False)
        e.add_field(name="Channel format", value=f"`{cfg['ticket_name_format']}`", inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="accessibility", description="Configure accessibility and reduced-decoration options.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def accessibility(
        self,
        interaction: discord.Interaction,
        accessibility_mode: bool | None = None,
        decorative_emojis: bool | None = None,
        separator_styling: bool | None = None,
    ):
        changes = {}
        if accessibility_mode is not None:
            changes["accessibility_mode"] = int(accessibility_mode)
        if decorative_emojis is not None:
            changes["decorative_emojis"] = int(decorative_emojis)
        if separator_styling is not None:
            changes["use_separator"] = int(separator_styling)
        if not changes:
            return await safe_ephemeral(interaction, "Choose at least one accessibility setting.")
        await db.update_config(interaction.guild_id, **changes)
        cfg = await db.config(interaction.guild_id)
        e = make_embed(
            cfg,
            "Accessibility settings updated",
            "Core actions always use readable text labels. Color and emoji are never the only indicators of state.",
            color=cfg["accent_color"],
        )
        e.add_field(name="Accessibility mode", value=bool_word(bool(cfg["accessibility_mode"])), inline=True)
        e.add_field(name="Decorative emoji", value=bool_word(bool(cfg["decorative_emojis"])), inline=True)
        e.add_field(name="Decorative separators", value=bool_word(bool(cfg["use_separator"])), inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="automation", description="Configure ticket notifications, DMs, transcripts, and archiving.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def automation(
        self,
        interaction: discord.Interaction,
        dm_on_close: bool | None = None,
        transcript_on_close: bool | None = None,
        ping_staff_on_create: bool | None = None,
        ping_staff_on_unclaim: bool | None = None,
        allow_user_close: bool | None = None,
        auto_archive: bool | None = None,
    ):
        mapping = {
            "dm_on_close": dm_on_close,
            "transcript_on_close": transcript_on_close,
            "ping_staff_on_create": ping_staff_on_create,
            "ping_staff_on_unclaim": ping_staff_on_unclaim,
            "allow_user_close": allow_user_close,
            "auto_archive": auto_archive,
        }
        changes = {k: int(v) for k, v in mapping.items() if v is not None}
        if not changes:
            return await safe_ephemeral(interaction, "Choose at least one automation setting.")
        await db.update_config(interaction.guild_id, **changes)
        cfg = await db.config(interaction.guild_id)
        e = make_embed(cfg, "Automation settings updated", "Your workflow preferences were saved.")
        for key, label in [
            ("dm_on_close", "DM customer on close"),
            ("transcript_on_close", "Transcript on close"),
            ("ping_staff_on_create", "Ping on creation"),
            ("ping_staff_on_unclaim", "Ping on unclaim"),
            ("allow_user_close", "Customers may close"),
            ("auto_archive", "Move closed tickets to archive"),
        ]:
            e.add_field(name=label, value=bool_word(bool(cfg[key])), inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ---- Category management ----

    @app_commands.command(name="category-add", description="Create a customizable ticket category.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def category_add(
        self,
        interaction: discord.Interaction,
        name: str,
        description: str,
        emoji: str = "🥐",
        color: str | None = None,
        staff_role: discord.Role | None = None,
        open_category: discord.CategoryChannel | None = None,
        archive_category: discord.CategoryChannel | None = None,
        welcome_text: str | None = None,
    ):
        if not 1 <= len(name.strip()) <= 80:
            return await safe_ephemeral(interaction, "Category names must be 1–80 characters.")
        if not 1 <= len(description.strip()) <= 100:
            return await safe_ephemeral(interaction, "Descriptions must be 1–100 characters.")
        try:
            color_int = parse_hex_color(color)
        except ValueError as exc:
            return await safe_ephemeral(interaction, str(exc))
        try:
            type_id = await db.add_type(
                interaction.guild_id, name.strip(), emoji.strip() or "🥐",
                description.strip(), slugify(name), color_int,
                staff_role.id if staff_role else None,
                open_category.id if open_category else None,
                archive_category.id if archive_category else None,
                welcome_text.strip()[:1000] if welcome_text else None,
            )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                return await safe_ephemeral(interaction, "A ticket category with that name already exists.")
            raise
        cfg = await db.config(interaction.guild_id)
        e = make_embed(cfg, "Ticket category created", f"**ID:** `{type_id}`\n**Name:** {emoji} {name}")
        e.add_field(name="Description", value=description[:1024], inline=False)
        if color_int:
            e.add_field(name="Color", value=color_hex(color_int), inline=True)
        if staff_role:
            e.add_field(name="Dedicated staff role", value=staff_role.mention, inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="category-edit", description="Edit a ticket category.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.autocomplete(type_id=ticket_type_choices)
    async def category_edit(
        self,
        interaction: discord.Interaction,
        type_id: int,
        name: str | None = None,
        description: str | None = None,
        emoji: str | None = None,
        color: str | None = None,
        staff_role: discord.Role | None = None,
        open_category: discord.CategoryChannel | None = None,
        archive_category: discord.CategoryChannel | None = None,
        welcome_text: str | None = None,
        enabled: bool | None = None,
    ):
        row = await db.type_by_id(interaction.guild_id, type_id)
        if not row:
            return await safe_ephemeral(interaction, "Ticket category not found.")
        changes = {}
        if name is not None:
            changes["name"] = name.strip()[:80]
            changes["slug"] = slugify(name)
        if description is not None:
            changes["description"] = description.strip()[:100]
        if emoji is not None:
            changes["emoji"] = emoji.strip()[:100]
        if color is not None:
            try:
                changes["color"] = parse_hex_color(color)
            except ValueError as exc:
                return await safe_ephemeral(interaction, str(exc))
        if staff_role is not None:
            changes["staff_role_id"] = staff_role.id
        if open_category is not None:
            changes["category_id"] = open_category.id
        if archive_category is not None:
            changes["archive_category_id"] = archive_category.id
        if welcome_text is not None:
            changes["welcome_text"] = welcome_text.strip()[:1000]
        if enabled is not None:
            changes["enabled"] = int(enabled)
        if not changes:
            return await safe_ephemeral(interaction, "Provide at least one field to change.")
        await db.edit_type(interaction.guild_id, type_id, **changes)
        cfg = await db.config(interaction.guild_id)
        fresh = await db.type_by_id(interaction.guild_id, type_id)
        await interaction.response.send_message(
            embed=make_embed(
                cfg, "Ticket category updated",
                f"`{type_id}` • {fresh['emoji']} **{fresh['name']}**\n{fresh['description']}"
            ),
            ephemeral=True,
        )

    @app_commands.command(name="category-remove", description="Disable a ticket category without deleting its history.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.autocomplete(type_id=ticket_type_choices)
    async def category_remove(self, interaction: discord.Interaction, type_id: int):
        changed = await db.edit_type(interaction.guild_id, type_id, enabled=0)
        await safe_ephemeral(interaction, "Ticket category disabled." if changed else "Ticket category not found.")

    @app_commands.command(name="category-list", description="List all ticket categories and IDs.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def category_list(self, interaction: discord.Interaction):
        cfg = await db.config(interaction.guild_id)
        rows = await db.types(interaction.guild_id, enabled_only=False)
        if not rows:
            return await safe_ephemeral(interaction, "No ticket categories exist yet.")
        lines = []
        for r in rows:
            status = "Enabled" if r["enabled"] else "Disabled"
            lines.append(f"`{r['id']}` {r['emoji']} **{r['name']}** — {r['description']} • {status}")
        e = make_embed(cfg, "Ticket categories", "\n".join(lines)[:4000])
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="form-customize", description="Customize the two questions shown when a ticket opens.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.autocomplete(type_id=ticket_type_choices)
    async def form_customize(
        self,
        interaction: discord.Interaction,
        type_id: int,
        subject_label: str | None = None,
        details_label: str | None = None,
    ):
        row = await db.type_by_id(interaction.guild_id, type_id)
        if not row:
            return await safe_ephemeral(interaction, "Ticket category not found.")
        changes = {}
        if subject_label is not None:
            if not 1 <= len(subject_label.strip()) <= 45:
                return await safe_ephemeral(interaction, "The subject label must be 1–45 characters.")
            changes["form_label_subject"] = subject_label.strip()
        if details_label is not None:
            if not 1 <= len(details_label.strip()) <= 45:
                return await safe_ephemeral(interaction, "The details label must be 1–45 characters.")
            changes["form_label_details"] = details_label.strip()
        if not changes:
            return await safe_ephemeral(interaction, "Provide at least one form label to change.")
        await db.edit_type(interaction.guild_id, type_id, **changes)
        cfg = await db.config(interaction.guild_id)
        fresh = await db.type_by_id(interaction.guild_id, type_id)
        e = make_embed(
            cfg,
            "Ticket form updated",
            f"**{fresh['name']}** now uses these accessible field labels:"
        )
        e.add_field(name="Short-answer field", value=fresh["form_label_subject"], inline=False)
        e.add_field(name="Long-answer field", value=fresh["form_label_details"], inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="category-inherit", description="Reset category routing/colors so it inherits the server defaults.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.autocomplete(type_id=ticket_type_choices)
    async def category_inherit(
        self,
        interaction: discord.Interaction,
        type_id: int,
        reset_staff_role: bool = True,
        reset_open_category: bool = True,
        reset_archive_category: bool = True,
        reset_color: bool = False,
    ):
        row = await db.type_by_id(interaction.guild_id, type_id)
        if not row:
            return await safe_ephemeral(interaction, "Ticket category not found.")
        changes = {}
        if reset_staff_role:
            changes["staff_role_id"] = None
        if reset_open_category:
            changes["category_id"] = None
        if reset_archive_category:
            changes["archive_category_id"] = None
        if reset_color:
            changes["color"] = None
        await db.edit_type(interaction.guild_id, type_id, **changes)
        await safe_ephemeral(interaction, "Selected category overrides were reset to server defaults.")

    # ---- Panels ----

    async def _render_panel(self, interaction, panel_row):
        cfg = await db.config(interaction.guild_id)
        rows = []
        for raw in panel_row["type_ids"].split(","):
            if not raw.strip():
                continue
            row = await db.type_by_id(interaction.guild_id, int(raw))
            if row and row["enabled"]:
                rows.append(row)
        if not rows:
            raise ValueError("This panel has no enabled ticket categories.")
        color = panel_row["color"] or cfg["primary_color"]
        e = make_embed(
            cfg,
            panel_row["title"],
            f"{panel_row['description']}\n\n{separator(cfg, 'Choose an option from the menu below')}",
            color=color,
        )
        preview = "\n".join(
            f"{r['emoji']} **{r['name']}** — {r['description']}"
            if cfg["decorative_emojis"]
            else f"**{r['name']}** — {r['description']}"
            for r in rows
        )
        e.add_field(name="Available ticket types", value=preview[:1024], inline=False)
        if panel_row["image_url"]:
            e.set_image(url=panel_row["image_url"])
        if panel_row["thumbnail_url"]:
            e.set_thumbnail(url=panel_row["thumbnail_url"])
        return e, PanelView(panel_row["id"], rows, cfg, panel_row["placeholder"])

    @app_commands.command(name="panel-create", description="Create a modern multi-category dropdown panel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def panel_create(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        category_ids: str,
        title: str = "🧁 cinnxmn help counter",
        description: str = "Choose what you need help with and we’ll get the right ticket started.",
        color: str | None = None,
        image_url: str | None = None,
        thumbnail_url: str | None = None,
        placeholder: str | None = None,
    ):
        try:
            ids = list(dict.fromkeys(int(x.strip()) for x in category_ids.split(",") if x.strip()))
        except ValueError:
            return await safe_ephemeral(interaction, "Category IDs must be comma-separated numbers, such as `1,2,4`.")
        if not 1 <= len(ids) <= 25:
            return await safe_ephemeral(interaction, "Panels must contain between 1 and 25 ticket categories.")
        valid = []
        for type_id in ids:
            row = await db.type_by_id(interaction.guild_id, type_id)
            if row and row["enabled"]:
                valid.append(type_id)
        if len(valid) != len(ids):
            return await safe_ephemeral(interaction, "One or more category IDs are invalid or disabled.")
        try:
            color_int = parse_hex_color(color)
        except ValueError as exc:
            return await safe_ephemeral(interaction, str(exc))

        panel_id = await db.create_panel(
            interaction.guild_id, channel.id, title[:256], description[:3500],
            valid, interaction.user.id, image_url, thumbnail_url, color_int, placeholder
        )
        panel = await db.panel(interaction.guild_id, panel_id)
        e, view = await self._render_panel(interaction, panel)
        msg = await channel.send(embed=e, view=view)
        await db.edit_panel(interaction.guild_id, panel_id, message_id=msg.id)
        self.bot.add_view(view, message_id=msg.id)
        await safe_ephemeral(interaction, f"Panel #{panel_id} created in {channel.mention}.")

    @app_commands.command(name="panel-edit", description="Edit an existing ticket panel and refresh its message.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.autocomplete(panel_id=panel_choices)
    async def panel_edit(
        self,
        interaction: discord.Interaction,
        panel_id: int,
        title: str | None = None,
        description: str | None = None,
        category_ids: str | None = None,
        color: str | None = None,
        image_url: str | None = None,
        thumbnail_url: str | None = None,
        placeholder: str | None = None,
    ):
        panel = await db.panel(interaction.guild_id, panel_id)
        if not panel:
            return await safe_ephemeral(interaction, "Panel not found.")
        changes = {}
        if title is not None:
            changes["title"] = title[:256]
        if description is not None:
            changes["description"] = description[:3500]
        if category_ids is not None:
            try:
                ids = list(dict.fromkeys(int(x.strip()) for x in category_ids.split(",") if x.strip()))
            except ValueError:
                return await safe_ephemeral(interaction, "Category IDs must be comma-separated numbers.")
            if not 1 <= len(ids) <= 25:
                return await safe_ephemeral(interaction, "Panels must contain 1–25 categories.")
            for tid in ids:
                if not await db.type_by_id(interaction.guild_id, tid):
                    return await safe_ephemeral(interaction, f"Category ID `{tid}` does not exist.")
            changes["type_ids"] = ids
        if color is not None:
            try:
                changes["color"] = parse_hex_color(color)
            except ValueError as exc:
                return await safe_ephemeral(interaction, str(exc))
        if image_url is not None:
            changes["image_url"] = image_url or None
        if thumbnail_url is not None:
            changes["thumbnail_url"] = thumbnail_url or None
        if placeholder is not None:
            changes["placeholder"] = placeholder[:150]
        if not changes:
            return await safe_ephemeral(interaction, "Provide at least one panel setting to change.")

        await db.edit_panel(interaction.guild_id, panel_id, **changes)
        fresh = await db.panel(interaction.guild_id, panel_id)
        e, view = await self._render_panel(interaction, fresh)
        channel = interaction.guild.get_channel(fresh["channel_id"])
        if isinstance(channel, discord.TextChannel) and fresh["message_id"]:
            try:
                msg = await channel.fetch_message(fresh["message_id"])
                await msg.edit(embed=e, view=view)
                self.bot.add_view(view, message_id=fresh["message_id"])
            except discord.HTTPException:
                pass
        await safe_ephemeral(interaction, f"Panel #{panel_id} updated.")

    @app_commands.command(name="panel-preview", description="Preview a panel privately without posting it.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.autocomplete(panel_id=panel_choices)
    async def panel_preview(self, interaction: discord.Interaction, panel_id: int):
        panel = await db.panel(interaction.guild_id, panel_id)
        if not panel:
            return await safe_ephemeral(interaction, "Panel not found.")
        try:
            e, view = await self._render_panel(interaction, panel)
        except ValueError as exc:
            return await safe_ephemeral(interaction, str(exc))
        await interaction.response.send_message(embed=e, view=view, ephemeral=True)

    @app_commands.command(name="panel-list", description="List configured ticket panels.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def panel_list(self, interaction: discord.Interaction):
        cfg = await db.config(interaction.guild_id)
        rows = await db.panels(interaction.guild_id)
        if not rows:
            return await safe_ephemeral(interaction, "No panels are configured.")
        lines = [
            f"`#{r['id']}` **{r['title']}** • <#{r['channel_id']}> • {'Enabled' if r['enabled'] else 'Disabled'}"
            for r in rows
        ]
        await interaction.response.send_message(
            embed=make_embed(cfg, "Ticket panels", "\n".join(lines)[:4000]),
            ephemeral=True,
        )

    @app_commands.command(name="panel-delete", description="Disable a panel and remove its Discord message.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.autocomplete(panel_id=panel_choices)
    async def panel_delete(self, interaction: discord.Interaction, panel_id: int):
        panel = await db.panel(interaction.guild_id, panel_id)
        if not panel:
            return await safe_ephemeral(interaction, "Panel not found.")
        channel = interaction.guild.get_channel(panel["channel_id"])
        if isinstance(channel, discord.TextChannel) and panel["message_id"]:
            try:
                msg = await channel.fetch_message(panel["message_id"])
                await msg.delete()
            except discord.HTTPException:
                pass
        await db.edit_panel(interaction.guild_id, panel_id, enabled=0)
        await safe_ephemeral(interaction, f"Panel #{panel_id} disabled and its message removed.")

    # ---- User / staff ticket commands ----

    @app_commands.command(name="my-tickets", description="See your currently open tickets.")
    async def my_tickets(self, interaction: discord.Interaction):
        cfg = await db.config(interaction.guild_id)
        rows = await db.open_tickets_for_user(interaction.guild_id, interaction.user.id)
        if not rows:
            return await safe_ephemeral(interaction, "You do not have any open tickets.")
        lines = [
            f"**#{r['id']:04d}** • {r['type_emoji']} {r['type_name']} • <#{r['channel_id']}>"
            for r in rows
        ]
        await interaction.response.send_message(
            embed=make_embed(cfg, "Your open tickets", "\n".join(lines)),
            ephemeral=True,
        )

    @app_commands.command(name="info", description="Show details about the current ticket.")
    async def info(self, interaction: discord.Interaction):
        ticket, cfg = await require_ticket(interaction)
        if ticket:
            await interaction.response.send_message(embed=await ticket_embed(ticket, cfg), ephemeral=True)

    @app_commands.command(name="claim", description="Claim the current ticket.")
    async def claim(self, interaction: discord.Interaction):
        ticket, _ = await require_ticket(interaction)
        if ticket:
            await do_claim(interaction, ticket["id"])

    @app_commands.command(name="unclaim", description="Return the current ticket to the staff queue.")
    async def unclaim(self, interaction: discord.Interaction):
        ticket, _ = await require_ticket(interaction)
        if ticket:
            await do_unclaim(interaction, ticket["id"])

    @app_commands.command(name="transfer", description="Transfer the current ticket to another staff member.")
    async def transfer(self, interaction: discord.Interaction, staff_member: discord.Member):
        ticket, _ = await require_ticket(interaction)
        if ticket:
            await do_transfer(interaction, ticket["id"], staff_member)

    @app_commands.command(name="close", description="Close the current ticket with a reason.")
    async def close(self, interaction: discord.Interaction):
        ticket, _ = await require_ticket(interaction)
        if ticket:
            await interaction.response.send_modal(CloseModal(ticket["id"]))

    @app_commands.command(name="reopen", description="Reopen the current closed ticket.")
    async def reopen(self, interaction: discord.Interaction):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        if ticket["status"] != "closed":
            return await safe_ephemeral(interaction, "This ticket is already open.")
        # Re-use the persistent control implementation.
        view = ClosedControls(ticket["id"])
        await view.reopen(interaction)

    @app_commands.command(name="delete", description="Permanently delete the current closed ticket channel.")
    async def delete(self, interaction: discord.Interaction):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        if ticket["status"] != "closed":
            return await safe_ephemeral(interaction, "Close the ticket before deleting it.")
        await safe_ephemeral(
            interaction,
            "This permanently deletes the Discord channel. Continue?",
            view=DeleteConfirm(ticket["id"], interaction.user.id),
        )

    @app_commands.command(name="transcript", description="Export the current ticket conversation as HTML.")
    async def transcript(self, interaction: discord.Interaction):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member):
            return
        if interaction.user.id != ticket["opener_id"] and not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "You do not have permission to export this transcript.")
        await interaction.response.defer(ephemeral=True)
        data = await transcript_bytes(interaction.channel, ticket, cfg)
        await interaction.followup.send(
            file=discord.File(io.BytesIO(data), filename=f"{cfg['brand_name']}-ticket-{ticket['id']:04d}.html"),
            ephemeral=True,
        )

    @app_commands.command(name="add-user", description="Give another member access to the current ticket.")
    async def add_user(self, interaction: discord.Interaction, member: discord.Member):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        await interaction.channel.set_permissions(
            member, view_channel=True, send_messages=True,
            read_message_history=True, attach_files=True
        )
        await db.add_member(ticket["id"], member.id, interaction.user.id)
        await db.audit(interaction.guild_id, "user_added", ticket["id"], interaction.user.id, str(member.id))
        await safe_ephemeral(interaction, f"{member.mention} can now access this ticket.")

    @app_commands.command(name="remove-user", description="Remove an added member from the current ticket.")
    async def remove_user(self, interaction: discord.Interaction, member: discord.Member):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        if member.id == ticket["opener_id"]:
            return await safe_ephemeral(interaction, "The ticket opener cannot be removed this way.")
        if member.id == ticket["claimed_by"]:
            return await safe_ephemeral(interaction, "Use /transfer or /unclaim for the assigned staff member.")
        await interaction.channel.set_permissions(member, overwrite=None)
        await db.remove_member(ticket["id"], member.id)
        await db.audit(interaction.guild_id, "user_removed", ticket["id"], interaction.user.id, str(member.id))
        await safe_ephemeral(interaction, f"{member.mention} was removed from this ticket.")

    @app_commands.command(name="rename", description="Rename the current ticket channel.")
    async def rename(self, interaction: discord.Interaction, name: str):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        new_name = f"{ticket['id']:04d}-{slugify(name)}"[:100]
        await interaction.channel.edit(name=new_name, reason=f"Ticket renamed by {interaction.user}")
        await db.audit(interaction.guild_id, "renamed", ticket["id"], interaction.user.id, new_name)
        await safe_ephemeral(interaction, f"Ticket renamed to `{new_name}`.")

    @app_commands.command(name="priority", description="Set the priority of the current ticket.")
    @app_commands.choices(level=[
        app_commands.Choice(name="Low", value="low"),
        app_commands.Choice(name="Normal", value="normal"),
        app_commands.Choice(name="High", value="high"),
        app_commands.Choice(name="Urgent", value="urgent"),
    ])
    async def priority(self, interaction: discord.Interaction, level: app_commands.Choice[str]):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        await db.set_priority(ticket["id"], level.value)
        await db.audit(interaction.guild_id, "priority_changed", ticket["id"], interaction.user.id, level.value)
        await refresh_ticket(interaction.guild, ticket["id"])
        await safe_ephemeral(interaction, f"Priority set to **{level.name}**.")

    @app_commands.command(name="note", description="Add a private internal note to the ticket record.")
    async def note(self, interaction: discord.Interaction, note: str):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        await db.add_note(ticket["id"], interaction.user.id, note[:1500])
        await db.audit(interaction.guild_id, "note_added", ticket["id"], interaction.user.id, note[:250])
        await safe_ephemeral(interaction, "Private staff note saved. It is not posted in the ticket channel.")

    @app_commands.command(name="notes", description="View private internal notes for this ticket.")
    async def notes(self, interaction: discord.Interaction):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        rows = await db.notes(ticket["id"])
        if not rows:
            return await safe_ephemeral(interaction, "No internal notes have been added.")
        text = "\n\n".join(
            f"**Note #{r['id']}** • <@{r['author_id']}> • {r['created_at']}\n{r['note']}"
            for r in rows
        )
        await interaction.response.send_message(
            embed=make_embed(cfg, "Internal ticket notes", text[:4000], color=cfg["accent_color"]),
            ephemeral=True,
        )

    @app_commands.command(name="lock", description="Prevent the customer from sending messages in this ticket.")
    async def lock(self, interaction: discord.Interaction):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        opener = interaction.guild.get_member(ticket["opener_id"])
        if opener:
            await interaction.channel.set_permissions(
                opener, view_channel=True, send_messages=False, read_message_history=True
            )
        await db.set_locked(ticket["id"], True)
        await db.audit(interaction.guild_id, "locked", ticket["id"], interaction.user.id)
        await refresh_ticket(interaction.guild, ticket["id"])
        await safe_ephemeral(interaction, "Customer replies are now locked.")

    @app_commands.command(name="unlock", description="Allow the customer to send messages again.")
    async def unlock(self, interaction: discord.Interaction):
        ticket, cfg = await require_ticket(interaction)
        if not ticket:
            return
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, cfg, ticket):
            return await safe_ephemeral(interaction, "Staff only.")
        opener = interaction.guild.get_member(ticket["opener_id"])
        if opener:
            await interaction.channel.set_permissions(
                opener, view_channel=True, send_messages=True,
                read_message_history=True, attach_files=True
            )
        await db.set_locked(ticket["id"], False)
        await db.audit(interaction.guild_id, "unlocked", ticket["id"], interaction.user.id)
        await refresh_ticket(interaction.guild, ticket["id"])
        await safe_ephemeral(interaction, "Customer replies are unlocked.")

    # ---- Moderation / analytics ----

    @app_commands.command(name="blacklist", description="Prevent a member from opening tickets.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def blacklist(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        await db.block_user(interaction.guild_id, member.id, reason[:1000], interaction.user.id)
        await safe_ephemeral(interaction, f"{member.mention} can no longer open tickets.\n**Reason:** {reason}")

    @app_commands.command(name="unblacklist", description="Allow a member to open tickets again.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def unblacklist(self, interaction: discord.Interaction, member: discord.Member):
        changed = await db.unblock_user(interaction.guild_id, member.id)
        await safe_ephemeral(interaction, f"{member.mention} was removed from the blacklist." if changed else "That member was not blacklisted.")

    @app_commands.command(name="blacklist-list", description="List members blocked from opening tickets.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def blacklist_list(self, interaction: discord.Interaction):
        cfg = await db.config(interaction.guild_id)
        rows = await db.blocked_list(interaction.guild_id)
        if not rows:
            return await safe_ephemeral(interaction, "The ticket blacklist is empty.")
        text = "\n".join(
            f"<@{r['user_id']}> — {r['reason'] or 'No reason provided'}"
            for r in rows
        )
        await interaction.response.send_message(
            embed=make_embed(cfg, "Ticket blacklist", text[:4000]),
            ephemeral=True,
        )

    @app_commands.command(name="stats", description="View ticket-system statistics.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def stats(self, interaction: discord.Interaction):
        cfg = await db.config(interaction.guild_id)
        s = await db.stats(interaction.guild_id)
        e = make_embed(cfg, "Ticket statistics", separator(cfg, "Current ticket activity"), color=cfg["accent_color"])
        e.add_field(name="All tickets", value=str(s["total"]), inline=True)
        e.add_field(name="Open", value=str(s["open"]), inline=True)
        e.add_field(name="Claimed open", value=str(s["claimed"]), inline=True)
        e.add_field(name="Closed", value=str(s["closed"]), inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="export-config", description="Export the ticket setup as a JSON backup.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def export_config(self, interaction: discord.Interaction):
        payload = await db.export_config(interaction.guild_id)
        data = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        await interaction.response.send_message(
            "Configuration backup:",
            file=discord.File(io.BytesIO(data), filename=f"{DEFAULT_BRAND}-ticket-config.json"),
            ephemeral=True,
        )

    @app_commands.command(name="dm-test", description="Send yourself a test DM to verify bot DM delivery.")
    async def dm_test(self, interaction: discord.Interaction):
        cfg = await db.config(interaction.guild_id)
        e = make_embed(
            cfg,
            decor(cfg, "🍪", f"{cfg['brand_name']} DM test"),
            f"{separator(cfg, 'DM delivery test')}\n\n"
            "If you can read this, direct messages from the ticket bot are working.",
            color=cfg["primary_color"],
        )
        try:
            await interaction.user.send(embed=e)
            await safe_ephemeral(interaction, "Test DM sent successfully.")
        except discord.Forbidden:
            await safe_ephemeral(
                interaction,
                "Discord rejected the DM. Check server privacy settings and whether the bot is blocked."
            )
        except discord.HTTPException as exc:
            log.warning("DM test failed for user %s: %s", interaction.user.id, exc)
            await safe_ephemeral(interaction, f"Discord returned an error while sending the DM: `{exc}`")

    @app_commands.command(name="help", description="Show the ticket bot command guide.")
    async def help_cmd(self, interaction: discord.Interaction):
        cfg = await db.config(interaction.guild_id)
        e = make_embed(
            cfg,
            decor(cfg, "🥐", f"{cfg['brand_name']} ticket help"),
            "Commands are grouped below by purpose. Buttons also include readable text labels for accessibility.",
        )
        e.add_field(
            name="Customer",
            value="`/my-tickets` • `/info` • `/transcript` • `/close` • `/dm-test`",
            inline=False,
        )
        e.add_field(
            name="Staff workflow",
            value="`/claim` • `/unclaim` • `/transfer` • `/priority` • `/note` • `/notes` • `/lock` • `/unlock` • `/rename` • `/add-user` • `/remove-user` • `/reopen` • `/delete`",
            inline=False,
        )
        e.add_field(
            name="Configuration",
            value="`/setup` • `/settings` • `/appearance` • `/accessibility` • `/automation` • `/category-add` • `/category-edit` • `/category-remove` • `/category-list` • `/category-inherit` • `/form-customize` • `/panel-create` • `/panel-edit` • `/panel-preview` • `/panel-list` • `/panel-delete`",
            inline=False,
        )
        e.add_field(
            name="Management",
            value="`/blacklist` • `/unblacklist` • `/blacklist-list` • `/stats` • `/export-config`",
            inline=False,
        )
        await interaction.response.send_message(embed=e, ephemeral=True)


class CinnxmnBot(commands.Bot):
    async def setup_hook(self):
        await db.init()
        await self.add_cog(TicketCog(self))

        # Restore persistent panels.
        for panel in await db.panels():
            cfg = await db.config(panel["guild_id"])
            rows = []
            for raw in panel["type_ids"].split(","):
                try:
                    tid = int(raw)
                except ValueError:
                    continue
                row = await db.type_by_id(panel["guild_id"], tid)
                if row and row["enabled"]:
                    rows.append(row)
            if rows and panel["message_id"]:
                self.add_view(PanelView(panel["id"], rows, cfg, panel["placeholder"]), message_id=panel["message_id"])

        # Restore persistent ticket buttons.
        for ticket in await db.persistent_tickets():
            if ticket["status"] == "open":
                if ticket["control_message_id"]:
                    self.add_view(TicketControls(ticket["id"]), message_id=ticket["control_message_id"])
                if ticket["queue_message_id"]:
                    self.add_view(QueueControls(ticket["id"]), message_id=ticket["queue_message_id"])
            elif ticket["status"] == "closed" and ticket["control_message_id"]:
                self.add_view(ClosedControls(ticket["id"]), message_id=ticket["control_message_id"])

        if GUILD_ID.isdigit():
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Synced commands to guild %s", GUILD_ID)
        else:
            await self.tree.sync()
            log.info("Synced commands globally")


bot = CinnxmnBot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    log.info("Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "?")


@bot.tree.error
async def app_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "You do not have permission to use that command."
    else:
        log.exception("Application command error", exc_info=error)
        msg = f"Something went wrong: `{error}`"
    try:
        await safe_ephemeral(interaction, msg)
    except discord.HTTPException:
        pass


bot.run(TOKEN)
