import asyncio
from collections import deque
from datetime import datetime, timedelta
import json
import logging
import os
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import exceptions, executor
from aiohttp import web

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
break_end_time = None          # datetime завершення перерви
current_timer_task = None      # Фоновий таймер перерви (15 хв)
pending_timeout_task = None    # Фоновий таймер очікування (25 хв)

break_duration = 900           # 15 хвилин у секундах
timeout_duration = 1500        # 25 хвилин у секундах

dashboard_msg_id = None        # ID змінного повідомлення-дашборду
user_cache = {}                # Кеш імен: {user_id: "clickable_name"}
KYIV_TZ = ZoneInfo("Europe/Kyiv")

# --- КНОПКИ ТА КЛАВІАТУРИ ---
def get_anchor_kb():
    """Кнопка для статичного закріпленого повідомлення в шапці"""
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📊 Дашборд черги ⬇️", callback_data="summon_dashboard"))
    return kb

def get_dashboard_kb():
    """Кнопки під динамічним дашбордом"""
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
    """Кнопка для персонального пейджера та старту"""
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Почати перерву ⚡️", callback_data="start_break"))
    return kb

def get_end_early_kb():
    """Кнопка дострокового завершення"""
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Завершити раніше 🔚", callback_data="end_early"))
    return kb

# --- ДОПОМІЖНІ ФУНКЦІЇ ---
def cache_user(user_id, user_name):
    """Кешує ім'я, щоб уникнути спаму запитами до Telegram API"""
    if user_id not in user_cache:
        user_cache[user_id] = f"<a href='tg://user?id={user_id}'>{user_name}</a>"

def get_cached_name(user_id):
    return user_cache.get(user_id, f"ID: {user_id}")

def generate_dashboard_text():
    """Формує текст інформаційного дашборду"""
    lines = ["<b>📊 ДАШБОРД ПЕРЕРВ</b>\n"]
    
    if current_break_user:
        lines.append(f"🟢 <b>На перерві:</b> {get_cached_name(current_break_user)}")
        if break_end_time:
            lines.append(f"⏳ <i>До: {break_end_time.strftime('%H:%M')}</i>\n")
    else:
        lines.append("🟢 <b>На перерві:</b> Нікого\n")

    if pending_break_user:
        lines.append(f"🟡 <b>Очікує підтвердження:</b> {get_cached_name(pending_break_user)}\n")

    lines.append("<b>🚶‍♂️ Черга:</b>")
    if not queue:
        lines.append("<i>Порожньо</i>")
    else:
        for i, uid in enumerate(queue, 1):
            lines.append(f"{i}. {get_cached_name(uid)}")
            
    now = datetime.now(KYIV_TZ).strftime('%H:%M:%S')
    lines.append(f"\n🔄 <i>Останнє оновлення: {now}</i>")
    return "\n".join(lines)

async def update_dashboard():
    """Редагує існуючий дашборд на місці, не зачіпаючи закріплені повідомлення"""
    global dashboard_msg_id
    text = generate_dashboard_text()
    kb = get_dashboard_kb()
    
    if dashboard_msg_id:
        try:
            await bot.edit_message_text(
                text,
                chat_id=GROUP_CHAT_ID,
                message_id=dashboard_msg_id,
                reply_markup=kb,
                parse_mode="HTML",
            )
            return
        except exceptions.MessageNotModified:
            return
        except Exception as e:
            logging.warning(f"Не вдалося відредагувати дашборд: {e}")
            dashboard_msg_id = None

    msg = await bot.send_message(GROUP_CHAT_ID, text, reply_markup=kb, parse_mode="HTML", disable_notification=True)
    dashboard_msg_id = msg.message_id

async def call_next():
    """Передає чергу: сповіщає людину персонально зі звуком і запускає 25-хв таймер"""
    global pending_break_user, current_break_user, break_end_time, pending_timeout_task
    
    current_break_user = None
    break_end_time = None
    
    if queue:
        next_user_id = queue.popleft()
        pending_break_user = next_user_id
        
        # Персональний виклик у ПП зі звуком та вібрацією
        try:
            await bot.send_message(
                next_user_id,
                "⚡️ <b>Твоя черга на перерву!</b>\n\n"
                "У тебе є <b>25 хвилин</b>, щоб розпочати її. Коли будеш готовий — тисни кнопку нижче:\n"
                "<i>(Якщо не підтвердити за 25 хв, черга перейде далі, а тебе перенесе в кінець)</i>",
                reply_markup=get_start_break_kb(),
                parse_mode="HTML"
            )
        except Exception as e:
            logging.warning(f"Не вдалося надіслати в ПП {next_user_id}: {e}")
        
        await update_dashboard()
        
        if pending_timeout_task:
            pending_timeout_task.cancel()
        pending_timeout_task = asyncio.create_task(timeout_timer(next_user_id))
    else:
        pending_break_user = None
        await update_dashboard()

async def timeout_timer(user_id):
    """Спрацьовує через 25 хв: переміщує людину в кінець черги"""
    try:
        await asyncio.sleep(timeout_duration)
        global pending_break_user, queue
        
        if pending_break_user == user_id:
            pending_break_user = None
            queue.append(user_id)
            
            try:
                await bot.send_message(
                    user_id,
                    "⚠️ <b>Час вийшов (25 хв)!</b>\n"
                    "Ти не підтвердив початок перерви, тому тебе автоматично перенесено в кінець черги.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

            await bot.send_message(
                GROUP_CHAT_ID, 
                f"⚠️ {get_cached_name(user_id)} не підтвердив (-ла) початок перерви за 25 хвилин.\n"
                f"🔄 Його автоматично перенесено в кінець черги.", 
                parse_mode="HTML"
            )
            await call_next()
            
    except asyncio.CancelledError:
        pass

async def break_timer(user_id):
    """Відраховує 15 хв перерви та будить у ПП і групі"""
    try:
        await asyncio.sleep(break_duration)
        
        try:
            await bot.send_message(
                user_id,
                "🔚 <b>Твоя 15-хвилинна перерва добігла кінця!</b>\nЧас повертатися до роботи 💼",
                parse_mode="HTML"
            )
        except Exception:
            pass
            
        await bot.send_message(
            GROUP_CHAT_ID,
            f"🔚 {get_cached_name(user_id)}, перерва завершилася!",
            parse_mode="HTML"
        )
        await call_next()
        
    except asyncio.CancelledError:
        logging.info(f"Таймер для {user_id} скасовано достроково.")

# --- ОБРОБНИКИ КОМАНД ---
@dp.message_handler(commands=['init_pin', 'pin_button'])
async def cmd_setup_anchor(message: types.Message):
    """Створює та закріплює статичне повідомлення з кнопкою 'Дашборд' у шапці"""
    if message.chat.id != GROUP_CHAT_ID:
        return
        
    msg = await bot.send_message(
        GROUP_CHAT_ID,
        "📌 <b>Керування перервами VIP лінії</b>\n"
        "Натисніть кнопку нижче, щоб викликати актуальний дашборд у самий низ чату:",
        reply_markup=get_anchor_kb(),
        parse_mode="HTML"
    )
    try:
        await bot.pin_chat_message(GROUP_CHAT_ID, msg.message_id, disable_notification=True)
    except Exception as e:
        logging.warning(f"Не вдалося закріпити повідомлення: {e}")
        
    try:
        await message.delete()
    except Exception:
        pass

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    """Активація бота в ПП або виклик дашборду в групі"""
    if message.chat.type == "private":
        cache_user(message.from_user.id, message.from_user.first_name or "Користувач")
        await message.reply(
            "👋 <b>Привіт! Я пейджер-бот перерв VIP лінії.</b>\n\n"
            "Тут ти отримуватимеш персональні виклики на перерву та нагадування про її завершення. "
            "Керувати чергою можна через закріплену кнопку в робочій групі!",
            parse_mode="HTML"
        )
        return

    if message.chat.id == GROUP_CHAT_ID:
        await cmd_dashboard(message)

@dp.message_handler(commands=['queue', 'dashboard'])
async def cmd_dashboard(message: types.Message):
    """Спускає дашборд у самий низ чату за ручною командою"""
    if message.chat.id != GROUP_CHAT_ID:
        return
        
    global dashboard_msg_id
    
    if dashboard_msg_id:
        try:
            await bot.delete_message(GROUP_CHAT_ID, dashboard_msg_id)
        except Exception:
            pass
        dashboard_msg_id = None

    await update_dashboard()
    
    try:
        await message.delete()
    except Exception:
        pass

@dp.message_handler(commands=['backup'])
async def backup_queue(message: types.Message):
    if message.chat.id != GROUP_CHAT_ID:
        return
    state = {
        "queue": list(queue),
        "current_break_user": current_break_user,
        "pending_break_user": pending_break_user,
        "cache": user_cache
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
                except Exception:
                    pass

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

# --- ОБРОБНИКИ КНОПОК (CALLBACKS) ---
@dp.callback_query_handler(lambda c: c.data == "summon_dashboard")
async def cb_summon_dashboard(callback_query: types.CallbackQuery):
    """Спрацьовує при кліку на закріплену в шапці кнопку"""
    global dashboard_msg_id
    
    if dashboard_msg_id:
        try:
            await bot.delete_message(GROUP_CHAT_ID, dashboard_msg_id)
        except Exception:
            pass
        dashboard_msg_id = None

    text = generate_dashboard_text()
    kb = get_dashboard_kb()
    msg = await bot.send_message(GROUP_CHAT_ID, text, reply_markup=kb, parse_mode="HTML", disable_notification=True)
    dashboard_msg_id = msg.message_id
    
    try:
        await callback_query.answer("Дашборд спущено вниз чату ⬇️")
    except Exception:
        pass

@dp.callback_query_handler(lambda c: c.data == "refresh_dash")
async def cb_refresh(callback_query: types.CallbackQuery):
    await update_dashboard()
    try:
        await callback_query.answer("Оновлено!")
    except Exception:
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
        
        try:
            await bot.send_message(
                user_id,
                f"✅ Твою перерву розпочато! Вона триває 15 хвилин (до {break_end_time.strftime('%H:%M')}).",
                reply_markup=get_end_early_kb(),
                parse_mode="HTML"
            )
        except Exception:
            pass

        await bot.send_message(
            GROUP_CHAT_ID,
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
        
    if pending_timeout_task:
        pending_timeout_task.cancel()
        
    current_break_user = user_id
    pending_break_user = None
    break_end_time = datetime.now(KYIV_TZ) + timedelta(seconds=break_duration)
    
    await callback_query.message.answer(
        f"✅ Перерву розпочато! У тебе 15 хвилин (до {break_end_time.strftime('%H:%M')}).",
        reply_markup=get_end_early_kb(),
        parse_mode="HTML"
    )
    
    try:
        await callback_query.message.delete()
    except Exception:
        pass

    await bot.send_message(
        GROUP_CHAT_ID,
        f"✅ {get_cached_name(user_id)} пішов(-ла) на перерву (до {break_end_time.strftime('%H:%M')}).",
        reply_markup=get_end_early_kb(),
        parse_mode="HTML"
    )
        
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
        if pending_timeout_task: 
            pending_timeout_task.cancel()
            
        await callback_query.answer("Ти відмовився від черги.")
        await call_next()
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
        
    await callback_query.answer("Перерву завершено достроково.")
    
    try:
        await callback_query.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await bot.send_message(
        GROUP_CHAT_ID,
        f"🏃‍♂️ {get_cached_name(user_id)} повернувся (-лась) з перерви раніше.",
        parse_mode="HTML"
    )
        
    await call_next()

# --- СТАРТ СЕРВЕРА ЧЕРЕЗ WEBHOOK ---
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
