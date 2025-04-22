import logging
import asyncio
import os
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from flask import Flask, request
from threading import Thread

# == ЛОГІНГ ==
logging.basicConfig(level=logging.INFO)

queue = []
active_break = None

# == КНОПКИ ==
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Долучитись до черги", callback_data="join")],
        [InlineKeyboardButton("🔴 Вийти з черги", callback_data="leave")],
        [InlineKeyboardButton("📋 Подивитись чергу", callback_data="queue")],
    ])

# == КОМАНДИ ==
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привіт! Я бот для черги на перерву ⏳\nОбери дію:",
        reply_markup=main_menu()
    )

# == ОБРОБКА КНОПОК ==
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global active_break
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if query.data == "join":
        if user.id in [u.id for u in queue]:
            position = [u.id for u in queue].index(user.id) + 1
            await query.edit_message_text(f"Ти вже в черзі. Твоє місце: {position}")
        else:
            queue.append(user)
            await query.edit_message_text("Тебе додано в чергу на перерву.")
            if active_break is None:
                await start_next_break(context)

    elif query.data == "leave":
        if user in queue:
            queue.remove(user)
            await query.edit_message_text("Тебе видалено з черги.")
        elif user == active_break:
            active_break = None
            await query.edit_message_text("Ти вийшов з перерви достроково.")
            await notify_next(context)
        else:
            await query.edit_message_text("Тебе немає в черзі.")
    
    elif query.data == "queue":
        if not queue:
            text = "Черга порожня."
        else:
            names = [f"{i+1}. {u.first_name}" for i, u in enumerate(queue)]
            text = "Поточна черга:\n" + "\n".join(names)
        await query.edit_message_text(text, reply_markup=main_menu())

# == ПЕРЕРВА ==
async def start_next_break(context: ContextTypes.DEFAULT_TYPE):
    global active_break
    if not queue:
        return

    active_break = queue.pop(0)
    chat_id = active_break.id

    await context.bot.send_message(chat_id=chat_id, text="🟢 Твоя черга! Почалась перерва на 10 хвилин ⏳")
    await asyncio.sleep(9 * 60)
    await context.bot.send_message(chat_id=chat_id, text="⚠️ Залишилась 1 хвилина до завершення перерви.")
    await asyncio.sleep(60)
    await context.bot.send_message(chat_id=chat_id, text="🔚 Твоя перерва завершена.")
    active_break = None
    await notify_next(context)

async def notify_next(context: ContextTypes.DEFAULT_TYPE):
    if queue:
        next_user = queue[0]
        await context.bot.send_message(chat_id=next_user.id, text="🔔 Ти наступний на перерву!")
        await start_next_break(context)

# == FLASK ==
flask_app = Flask(__name__)
application = None  # буде створено асинхронно

@flask_app.route('/')
def index():
    return 'Бот працює!'

@flask_app.route(f"/{os.getenv('BOT_TOKEN')}", methods=["POST"])
async def webhook_handler():
    data = await request.get_data()
    update = Update.de_json(data.decode("utf-8"), application.bot)
    await application.process_update(update)
    return 'OK'

def run_flask():
    flask_app.run(host="0.0.0.0", port=5000)

# == MAIN ==
async def main():
    global application
    token = os.getenv("BOT_TOKEN")
    webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{token}"

    application = ApplicationBuilder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))

    await application.bot.set_webhook(url=webhook_url)
    await application.initialize()
    await application.start()
    logging.info(f"Webhook встановлено: {webhook_url}")

if __name__ == "__main__":
    Thread(target=run_flask).start()
    asyncio.run(main())
