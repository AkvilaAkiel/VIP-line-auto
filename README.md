# VIP-line-auto

A Telegram bot that coordinates breaks for a support team. The queue and shared dashboard let team members see who is on break and who is next.

## How it works

- A team member joins from an inline button. If the queue is empty and nobody is on break, the bot starts a 15-minute break immediately.
- When a break ends, the next person has 25 minutes to confirm. If that expires, the bot calls the next person in the queue.
- Team members can leave the queue, end a break early, or swap places using `/swap @username`.
- `/queue` opens the dashboard. `/init_pin` creates and pins its entry point when the bot has permission to pin messages.
- `/backup` posts a JSON snapshot to the configured group. Queue state is held in memory and resets when the process restarts.

## Run in a test group

Use Python 3.11 and a Telegram bot added to a dedicated test group. The bot receives updates at `/webhook`, so its server needs a publicly reachable HTTPS URL.

```sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python bot.py
```

Set the following environment variables before starting the bot.

| Variable | Purpose |
| --- | --- |
| `API_TOKEN` | Telegram bot token |
| `GROUP_CHAT_ID` | Numeric ID of the test group |
| `WEBHOOK_HOST` | Public HTTPS origin without a trailing slash |
| `PORT` | HTTP listen port. The application defaults to `10000` |

The repository includes a [Render blueprint](render.yaml). Set `GROUP_CHAT_ID` in the Render service environment as well as the token and webhook origin. The blueprint sets `PORT=8000`.

## Implementation

[bot.py](bot.py) uses aiogram 2.x, aiohttp, a Python deque, and asyncio timers. The current webhook does not verify a Telegram webhook secret. Use the current version as a portfolio demonstration in a dedicated test environment.
