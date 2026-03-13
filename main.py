import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import database as db
from ai_parser import parse_message, transcribe_audio

logging.basicConfig(level=logging.INFO)
bot = Bot(token=os.getenv("BOT_TOKEN", "YOUR_TOKEN"))
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# --- ROLE CHECKING & AUTH ---
async def check_access(message: types.Message):
    user = await db.get_user(message.from_user.id)
    if not user:
        admin = await db.create_admin(message.from_user.id)
        if admin:
            await message.answer("👑 Вы зарегистрированы как Главный Руководитель.")
            return admin
    return user

# --- COMMAND HANDLERS ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    args = message.text.split()
    if len(args) > 1:
        user = await db.register_user(args[1], message.from_user.id)
        if user:
            return await message.answer(f"✅ Добро пожаловать, {user.name}! Вы в системе.")
        return await message.answer("❌ Неверный или устаревший invite-код.")
    
    user = await check_access(message)
    if not user:
        return await message.answer("⛔️ Доступ ограничен. Используйте invite-ссылку.")
    
    if user.role == db.Role.ADMIN:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧹 Заказы", callback_data="orders"), InlineKeyboardButton(text="👥 Сотрудники", callback_data="employees")],
            [InlineKeyboardButton(text="💰 Финансы", callback_data="finance"), InlineKeyboardButton(text="📊 Отчёты", callback_data="reports")]
        ])
        await message.answer("🏢 Главное меню (Руководитель):", reply_markup=kb)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧹 Мои заказы", callback_data="my_orders"), InlineKeyboardButton(text="💳 Мой баланс", callback_data="my_balance")]
        ])
        await message.answer("👷‍♂️ Главное меню (Сотрудник):", reply_markup=kb)

@dp.message(Command("invite"))
async def cmd_invite(message: types.Message):
    user = await check_access(message)
    if user and user.role == db.Role.ADMIN:
        name = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else "Сотрудник"
        code = await db.create_invite(name)
        bot_info = await bot.get_me()
        await message.answer(f"🔗 Invite-ссылка для {name}:\n`https://t.me/{bot_info.username}?start={code}`", parse_mode="Markdown")

# --- INLINE KEYBOARDS & CALLBACKS ---
@dp.callback_query()
async def handle_callbacks(call: types.CallbackQuery):
    user = await db.get_user(call.from_user.id)
    if not user: return await call.answer("Доступ запрещен", show_alert=True)

    if call.data == "reports" and user.role == db.Role.ADMIN:
        stats = await db.get_stats("day")
        await call.message.answer(f"📊 Отчет за день:\nДоход: {stats['income']}₽\nРасход: {stats['expense']}₽\nПрибыль: {stats['profit']}₽")
    elif call.data == "employees" and user.role == db.Role.ADMIN:
        emps = await db.get_all_employees()
        text = "👥 Сотрудники:\n" + "\n".join([f"- {e.name} (Баланс: {e.balance}₽)" for e in emps]) if emps else "Нет сотрудников."
        await call.message.answer(text)
    elif call.data == "orders" and user.role == db.Role.ADMIN:
        orders = await db.get_orders()
        text = "🧹 Все заказы:\n" + "\n".join([f"- {o.address} ({o.price}₽) [{o.status.value}]" for o in orders]) if orders else "Заказов нет."
        await call.message.answer(text)
    elif call.data == "my_orders" and user.role == db.Role.EMPLOYEE:
        orders = await db.get_orders(user.id)
        text = "🧹 Ваши заказы:\n" + "\n".join([f"- {o.address} ({o.price}₽)" for o in orders]) if orders else "Заказов нет."
        await call.message.answer(text)
    elif call.data == "my_balance" and user.role == db.Role.EMPLOYEE:
        await call.message.answer(f"💳 Ваш текущий баланс: {user.balance} ₽")
    await call.answer()

# --- VOICE & TEXT MESSAGE PROCESSING ---
@dp.message(F.voice)
async def handle_voice(message: types.Message):
    user = await check_access(message)
    if user and user.role == db.Role.ADMIN:
        msg = await message.answer("🎙 Распознаю голосовое сообщение...")
        file = await bot.get_file(message.voice.file_id)
        path = f"voice_{message.voice.file_id}.ogg"
        await bot.download_file(file.file_path, path)
        text = await transcribe_audio(path)
        os.remove(path)
        await msg.edit_text(f"🗣 Распознано: _{text}_", parse_mode="Markdown")
        await process_business_logic(message, text, user)

@dp.message(F.text)
async def handle_text(message: types.Message):
    user = await check_access(message)
    if user and user.role == db.Role.ADMIN:
        await process_business_logic(message, message.text, user)
    elif user:
        await message.answer("ℹ️ Сотрудники используют только кнопки меню.")

# --- MAIN BUSINESS LOGIC ---
async def process_business_logic(message: types.Message, text: str, user):
    msg = await message.answer("🤖 Анализирую запрос...")
    data = await parse_message(text)
    
    action = data.get("action_type")
    if action == "finance":
        emp = await db.get_user_by_name(data.get("employee_name", "")) if data.get("employee_name") else None
        await db.add_transaction(data.get("amount", 0), data.get("category", "expense"), data.get("comment", ""), emp.id if emp else None)
        await msg.edit_text(f"✅ Финансы сохранены:\nКатегория: {data.get('category')}\nСумма: {data.get('amount')}₽")
    
    elif action == "order":
        emp = await db.get_user_by_name(data.get("employee_name", "")) if data.get("employee_name") else None
        await db.create_order(data.get("address", "Не указан"), data.get("price", 0), data.get("clean_type", "Стандарт"), assigned_to=emp.id if emp else None)
        await msg.edit_text(f"✅ Заказ создан:\nАдрес: {data.get('address')}\nЦена: {data.get('price')}₽")
    
    elif action == "analytics":
        stats = await db.get_stats(data.get("period", "day"))
        await msg.edit_text(f"📊 Аналитика ({data.get('period', 'day')}):\nДоход: {stats['income']}₽\nРасход: {stats['expense']}₽\nПрибыль: {stats['profit']}₽")
    
    else:
        await msg.edit_text("❓ Не удалось распознать команду. Попробуйте иначе.")

# --- DAILY REPORTS ---
async def daily_report():
    async with db.AsyncSessionLocal() as session:
        admin = (await session.execute(db.select(db.User).where(db.User.role == db.Role.ADMIN))).scalars().first()
        if admin and admin.tg_id:
            stats = await db.get_stats("day")
            await bot.send_message(admin.tg_id, f"📈 Итоги дня:\nДоход: {stats['income']}₽\nРасход: {stats['expense']}₽\nПрибыль: {stats['profit']}₽")

async def main():
    await db.init_db()
    scheduler.add_job(daily_report, 'cron', hour=20)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())