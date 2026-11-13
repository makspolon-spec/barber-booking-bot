import asyncio
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

OWNER_ID = 0  # вставьте ваш Telegram ID (узнать: команда /id в боте)

bot = Bot(token=os.environ["BOT_TOKEN"])
dp = Dispatcher()


class Booking(StatesGroup):
    service = State()
    time = State()
    contact = State()


menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📝 Записаться")],
        [KeyboardButton(text="💈 Услуги"), KeyboardButton(text="💰 Цены")],
        [KeyboardButton(text="📍 Контакты")],
    ],
    resize_keyboard=True,
)

services_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Стрижка"), KeyboardButton(text="Борода")],
        [KeyboardButton(text="Стрижка + борода")],
        [KeyboardButton(text="❌ Отмена")],
    ],
    resize_keyboard=True,
)

cancel_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Отмена")]],
    resize_keyboard=True,
)


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer("Привет! Выберите, что вас интересует:", reply_markup=menu)


@dp.message(Command("id"))
async def show_id(message: Message):
    await message.answer(f"Ваш ID: {message.from_user.id}")


@dp.message(F.text == "❌ Отмена")
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Запись отменена.", reply_markup=menu)


@dp.message(F.text == "📝 Записаться")
async def book_start(message: Message, state: FSMContext):
    await state.set_state(Booking.service)
    await message.answer("Выберите услугу:", reply_markup=services_kb)


@dp.message(Booking.service)
async def book_service(message: Message, state: FSMContext):
    await state.update_data(service=message.text)
    await state.set_state(Booking.time)
    await message.answer("Напишите удобные дату и время, например: завтра в 15:00", reply_markup=cancel_kb)


@dp.message(Booking.time)
async def book_time(message: Message, state: FSMContext):
    await state.update_data(time=message.text)
    await state.set_state(Booking.contact)
    await message.answer("Напишите ваше имя и номер телефона:", reply_markup=cancel_kb)


@dp.message(Booking.contact)
async def book_contact(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    text = (
        "🔔 Новая заявка!\n"
        f"Услуга: {data['service']}\n"
        f"Время: {data['time']}\n"
        f"Контакт: {message.text}"
    )
    if OWNER_ID:
        await bot.send_message(OWNER_ID, text)
    await message.answer("Спасибо! Заявка отправлена, мастер свяжется с вами.", reply_markup=menu)


@dp.message(F.text == "💈 Услуги")
async def services(message: Message):
    await message.answer("Наши услуги:\n• Мужская стрижка\n• Оформление бороды\n• Стрижка + борода")


@dp.message(F.text == "💰 Цены")
async def prices(message: Message):
    await message.answer("Цены:\n• Стрижка: 400 грн\n• Борода: 250 грн\n• Стрижка + борода: 600 грн")


@dp.message(F.text == "📍 Контакты")
async def contacts(message: Message):
    await message.answer("Адрес: ул. Примерная, 1\nТелефон: +380 00 000 00 00\nРаботаем: 10:00-20:00")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
