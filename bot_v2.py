import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from flask import Flask, request
import os

# Налаштування логування
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

# == ЛОГІКА ПЕРЕРВИ ==
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

# == FLASK ДЛЯ WEBHOOK ==
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('UTF-8')
    update = Update.de_json(json_str, application.bot)
    application.update_queue.put(update)
    return 'OK'

if __name__ == "__main__":
    # Створення бота
    application = ApplicationBuilder().token("YOUR_BOT_TOKEN").build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))

    # Налаштування webhook
    webhook_url = os.getenv('WEBHOOK_URL')  # Наприклад, https://your-app-name.onrender.com/webhook
    application.bot.set_webhook(webhook_url)

    # Запуск Flask-сервера для обробки запитів webhook
    app.run(host='0.0.0.0', port=5000)
