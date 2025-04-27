from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import asyncio
from collections import deque

# Замените на ваш токен от @BotFather
API_TOKEN = 'ВАШ_ТОКЕН'

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Переменные для управления очередью и перерывами
queue = deque()  # Очередь пользователей (хранит user_id)
current_break_user = None  # Текущий пользователь на перерыве (user_id)
break_duration = 600  # 10 минут в секундах

# Создаем инлайн-кнопку "На перерыв"
break_button = InlineKeyboardMarkup()
break_button.add(InlineKeyboardButton("На перерыв", callback_data="go_break"))

# Обработчик команды /start
@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    await message.reply(
        "Привет! Я бот для управления перерывами в группе. Нажми кнопку ниже, чтобы встать в очередь на перерыв.",
        reply_markup=break_button
    )

# Обработчик нажатия на кнопку "На перерыв"
@dp.callback_query_handler(lambda c: c.data == "go_break")
async def process_break_request(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_name = callback_query.from_user.first_name or callback_query.from_user.username or str(user_id)

    # Проверка, находится ли пользователь уже на перерыве или в очереди
    if user_id == current_break_user:
        await callback_query.message.answer(f"{user_name}, ты уже на перерыве!")
        await callback_query.answer()
        return
    if user_id in queue:
        await callback_query.message.answer(f"{user_name}, ты уже в очереди!")
        await callback_query.answer()
        return

    # Если очередь пуста и никто не на перерыве
    global current_break_user
    if not queue and current_break_user is None:
        current_break_user = user_id
        await callback_query.message.answer(
            f"{user_name}, ты пошел на перерыв! У тебя 10 минут.",
            reply_markup=break_button
        )
        # Запускаем таймер на 10 минут
        asyncio.create_task(break_timer(user_id, user_name))
    else:
        # Добавляем пользователя в очередь
        queue.append(user_id)
        await callback_query.message.answer(
            f"{user_name}, ты добавлен в очередь! Позиция: {len(queue)}",
            reply_markup=break_button
        )

    await callback_query.answer()

# Функция для обработки таймера перерыва
async def break_timer(user_id, user_name):
    await asyncio.sleep(break_duration)  # Ждем 10 минут
    global current_break_user, queue

    # Уведомляем пользователя, что его перерыв закончился
    await bot.send_message(
        user_id,
        f"{user_name}, твой перерыв окончен!"
    )

    # Если есть люди в очереди, запускаем перерыв для следующего
    if queue:
        next_user_id = queue.popleft()
        next_user = await bot.get_chat_member(chat_id=next_user_id, user_id=next_user_id)
        next_user_name = next_user.user.first_name or next_user.user.username or str(next_user_id)
        current_break_user = next_user_id
        await bot.send_message(
            next_user_id,
            f"{next_user_name}, твоя очередь! Ты пошел на перерыв (10 минут).",
            reply_markup=break_button
        )
        # Запускаем таймер для следующего пользователя
        asyncio.create_task(break_timer(next_user_id, next_user_name))
    else:
        # Если очереди нет, сбрасываем текущего пользователя
        current_break_user = None

# Запуск бота
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
