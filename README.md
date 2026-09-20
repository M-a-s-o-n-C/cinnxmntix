# cinnxmn Tickets v2

A modern, bakery-themed Discord ticket system written in Python with `discord.py`.

This version is a full redesign of the original cinnxmn ticket bot. Commands are **top-level slash commands** — there is no `/ticket ...` prefix.

## Design goals

- Cute bakery / coffee aesthetic without making information hard to read
- Highly customizable per server and per ticket category
- Accessibility-first controls
- Private staff claiming
- Lightweight enough for small free Python/Pterodactyl hosting
- Persistent SQLite storage
- No web dashboard or heavyweight database required

## Accessibility

cinnxmn v2 intentionally does not rely on color or emoji alone.

- Buttons always have readable text labels
- Ticket status is always written in plain language
- Priority is always written in plain language
- Destructive actions require confirmation or a close reason
- `/accessibility` can reduce decorative emoji and separator styling
- `!*!*` styling is only inserted into normal embed/message body text where Discord Markdown can render it
- Embed footers stay plain text
- Images are optional; important information is never contained only in an image
- Users can access `/my tickets` without having to remember channel names
- Staff-only actions provide ephemeral confirmation/error messages
- The ticket-opening form uses clear short-answer and long-answer labels, customizable with `/form customize`

> Discord administrators can always bypass channel permission overwrites. No Discord bot can hide a channel from a member who has the server-wide Administrator permission.

---

# Commands

There are currently **39 top-level slash commands**.

## Setup & customization

### `/setup`
Configure:
- staff role
- private staff queue
- open ticket category
- archive category
- transcript/log channel
- per-user open-ticket limit

### `/settings`
View current configuration.

### `/appearance`
Customize:
- brand name
- primary color
- accent color
- closed-ticket color
- footer text
- dropdown placeholder
- ticket channel naming format

Supported ticket-channel placeholders:

```text
{type}
{id}
{user}
{username}
```

Example:

```text
{type}-{id}-{user}
```

### `/accessibility`
Toggle:
- accessibility mode
- decorative emoji
- decorative `!*!*` separators

### `/automation`
Toggle:
- DM customer when closing
- automatic transcript on close
- staff ping when created
- staff ping when unclaimed
- whether customers may close tickets
- automatic move to archive category

---

# Ticket category commands

### `/category add`
Create a ticket category with:
- name
- description
- emoji
- custom embed color
- dedicated staff role
- dedicated open-ticket category
- dedicated archive category
- custom welcome message

This means different ticket types can be routed to different teams.

Example:

```text
General Support → @Support Team
Member Reports → @Moderation Team
Partnerships → @Management
```

### `/category edit`
Edit existing category configuration.

### `/category remove`
Disable a category without deleting historical ticket data.

### `/category list`
See IDs and status of all categories.

### `/category inherit`
Reset category-specific routing/color overrides so the category inherits global defaults.

### `/form customize`
Customize the two modal questions shown when a customer opens that ticket type.

For example:

```text
General Support
Short field: "What do you need help with?"
Long field: "Tell us what happened"

Member Report
Short field: "Who are you reporting?"
Long field: "Explain what happened and include evidence"
```

---

# Panel commands

### `/panel create`
Build one dropdown panel containing **1–25 ticket categories**.

Customizable:
- target channel
- category IDs
- title
- description
- color
- banner image URL
- thumbnail URL
- dropdown placeholder

### `/panel edit`
Edit a live panel. The existing Discord message is updated instead of forcing you to make a new one.

### `/panel preview`
Privately preview an existing panel.

### `/panel list`
See all configured panels.

### `/panel delete`
Disable a panel and remove its Discord message.

---

# Customer commands

### `/my tickets`
Shows the user's currently open tickets.

### `/info`
Shows the current ticket's status, type, priority, subject, and claim state.

### `/transcript`
Exports an HTML transcript when the user has permission.

### `/close`
Opens a required close-reason modal.

---

# Staff workflow commands

### `/claim`
Claim the current ticket.

The full staff role is denied ticket visibility. When claimed, the bot grants access only to the individual staff member.

### `/unclaim`
Returns the ticket to the queue and removes the previous claimer's channel access.

### `/transfer`
Transfers the ticket to another authorized staff member.

The old claimer loses access and the new claimer receives access.

### `/priority`
Set:
- Low
- Normal
- High
- Urgent

### `/rename`
Rename the current ticket channel.

### `/user add`
Give another member access.

### `/user remove`
Remove an added member.

### `/note`
Store a private internal staff note. The note is **not posted into the customer-facing ticket**.

### `/notes`
View internal staff notes.

### `/lock`
Prevent the customer from sending new messages while still allowing them to read the ticket.

### `/unlock`
Restore customer reply access.

### `/reopen`
Reopen a closed ticket and return it to the staff queue.

### `/delete`
Permanently delete a closed Discord ticket channel after a confirmation prompt.

---

# Management commands

### `/blacklist add`
Prevent a member from opening tickets, with a recorded reason.

### `/blacklist add remove`
Restore ticket access.

### `/blacklist add list`
View the current ticket blacklist.

### `/stats`
View:
- total ticket count
- open tickets
- currently claimed tickets
- closed tickets

### `/config export`
Download a JSON backup of the bot configuration, ticket types, and panel definitions.

### `/help`
Accessible in-Discord command guide.

---

# Staff queue behavior

When a new ticket opens:

```text
Unclaimed — needs a staff member
```

The configured staff role can be pinged in the private queue.

When a staff member claims it:

```text
Claimed by @StaffMember
```

The **same queue card is edited**.

Other normal staff do not gain access to the ticket channel.

When unclaimed:
- previous claimer access is removed
- the queue card returns to unclaimed
- staff can optionally be pinged again

---

# Ticket close behavior

Closing requires a reason.

The bot can automatically:

1. Generate an HTML transcript
2. Save it to the staff log channel
3. DM the customer a themed embed
4. Include the close reason
5. Include who closed the ticket
6. Attach the transcript
7. Remove customer access
8. Move the ticket into the archive category

If customer DMs are closed, the staff log records that delivery failed.

---

# Theme

Default palette:

```text
Croissant gold
Latte tan
Coffee brown
Espresso brown
Warm cream
```

You can replace the colors using `/appearance` or set a unique color for a specific ticket category.

Hex example:

```text
D7A86E
```

Do not include a color name such as `brown`; use a six-digit hex value.

---

# Images

Panel images are optional.

You can set:
- banner image
- thumbnail

Important context should still be written in the panel description because images are not equally accessible to all Discord users.

---

# Database / upgrading from v1

The bot uses:

```text
tickets.db
```

**Do not delete your existing database just to install v2.**

v2 includes automatic SQLite schema migration for the original cinnxmn database. It adds the new configuration fields while preserving existing rows.

Back up `tickets.db` before a major update anyway.

---

# Installation on Pterodactyl / Silly Development

Upload:

```text
main.py
database.py
requirements.txt
```

Set your Python file/startup file to:

```text
main.py
```

Environment variables:

```env
DISCORD_TOKEN=YOUR_TOKEN
GUILD_ID=YOUR_CINNXMN_SERVER_ID
BOT_BRAND=cinnxmn
```

`GUILD_ID` is strongly recommended while developing because guild slash commands update immediately.

## Discord Developer Portal

Under the bot's settings, enable:

```text
Message Content Intent
```

This is used so HTML transcripts can include actual message text.

Invite the application with:

```text
bot
applications.commands
```

Recommended bot permissions:

```text
View Channels
Send Messages
Manage Channels
Manage Messages
Read Message History
Embed Links
Attach Files
Use External Emojis
```

The bot needs `Manage Channels` because private ticket claiming is implemented using individual channel permission overrides.

---

# First setup

Run:

```text
/setup
```

Then make your ticket types:

```text
/category add
/category add
/category add
```

Check their IDs:

```text
/category list
```

Then create a multi-category panel:

```text
/panel create
```

For category IDs:

```text
1,2,3
```

---

# Resource use

The bot intentionally uses:

- one Python process
- discord.py
- SQLite
- aiosqlite

It does **not** require:

- PostgreSQL
- Redis
- a dashboard web server
- headless Chrome
- image processing libraries

That keeps it substantially lighter than a dashboard-heavy ticket bot.

---

# Security

- Never paste the bot token directly into `main.py`
- Keep the staff queue private
- Keep transcript logs private
- Transcripts may contain sensitive server conversations
- Limit Discord Administrator permission to trusted members
- Back up `tickets.db`

## v2.1 reliability patch

- Claim, unclaim, and transfer interactions are acknowledged immediately to prevent Discord `Unknown interaction (10062)` failures.
- Closing a ticket now explicitly fetches the opener from Discord when the user is not already cached.
- `/dm test` sends a themed test DM and reports whether Discord accepted it.
- DM failures now log the actual Discord error.
- Ticket category name edits continue to regenerate the slug used in new channel names.


# Moderation Suite — v3

cinnxmn v3 adds a persistent moderation, reporting, appeals, and jail system. Moderation is intentionally case-based: actions create durable case numbers instead of disappearing into transient Discord messages.

## Moderation setup

Run:

```text
/mod setup
```

Configure:
- moderator role
- jail role
- moderation log
- reports category
- appeals category
- report staff queue
- appeal staff queue
- warning-point threshold
- optional automatic jail at the warning threshold

The bot role must be **above the jail role and any normal roles it needs to remove/restore**.

Recommended bot permissions now include:

```text
Manage Roles
Manage Channels
Manage Messages
Moderate Members
Kick Members
Ban Members
View Audit Log
Read Message History
Send Messages
Embed Links
Attach Files
```

## Jail system

This is not just a timeout alias.

When `/jail add` or `/timeout` is used:

1. The bot snapshots every removable role the member currently has.
2. Those roles are removed.
3. The configured jail role is added.
4. A moderation case is created.
5. The member receives a moderation DM when Discord permits it.
6. `/jail add remove` or `/untimeout` removes the jail role and restores the saved roles that still exist and are assignable.

Discord does not allow bots to remove:
- managed integration/bot roles
- roles above the bot's highest role
- the `@everyone` role

### Jail-safe channels

Add channels with:

```text
/jail add channel add
```

Examples:
- rules → `can_send: False`
- ticket/support channel → `can_send: True`
- appeal channel → `can_send: True`

Then run:

```text
/jail add sync
```

The jail role receives `View Channel: Deny` on ordinary channels and explicit access only to your jail-safe list.

Commands:

```text
/jail add channel add
/jail add channel remove
/jail add channel list
/jail add sync
/jail add
/jail add remove
/timeout
/untimeout
```

## Warning system

```text
/warn add
/warn add list
/warn add remove
```

Warnings have:
- unique case number
- moderator
- member
- reason
- warning points
- active/cleared status
- private staff notes
- permanent historical record

The point total is calculated from active warning cases.

You may optionally configure automatic jail when the active point total reaches the server threshold.

Clearing a warning does **not** erase it. It marks the case inactive and preserves the audit trail.

## Case system

Every major moderation action is stored as a numbered case.

```text
/case view
/case view note
/case view link ticket
/mod context
```

`/case view note` stores private staff notes without posting them into a public or member-facing channel.

`/case view link ticket` links a moderation case to a cinnxmn support ticket.

### `/mod context`

This is a staff context dashboard rather than an automatic punishment recommender.

It shows:
- active warning points
- whether the member is currently jailed
- unresolved reports naming the member
- counts of prior moderation actions
- recent cases

The bot deliberately does **not** automatically decide a punishment from this information.

## Kick / ban

```text
/kick
/ban
/unban
```

Kick and ban:
- perform role hierarchy checks first
- create moderation cases
- attempt a DM before removal
- write to the moderation log

`/ban` can optionally delete 0–7 days of the member's messages.

## Timeout

```text
/timeout member duration reason
```

Duration examples:

```text
30m
2h
3d
1w
```

Discord limits timeouts to 28 days.

In cinnxmn, timeout is intentionally stricter than Discord's standard timeout:

```text
Discord timeout
+
role snapshot
+
remove removable roles
+
jail role
+
case record
+
moderation log
```

`/untimeout` clears the timeout and restores the saved roles.

## Reports module

Members submit reports with:

```text
/report submit
```

A report records:
- reporter
- reported member
- concise reason
- detailed explanation
- optional evidence/links
- unique report number
- claim state
- resolution
- timestamps

The bot creates a private report channel visible to:
- the reporter
- moderators
- the bot

A separate staff report queue is notified.

Staff workflow:

```text
/report submit claim
/report submit resolve
```

Resolving a report requires a written outcome that is retained in the database and moderation log.

## Appeals module

Members appeal their own moderation cases with:

```text
/appeal submit
```

They must reference a valid case that belongs to them.

The bot creates a private appeal channel containing:
- original case
- original action
- original reason
- appeal reason
- detailed appeal statement

Staff queue:

```text
/appeal submit claim
```

Resolution:

```text
/appeal submit resolve
```

When resolving, staff can choose whether to mark the original moderation case inactive.

The user receives a DM with the appeal outcome when Discord allows delivery.

### Important ban limitation

A user banned from the server cannot run the server's slash commands while banned. For ban appeals, use an external appeal server, website/form, or another community entry point if you want banned users to submit appeals.

## Other moderation tools

```text
/purge
/slowmode
```

`/purge` deletes up to 100 recent messages and logs the action as a case.

`/slowmode` sets channel slowmode up to Discord's maximum.

## Less-common / advanced features

cinnxmn v3 includes several workflows that are uncommon in lightweight ticket bots:

- role snapshots and restoration after jail
- warning-point threshold with optional automatic jail
- case-to-support-ticket linking
- private case notes
- cross-system `/mod context`
- report claim/resolution workflow
- case-backed appeals
- clearing a case without deleting history
- separate moderation/report submit/appeal submit queues
- moderation DMs tied to exact case numbers
- explicit jail-safe channel allowlist
- read-only versus read/write jail-safe channels
- persistent moderation records in the same SQLite database as tickets

## Recommended setup order

```text
/setup
/mod setup

/jail add channel add  # rules, read-only
/jail add channel add  # support/ticket access, read/write
/jail add channel add  # appeal access, read/write
/jail add sync

/category add
/panel create
```

Back up `tickets.db` before major upgrades. v3 adds its moderation tables without deleting existing ticket data.

## Automatic timeout cleanup

cinnxmn checks active timeout+jail cases every 60 seconds. When the recorded Discord timeout expires, it automatically removes jail and restores the saved roles that are still available/assignable, then marks that timeout case inactive and logs the restoration.


# Grouped slash-command structure

This build uses Discord's native command groups instead of hyphenated command names.

Examples:

```text
/category add
/category edit
/category list

/panel create
/panel edit
/panel preview

/user add
/user remove

/blacklist add
/blacklist remove
/blacklist list

/dm test
/config export

/mod setup
/mod context

/jail add
/jail remove
/jail sync
/jail channel add
/jail channel remove
/jail channel list

/warn add
/warn list
/warn remove

/case view
/case note
/case link ticket

/report submit
/report claim
/report resolve

/appeal submit
/appeal claim
/appeal resolve
```

Simple actions remain simple top-level commands, such as:

```text
/setup
/settings
/appearance
/accessibility
/automation
/claim
/unclaim
/transfer
/close
/reopen
/delete
/transcript
/rename
/priority
/note
/notes
/lock
/unlock
/kick
/ban
/unban
/timeout
/untimeout
/purge
/slowmode
/stats
/help
```

There are no hyphens in slash-command names in this build.
- The ticket-opening form uses clear short-answer and long-answer labels, customizable with `/form-customize`

> Discord administrators can always bypass channel permission overwrites. No Discord bot can hide a channel from a member who has the server-wide Administrator permission.

---

# Commands

There are currently **39 top-level slash commands**.

## Setup & customization

### `/setup`
Configure:
- staff role
- private staff queue
- open ticket category
- archive category
- transcript/log channel
- per-user open-ticket limit

### `/settings`
View current configuration.

### `/appearance`
Customize:
- brand name
- primary color
- accent color
- closed-ticket color
- footer text
- dropdown placeholder
- ticket channel naming format

Supported ticket-channel placeholders:

```text
{type}
{id}
{user}
{username}
```

Example:

```text
{type}-{id}-{user}
```

### `/accessibility`
Toggle:
- accessibility mode
- decorative emoji
- decorative `!*!*` separators

### `/automation`
Toggle:
- DM customer when closing
- automatic transcript on close
- staff ping when created
- staff ping when unclaimed
- whether customers may close tickets
- automatic move to archive category

---

# Ticket category commands

### `/category-add`
Create a ticket category with:
- name
- description
- emoji
- custom embed color
- dedicated staff role
- dedicated open-ticket category
- dedicated archive category
- custom welcome message

This means different ticket types can be routed to different teams.

Example:

```text
General Support → @Support Team
Member Reports → @Moderation Team
Partnerships → @Management
```

### `/category-edit`
Edit existing category configuration.

### `/category-remove`
Disable a category without deleting historical ticket data.

### `/category-list`
See IDs and status of all categories.

### `/category-inherit`
Reset category-specific routing/color overrides so the category inherits global defaults.

### `/form-customize`
Customize the two modal questions shown when a customer opens that ticket type.

For example:

```text
General Support
Short field: "What do you need help with?"
Long field: "Tell us what happened"

Member Report
Short field: "Who are you reporting?"
Long field: "Explain what happened and include evidence"
```

---

# Panel commands

### `/panel-create`
Build one dropdown panel containing **1–25 ticket categories**.

Customizable:
- target channel
- category IDs
- title
- description
- color
- banner image URL
- thumbnail URL
- dropdown placeholder

### `/panel-edit`
Edit a live panel. The existing Discord message is updated instead of forcing you to make a new one.

### `/panel-preview`
Privately preview an existing panel.

### `/panel-list`
See all configured panels.

### `/panel-delete`
Disable a panel and remove its Discord message.

---

# Customer commands

### `/my-tickets`
Shows the user's currently open tickets.

### `/info`
Shows the current ticket's status, type, priority, subject, and claim state.

### `/transcript`
Exports an HTML transcript when the user has permission.

### `/close`
Opens a required close-reason modal.

---

# Staff workflow commands

### `/claim`
Claim the current ticket.

The full staff role is denied ticket visibility. When claimed, the bot grants access only to the individual staff member.

### `/unclaim`
Returns the ticket to the queue and removes the previous claimer's channel access.

### `/transfer`
Transfers the ticket to another authorized staff member.

The old claimer loses access and the new claimer receives access.

### `/priority`
Set:
- Low
- Normal
- High
- Urgent

### `/rename`
Rename the current ticket channel.

### `/add-user`
Give another member access.

### `/remove-user`
Remove an added member.

### `/note`
Store a private internal staff note. The note is **not posted into the customer-facing ticket**.

### `/notes`
View internal staff notes.

### `/lock`
Prevent the customer from sending new messages while still allowing them to read the ticket.

### `/unlock`
Restore customer reply access.

### `/reopen`
Reopen a closed ticket and return it to the staff queue.

### `/delete`
Permanently delete a closed Discord ticket channel after a confirmation prompt.

---

# Management commands

### `/blacklist`
Prevent a member from opening tickets, with a recorded reason.

### `/unblacklist`
Restore ticket access.

### `/blacklist-list`
View the current ticket blacklist.

### `/stats`
View:
- total ticket count
- open tickets
- currently claimed tickets
- closed tickets

### `/export-config`
Download a JSON backup of the bot configuration, ticket types, and panel definitions.

### `/help`
Accessible in-Discord command guide.

---

# Staff queue behavior

When a new ticket opens:

```text
Unclaimed — needs a staff member
```

The configured staff role can be pinged in the private queue.

When a staff member claims it:

```text
Claimed by @StaffMember
```

The **same queue card is edited**.

Other normal staff do not gain access to the ticket channel.

When unclaimed:
- previous claimer access is removed
- the queue card returns to unclaimed
- staff can optionally be pinged again

---

# Ticket close behavior

Closing requires a reason.

The bot can automatically:

1. Generate an HTML transcript
2. Save it to the staff log channel
3. DM the customer a themed embed
4. Include the close reason
5. Include who closed the ticket
6. Attach the transcript
7. Remove customer access
8. Move the ticket into the archive category

If customer DMs are closed, the staff log records that delivery failed.

---

# Theme

Default palette:

```text
Croissant gold
Latte tan
Coffee brown
Espresso brown
Warm cream
```

You can replace the colors using `/appearance` or set a unique color for a specific ticket category.

Hex example:

```text
D7A86E
```

Do not include a color name such as `brown`; use a six-digit hex value.

---

# Images

Panel images are optional.

You can set:
- banner image
- thumbnail

Important context should still be written in the panel description because images are not equally accessible to all Discord users.

---

# Database / upgrading from v1

The bot uses:

```text
tickets.db
```

**Do not delete your existing database just to install v2.**

v2 includes automatic SQLite schema migration for the original cinnxmn database. It adds the new configuration fields while preserving existing rows.

Back up `tickets.db` before a major update anyway.

---

# Installation on Pterodactyl / Silly Development

Upload:

```text
main.py
database.py
requirements.txt
```

Set your Python file/startup file to:

```text
main.py
```

Environment variables:

```env
DISCORD_TOKEN=YOUR_TOKEN
GUILD_ID=YOUR_CINNXMN_SERVER_ID
BOT_BRAND=cinnxmn
```

`GUILD_ID` is strongly recommended while developing because guild slash commands update immediately.

## Discord Developer Portal

Under the bot's settings, enable:

```text
Message Content Intent
```

This is used so HTML transcripts can include actual message text.

Invite the application with:

```text
bot
applications.commands
```

Recommended bot permissions:

```text
View Channels
Send Messages
Manage Channels
Manage Messages
Read Message History
Embed Links
Attach Files
Use External Emojis
```

The bot needs `Manage Channels` because private ticket claiming is implemented using individual channel permission overrides.

---

# First setup

Run:

```text
/setup
```

Then make your ticket types:

```text
/category-add
/category-add
/category-add
```

Check their IDs:

```text
/category-list
```

Then create a multi-category panel:

```text
/panel-create
```

For category IDs:

```text
1,2,3
```

---

# Resource use

The bot intentionally uses:

- one Python process
- discord.py
- SQLite
- aiosqlite

It does **not** require:

- PostgreSQL
- Redis
- a dashboard web server
- headless Chrome
- image processing libraries

That keeps it substantially lighter than a dashboard-heavy ticket bot.

---

# Security

- Never paste the bot token directly into `main.py`
- Keep the staff queue private
- Keep transcript logs private
- Transcripts may contain sensitive server conversations
- Limit Discord Administrator permission to trusted members
- Back up `tickets.db`
