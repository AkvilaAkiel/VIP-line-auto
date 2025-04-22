import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes
)
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# Черга та поточний користувач
queue = []
current_user = None
BREAK_DURATION = 600  # 10 хвилин

# Логування
logging.basicConfig(level=logging.INFO)

# Команди
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🟢 У чергу", callback_data='join')],
        [InlineKeyboardButton("🔚 Вийти", callback_data='leave')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("👋 Привіт! Я бот черги на перерву.", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'join':
        await join(update, context)
    elif query.data == 'leave':
        await leave(update, context)

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_user
    user = update.effective_user

    if user.id in [u.id for u in queue] or (current_user and current_user.id == user.id):
        await context.bot.send_message(chat_id=user.id, text="⏳ Ви вже у черзі або на перерві.")
        return

    queue.append(user)
    await context.bot.send_message(chat_id=user.id, text="✅ Ви додані до черги.")

    if not current_user:
        await start_break(context)

async def leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_user
    user = update.effective_user

    if current_user and user.id == current_user.id:
        current_user = None
        await context.bot.send_message(chat_id=user.id, text="❌ Ви вийшли з перерви.")
        await start_break(context)
        return

    for u in queue:
        if u.id == user.id:
            queue.remove(u)
            await context.bot.send_message(chat_id=user.id, text="❌ Ви вийшли з черги.")
            return

    await context.bot.send_message(chat_id=user.id, text="🤷‍♂️ Вас немає в черзі.")

async def start_break(context: ContextTypes.DEFAULT_TYPE):
    global current_user
    if not queue:
        return

    current_user = queue.pop(0)
    await context.bot.send_message(chat_id=current_user.id, text="🚨 Ваша черга на перерву! 10 хвилин ⏱")
    await asyncio.sleep(BREAK_DURATION)
    await context.bot.send_message(chat_id=current_user.id, text="⏰ Перерва закінчилась!")
    current_user = None
    await start_break(context)

# Запуск
if __name__ == '__main__':
    import os
    TOKEN = os.getenv("BOT_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🤖 Бот запущено...")
    app.run_polling()
