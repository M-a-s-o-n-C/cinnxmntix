
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import json
import aiosqlite

DB_PATH = Path(__file__).with_name("tickets.db")


class Database:
    def __init__(self, path: Path = DB_PATH):
        self.path = path

    @asynccontextmanager
    async def connect(self):
        db = await aiosqlite.connect(self.path)
        db.row_factory = aiosqlite.Row
        try:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute("PRAGMA journal_mode = WAL")
            yield db
        finally:
            await db.close()

    async def init(self):
        async with self.connect() as db:
            await db.executescript("""
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id INTEGER PRIMARY KEY,
                staff_role_id INTEGER,
                staff_queue_channel_id INTEGER,
                ticket_category_id INTEGER,
                archive_category_id INTEGER,
                log_channel_id INTEGER,
                max_open_per_user INTEGER NOT NULL DEFAULT 2,
                brand_name TEXT NOT NULL DEFAULT 'cinnxmn',
                primary_color INTEGER NOT NULL DEFAULT 14133358,
                accent_color INTEGER NOT NULL DEFAULT 7298615,
                closed_color INTEGER NOT NULL DEFAULT 4937249,
                footer_text TEXT NOT NULL DEFAULT 'cinnxmn',
                panel_placeholder TEXT NOT NULL DEFAULT 'Choose what you need help with…',
                decorative_emojis INTEGER NOT NULL DEFAULT 1,
                accessibility_mode INTEGER NOT NULL DEFAULT 1,
                use_separator INTEGER NOT NULL DEFAULT 1,
                dm_on_close INTEGER NOT NULL DEFAULT 1,
                transcript_on_close INTEGER NOT NULL DEFAULT 1,
                ping_staff_on_create INTEGER NOT NULL DEFAULT 1,
                ping_staff_on_unclaim INTEGER NOT NULL DEFAULT 1,
                allow_user_close INTEGER NOT NULL DEFAULT 1,
                auto_archive INTEGER NOT NULL DEFAULT 1,
                ticket_name_format TEXT NOT NULL DEFAULT '{type}-{id}-{user}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS ticket_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                emoji TEXT NOT NULL DEFAULT '🥐',
                description TEXT NOT NULL,
                slug TEXT NOT NULL,
                color INTEGER,
                enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                staff_role_id INTEGER,
                category_id INTEGER,
                archive_category_id INTEGER,
                welcome_text TEXT,
                form_label_subject TEXT NOT NULL DEFAULT 'What can we help with?',
                form_label_details TEXT NOT NULL DEFAULT 'Tell us the details',
                UNIQUE(guild_id, name)
            );

            CREATE TABLE IF NOT EXISTS panels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                image_url TEXT,
                thumbnail_url TEXT,
                color INTEGER,
                placeholder TEXT,
                type_ids TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER UNIQUE,
                opener_id INTEGER NOT NULL,
                type_id INTEGER NOT NULL,
                subject TEXT NOT NULL,
                details TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                claimed_by INTEGER,
                queue_message_id INTEGER,
                control_message_id INTEGER,
                priority TEXT NOT NULL DEFAULT 'normal',
                locked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                closed_at TEXT,
                closed_by INTEGER,
                close_reason TEXT,
                FOREIGN KEY(type_id) REFERENCES ticket_types(id)
            );

            CREATE TABLE IF NOT EXISTS ticket_members (
                ticket_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                added_by INTEGER NOT NULL,
                PRIMARY KEY(ticket_id, user_id),
                FOREIGN KEY(ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ticket_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL,
                note TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS blocked_users (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                reason TEXT,
                blocked_by INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                ticket_id INTEGER,
                actor_id INTEGER,
                action TEXT NOT NULL,
                details TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """)
            # Automatic migration for v1 databases. SQLite does not add new
            # columns when CREATE TABLE IF NOT EXISTS sees an existing table.
            async def ensure_columns(table: str, columns: dict[str, str]):
                cur = await db.execute(f"PRAGMA table_info({table})")
                existing = {row[1] for row in await cur.fetchall()}
                for name, ddl in columns.items():
                    if name not in existing:
                        await db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

            await ensure_columns("guild_config", {
                "brand_name": "TEXT NOT NULL DEFAULT 'cinnxmn'",
                "primary_color": "INTEGER NOT NULL DEFAULT 14133358",
                "accent_color": "INTEGER NOT NULL DEFAULT 7298615",
                "closed_color": "INTEGER NOT NULL DEFAULT 4937249",
                "footer_text": "TEXT NOT NULL DEFAULT 'cinnxmn'",
                "panel_placeholder": "TEXT NOT NULL DEFAULT 'Choose what you need help with…'",
                "decorative_emojis": "INTEGER NOT NULL DEFAULT 1",
                "accessibility_mode": "INTEGER NOT NULL DEFAULT 1",
                "use_separator": "INTEGER NOT NULL DEFAULT 1",
                "dm_on_close": "INTEGER NOT NULL DEFAULT 1",
                "transcript_on_close": "INTEGER NOT NULL DEFAULT 1",
                "ping_staff_on_create": "INTEGER NOT NULL DEFAULT 1",
                "ping_staff_on_unclaim": "INTEGER NOT NULL DEFAULT 1",
                "allow_user_close": "INTEGER NOT NULL DEFAULT 1",
                "auto_archive": "INTEGER NOT NULL DEFAULT 1",
                "ticket_name_format": "TEXT NOT NULL DEFAULT '{type}-{id}-{user}'",
                "created_at": "TEXT",
                "updated_at": "TEXT",
            })

            await ensure_columns("ticket_types", {
                "color": "INTEGER",
                "sort_order": "INTEGER NOT NULL DEFAULT 0",
                "staff_role_id": "INTEGER",
                "category_id": "INTEGER",
                "archive_category_id": "INTEGER",
                "welcome_text": "TEXT",
                "form_label_subject": "TEXT NOT NULL DEFAULT 'What can we help with?'",
                "form_label_details": "TEXT NOT NULL DEFAULT 'Tell us the details'",
            })

            await ensure_columns("panels", {
                "color": "INTEGER",
                "placeholder": "TEXT",
                "enabled": "INTEGER NOT NULL DEFAULT 1",
            })

            await ensure_columns("tickets", {
                "locked": "INTEGER NOT NULL DEFAULT 0",
            })

            await db.commit()

    async def execute(self, sql: str, params: tuple = ()) -> int:
        async with self.connect() as db:
            cur = await db.execute(sql, params)
            await db.commit()
            return cur.lastrowid

    async def rowcount(self, sql: str, params: tuple = ()) -> int:
        async with self.connect() as db:
            cur = await db.execute(sql, params)
            await db.commit()
            return cur.rowcount

    async def one(self, sql: str, params: tuple = ()):
        async with self.connect() as db:
            cur = await db.execute(sql, params)
            return await cur.fetchone()

    async def all(self, sql: str, params: tuple = ()):
        async with self.connect() as db:
            cur = await db.execute(sql, params)
            return await cur.fetchall()

    async def ensure_config(self, guild_id: int):
        await self.execute(
            "INSERT OR IGNORE INTO guild_config(guild_id) VALUES(?)",
            (guild_id,),
        )

    async def config(self, guild_id: int):
        await self.ensure_config(guild_id)
        return await self.one("SELECT * FROM guild_config WHERE guild_id=?", (guild_id,))

    async def update_config(self, guild_id: int, **fields):
        if not fields:
            return
        allowed = {
            "staff_role_id", "staff_queue_channel_id", "ticket_category_id",
            "archive_category_id", "log_channel_id", "max_open_per_user",
            "brand_name", "primary_color", "accent_color", "closed_color",
            "footer_text", "panel_placeholder", "decorative_emojis",
            "accessibility_mode", "use_separator", "dm_on_close",
            "transcript_on_close", "ping_staff_on_create",
            "ping_staff_on_unclaim", "allow_user_close", "auto_archive",
            "ticket_name_format",
        }
        clean = {k: v for k, v in fields.items() if k in allowed}
        if not clean:
            return
        await self.ensure_config(guild_id)
        sets = ", ".join(f"{k}=?" for k in clean)
        values = list(clean.values()) + [guild_id]
        await self.execute(
            f"UPDATE guild_config SET {sets}, updated_at=CURRENT_TIMESTAMP WHERE guild_id=?",
            tuple(values),
        )

    async def add_type(self, guild_id: int, name: str, emoji: str, description: str, slug: str,
                       color: int | None = None, staff_role_id: int | None = None,
                       category_id: int | None = None, archive_category_id: int | None = None,
                       welcome_text: str | None = None):
        return await self.execute("""
            INSERT INTO ticket_types(
                guild_id,name,emoji,description,slug,color,staff_role_id,
                category_id,archive_category_id,welcome_text
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """, (
            guild_id, name, emoji, description, slug, color, staff_role_id,
            category_id, archive_category_id, welcome_text
        ))

    async def edit_type(self, guild_id: int, type_id: int, **fields):
        allowed = {
            "name", "emoji", "description", "slug", "color", "enabled",
            "sort_order", "staff_role_id", "category_id", "archive_category_id",
            "welcome_text", "form_label_subject", "form_label_details"
        }
        clean = {k: v for k, v in fields.items() if k in allowed}
        if not clean:
            return 0
        sets = ", ".join(f"{k}=?" for k in clean)
        params = tuple(clean.values()) + (guild_id, type_id)
        return await self.rowcount(
            f"UPDATE ticket_types SET {sets} WHERE guild_id=? AND id=?",
            params,
        )

    async def types(self, guild_id: int, enabled_only: bool = True):
        sql = "SELECT * FROM ticket_types WHERE guild_id=?"
        if enabled_only:
            sql += " AND enabled=1"
        sql += " ORDER BY sort_order ASC, id ASC"
        return await self.all(sql, (guild_id,))

    async def type_by_id(self, guild_id: int, type_id: int):
        return await self.one(
            "SELECT * FROM ticket_types WHERE guild_id=? AND id=?",
            (guild_id, type_id),
        )

    async def create_panel(self, guild_id: int, channel_id: int, title: str,
                           description: str, type_ids: list[int], created_by: int,
                           image_url: str | None = None, thumbnail_url: str | None = None,
                           color: int | None = None, placeholder: str | None = None):
        return await self.execute("""
            INSERT INTO panels(
                guild_id,channel_id,title,description,type_ids,created_by,
                image_url,thumbnail_url,color,placeholder
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """, (
            guild_id, channel_id, title, description,
            ",".join(str(x) for x in type_ids), created_by,
            image_url, thumbnail_url, color, placeholder
        ))

    async def edit_panel(self, guild_id: int, panel_id: int, **fields):
        allowed = {
            "channel_id", "message_id", "title", "description", "type_ids",
            "image_url", "thumbnail_url", "color", "placeholder", "enabled"
        }
        clean = {}
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k == "type_ids" and isinstance(v, list):
                v = ",".join(str(x) for x in v)
            clean[k] = v
        if not clean:
            return 0
        sets = ", ".join(f"{k}=?" for k in clean)
        return await self.rowcount(
            f"UPDATE panels SET {sets} WHERE guild_id=? AND id=?",
            tuple(clean.values()) + (guild_id, panel_id),
        )

    async def panel(self, guild_id: int, panel_id: int):
        return await self.one(
            "SELECT * FROM panels WHERE guild_id=? AND id=?",
            (guild_id, panel_id),
        )

    async def panels(self, guild_id: int | None = None):
        if guild_id is None:
            return await self.all("SELECT * FROM panels WHERE enabled=1 AND message_id IS NOT NULL")
        return await self.all(
            "SELECT * FROM panels WHERE guild_id=? ORDER BY id",
            (guild_id,),
        )

    async def create_ticket(self, guild_id: int, opener_id: int, type_id: int,
                            subject: str, details: str):
        return await self.execute("""
            INSERT INTO tickets(guild_id,opener_id,type_id,subject,details)
            VALUES(?,?,?,?,?)
        """, (guild_id, opener_id, type_id, subject, details))

    async def attach_ticket_channel(self, ticket_id: int, channel_id: int):
        await self.execute(
            "UPDATE tickets SET channel_id=? WHERE id=?",
            (channel_id, ticket_id),
        )

    async def set_control_message(self, ticket_id: int, message_id: int):
        await self.execute(
            "UPDATE tickets SET control_message_id=? WHERE id=?",
            (message_id, ticket_id),
        )

    async def set_queue_message(self, ticket_id: int, message_id: int):
        await self.execute(
            "UPDATE tickets SET queue_message_id=? WHERE id=?",
            (message_id, ticket_id),
        )

    async def ticket(self, ticket_id: int):
        return await self.one("""
            SELECT t.*, tt.name type_name, tt.emoji type_emoji,
                   tt.slug type_slug, tt.description type_description,
                   tt.staff_role_id type_staff_role_id,
                   tt.category_id type_category_id,
                   tt.archive_category_id type_archive_category_id,
                   tt.color type_color, tt.welcome_text type_welcome_text
            FROM tickets t
            JOIN ticket_types tt ON tt.id=t.type_id
            WHERE t.id=?
        """, (ticket_id,))

    async def ticket_by_channel(self, channel_id: int):
        return await self.one("""
            SELECT t.*, tt.name type_name, tt.emoji type_emoji,
                   tt.slug type_slug, tt.description type_description,
                   tt.staff_role_id type_staff_role_id,
                   tt.category_id type_category_id,
                   tt.archive_category_id type_archive_category_id,
                   tt.color type_color, tt.welcome_text type_welcome_text
            FROM tickets t
            JOIN ticket_types tt ON tt.id=t.type_id
            WHERE t.channel_id=?
        """, (channel_id,))

    async def open_tickets_for_user(self, guild_id: int, user_id: int):
        return await self.all("""
            SELECT t.*, tt.name type_name, tt.emoji type_emoji
            FROM tickets t JOIN ticket_types tt ON tt.id=t.type_id
            WHERE t.guild_id=? AND t.opener_id=? AND t.status='open'
            ORDER BY t.id DESC
        """, (guild_id, user_id))

    async def persistent_tickets(self):
        return await self.all("""
            SELECT t.*, tt.name type_name, tt.emoji type_emoji, tt.slug type_slug
            FROM tickets t JOIN ticket_types tt ON tt.id=t.type_id
            WHERE t.status IN ('open','closed') AND t.channel_id IS NOT NULL
        """)

    async def claim(self, ticket_id: int, user_id: int):
        changed = await self.rowcount("""
            UPDATE tickets SET claimed_by=?
            WHERE id=? AND status='open' AND claimed_by IS NULL
        """, (user_id, ticket_id))
        return changed == 1

    async def unclaim(self, ticket_id: int, user_id: int | None = None):
        if user_id is None:
            changed = await self.rowcount(
                "UPDATE tickets SET claimed_by=NULL WHERE id=? AND claimed_by IS NOT NULL",
                (ticket_id,),
            )
        else:
            changed = await self.rowcount(
                "UPDATE tickets SET claimed_by=NULL WHERE id=? AND claimed_by=?",
                (ticket_id, user_id),
            )
        return changed == 1

    async def transfer(self, ticket_id: int, user_id: int):
        await self.execute(
            "UPDATE tickets SET claimed_by=? WHERE id=? AND status='open'",
            (user_id, ticket_id),
        )

    async def close(self, ticket_id: int, actor_id: int, reason: str):
        await self.execute("""
            UPDATE tickets SET status='closed', closed_at=CURRENT_TIMESTAMP,
            closed_by=?, close_reason=? WHERE id=?
        """, (actor_id, reason, ticket_id))

    async def reopen(self, ticket_id: int):
        await self.execute("""
            UPDATE tickets SET status='open', claimed_by=NULL, closed_at=NULL,
            closed_by=NULL, close_reason=NULL, locked=0 WHERE id=?
        """, (ticket_id,))

    async def mark_deleted(self, ticket_id: int):
        await self.execute("UPDATE tickets SET status='deleted' WHERE id=?", (ticket_id,))

    async def set_priority(self, ticket_id: int, priority: str):
        await self.execute("UPDATE tickets SET priority=? WHERE id=?", (priority, ticket_id))

    async def set_locked(self, ticket_id: int, locked: bool):
        await self.execute("UPDATE tickets SET locked=? WHERE id=?", (int(locked), ticket_id))

    async def add_member(self, ticket_id: int, user_id: int, added_by: int):
        await self.execute("""
            INSERT OR REPLACE INTO ticket_members(ticket_id,user_id,added_by)
            VALUES(?,?,?)
        """, (ticket_id, user_id, added_by))

    async def remove_member(self, ticket_id: int, user_id: int):
        await self.execute(
            "DELETE FROM ticket_members WHERE ticket_id=? AND user_id=?",
            (ticket_id, user_id),
        )

    async def members(self, ticket_id: int):
        return await self.all("SELECT * FROM ticket_members WHERE ticket_id=?", (ticket_id,))

    async def add_note(self, ticket_id: int, author_id: int, note: str):
        return await self.execute("""
            INSERT INTO ticket_notes(ticket_id,author_id,note) VALUES(?,?,?)
        """, (ticket_id, author_id, note))

    async def notes(self, ticket_id: int):
        return await self.all(
            "SELECT * FROM ticket_notes WHERE ticket_id=? ORDER BY id",
            (ticket_id,),
        )

    async def block_user(self, guild_id: int, user_id: int, reason: str, actor_id: int):
        await self.execute("""
            INSERT INTO blocked_users(guild_id,user_id,reason,blocked_by)
            VALUES(?,?,?,?)
            ON CONFLICT(guild_id,user_id) DO UPDATE SET
                reason=excluded.reason, blocked_by=excluded.blocked_by,
                created_at=CURRENT_TIMESTAMP
        """, (guild_id, user_id, reason, actor_id))

    async def unblock_user(self, guild_id: int, user_id: int):
        return await self.rowcount(
            "DELETE FROM blocked_users WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )

    async def blocked(self, guild_id: int, user_id: int):
        return await self.one(
            "SELECT * FROM blocked_users WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )

    async def blocked_list(self, guild_id: int):
        return await self.all(
            "SELECT * FROM blocked_users WHERE guild_id=? ORDER BY created_at DESC",
            (guild_id,),
        )

    async def audit(self, guild_id: int, action: str, ticket_id: int | None = None,
                    actor_id: int | None = None, details: str | None = None):
        await self.execute("""
            INSERT INTO audit_log(guild_id,ticket_id,actor_id,action,details)
            VALUES(?,?,?,?,?)
        """, (guild_id, ticket_id, actor_id, action, details))

    async def stats(self, guild_id: int):
        total = await self.one("SELECT COUNT(*) c FROM tickets WHERE guild_id=?", (guild_id,))
        open_ = await self.one("SELECT COUNT(*) c FROM tickets WHERE guild_id=? AND status='open'", (guild_id,))
        closed = await self.one("SELECT COUNT(*) c FROM tickets WHERE guild_id=? AND status='closed'", (guild_id,))
        claimed = await self.one("SELECT COUNT(*) c FROM tickets WHERE guild_id=? AND status='open' AND claimed_by IS NOT NULL", (guild_id,))
        return {
            "total": int(total["c"]) if total else 0,
            "open": int(open_["c"]) if open_ else 0,
            "closed": int(closed["c"]) if closed else 0,
            "claimed": int(claimed["c"]) if claimed else 0,
        }

    async def export_config(self, guild_id: int):
        cfg = await self.config(guild_id)
        types = await self.types(guild_id, enabled_only=False)
        panels = await self.panels(guild_id)
        def conv(row):
            return dict(row) if row else None
        return {
            "guild_config": conv(cfg),
            "ticket_types": [dict(r) for r in types],
            "panels": [dict(r) for r in panels],
        }
