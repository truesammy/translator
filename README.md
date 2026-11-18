# Translator bot

A Discord bot that carries announcements to many languages. Every message in a source
channel is posted, translated, into each linked target channel. Edits and deletions of the
original follow along. It is one-way: nothing is translated back.

- Works for messages from people, other bots and webhooks.
- Keeps Discord formatting, mentions, links, emojis and code untouched.
- Rebuilds embeds with only their text translated.
- Posts under the original author's name and avatar.
- Replaces `@everyone` and `@here` with the target channel's language role, if it has one.
- Catches up after downtime: missed messages, edits and deletions of the last 30 days.
- Or, instead of a channel per language: flag buttons under each announcement that show it,
  translated, only to whoever presses one. Each language is translated once, on its first press.

## Set up the Discord application

1. Create an application at <https://discord.com/developers/applications> and add a bot.
2. Under **Bot**, turn on **Message Content Intent**.
3. Invite it with the scopes `bot` and `applications.commands` and these permissions:
   View Channels, Send Messages, Manage Webhooks, Manage Messages, Embed Links,
   Attach Files, Read Message History, Add Reactions.

## Configure

| Variable | Meaning |
| --- | --- |
| `DISCORD_TOKEN` | The bot token |
| `ENCRYPTION_KEY` | Key that encrypts the servers' DeepL keys in the database |
| `DATABASE_PATH` | SQLite file. Docker sets it; without Docker the default is `data/bot.db` |

Copy `.env.example` to `.env` and fill it in.

Generate an `ENCRYPTION_KEY` once and keep it. Without it the stored DeepL keys cannot be read.

```bash
docker run --rm python:3.12-slim sh -c "pip install -q cryptography && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
```

## Run

The bot is meant to run in Docker. You do not build the image yourself: GitHub Actions
tests every push to `main` and publishes the image as `ghcr.io/truesammy/translator:latest`.
All you need on the server is `compose.yaml` and `.env` in one folder:

```bash
docker compose up -d
```

It restarts by itself after a crash or a reboot. The database is kept in the Docker
volume `data`, so it survives updates.

| Task | Command |
| --- | --- |
| Follow the log | `docker compose logs -f` |
| Update to the newest image | `docker compose pull && docker compose up -d` |
| Stop | `docker compose down` |
| Back up the database | `docker compose cp bot:/data/bot.db ./bot.db` |
| Go back to an older version | Set `image:` in `compose.yaml` to `ghcr.io/truesammy/translator:<commit hash>` |

Keep the backup secret: it holds the webhook tokens, and with one of them anyone can post in
that channel.

### Without Docker

With Python 3.12 or newer. Leave `DATABASE_PATH` empty or point it at a file.

```bash
pip install -r requirements.txt
pip install --no-deps .
DISCORD_TOKEN=... ENCRYPTION_KEY=... python -m translator_bot
```

## Commands

All commands need the **Manage Server** permission, and only you see the replies.

| Command | What it does |
| --- | --- |
| `/link add source target language [role]` | Translate `source` into `target`. Run it again for the same pair to change language or role. |
| `/link remove source target` | Remove a link and delete the translations it posted. |
| `/link list` | Show all links of the server. |
| `/source-language channel language` | Fix the language of a source channel, or detect it automatically (default). |
| `/apikey set` | Store a DeepL API key for the server. |
| `/apikey remove` | Remove it. |
| `/apikey status` | Show whether a key is set and how many characters are used. |
| `/embed create channel` | Fill in a form and post an embed in a source channel. It is translated like any message. |
| `/embed edit message` | Change an embed made with `/embed create`. If someone other than its author edits it, its text ends with a mention of who edited it last. Deleting it removes its translations. |
| `/flags add language` | Offer a language on the flag buttons (at most 25). |
| `/flags remove language` | Stop offering it. |
| `/flags list` | Show the languages on the flag buttons. |
| *Apps → Add translation flags* (right-click a message) | Reply to that one message with the flag buttons. Deleting the message deletes the reply. |
| *Apps → Translate* (right-click a message) | Show the flag buttons for that message, only to you. |

## Private translations with flags

People pick their language themselves and nothing is translated before someone asks for it.

1. Write the announcements in a channel only admins see, the source.
2. `/link add source target language:Original (no translation)` copies every message, untranslated,
   into the public channel `target`.
3. `/flags add language` once per language. Every copy now carries a flag button per language.

Pressing a flag shows the announcement in that language, visible only to whoever pressed it.
The first press per language translates and stores the result; every later press, by anyone,
reuses it. An edit of the announcement makes the next press translate once more. Attachments
are not repeated in the private reply. Changing the languages updates a copy's buttons the next
time its announcement is edited.

The *Translate* menu is for admins only at first. To offer it to everyone, open
**Server Settings → Integrations → the bot → Translate** and allow `@everyone`.

## Translation order

1. The official DeepL API, with the key of the server (`/apikey set`).
2. Google Translate, through an unofficial endpoint.

A server without a key starts at step 2. If a step fails, runs out of quota, cannot handle
the language or damages a mention or link, the next one is tried. If all fail, nothing is
posted in that channel, the original gets a ⚠️ reaction, and the reason is written to the
bot's log output. The bot tries such a message again after its next restart, and right
after a DeepL key is saved with `/apikey set`.

## Good to know

- Message text is sent to DeepL and, on the fallback, to an unofficial Google endpoint.
  That one is not covered by Google's terms, blocks addresses quickly and can stop
  working at any time. For dependable translations, set a DeepL key.
- A translation pings only what pinged in the original. `@everyone` written by someone
  who may not mention everyone stays plain text in every channel.
- Link previews are not copied. Discord creates them again in the target channel.
- A message longer than 2000 characters after translation is split into several messages.
- Edits update text and embeds. Attachments added or removed by an edit are not synced.
- Threads, forum channels, polls, stickers and voice messages are not relayed.

## Develop

```bash
pip install -r requirements.txt
pip install -e ".[dev]"
python -m pytest
python scripts/smoke_providers.py   # live check of the providers, makes network calls
```

`docs/smoke-checklist.md` is the manual test to run against a real server.
