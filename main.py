import asyncio
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import io

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from extra_handlers import extra_router, process_quick_add

# Voice recognition
import speech_recognition as sr
from pydub import AudioSegment

# Setup logging
logging.basicConfig(level=logging.INFO)

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Initialize bot and dispatcher
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set. Please set it in your environment variables.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)
dp.include_router(extra_router)

# Timezone
from keyboards import (
    TZ, main_menu_kb, back_to_main_kb, jobs_menu_kb, employees_menu_kb,
    finance_menu_kb, select_employee_kb, date_kb
)
from states import (
    JobFSM, EmployeeFSM, ExpenseFSM, IncomeFSM, SalaryFSM, InventoryFSM
)

# --- DATABASE SETUP ---
from database import init_db, get_db_connection

init_db()

# --- HANDLERS: MAIN MENU ---
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("👋 Добро пожаловать в систему управления клининговой компанией!\nВыберите раздел:", reply_markup=main_menu_kb())

@router.message(F.text == "/help")
async def cmd_help(message: Message):
    help_text = (
        "🛠 **Справка по использованию бота:**\n\n"
        "1️⃣ **Быстрое добавление заявок:**\n"
        "Вы можете просто написать текст или отправить голосовое сообщение.\n"
        "Пример: `Анна 5000 2500 улица Ленина 10`\n"
        "Бот сам найдет сотрудника 'Анна', установит цену 5000, зарплату 2500 и адрес 'Улица Ленина 10'.\n\n"
        "2️⃣ **Отмена действий:**\n"
        "Если вы ошиблись при вводе данных, просто напишите слово `отмена` или `/cancel`.\n\n"
        "3️⃣ **Удаление записей:**\n"
        "В каждом разделе есть кнопка '❌ Удалить', где вы можете удалить последние записи по их ID.\n\n"
        "4️⃣ **Отчеты:**\n"
        "В разделе 'Отчет' вы можете выгрузить все данные в формате Excel (.xlsx)."
    )
    await message.answer(help_text, parse_mode="Markdown")

@router.message(F.text.lower().in_(["отмена", "cancel", "/cancel"]))
async def cancel_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        return
    await state.clear()
    await message.answer("❌ Действие отменено.", reply_markup=main_menu_kb())

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("📊 Главное меню:", reply_markup=main_menu_kb())

@router.callback_query(F.data == "menu_panel")
async def menu_panel(callback: CallbackQuery):
    conn = get_db_connection()
    today = datetime.now(TZ).strftime("%d.%m.%Y")
    
    jobs_today = conn.execute("SELECT COUNT(*) FROM jobs WHERE date = ?", (today,)).fetchone()[0]
    jobs_profit = conn.execute("SELECT SUM(profit) FROM jobs WHERE date = ?", (today,)).fetchone()[0] or 0
    expenses_today = conn.execute("SELECT SUM(amount) FROM expenses WHERE date = ?", (today,)).fetchone()[0] or 0
    income_today = conn.execute("SELECT SUM(amount) FROM income WHERE date = ?", (today,)).fetchone()[0] or 0
    salaries_today = conn.execute("SELECT SUM(amount) FROM salary_payments WHERE date = ?", (today,)).fetchone()[0] or 0
    
    conn.close()
    
    net_profit = jobs_profit + income_today - expenses_today
    
    text = (
        f"📊 **Сводка за сегодня ({today}):**\n\n"
        f"🧹 Заявок выполнено: {jobs_today}\n"
        f"📈 Прибыль с заявок: {jobs_profit} руб.\n"
        f"🎁 Доп. доходы: {income_today} руб.\n"
        f"📉 Расходы: {expenses_today} руб.\n"
        f"💸 Выплачено ЗП: {salaries_today} руб.\n\n"
        f"💰 **Чистая прибыль за день: {net_profit} руб.**"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_kb())

# --- HANDLERS: JOBS ---
@router.callback_query(F.data == "menu_jobs")
async def menu_jobs(callback: CallbackQuery):
    await callback.message.edit_text("🧹 **Управление заявками**", parse_mode="Markdown", reply_markup=jobs_menu_kb())

@router.callback_query(F.data == "job_add")
async def job_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Выберите сотрудника для заявки:", reply_markup=select_employee_kb())
    await state.set_state(JobFSM.employee_id)

@router.callback_query(JobFSM.employee_id, F.data.startswith("sel_emp_"))
async def job_add_emp(callback: CallbackQuery, state: FSMContext):
    emp_id = int(callback.data.split("_")[2])
    await state.update_data(employee_id=emp_id)
    await callback.message.edit_text("Введите имя клиента (или телефон):")
    await state.set_state(JobFSM.client_name)

@router.message(JobFSM.client_name)
async def job_add_client(message: Message, state: FSMContext):
    await state.update_data(client_name=message.text)
    await message.answer("Введите адрес объекта:")
    await state.set_state(JobFSM.address)

@router.message(JobFSM.address)
async def job_add_address(message: Message, state: FSMContext):
    await state.update_data(address=message.text)
    await message.answer("Введите цену заказа (только число):")
    await state.set_state(JobFSM.price)

@router.message(JobFSM.price)
async def job_add_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
        await state.update_data(price=price)
        await message.answer("Введите зарплату сотрудника за этот заказ (только число):")
        await state.set_state(JobFSM.employee_salary)
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число.")

@router.message(JobFSM.employee_salary)
async def job_add_salary(message: Message, state: FSMContext):
    try:
        salary = float(message.text.replace(",", "."))
        await state.update_data(employee_salary=salary)
        await message.answer("Выберите дату заявки:", reply_markup=date_kb("jobdate_"))
        await state.set_state(JobFSM.date)
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число.")

@router.callback_query(JobFSM.date, F.data.startswith("jobdate_"))
async def job_add_date_cb(callback: CallbackQuery, state: FSMContext):
    date_val = callback.data.split("_")[1]
    if date_val == "manual":
        await callback.message.edit_text("Введите дату в формате ДД.ММ.ГГГГ:")
        return
    await process_job_save(callback.message, state, date_val)

@router.message(JobFSM.date)
async def job_add_date_manual(message: Message, state: FSMContext):
    await process_job_save(message, state, message.text)

async def process_job_save(message: Message, state: FSMContext, date_str: str):
    data = await state.get_data()
    profit = data['price'] - data['employee_salary']
    
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO jobs (employee_id, client_name, address, price, employee_salary, profit, date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (data['employee_id'], data['client_name'], data['address'], data['price'], data['employee_salary'], profit, date_str))
    conn.commit()
    conn.close()
    
    await state.clear()
    text = f"✅ Заявка успешно добавлена!\n\nКлиент: {data['client_name']}\nАдрес: {data['address']}\nЦена: {data['price']}\nЗП: {data['employee_salary']}\nПрибыль: {profit}\nДата: {date_str}"
    
    if isinstance(message, Message):
        await message.answer(text, reply_markup=back_to_main_kb())
    else:
        await message.edit_text(text, reply_markup=back_to_main_kb())

@router.callback_query(F.data == "job_view")
async def job_view(callback: CallbackQuery):
    conn = get_db_connection()
    jobs = conn.execute('''
        SELECT j.id, e.name as emp_name, j.client_name, j.price, j.date 
        FROM jobs j JOIN employees e ON j.employee_id = e.id 
        ORDER BY j.id DESC LIMIT 10
    ''').fetchall()
    conn.close()
    
    if not jobs:
        await callback.message.edit_text("Заявок пока нет.", reply_markup=back_to_main_kb())
        return
        
    text = "📋 **Последние 10 заявок:**\n\n"
    for j in jobs:
        text += f"ID: {j['id']} | {j['date']} | {j['emp_name']} | {j['client_name']} | {j['price']} руб.\n"
        
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_kb())

# --- HANDLERS: EMPLOYEES ---
@router.callback_query(F.data == "menu_employees")
async def menu_employees(callback: CallbackQuery):
    await callback.message.edit_text("👥 **Сотрудники**", parse_mode="Markdown", reply_markup=employees_menu_kb())

@router.callback_query(F.data == "emp_add")
async def emp_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите ФИО сотрудника:")
    await state.set_state(EmployeeFSM.name)

@router.message(EmployeeFSM.name)
async def emp_add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите телефон сотрудника:")
    await state.set_state(EmployeeFSM.phone)

@router.message(EmployeeFSM.phone)
async def emp_add_phone(message: Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await message.answer("Введите должность (например, Клинер):")
    await state.set_state(EmployeeFSM.role)

@router.message(EmployeeFSM.role)
async def emp_add_role(message: Message, state: FSMContext):
    data = await state.get_data()
    role = message.text
    
    conn = get_db_connection()
    conn.execute('INSERT INTO employees (name, phone, role) VALUES (?, ?, ?)', (data['name'], data['phone'], role))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(f"✅ Сотрудник {data['name']} добавлен!", reply_markup=back_to_main_kb())

@router.callback_query(F.data == "emp_view")
async def emp_view(callback: CallbackQuery):
    conn = get_db_connection()
    emps = conn.execute('SELECT * FROM employees').fetchall()
    conn.close()
    
    if not emps:
        await callback.message.edit_text("Сотрудников пока нет.", reply_markup=back_to_main_kb())
        return
        
    text = "📋 **Список сотрудников:**\n\n"
    for e in emps:
        text += f"ID: {e['id']} | {e['name']} | {e['phone']} | {e['role']}\n"
        
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_kb())

@router.callback_query(F.data == "emp_stats")
async def emp_stats_start(callback: CallbackQuery):
    await callback.message.edit_text("Выберите сотрудника для просмотра статистики:", reply_markup=select_employee_kb("stat_emp_"))

@router.callback_query(F.data.startswith("stat_emp_"))
async def emp_stats_view(callback: CallbackQuery):
    emp_id = int(callback.data.split("_")[2])
    conn = get_db_connection()
    
    emp = conn.execute("SELECT * FROM employees WHERE id = ?", (emp_id,)).fetchone()
    if not emp:
        await callback.message.edit_text("Сотрудник не найден.", reply_markup=back_to_main_kb())
        conn.close()
        return
        
    jobs_count = conn.execute("SELECT COUNT(*) FROM jobs WHERE employee_id = ?", (emp_id,)).fetchone()[0]
    total_earned = conn.execute("SELECT SUM(employee_salary) FROM jobs WHERE employee_id = ?", (emp_id,)).fetchone()[0] or 0
    total_paid = conn.execute("SELECT SUM(amount) FROM salary_payments WHERE employee_id = ?", (emp_id,)).fetchone()[0] or 0
    
    conn.close()
    
    balance = total_earned - total_paid
    
    text = (
        f"📈 **Статистика: {emp['name']}**\n"
        f"Должность: {emp['role']}\n"
        f"Телефон: {emp['phone']}\n\n"
        f"🧹 Выполнено заявок: {jobs_count}\n"
        f"💰 Заработано всего: {total_earned} руб.\n"
        f"💸 Выплачено всего: {total_paid} руб.\n\n"
        f"⚖️ **Текущий баланс (долг): {balance} руб.**"
    )
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_kb())

# --- HANDLERS: EXPENSES ---
@router.callback_query(F.data == "menu_expenses")
async def menu_expenses(callback: CallbackQuery):
    await callback.message.edit_text("📉 **Расходы**", parse_mode="Markdown", reply_markup=finance_menu_kb("exp"))

@router.callback_query(F.data == "exp_add")
async def exp_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите категорию расхода (например, Химия, Бензин):")
    await state.set_state(ExpenseFSM.category)

@router.message(ExpenseFSM.category)
async def exp_add_cat(message: Message, state: FSMContext):
    await state.update_data(category=message.text)
    await message.answer("Введите сумму (только число):")
    await state.set_state(ExpenseFSM.amount)

@router.message(ExpenseFSM.amount)
async def exp_add_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        await state.update_data(amount=amount)
        await message.answer("Введите комментарий:")
        await state.set_state(ExpenseFSM.comment)
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число.")

@router.message(ExpenseFSM.comment)
async def exp_add_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    comment = message.text
    date_str = datetime.now(TZ).strftime("%d.%m.%Y")
    
    conn = get_db_connection()
    conn.execute('INSERT INTO expenses (category, amount, comment, date) VALUES (?, ?, ?, ?)', 
                 (data['category'], data['amount'], comment, date_str))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(f"✅ Расход добавлен!\nСумма: {data['amount']} руб.\nКатегория: {data['category']}", reply_markup=back_to_main_kb())

@router.callback_query(F.data == "exp_view")
async def exp_view(callback: CallbackQuery):
    conn = get_db_connection()
    exps = conn.execute('SELECT * FROM expenses ORDER BY id DESC LIMIT 10').fetchall()
    conn.close()
    
    if not exps:
        await callback.message.edit_text("Расходов пока нет.", reply_markup=back_to_main_kb())
        return
        
    text = "📋 **Последние 10 расходов:**\n\n"
    for e in exps:
        text += f"{e['date']} | {e['category']} | {e['amount']} руб. | {e['comment']}\n"
        
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_kb())

# --- HANDLERS: REPORTS & STATISTICS ---
@router.callback_query(F.data == "menu_reports")
async def menu_reports(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Месячный отчет", callback_data="rep_month")],
        [InlineKeyboardButton(text="🏆 Топ сотрудник", callback_data="rep_top_emp")],
        [InlineKeyboardButton(text="📊 Экспорт в Excel", callback_data="export_excel")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])
    await callback.message.edit_text("📑 **Отчеты**", parse_mode="Markdown", reply_markup=kb)

@router.callback_query(F.data == "rep_month")
async def rep_month(callback: CallbackQuery):
    current_month = datetime.now(TZ).strftime(".%m.%Y")
    conn = get_db_connection()
    
    # Income from jobs
    jobs_income = conn.execute("SELECT SUM(price) FROM jobs WHERE date LIKE ?", (f"%{current_month}",)).fetchone()[0] or 0
    jobs_profit = conn.execute("SELECT SUM(profit) FROM jobs WHERE date LIKE ?", (f"%{current_month}",)).fetchone()[0] or 0
    
    # Other income
    other_income = conn.execute("SELECT SUM(amount) FROM income WHERE date LIKE ?", (f"%{current_month}",)).fetchone()[0] or 0
    
    # Expenses
    expenses = conn.execute("SELECT SUM(amount) FROM expenses WHERE date LIKE ?", (f"%{current_month}",)).fetchone()[0] or 0
    
    # Salaries
    salaries = conn.execute("SELECT SUM(amount) FROM salary_payments WHERE date LIKE ?", (f"%{current_month}",)).fetchone()[0] or 0
    
    conn.close()
    
    total_income = jobs_income + other_income
    net_profit = jobs_profit + other_income - expenses
    
    text = f"📅 **Отчет за текущий месяц ({current_month})**\n\n"
    text += f"📈 Оборот (заявки): {jobs_income} руб.\n"
    text += f"📈 Доп. доходы: {other_income} руб.\n"
    text += f"📉 Расходы: {expenses} руб.\n"
    text += f"💸 Выплачено ЗП: {salaries} руб.\n"
    text += f"💰 **Чистая прибыль: {net_profit} руб.**"
    
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_kb())

@router.callback_query(F.data == "rep_top_emp")
async def rep_top_emp(callback: CallbackQuery):
    current_month = datetime.now(TZ).strftime(".%m.%Y")
    conn = get_db_connection()
    
    top_emps = conn.execute('''
        SELECT e.name, COUNT(j.id) as job_count, SUM(j.price) as total_brought
        FROM jobs j
        JOIN employees e ON j.employee_id = e.id
        WHERE j.date LIKE ?
        GROUP BY e.id
        ORDER BY total_brought DESC
        LIMIT 5
    ''', (f"%{current_month}",)).fetchall()
    
    conn.close()
    
    if not top_emps:
        await callback.message.edit_text("Нет данных за этот месяц.", reply_markup=back_to_main_kb())
        return
        
    text = f"🏆 **Топ сотрудников за месяц ({current_month})**\n\n"
    for i, emp in enumerate(top_emps, 1):
        text += f"{i}. {emp['name']} — {emp['job_count']} заявок, принес {emp['total_brought']} руб.\n"
        
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_to_main_kb())

# --- VOICE RECOGNITION ---
@router.message(F.voice)
async def handle_voice(message: Message):
    msg = await message.answer("⏳ Обработка голосового сообщения...")
    try:
        # Download voice
        file_id = message.voice.file_id
        file = await bot.get_file(file_id)
        file_path = file.file_path
        
        voice_io = io.BytesIO()
        await bot.download_file(file_path, voice_io)
        voice_io.seek(0)
        
        # Convert ogg to wav
        audio = AudioSegment.from_file(voice_io, format="ogg")
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        
        # Recognize
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_io) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="ru-RU")
            
        await msg.delete()
        await process_quick_add(text, message)
    except Exception as e:
        logging.error(f"Voice recognition error: {e}")
        await msg.edit_text("❌ Не удалось распознать голосовое сообщение. Убедитесь, что установлен ffmpeg.", reply_markup=back_to_main_kb())

# --- MAIN RUNNER ---
async def main():
    logging.info("Starting bot...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
