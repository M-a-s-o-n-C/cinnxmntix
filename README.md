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
- Users can access `/my-tickets` without having to remember channel names
- Staff-only actions provide ephemeral confirmation/error messages
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
