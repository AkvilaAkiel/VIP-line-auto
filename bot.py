from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from aiohttp import web
import asyncio
from collections import deque
import os
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Токен и URL для Webhook
API_TOKEN = os.getenv('API_TOKEN', 'ВАШ_ТОКЕН')
WEBHOOK_PATH = '/webhook'
WEBHOOK_HOST = os.getenv('WEBHOOK_HOST', 'https://ВАШ_URL.onrender.com')
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

# ID группы из переменной окружения
GROUP_CHAT_ID = os.getenv('GROUP_CHAT_ID')
if not GROUP_CHAT_ID:
    logging.error("GROUP_CHAT_ID не задан в переменных окружения!")
    raise ValueError("GROUP_CHAT_ID не задан в переменных окружения")
GROUP_CHAT_ID = int(GROUP_CHAT_ID)

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Глобальные переменные
queue = deque()  # Очередь пользователей (хранит user_id)
current_break_user = None  # Текущий пользователь на перерыве (user_id)
pending_break_user = None  # Пользователь, ожидающий подтверждения перерыва (user_id)
break_duration = 600  # 10 минут в секундах

# Создаём инлайн-кнопки
break_button = InlineKeyboardMarkup()
break_button.add(InlineKeyboardButton("На перерву ⚡️", callback_data="go_break"))

start_break_button = InlineKeyboardMarkup()
start_break_button.add(InlineKeyboardButton("Почати перерву ⚡️", callback_data="start_break"))

# Функция для получения кликабельного имени
def get_clickable_name(user_id, user_name):
    return f"<a href='tg://user?id={user_id}'>{user_name}</a>"

# Обработчик команды /start
@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    await message.reply(
        "Привіт! Я бот для керування перервою. Натисни кнопку нижче, щоб піти на перерву або встати в чергу. Перевірити чергу - /queue.",
        reply_markup=break_button
    )
    logging.info(f"Команда /start в группе {GROUP_CHAT_ID}")

# Обработчик команды /queue
@dp.message_handler(commands=['queue'])
async def show_queue(message: types.Message):
    if message.chat.id != GROUP_CHAT_ID:
        await message.reply("Этот бот работает только в определённой группе!")
        logging.info(f"Попытка /queue в неверном чате {message.chat.id}")
        return
    queue_text = []
    if current_break_user:  # Добавляем текущего человека на перерыве
        try:
            user = await bot.get_chat_member(chat_id=GROUP_CHAT_ID, user_id=current_break_user)
            user_name = user.user.first_name or user.user.username or str(current_break_user)
            queue_text.append(f"На перерві: {get_clickable_name(current_break_user, user_name)}")
        except Exception as e:
            queue_text.append(f"На перерві: User ID: {current_break_user} (помилка при отриманні імені)")
            logging.error(f"Помилка при отриманні імені для current_break_user {current_break_user}: {str(e)}")
    if pending_break_user:
        try:
            user = await bot.get_chat_member(chat_id=GROUP_CHAT_ID, user_id=pending_break_user)
            user_name = user.user.first_name or user.user.username or str(pending_break_user)
            queue_text.append(f"Очікує підтвердження: {get_clickable_name(pending_break_user, user_name)}")
        except Exception as e:
            queue_text.append(f"Очікує підтвердження: User ID: {pending_break_user} (ошибка получения имени)")
            logging.error(f"Помилка при отриманні імені для pending_break_user {pending_break_user}: {str(e)}")
    if queue:
        for i, user_id in enumerate(queue):
            try:
                user = await bot.get_chat_member(chat_id=GROUP_CHAT_ID, user_id=user_id)
                user_name = user.user.first_name or user.user.username or str(user_id)
                queue_text.append(f"{i+1}. {get_clickable_name(user_id, user_name)}")
            except Exception as e:
                queue_text.append(f"{i+1}. User ID: {user_id} (ошибка получения имени)")
                logging.error(f"Помилка при отриманні імені для для user_id {user_id}: {str(e)}")
    if not queue_text:
        await message.reply("Нікого в черзі!")
        logging.info(f"Команда /queue в группе {GROUP_CHAT_ID}: нікого в черзі")
    else:
        await message.reply(f"Поточна черга:\n" + "\n".join(queue_text), parse_mode="HTML")
        logging.info(f"Команда /queue в группе {GROUP_CHAT_ID}: показана черга\n" + "\n".join(queue_text))

# Обробник команди виходу з черги /cancel
@dp.message_handler(commands=['cancel'])
async def cancel_break(message: types.Message):
    global current_break_user, pending_break_user, queue
    user_id = message.from_user.id
    user_name = message.from_user.first_name or message.from_user.username or str(user_id)
    clickable_name = get_clickable_name(user_id, user_name)
    if user_id == current_break_user:
        current_break_user = None
        await message.reply(f"{clickable_name}, твою перерву скасовано!", parse_mode="HTML")
        logging.info(f"{user_name} (ID: {user_id}) перерву скасовано")
    elif user_id == pending_break_user:
        pending_break_user = None
        await message.reply(f"{clickable_name}, ти відмовився від перерви.", parse_mode="HTML")
        logging.info(f"{user_name} (ID: {user_id}) відмовився від очікування перерви")
    elif user_id in queue:
        queue.remove(user_id)
        await message.reply(f"{clickable_name} 🚪, тебе видалено з черги!", parse_mode="HTML")  # /cancel
        logging.info(f"{user_name} (ID: {user_id}) видалено з черги")
    else:
        await message.reply(f"{clickable_name}, ти не на перерві, не у черзі й не очікуєш підтвердження!", parse_mode="HTML")
        
# Обробник команди обміну чергою /swap
@dp.message_handler(commands=['swap'])
initiator_id = message.from_user.id
initiator_name = message.from_user.first_name or message.from_user.username or str(initiator_id)
if initiator_id not in queue:
    await message.reply(f"{get_clickable_name(initiator_id, initiator_name)}, ти не в черзі!", parse_mode="HTML")
    return
try:
    target_username = message.text.split()[1].lstrip('@')
    target_user = None
    chat_members = await bot.get_chat_administrators(chat_id=GROUP_CHAT_ID)  # Проверяем админов
    for member in chat_members:
        if member.user.username == target_username:
            target_user = member
            break
    if not target_user:
        chat_members = await bot.get_chat_members(chat_id=GROUP_CHAT_ID)  # Проверяем всех участников
        for member in chat_members:
            if member.user.username == target_username:
                target_user = member
                break
    if not target_user:
        await message.reply(f"Користувач @{target_username} не знайдений у групі!")
        return
    target_id = target_user.user.id
    target_name = target_user.user.first_name or target_user.user.username or str(target_id)
    if target_id not in queue:
        await message.reply(f"{get_clickable_name(target_id, target_name)}, не у черзі!", parse_mode="HTML")
        return
    if initiator_id == target_id:
        await message.reply(f"{get_clickable_name(initiator_id, initiator_name)}, неможливо мінятися з самим собою!", parse_mode="HTML")
        return
    initiator_idx = list(queue).index(initiator_id)
    target_idx = list(queue).index(target_id)
    queue[initiator_idx], queue[target_idx] = queue[target_idx], queue[initiator_idx]
    await message.reply(
        f"{get_clickable_name(initiator_id, initiator_name)} 🔄 "
        f"{get_clickable_name(target_id, target_name)} помінялись місцями у черзі!",
        parse_mode="HTML"
    )
    logging.info(f"{initiator_name} (ID: {initiator_id}) и {target_name} (ID: {target_id}) помінялись місцями")
except IndexError:
    await message.reply("Вкажи username! Приклад: /swap @username")
except Exception as e:
    await message.reply("Помилка при обміні місцями. Спробуй знову!")
    logging.error(f"Помилка в /swap для {initiator_name} (ID: {initiator_id}): {str(e)}")

# Обработчик нажатия на кнопку "На перерыв"
@dp.callback_query_handler(lambda c: c.data == "go_break")
async def process_break_request(callback_query: types.CallbackQuery):
    global current_break_user, pending_break_user, queue
    user_id = callback_query.from_user.id
    user_name = callback_query.from_user.first_name or callback_query.from_user.username or str(user_id)
    clickable_name = get_clickable_name(user_id, user_name)

    # Проверка, находится ли пользователь на перерыве или ожидает подтверждения
    if user_id == current_break_user:
        await callback_query.message.answer(f"{clickable_name}, ти вже на перерві!", parse_mode="HTML")
        await callback_query.answer()
        return
    if user_id == pending_break_user:
        await callback_query.message.answer(f"{clickable_name}, твоя черга! Натисни 'Почати перерву ⚡️', по готовності.", parse_mode="HTML")
        await callback_query.answer()
        return
    if user_id in queue:
        await callback_query.message.answer(f"{clickable_name}, ти вже в черзі!", parse_mode="HTML")
        await callback_query.answer()
        return

    # Если очередь пуста, нет текущего перерыва и нет ожидающего подтверждения
    if not queue and current_break_user is None and pending_break_user is None:
        current_break_user = user_id
        await callback_query.message.answer(
            f"{clickable_name}, перерву розпочато! У тебе 10 хвилин. ✅", parse_mode="HTML"
        )
        logging.info(f"{user_name} (ID: {user_id}) користувач почав перерву в групі {GROUP_CHAT_ID}")
        asyncio.create_task(break_timer(user_id, user_name))
    else:
        # Добавляем пользователя в очередь
        queue.append(user_id)
        await callback_query.message.answer(
            f"{clickable_name}, тебе додано до черги! 🟨 Позиція: {len(queue)}",
            parse_mode="HTML"
        )
        logging.info(f"{user_name} (ID: {user_id}) добавлен в очередь в группе {GROUP_CHAT_ID}, позиция: {len(queue)}")

    await callback_query.answer()

# Обработчик нажатия на кнопку "Начать перерыв"
@dp.callback_query_handler(lambda c: c.data == "start_break")
async def start_break(callback_query: types.CallbackQuery):
    global current_break_user, pending_break_user
    user_id = callback_query.from_user.id
    user_name = callback_query.from_user.first_name or callback_query.from_user.username or str(user_id)
    clickable_name = get_clickable_name(user_id, user_name)

    # Проверяем, является ли пользователь ожидающим подтверждения
    if user_id == pending_break_user:
        current_break_user = user_id
        pending_break_user = None
        await callback_query.message.answer(
            f"{clickable_name}, перерву розпочато! У тебе 10 хвилин. ✅", parse_mode="HTML"
        )
        logging.info(f"{user_name} (ID: {user_id}) користувач почав перерву в групі {GROUP_CHAT_ID}")
        asyncio.create_task(break_timer(user_id, user_name))
    else:
        await callback_query.message.answer(f"{clickable_name}, це не твоя черга! 🟥", parse_mode="HTML")
        logging.info(f"{user_name} (ID: {user_id}) користувач намагався почати перерву не в свою чергу в групі {GROUP_CHAT_ID}")

    await callback_query.answer()

# Функция для обработки таймера перерыва
async def break_timer(user_id, user_name):
    try:
        await asyncio.sleep(break_duration)  # Ждём 10 минут
        global current_break_user, pending_break_user, queue

        # Уведомляем в группе, что перерыв закончился
        clickable_name = get_clickable_name(user_id, user_name)
        await bot.send_message(
            GROUP_CHAT_ID,  # Отправляем в группу
            f"{clickable_name}, твоя перерва добігла кінця! 🔚",
            parse_mode="HTML"
        )
        logging.info(f"{user_name} (ID: {user_id}) користувач завершив перерву в групі {GROUP_CHAT_ID}")

        # Если есть люди в очереди, уведомляем следующего
        if queue:
            next_user_id = queue.popleft()
            next_user = await bot.get_chat_member(chat_id=GROUP_CHAT_ID, user_id=next_user_id)
            next_user_name = next_user.user.first_name or next_user.user.username or str(next_user_id)
            pending_break_user = next_user_id
            await bot.send_message(
                next_user_id,  # Личное сообщение следующему
                f"{next_user_name}, твоя черга на перерву! ⚡️ Натисни 'Почати перерву', по готовності.",
                reply_markup=start_break_button
            )
            logging.info(f"{next_user_name} (ID: {next_user_id}) користувач обізнаний про свою чергу в групі {GROUP_CHAT_ID}")
        else:
            # Если очереди нет, сбрасываем текущего пользователя
            current_break_user = None
            logging.info(f"Черга пуста, перерву завершено в групі {GROUP_CHAT_ID}")

    except Exception as e:
        logging.error(f"Поомилка в break_timer для {user_name} (ID: {user_id}) в группе {GROUP_CHAT_ID}: {str(e)}")

# Настройка Webhook при запуске
async def on_startup(_):
    # Проверяем и устанавливаем Webhook
    webhook_info = await bot.get_webhook_info()
    if webhook_info.url != WEBHOOK_URL:
        await bot.set_webhook(url=WEBHOOK_URL)
        logging.info(f"Webhook установлен: {WEBHOOK_URL}")
    else:
        logging.info(f"Webhook уже установлен: {WEBHOOK_URL}")

# Обработчик входящих обновлений через Webhook
async def webhook(request):
    update = await request.json()
    update = types.Update(**update)
    await dp.process_update(update)
    return web.Response()

# Создание aiohttp сервера
app = web.Application()
app.router.add_post(WEBHOOK_PATH, webhook)

# Запуск бота
if __name__ == '__main__':
    executor.start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        skip_updates=True,
        host='0.0.0.0',
        port=int(os.getenv('PORT', 8000))
    )
