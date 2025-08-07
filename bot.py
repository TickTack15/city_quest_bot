import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor
from geopy.distance import geodesic
import os

API_TOKEN = os.getenv("BOT_TOKEN")  # Получаем токен из переменной окружения

# Список user_id допущенных пользователей
AUTHORIZED_USERS = {123456789, 987654321}  # замени на реальные id

# Админ user_id (твой)
ADMIN_ID = 123456789

# Локации квеста с координатами и радиусом в метрах
LOCATIONS = {
    'Площадь Свободы': {'coords': (50.4501, 30.5234), 'radius': 100},
    'Парк Горького': {'coords': (50.4356, 30.5200), 'radius': 150},
}

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Хранилище состояния пользователей: включена ли трансляция
user_live_location_status = {}

# Задания и ответы (просто словари для примера)
tasks = {
    1: "Найди памятник и пришли фото",
    2: "Отправь фото с QR-кодом на стене"
}
user_tasks = {}  # user_id -> текущее задание
user_answers = {}  # user_id -> ответ

# Клавиатура для пользователя
main_kb = ReplyKeyboardMarkup(resize_keyboard=True)
main_kb.add(KeyboardButton("Отправить локацию", request_location=True))
main_kb.add(KeyboardButton("Запросить подсказку"))

# --- Проверка доступа ---

@dp.message_handler(lambda message: message.from_user.id not in AUTHORIZED_USERS)
async def unauthorized(message: types.Message):
    await message.reply("Извините, у вас нет доступа к этому квесту.")

# --- Старт и инструкции ---

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    if message.from_user.id not in AUTHORIZED_USERS:
        return
    user_tasks[message.from_user.id] = 1  # выдаём первое задание
    await message.reply(f"Привет! Твоё задание:\n{tasks[1]}", reply_markup=main_kb)

# --- Приём текстовых сообщений как ответов ---

@dp.message_handler(lambda message: message.from_user.id in AUTHORIZED_USERS, content_types=types.ContentTypes.TEXT)
async def answer_handler(message: types.Message):
    uid = message.from_user.id
    if message.text == "Запросить подсказку":
        await bot.send_message(ADMIN_ID, f"Пользователь {uid} запросил подсказку.")
        await message.reply("Запрос на подсказку отправлен организатору.")
        return
    # Сохраняем ответ
    user_answers[uid] = message.text
    await message.reply("Ответ получен. Ожидайте проверки.")

    # Отправляем админу уведомление с кнопками
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Принять", callback_data=f"accept_{uid}"))
    markup.add(InlineKeyboardButton("Отклонить", callback_data=f"reject_{uid}"))
    await bot.send_message(ADMIN_ID, f"Ответ от пользователя {uid}:\n{message.text}", reply_markup=markup)

# --- Приём фото ---

@dp.message_handler(lambda message: message.from_user.id in AUTHORIZED_USERS, content_types=types.ContentTypes.PHOTO)
async def photo_handler(message: types.Message):
    uid = message.from_user.id
    await message.reply("Фото получено. Спасибо!")
    # Можно также отправлять админу

# --- Приём локации ---

@dp.message_handler(lambda message: message.from_user.id in AUTHORIZED_USERS, content_types=types.ContentTypes.LOCATION)
async def location_handler(message: types.Message):
    uid = message.from_user.id
    loc = (message.location.latitude, message.location.longitude)
    # Проверяем по базовым локациям
    for loc_name, data in LOCATIONS.items():
        center = data['coords']
        radius = data['radius'] / 1000  # км
        dist = geodesic(center, loc).km
        if dist <= radius:
            await bot.send_message(ADMIN_ID, f"Пользователь {uid} в зоне '{loc_name}' (расстояние {dist*1000:.0f} м)")
            await message.reply(f"Вы в зоне локации: {loc_name}")
            return
    await message.reply("Локация вне допустимых зон.")

# --- Управление трансляцией локации ---

@dp.callback_query_handler(lambda c: c.from_user.id == ADMIN_ID and c.data.startswith(("start_loc_", "stop_loc_")))
async def toggle_live_location(call: types.CallbackQuery):
    data = call.data
    uid = int(data.split("_")[-1])
    if data.startswith("start_loc_"):
        user_live_location_status[uid] = True
        await call.answer(f"Трансляция для {uid} включена")
        await bot.send_message(uid, "Администратор попросил включить трансляцию локации.")
    elif data.startswith("stop_loc_"):
        user_live_location_status[uid] = False
        await call.answer(f"Трансляция для {uid} отключена")
        await bot.send_message(uid, "Администратор попросил отключить трансляцию локации.")

# --- Обработка кнопок принятия/отклонения ответов ---

@dp.callback_query_handler(lambda c: c.from_user.id == ADMIN_ID and c.data.startswith(("accept_", "reject_")))
async def answer_decision(call: types.CallbackQuery):
    data = call.data
    uid = int(data.split("_")[1])
    if data.startswith("accept_"):
        await bot.send_message(uid, "Ваш ответ принят. Следующее задание скоро будет.")
        # Выдаём следующее задание
        next_task = user_tasks.get(uid, 1) + 1
        if next_task in tasks:
            user_tasks[uid] = next_task
            await bot.send_message(uid, f"Новое задание:\n{tasks[next_task]}")
        else:
            await bot.send_message(uid, "Вы завершили все задания! Поздравляем!")
    elif data.startswith("reject_"):
        await bot.send_message(uid, "Ваш ответ отклонён. Попробуйте ещё раз.")
    await call.answer()

# --- Админ-команды ---

@dp.message_handler(lambda message: message.from_user.id == ADMIN_ID, commands=['send_hint'])
async def send_hint(message: types.Message):
    # Формат: /send_hint user_id текст подсказки
    try:
        parts = message.text.split(maxsplit=2)
        user_id = int(parts[1])
        hint = parts[2]
        await bot.send_message(user_id, f"Подсказка: {hint}")
        await message.reply("Подсказка отправлена.")
    except Exception as e:
        await message.reply(f"Ошибка: {e}")

@dp.message_handler(lambda message: message.from_user.id == ADMIN_ID, commands=['start_loc'])
async def admin_start_loc(message: types.Message):
    # Формат: /start_loc user_id
    try:
        user_id = int(message.text.split()[1])
        user_live_location_status[user_id] = True
        await bot.send_message(user_id, "Пожалуйста, включите трансляцию локации.")
        await message.reply(f"Запрос на включение локации отправлен {user_id}")
    except Exception as e:
        await message.reply(f"Ошибка: {e}")

@dp.message_handler(lambda message: message.from_user.id == ADMIN_ID, commands=['stop_loc'])
async def admin_stop_loc(message: types.Message):
    # Формат: /stop_loc user_id
    try:
        user_id = int(message.text.split()[1])
        user_live_location_status[user_id] = False
        await bot.send_message(user_id, "Пожалуйста, отключите трансляцию локации.")
        await message.reply(f"Запрос на отключение локации отправлен {user_id}")
    except Exception as e:
        await message.reply(f"Ошибка: {e}")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
