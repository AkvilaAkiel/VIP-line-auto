from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from aiogram.utils import exceptions
from aiohttp import web
import asyncio
from collections import deque
import os
import logging
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Налаштування логування
logging.basicConfig(level=logging.INFO)

# Токен та URL для Webhook
API_TOKEN = os.getenv('API_TOKEN', 'ВАШ_ТОКЕН')
WEBHOOK_PATH = '/webhook'
WEBHOOK_HOST = os.getenv('WEBHOOK_HOST', 'https://ВАШ_URL.onrender.com')
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

GROUP_CHAT_ID = os.getenv('GROUP_CHAT_ID')
if not GROUP_CHAT_ID:
    raise ValueError("GROUP_CHAT_ID не задано в змінних оточення")
GROUP_CHAT_ID = int(GROUP_CHAT_ID)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# --- ГЛОБАЛЬНИЙ СТАН ---
queue = deque()
current_break_user = None
pending_break_user = None
break_end_time = None          # Зберігає datetime завершення перерви
current_timer_task = None      # Фонова задача таймера 15 хв
pending_timeout_task = None    # Фонова задача тайм-ауту 25 хв

break_duration = 900           # 15 хвилин у секундах
timeout_duration = 1500        # 25 хвилин у секундах (час на підтвердження)

dashboard_msg_id = None        # ID повідомлення дашборду
user_cache = {}                # Кеш імен: {user_id: "clickable_name"}
KYIV_TZ = ZoneInfo("Europe/Kyiv")

# --- КНОПКИ ---
def get_dashboard_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🔄 Оновити", callback_data="refresh_dash"),
        InlineKeyboardButton("⚡️ Встати в чергу", callback_data="go_break")
    )
    kb.add(
        InlineKeyboardButton("🚪 Покинути чергу", callback_data="leave_queue")
    )
    return kb

def get_start_break_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Почати перерву ⚡️", callback_data="start_break"))
    return kb

def get_end_early_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Завершити раніше 🔚", callback_data="end_early"))
    return kb

# --- ДОПОМІЖНІ ФУНКЦІЇ ---
def cache_user(user_id, user_name):
    """Кешує ім'я, щоб не смикати API Telegram"""
    if user_id not in user_cache:
        user_cache[user_id] = f"<a href='tg://user?id={user_id}'>{user_name}</a>"

def get_cached_name(user_id):
    return user_cache.get(user_id, f"ID: {user_id}")

def generate_dashboard_text():
    """Генерує візуал для єдиного дашборду черги"""
    lines = ["<b>📊 ДАШБОРД ПЕРЕРВ</b>\n"]
    
    if current_break_user:
        lines.append(f"🟢 <b>На перерві:</b> {get_cached_name(current_break_user)}")
        if break_end_time:
            lines.append(f"⏳ <i>До: {break_end_time.strftime('%H:%M')}</i>\n")
    else:
        lines.append("🟢 <b>На перерві:</b> Нікого\n")

    if pending_break_user:
        lines.append(f"🟡 <b>Очікує:</b> {get_cached_name(pending_break_user)}\n")

    lines.append("<b>🚶‍♂️ Черга:</b>")
    if not queue:
        lines.append("<i>Порожньо</i>")
    else:
        for i, uid in enumerate(queue, 1):
            lines.append(f"{i}. {get_cached_name(uid)}")
            
    now = datetime.now(KYIV_TZ).strftime('%H:%M:%S')
    lines.append(f"\n🔄 <i>Оновлено: {now}</i>")
    return "\n".join(lines)

async def update_dashboard():
    """Оновлює закріплене повідомлення. Якщо його немає — створює нове."""
    global dashboard_msg_id
    text = generate_dashboard_text()
    kb = get_dashboard_kb()
    
    if dashboard_msg_id:
        try:
            await bot.edit_message_text(text, chat_id=GROUP_CHAT_ID, message_id=dashboard_msg_id, reply_markup=kb, parse_mode="HTML")
            return
        except exceptions.MessageNotModified:
            return  # Текст не змінився
        except Exception as e:
            logging.warning(f"Не вдалося оновити дашборд (можливо видалений): {e}")
            dashboard_msg_id = None

    # Якщо повідомлення ще немає
    msg = await bot.send_message(GROUP_CHAT_ID, text, reply_markup=kb, parse_mode="HTML")
    dashboard_msg_id = msg.message_id
    
    try:
        await bot.pin_chat_message(GROUP_CHAT_ID, dashboard_msg_id, disable_notification=True)
    except Exception as e:
        logging.warning(f"Немає прав на закріплення повідомлення: {e}")

async def call_next():
    """Викликає наступного в черзі та запускає тайм-аут на 25 хв"""
    global pending_break_user, current_break_user, break_end_time, pending_timeout_task
    
    current_break_user = None
    break_end_time = None
    
    if queue:
        next_user_id = queue.popleft()
        pending_break_user = next_user_id
        
        await bot.send_message(
            GROUP_CHAT_ID,
            f"{get_cached_name(next_user_id)}, твоя черга! ⚡️ Натисни кнопку нижче, коли будеш готовий піти.",
            reply_markup=get_start_break_kb(),
            parse_mode="HTML"
        )
        
        # Скасовуємо старий тайм-аут (про всяк випадок) і запускаємо новий
        if pending_timeout_task:
            pending_timeout_task.cancel()
        pending_timeout_task = asyncio.create_task(timeout_timer(next_user_id))
    else:
        pending_break_user = None

async def timeout_timer(user_id):
    """Скасовує очікування, якщо людина не натиснула 'Почати' за 25 хв, і переносить її в кінець черги"""
    try:
        await asyncio.sleep(timeout_duration)
        global pending_break_user, queue
        
        if pending_break_user == user_id:
            pending_break_user = None
            queue.append(user_id)  # Переносимо в кінець
            
            await bot.send_message(
                GROUP_CHAT_ID, 
                f"⚠️ {get_cached_name(user_id)} не підтвердив початок перерви за 25 хвилин.\n"
                f"🔄 Його автоматично перенесено в кінець черги.", 
                parse_mode="HTML"
            )
            await call_next()
            await update_dashboard()
            
    except asyncio.CancelledError:
        # Спрацьовує без помилок, якщо людина встигла натиснути кнопку "Почати"
        pass

async def break_timer(user_id):
    """Таймер самої перерви (15 хв)"""
    try:
        await asyncio.sleep(break_duration)
        await bot.send_message(
            GROUP_CHAT_ID,
            f"🔚 {get_cached_name(user_id)}, твоя перерва добігла кінця!",
            parse_mode="HTML"
        )
        await call_next()
        await update_dashboard()
    except asyncio.CancelledError:
        logging.info(f"Таймер для {user_id} скасовано достроково.")

# --- ОБРОБНИКИ КОМАНД ---
@dp.message_handler(commands=['start', 'queue', 'dashboard'])
async def cmd_dashboard(message: types.Message):
    if message.chat.id != GROUP_CHAT_ID:
        return
        
    global dashboard_msg_id
    
    # Видаляємо старий дашборд, щоб бот створив новий у самому низу чату
    if dashboard_msg_id:
        try:
            await bot.delete_message(GROUP_CHAT_ID, dashboard_msg_id)
        except:
            pass
        dashboard_msg_id = None

    await update_dashboard()
    
    # Видаляємо команду /queue користувача, щоб не засмічувати чат
    try:
        await message.delete()
    except:
        pass

@dp.message_handler(commands=['backup'])
async def backup_queue(message: types.Message):
    if message.chat.id != GROUP_CHAT_ID:
        return
    state = {
        "queue": list(queue),
        "current_break_user": current_break_user,
        "pending_break_user": pending_break_user
    }
    await message.reply(
        f"Резервна копія:\n```json\n{json.dumps(state, indent=2, ensure_ascii=False)}\n```",
        parse_mode="Markdown"
    )

@dp.message_handler(commands=['swap'])
async def swap_queue_position(message: types.Message):
    if message.chat.id != GROUP_CHAT_ID:
        return
        
    initiator_id = message.from_user.id
    initiator_name = message.from_user.first_name or message.from_user.username or str(initiator_id)
    cache_user(initiator_id, initiator_name)
    
    if initiator_id not in queue:
        await message.reply(f"{get_cached_name(initiator_id)}, ти не в черзі!", parse_mode="HTML")
        return
    if not message.entities:
        await message.reply("Вкажи користувача через @username! Наприклад: /swap @User")
        return
        
    target_id, target_name = None, None
    for entity in message.entities:
        if entity.type == "text_mention":
            target_id = entity.user.id
            target_name = entity.user.first_name or entity.user.username or str(target_id)
        elif entity.type == "mention":
            username = message.text[entity.offset:entity.offset + entity.length].lstrip('@')
            for uid in queue:
                try:
                    user = await bot.get_chat_member(chat_id=GROUP_CHAT_ID, user_id=uid)
                    if user.user.username and user.user.username.lstrip('@') == username:
                        target_id = uid
                        target_name = user.user.first_name or user.user.username or str(uid)
                        break
                except: pass

    if not target_id or target_id not in queue:
        await message.reply("Користувача не знайдено в черзі!")
        return
        
    if initiator_id == target_id:
        return
        
    cache_user(target_id, target_name)
    
    idx1, idx2 = list(queue).index(initiator_id), list(queue).index(target_id)
    queue[idx1], queue[idx2] = queue[idx2], queue[idx1]
    
    await message.reply(
        f"{get_cached_name(initiator_id)} 🔄 {get_cached_name(target_id)} помінялися місцями!",
        parse_mode="HTML"
    )
    await update_dashboard()

# --- ОБРОБНИКИ КНОПОК ---
@dp.callback_query_handler(lambda c: c.data == "refresh_dash")
async def cb_refresh(callback_query: types.CallbackQuery):
    await update_dashboard()
    try:
        await callback_query.answer("Оновлено!")
    except:
        pass

@dp.callback_query_handler(lambda c: c.data == "go_break")
async def cb_go_break(callback_query: types.CallbackQuery):
    global current_break_user, break_end_time, current_timer_task
    
    user_id = callback_query.from_user.id
    user_name = callback_query.from_user.first_name or callback_query.from_user.username or str(user_id)
    cache_user(user_id, user_name)
    
    if user_id == current_break_user or user_id == pending_break_user or user_id in queue:
        await callback_query.answer("Ти вже в черзі або на перерві!", show_alert=True)
        return

    if not queue and current_break_user is None and pending_break_user is None:
        current_break_user = user_id
        break_end_time = datetime.now(KYIV_TZ) + timedelta(seconds=break_duration)
        
        await callback_query.message.answer(
            f"✅ {get_cached_name(user_id)}, перерву розпочато! До {break_end_time.strftime('%H:%M')}.",
            reply_markup=get_end_early_kb(),
            parse_mode="HTML"
        )
        current_timer_task = asyncio.create_task(break_timer(user_id))
    else:
        queue.append(user_id)
        await callback_query.answer(f"Тебе додано до черги! Позиція: {len(queue)}")
    
    await update_dashboard()

@dp.callback_query_handler(lambda c: c.data == "start_break")
async def cb_start_break(callback_query: types.CallbackQuery):
    global current_break_user, pending_break_user, break_end_time, current_timer_task, pending_timeout_task
    
    user_id = callback_query.from_user.id
    if user_id != pending_break_user:
        await callback_query.answer("Це не твоя черга!", show_alert=True)
        return
        
    # Зупиняємо таймер відліку 25 хвилин, бо людина встигла
    if pending_timeout_task:
        pending_timeout_task.cancel()
        
    current_break_user = user_id
    pending_break_user = None
    break_end_time = datetime.now(KYIV_TZ) + timedelta(seconds=break_duration)
    
    await callback_query.message.answer(
        f"✅ {get_cached_name(user_id)}, перерву розпочато! До {break_end_time.strftime('%H:%M')}.",
        reply_markup=get_end_early_kb(),
        parse_mode="HTML"
    )
    
    try:
        await callback_query.message.delete()
    except:
        pass
        
    current_timer_task = asyncio.create_task(break_timer(user_id))
    await update_dashboard()

@dp.callback_query_handler(lambda c: c.data == "leave_queue")
async def cb_leave_queue(callback_query: types.CallbackQuery):
    global pending_break_user, pending_timeout_task
    
    user_id = callback_query.from_user.id
    
    if user_id in queue:
        queue.remove(user_id)
        await callback_query.answer("Тебе видалено з черги.")
        await update_dashboard()
    elif user_id == pending_break_user:
        pending_break_user = None
        # Скасовуємо 25-хв таймер, бо людина сама відмовилась
        if pending_timeout_task: 
            pending_timeout_task.cancel()
            
        await callback_query.answer("Ти відмовився від черги.")
        await call_next()
        await update_dashboard()
    else:
        await callback_query.answer("Тебе немає в черзі.", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == "end_early")
async def cb_end_early(callback_query: types.CallbackQuery):
    global current_timer_task
    user_id = callback_query.from_user.id
    
    if user_id != current_break_user:
        await callback_query.answer("Ти не на перерві!", show_alert=True)
        return
        
    if current_timer_task:
        current_timer_task.cancel()
        
    await callback_query.answer("Перерву завершено.")
    try:
        await callback_query.message.edit_reply_markup(reply_markup=None)
    except:
        pass
        
    await call_next()
    await update_dashboard()

# --- ЗАПУСК ---
async def on_startup(_):
    webhook_info = await bot.get_webhook_info()
    if webhook_info.url != WEBHOOK_URL:
        await bot.set_webhook(url=WEBHOOK_URL)
        logging.info(f"Webhook встановлено: {WEBHOOK_URL}")

async def webhook(request):
    update = await request.json()
    update = types.Update(**update)
    await dp.process_update(update)
    return web.Response()

app = web.Application()
app.router.add_post(WEBHOOK_PATH, webhook)

if __name__ == '__main__':
    executor.start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        skip_updates=True,
        host='0.0.0.0',
        port=int(os.getenv('PORT', 10000))
    )
