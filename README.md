# Telegram Team Queue Coordinator Bot 🤖⏱

> **Note:** *This bot was developed to automate workflow and break schedules for the VIP Management team at a major logistics/e-commerce company. Sensitive data and environment variables have been redacted.*

## 📌 Overview
In fast-paced customer support and VIP management environments, coordinating team breaks manually via chat creates "bazaar-style" chaos. This often leads to overlapping absences, missed SLAs, and unnecessary notification noise.

**The Solution:** A Python-based, asynchronous Telegram bot that acts as a centralized break coordinator. It enforces a strict concurrency limit (only one person on break at a time), provides a real-time visual queue, and automatically manages break durations.

## 🚀 Business Impact
* **Workflow Optimization:** Eliminated manual schedule negotiations, drastically reducing chat "noise".
* **Coverage Guarantee:** Ensured 100% team coverage by preventing simultaneous breaks among key personnel.
* **Transparency:** Provided the management team with a clear, real-time overview of who is currently unavailable and who is next in line.

## ✨ Key Features
* **⚡ Interactive UI:** Uses Telegram Inline Keyboards for seamless 1-click actions (Join Queue, Start Break).
* **⏱ Automated Timers:** Utilizes `asyncio.sleep` to track 15-minute intervals, automatically notifying the user when their time is up and pinging the next person in line.
* **🔄 Queue Management:** Users can dynamically cancel their breaks, leave the queue, or swap positions (`/swap @username`) without breaking the flow.
* **📦 State Backup:** Includes a `/backup` command to export the current queue state as a JSON snippet.
* **🔒 Access Control:** Hardcoded to respond only within the designated corporate group chat (`GROUP_CHAT_ID`), ignoring direct messages or unauthorized groups.

## 🛠 Tech Stack
* **Language:** Python 3.11
* **Framework:** `aiogram` 2.x (Asynchronous Telegram Bot API)
* **Web Server:** `aiohttp` (for handling Webhooks)
* **Deployment:** Render (PaaS) via Webhooks (`render.yaml` included)

## 🏗 Architecture & Design Decisions
* **Webhooks over Polling:** To deploy efficiently on Render's free tier and ensure instant response times, the bot uses Webhooks instead of long-polling.
* **In-Memory State:** The queue uses Python's `collections.deque` for O(1) appends and pops. *Note: Since this is deployed on a stateless container, queue data resides in RAM. For a more robust V2, state could be externalized to Redis or SQLite.*

## ⚙️ Setup & Deployment
1. Clone the repository.
2. Install dependencies: `pip install -r requirements.txt`
3. Set up environment variables:
   * `API_TOKEN` - Telegram Bot Token
   * `GROUP_CHAT_ID` - The specific Chat ID where the bot is allowed to operate
   * `WEBHOOK_HOST` - Your server URL (e.g., `https://your-app.onrender.com`)
4. Run the application: `python bot.py`
