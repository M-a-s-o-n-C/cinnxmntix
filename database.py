
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

            CREATE TABLE IF NOT EXISTS moderation_config (
                guild_id INTEGER PRIMARY KEY,
                moderator_role_id INTEGER,
                jail_role_id INTEGER,
                mod_log_channel_id INTEGER,
                reports_category_id INTEGER,
                appeals_category_id INTEGER,
                report_queue_channel_id INTEGER,
                appeal_queue_channel_id INTEGER,
                warning_threshold_points INTEGER NOT NULL DEFAULT 6,
                auto_jail_on_threshold INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS jail_channels (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                can_send INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY(guild_id, channel_id)
            );

            CREATE TABLE IF NOT EXISTS moderation_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                reason TEXT NOT NULL,
                points INTEGER NOT NULL DEFAULT 0,
                duration_seconds INTEGER,
                active INTEGER NOT NULL DEFAULT 1,
                related_ticket_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT,
                metadata TEXT
            );

            CREATE TABLE IF NOT EXISTS moderation_case_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL,
                note TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(case_id) REFERENCES moderation_cases(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS jail_snapshots (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role_ids TEXT NOT NULL,
                jailed_by INTEGER NOT NULL,
                reason TEXT NOT NULL,
                case_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                reporter_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                channel_id INTEGER,
                reason TEXT NOT NULL,
                details TEXT NOT NULL,
                evidence TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                claimed_by INTEGER,
                resolution TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                resolved_at TEXT
            );

            CREATE TABLE IF NOT EXISTS appeals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                case_id INTEGER,
                channel_id INTEGER,
                reason TEXT NOT NULL,
                details TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                claimed_by INTEGER,
                resolution TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                resolved_at TEXT
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


    async def ensure_mod_config(self, guild_id: int):
        await self.execute(
            "INSERT OR IGNORE INTO moderation_config(guild_id) VALUES(?)",
            (guild_id,),
        )

    async def mod_config(self, guild_id: int):
        await self.ensure_mod_config(guild_id)
        return await self.one(
            "SELECT * FROM moderation_config WHERE guild_id=?",
            (guild_id,),
        )

    async def update_mod_config(self, guild_id: int, **fields):
        allowed = {
            "moderator_role_id", "jail_role_id", "mod_log_channel_id",
            "reports_category_id", "appeals_category_id",
            "report_queue_channel_id", "appeal_queue_channel_id",
            "warning_threshold_points", "auto_jail_on_threshold",
        }
        clean = {k: v for k, v in fields.items() if k in allowed}
        if not clean:
            return
        await self.ensure_mod_config(guild_id)
        sets = ", ".join(f"{k}=?" for k in clean)
        await self.execute(
            f"UPDATE moderation_config SET {sets}, updated_at=CURRENT_TIMESTAMP WHERE guild_id=?",
            tuple(clean.values()) + (guild_id,),
        )

    async def add_jail_channel(self, guild_id: int, channel_id: int, can_send: bool = True):
        await self.execute("""
            INSERT INTO jail_channels(guild_id,channel_id,can_send)
            VALUES(?,?,?)
            ON CONFLICT(guild_id,channel_id) DO UPDATE SET can_send=excluded.can_send
        """, (guild_id, channel_id, int(can_send)))

    async def remove_jail_channel(self, guild_id: int, channel_id: int):
        return await self.rowcount(
            "DELETE FROM jail_channels WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )

    async def jail_channels(self, guild_id: int):
        return await self.all(
            "SELECT * FROM jail_channels WHERE guild_id=? ORDER BY channel_id",
            (guild_id,),
        )

    async def create_case(
        self, guild_id: int, target_id: int, moderator_id: int,
        action: str, reason: str, points: int = 0,
        duration_seconds: int | None = None, expires_at: str | None = None,
        related_ticket_id: int | None = None, metadata: str | None = None,
        active: bool = True
    ):
        return await self.execute("""
            INSERT INTO moderation_cases(
                guild_id,target_id,moderator_id,action,reason,points,
                duration_seconds,active,related_ticket_id,expires_at,metadata
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """, (
            guild_id, target_id, moderator_id, action, reason, points,
            duration_seconds, int(active), related_ticket_id, expires_at, metadata
        ))

    async def case(self, guild_id: int, case_id: int):
        return await self.one(
            "SELECT * FROM moderation_cases WHERE guild_id=? AND id=?",
            (guild_id, case_id),
        )

    async def cases_for_user(self, guild_id: int, user_id: int, limit: int = 25):
        return await self.all("""
            SELECT * FROM moderation_cases
            WHERE guild_id=? AND target_id=?
            ORDER BY id DESC LIMIT ?
        """, (guild_id, user_id, limit))

    async def active_warning_points(self, guild_id: int, user_id: int):
        row = await self.one("""
            SELECT COALESCE(SUM(points),0) p
            FROM moderation_cases
            WHERE guild_id=? AND target_id=? AND action='warning' AND active=1
        """, (guild_id, user_id))
        return int(row["p"]) if row else 0

    async def deactivate_case(self, guild_id: int, case_id: int):
        return await self.rowcount(
            "UPDATE moderation_cases SET active=0 WHERE guild_id=? AND id=?",
            (guild_id, case_id),
        )

    async def add_case_note(self, case_id: int, author_id: int, note: str):
        return await self.execute("""
            INSERT INTO moderation_case_notes(case_id,author_id,note)
            VALUES(?,?,?)
        """, (case_id, author_id, note))

    async def case_notes(self, case_id: int):
        return await self.all(
            "SELECT * FROM moderation_case_notes WHERE case_id=? ORDER BY id",
            (case_id,),
        )

    async def save_jail_snapshot(
        self, guild_id: int, user_id: int, role_ids: list[int],
        jailed_by: int, reason: str, case_id: int | None
    ):
        await self.execute("""
            INSERT INTO jail_snapshots(
                guild_id,user_id,role_ids,jailed_by,reason,case_id
            ) VALUES(?,?,?,?,?,?)
            ON CONFLICT(guild_id,user_id) DO UPDATE SET
                role_ids=excluded.role_ids,
                jailed_by=excluded.jailed_by,
                reason=excluded.reason,
                case_id=excluded.case_id,
                created_at=CURRENT_TIMESTAMP
        """, (
            guild_id, user_id, ",".join(str(x) for x in role_ids),
            jailed_by, reason, case_id
        ))

    async def jail_snapshot(self, guild_id: int, user_id: int):
        return await self.one(
            "SELECT * FROM jail_snapshots WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )

    async def delete_jail_snapshot(self, guild_id: int, user_id: int):
        await self.execute(
            "DELETE FROM jail_snapshots WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )

    async def create_report(
        self, guild_id: int, reporter_id: int, target_id: int,
        reason: str, details: str, evidence: str | None = None
    ):
        return await self.execute("""
            INSERT INTO reports(guild_id,reporter_id,target_id,reason,details,evidence)
            VALUES(?,?,?,?,?,?)
        """, (guild_id, reporter_id, target_id, reason, details, evidence))

    async def report(self, guild_id: int, report_id: int):
        return await self.one(
            "SELECT * FROM reports WHERE guild_id=? AND id=?",
            (guild_id, report_id),
        )

    async def set_report_channel(self, report_id: int, channel_id: int):
        await self.execute(
            "UPDATE reports SET channel_id=? WHERE id=?",
            (channel_id, report_id),
        )

    async def claim_report(self, report_id: int, user_id: int):
        changed = await self.rowcount("""
            UPDATE reports SET claimed_by=?, status='claimed'
            WHERE id=? AND status IN ('open','claimed')
        """, (user_id, report_id))
        return changed == 1

    async def resolve_report(self, report_id: int, resolution: str):
        await self.execute("""
            UPDATE reports SET status='resolved', resolution=?,
            resolved_at=CURRENT_TIMESTAMP WHERE id=?
        """, (resolution, report_id))

    async def create_appeal(
        self, guild_id: int, user_id: int, case_id: int | None,
        reason: str, details: str
    ):
        return await self.execute("""
            INSERT INTO appeals(guild_id,user_id,case_id,reason,details)
            VALUES(?,?,?,?,?)
        """, (guild_id, user_id, case_id, reason, details))

    async def appeal(self, guild_id: int, appeal_id: int):
        return await self.one(
            "SELECT * FROM appeals WHERE guild_id=? AND id=?",
            (guild_id, appeal_id),
        )

    async def set_appeal_channel(self, appeal_id: int, channel_id: int):
        await self.execute(
            "UPDATE appeals SET channel_id=? WHERE id=?",
            (channel_id, appeal_id),
        )

    async def claim_appeal(self, appeal_id: int, user_id: int):
        changed = await self.rowcount("""
            UPDATE appeals SET claimed_by=?, status='claimed'
            WHERE id=? AND status IN ('open','claimed')
        """, (user_id, appeal_id))
        return changed == 1

    async def resolve_appeal(self, appeal_id: int, resolution: str):
        await self.execute("""
            UPDATE appeals SET status='resolved', resolution=?,
            resolved_at=CURRENT_TIMESTAMP WHERE id=?
        """, (resolution, appeal_id))

    async def open_reports_for_user(self, guild_id: int, reporter_id: int):
        return await self.all("""
            SELECT * FROM reports
            WHERE guild_id=? AND reporter_id=? AND status!='resolved'
            ORDER BY id DESC
        """, (guild_id, reporter_id))

    async def open_appeals_for_user(self, guild_id: int, user_id: int):
        return await self.all("""
            SELECT * FROM appeals
            WHERE guild_id=? AND user_id=? AND status!='resolved'
            ORDER BY id DESC
        """, (guild_id, user_id))

    async def active_timeout_cases(self):
        return await self.all("""
            SELECT * FROM moderation_cases
            WHERE action='timeout_jail' AND active=1 AND expires_at IS NOT NULL
            ORDER BY id
        """)

    async def export_config(self, guild_id: int):
        cfg = await self.config(guild_id)
        types = await self.types(guild_id, enabled_only=False)
        panels = await self.panels(guild_id)
        def conv(row):
            return dict(row) if row else None
        mod_cfg = await self.mod_config(guild_id)
        jail_channels = await self.jail_channels(guild_id)
        return {
            "guild_config": conv(cfg),
            "moderation_config": conv(mod_cfg),
            "jail_channels": [dict(r) for r in jail_channels],
            "ticket_types": [dict(r) for r in types],
            "panels": [dict(r) for r in panels],
        }
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
