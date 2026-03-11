import asyncio
import io
import logging
import os
import sqlite3
from datetime import datetime
import pytz

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

import speech_recognition as sr
from pydub import AudioSegment

# Setup logging
logging.basicConfig(level=logging.INFO)

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logging.warning("BOT_TOKEN environment variable is not set!")

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()

# Timezone
TZ = pytz.timezone('Europe/Moscow')

def get_now():
    """Returns current date in DD.MM.YYYY format"""
    return datetime.now(TZ).strftime("%d.%m.%Y")

# Database setup
DB_NAME = "cleaning_erp.db"

def execute_query(query, params=(), fetch=False, fetchall=False):
    """Helper function to execute database queries"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(query, params)
    if fetch:
        res = cursor.fetchone()
    elif fetchall:
        res = cursor.fetchall()
    else:
        conn.commit()
        res = None
    conn.close()
    return res

def init_db():
    """Initialize database tables"""
    queries = [
        '''CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, phone TEXT, role TEXT, created_at TEXT
        )''',
        '''CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, phone TEXT, address TEXT, created_at TEXT
        )''',
        '''CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee TEXT, client TEXT, address TEXT,
            price REAL, employee_salary REAL, profit REAL,
            date TEXT, created_at TEXT
        )''',
        '''CREATE TABLE IF NOT EXISTS salary_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee TEXT, amount REAL, type TEXT,
            comment TEXT, date TEXT, created_at TEXT
        )''',
        '''CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT, amount REAL, comment TEXT,
            date TEXT, created_at TEXT
        )''',
        '''CREATE TABLE IF NOT EXISTS income (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT, amount REAL, comment TEXT,
            date TEXT, created_at TEXT
        )''',
        '''CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT, quantity REAL, price REAL, created_at TEXT
        )'''
    ]
    for q in queries:
        execute_query(q)

init_db()

# Keyboards
menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Панель"), KeyboardButton(text="🧹 Заявки"), KeyboardButton(text="👥 Сотрудники")],
        [KeyboardButton(text="💰 Зарплаты"), KeyboardButton(text="📉 Расходы"), KeyboardButton(text="📈 Доходы")],
        [KeyboardButton(text="📦 Склад"), KeyboardButton(text="📊 Статистика"), KeyboardButton(text="📑 Отчет")]
    ],
    resize_keyboard=True
)

# FSM States for Job Creation
class JobForm(StatesGroup):
    employee = State()
    client = State()
    address = State()
    price = State()
    salary = State()

# Smart Parser
def parse_message(text: str):
    """Parses natural Russian text to extract commands and data"""
    text = text.lower().strip()
    words = text.split()
    if not words: return None
    
    # Inventory: добавить химия 5 / списать химия 2
    if words[0] in ['добавить', 'списать'] and len(words) >= 3:
        try:
            qty = float(words[-1])
            item = " ".join(words[1:-1]).capitalize()
            return {"type": "inventory", "action": words[0], "item": item, "qty": qty}
        except ValueError:
            pass
            
    # Job: "анна пушкина 10 12000 зарплата 4000"
    if 'зарплата' in words:
        z_idx = words.index('зарплата')
        if z_idx >= 3 and z_idx + 1 < len(words):
            try:
                salary = float(words[z_idx + 1])
                price = float(words[z_idx - 1])
                employee = words[0].capitalize()
                client_address = " ".join(words[1:z_idx - 1]).title()
                return {"type": "job", "employee": employee, "client": client_address, "price": price, "salary": salary}
            except ValueError:
                pass
                
        # Salary payment: "вася 3000 зарплата"
        try:
            amount = next(float(w) for w in words if w.isdigit())
            employee = next(w.capitalize() for w in words if w != 'зарплата' and not w.isdigit())
            return {"type": "salary_payment", "employee": employee, "amount": amount, "payment_type": "зарплата"}
        except StopIteration:
            pass
            
    # Advance payment: "анна 5000 аванс"
    if 'аванс' in words:
        try:
            amount = next(float(w) for w in words if w.isdigit())
            employee = next(w.capitalize() for w in words if w != 'аванс' and not w.isdigit())
            return {"type": "salary_payment", "employee": employee, "amount": amount, "payment_type": "аванс"}
        except StopIteration:
            pass

    # Income: "клиент 15000" or "доход 15000"
    if 'доход' in words or 'клиент' in words:
        try:
            amount = next(float(w) for w in words if w.isdigit())
            source = " ".join([w for w in words if not w.isdigit()]).capitalize()
            return {"type": "income", "source": source, "amount": amount}
        except StopIteration:
            pass

    # Expense: "химия 2000" or "бензин 1500"
    try:
        numbers = [float(w) for w in words if w.isdigit()]
        if len(numbers) == 1:
            amount = numbers[0]
            category = " ".join([w for w in words if not w.isdigit()]).capitalize()
            return {"type": "expense", "category": category, "amount": amount}
    except Exception:
        pass

    return None

async def process_text_message(message: types.Message, text: str):
    parsed = parse_message(text)
    if not parsed:
        await message.answer("Не удалось распознать команду. Попробуйте переформулировать.")
        return
        
    now = get_now()
    
    if parsed["type"] == "job":
        profit = parsed["price"] - parsed["salary"]
        execute_query(
            "INSERT INTO jobs (employee, client, address, price, employee_salary, profit, date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (parsed["employee"], parsed["client"], parsed["client"], parsed["price"], parsed["salary"], profit, now, now)
        )
        await message.answer(f"✅ **Заявка сохранена!**\n\n"
                             f"Сотрудник: {parsed['employee']}\n"
                             f"Клиент/Адрес: {parsed['client']}\n"
                             f"Цена: {parsed['price']}\n"
                             f"Зарплата: {parsed['salary']}\n"
                             f"Прибыль: {profit}", parse_mode="Markdown")
                             
    elif parsed["type"] == "salary_payment":
        execute_query(
            "INSERT INTO salary_payments (employee, amount, type, comment, date, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (parsed["employee"], parsed["amount"], parsed["payment_type"], "Smart Parser", now, now)
        )
        await message.answer(f"✅ **{parsed['payment_type'].capitalize()} записан(а)!**\n\n"
                             f"Сотрудник: {parsed['employee']}\n"
                             f"Сумма: {parsed['amount']}", parse_mode="Markdown")
                             
    elif parsed["type"] == "expense":
        execute_query(
            "INSERT INTO expenses (category, amount, comment, date, created_at) VALUES (?, ?, ?, ?, ?)",
            (parsed["category"], parsed["amount"], "Smart Parser", now, now)
        )
        await message.answer(f"✅ **Расход сохранен!**\n\n"
                             f"Категория: {parsed['category']}\n"
                             f"Сумма: {parsed['amount']}", parse_mode="Markdown")
                             
    elif parsed["type"] == "income":
        execute_query(
            "INSERT INTO income (source, amount, comment, date, created_at) VALUES (?, ?, ?, ?, ?)",
            (parsed["source"], parsed["amount"], "Smart Parser", now, now)
        )
        await message.answer(f"✅ **Доход сохранен!**\n\n"
                             f"Источник: {parsed['source']}\n"
                             f"Сумма: {parsed['amount']}", parse_mode="Markdown")
                             
    elif parsed["type"] == "inventory":
        item = parsed["item"]
        qty = parsed["qty"]
        action = parsed["action"]
        
        existing = execute_query("SELECT quantity FROM inventory WHERE item_name=?", (item,), fetch=True)
        if existing:
            new_qty = existing[0] + qty if action == "добавить" else existing[0] - qty
            execute_query("UPDATE inventory SET quantity=? WHERE item_name=?", (new_qty, item))
        else:
            new_qty = qty if action == "добавить" else -qty
            execute_query("INSERT INTO inventory (item_name, quantity, price, created_at) VALUES (?, ?, ?, ?)", (item, new_qty, 0, now))
            
        await message.answer(f"✅ **Склад обновлен!**\n\n"
                             f"Товар: {item}\n"
                             f"Действие: {action} {qty}\n"
                             f"Остаток: {new_qty}", parse_mode="Markdown")

# --- Handlers ---

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer("👋 Добро пожаловать в систему управления клининговой компанией!\n\n"
                         "Вы можете использовать кнопки меню или писать запросы естественным языком.\n"
                         "Например:\n"
                         "• Анна 5000 аванс\n"
                         "• химия 2000\n"
                         "• Анна Пушкина 10 12000 зарплата 4000", reply_markup=menu_kb)

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = """
🛠 **Доступные команды и форматы:**

**Умный ввод (текст или голос):**
• `Анна 5000 аванс` - Выдать аванс
• `Вася 3000 зарплата` - Выплатить зарплату
• `химия 2000` - Записать расход
• `клиент 15000` - Записать доход
• `Анна Пушкина 10 12000 зарплата 4000` - Создать заявку
• `добавить химия 5` - Пополнить склад
• `списать химия 2` - Списать со склада

**Команды:**
/balance [Имя] - Баланс сотрудника
/stats - Статистика
/report - Отчет
/job - Создать заявку по шагам
/add_employee [Имя] - Добавить сотрудника
/delete_employee [Имя] - Удалить сотрудника
    """
    await message.answer(help_text, parse_mode="Markdown")

@dp.message(Command("add_employee"))
async def cmd_add_employee(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Укажите имя сотрудника: /add_employee Анна")
        return
    
    employee = args[1].capitalize()
    now = get_now()
    execute_query("INSERT INTO employees (name, created_at) VALUES (?, ?)", (employee, now))
    await message.answer(f"✅ Сотрудник {employee} добавлен.")

@dp.message(Command("delete_employee"))
async def cmd_delete_employee(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Укажите имя сотрудника: /delete_employee Анна")
        return
    
    employee = args[1].capitalize()
    execute_query("DELETE FROM employees WHERE name=?", (employee,))
    await message.answer(f"✅ Сотрудник {employee} удален.")

@dp.message(Command("balance"))
async def cmd_balance(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Укажите имя сотрудника: /balance Анна")
        return
    
    employee = args[1].capitalize()
    
    jobs = execute_query("SELECT SUM(employee_salary), COUNT(id) FROM jobs WHERE employee=?", (employee,), fetch=True)
    earned = jobs[0] or 0
    jobs_count = jobs[1] or 0
    
    payments = execute_query("SELECT SUM(amount) FROM salary_payments WHERE employee=?", (employee,), fetch=True)
    paid = payments[0] or 0
    
    balance = earned - paid
    
    await message.answer(f"👤 **Баланс: {employee}**\n\n"
                         f"Выполнено заявок: {jobs_count}\n"
                         f"Заработано: {earned} руб.\n"
                         f"Выплачено: {paid} руб.\n"
                         f"К выплате: {balance} руб.", parse_mode="Markdown")

@dp.message(Command("stats"))
@dp.message(Command("today"))
@dp.message(Command("dashboard"))
@dp.message(F.text.in_({"📊 Панель", "📊 Статистика"}))
async def cmd_stats(message: types.Message):
    today = get_now()
    month = today[3:] # MM.YYYY
    
    # Today
    t_income = execute_query("SELECT SUM(amount) FROM income WHERE date=?", (today,), fetch=True)[0] or 0
    t_jobs_price = execute_query("SELECT SUM(price) FROM jobs WHERE date=?", (today,), fetch=True)[0] or 0
    t_total_income = t_income + t_jobs_price
    
    t_expenses = execute_query("SELECT SUM(amount) FROM expenses WHERE date=?", (today,), fetch=True)[0] or 0
    t_salaries = execute_query("SELECT SUM(employee_salary) FROM jobs WHERE date=?", (today,), fetch=True)[0] or 0
    t_profit = t_total_income - t_expenses - t_salaries
    
    # Month
    m_income = execute_query("SELECT SUM(amount) FROM income WHERE date LIKE ?", (f"%{month}",), fetch=True)[0] or 0
    m_jobs_price = execute_query("SELECT SUM(price) FROM jobs WHERE date LIKE ?", (f"%{month}",), fetch=True)[0] or 0
    m_total_income = m_income + m_jobs_price
    
    m_expenses = execute_query("SELECT SUM(amount) FROM expenses WHERE date LIKE ?", (f"%{month}",), fetch=True)[0] or 0
    m_salaries = execute_query("SELECT SUM(employee_salary) FROM jobs WHERE date LIKE ?", (f"%{month}",), fetch=True)[0] or 0
    m_profit = m_total_income - m_expenses - m_salaries
    
    await message.answer(f"📊 **Статистика**\n\n"
                         f"**Сегодня ({today}):**\n"
                         f"Доход: {t_total_income}\n"
                         f"Расходы: {t_expenses}\n"
                         f"Зарплаты: {t_salaries}\n"
                         f"Чистая прибыль: {t_profit}\n\n"
                         f"**Этот месяц ({month}):**\n"
                         f"Доход: {m_total_income}\n"
                         f"Расходы: {m_expenses}\n"
                         f"Зарплаты: {m_salaries}\n"
                         f"Чистая прибыль: {m_profit}", parse_mode="Markdown")

@dp.message(Command("report"))
@dp.message(F.text == "📑 Отчет")
async def cmd_report(message: types.Message):
    month = get_now()[3:]
    
    m_jobs_count = execute_query("SELECT COUNT(id), SUM(price), SUM(profit) FROM jobs WHERE date LIKE ?", (f"%{month}",), fetch=True)
    jobs_count = m_jobs_count[0] or 0
    total_price = m_jobs_count[1] or 0
    total_profit = m_jobs_count[2] or 0
    
    avg_check = round(total_price / jobs_count, 2) if jobs_count > 0 else 0
    
    top_employee = execute_query("SELECT employee, COUNT(id) as c FROM jobs WHERE date LIKE ? GROUP BY employee ORDER BY c DESC LIMIT 1", (f"%{month}",), fetch=True)
    top_emp_name = top_employee[0] if top_employee else "Нет данных"
    
    await message.answer(f"📑 **Отчет за {month}**\n\n"
                         f"Всего заявок: {jobs_count}\n"
                         f"Средний чек: {avg_check} руб.\n"
                         f"Прибыль с заявок: {total_profit} руб.\n"
                         f"Лучший сотрудник: {top_emp_name}", parse_mode="Markdown")

@dp.message(Command("inventory"))
@dp.message(F.text == "📦 Склад")
async def cmd_inventory(message: types.Message):
    items = execute_query("SELECT item_name, quantity FROM inventory", fetchall=True)
    if not items:
        await message.answer("Склад пуст.")
        return
    
    text = "📦 **Склад:**\n\n"
    for item in items:
        text += f"• {item[0]}: {item[1]} шт.\n"
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("jobs"))
@dp.message(F.text == "🧹 Заявки")
async def show_jobs(message: types.Message):
    jobs = execute_query("SELECT employee, client, price, date FROM jobs ORDER BY id DESC LIMIT 5", fetchall=True)
    if not jobs:
        await message.answer("Заявок пока нет.")
        return
    res = "🧹 **Последние 5 заявок:**\n\n"
    for j in jobs:
        res += f"• {j[3]} | {j[0]} | {j[1]} | {j[2]} руб.\n"
    await message.answer(res, parse_mode="Markdown")

@dp.message(Command("employees"))
@dp.message(F.text == "👥 Сотрудники")
async def show_employees(message: types.Message):
    emps = execute_query("SELECT DISTINCT employee FROM jobs", fetchall=True)
    if not emps:
        await message.answer("Сотрудников пока нет.")
        return
    res = "👥 **Сотрудники:**\n\n"
    for e in emps:
        res += f"• {e[0]}\n"
    await message.answer(res, parse_mode="Markdown")

@dp.message(Command("salary"))
@dp.message(F.text == "💰 Зарплаты")
async def show_salaries(message: types.Message):
    payments = execute_query("SELECT employee, amount, type, date FROM salary_payments ORDER BY id DESC LIMIT 5", fetchall=True)
    if not payments:
        await message.answer("Выплат пока нет.")
        return
    res = "💰 **Последние выплаты:**\n\n"
    for p in payments:
        res += f"• {p[3]} | {p[0]} | {p[2]} | {p[1]} руб.\n"
    await message.answer(res, parse_mode="Markdown")

@dp.message(Command("expenses"))
@dp.message(F.text == "📉 Расходы")
async def show_expenses(message: types.Message):
    expenses = execute_query("SELECT category, amount, date FROM expenses ORDER BY id DESC LIMIT 5", fetchall=True)
    if not expenses:
        await message.answer("Расходов пока нет.")
        return
    res = "📉 **Последние расходы:**\n\n"
    for e in expenses:
        res += f"• {e[2]} | {e[0]} | {e[1]} руб.\n"
    await message.answer(res, parse_mode="Markdown")

@dp.message(Command("income"))
@dp.message(F.text == "📈 Доходы")
async def show_incomes(message: types.Message):
    incomes = execute_query("SELECT source, amount, date FROM income ORDER BY id DESC LIMIT 5", fetchall=True)
    if not incomes:
        await message.answer("Доходов пока нет.")
        return
    res = "📈 **Последние доходы:**\n\n"
    for i in incomes:
        res += f"• {i[2]} | {i[0]} | {i[1]} руб.\n"
    await message.answer(res, parse_mode="Markdown")

# --- Step-by-step Job Creation ---

@dp.message(Command("job"))
async def cmd_job(message: types.Message, state: FSMContext):
    await message.answer("Введите имя сотрудника:")
    await state.set_state(JobForm.employee)

@dp.message(JobForm.employee)
async def process_employee(message: types.Message, state: FSMContext):
    await state.update_data(employee=message.text.capitalize())
    await message.answer("Введите имя клиента (или адрес):")
    await state.set_state(JobForm.client)

@dp.message(JobForm.client)
async def process_client(message: types.Message, state: FSMContext):
    await state.update_data(client=message.text)
    await message.answer("Введите адрес:")
    await state.set_state(JobForm.address)

@dp.message(JobForm.address)
async def process_address(message: types.Message, state: FSMContext):
    await state.update_data(address=message.text)
    await message.answer("Введите цену заказа (число):")
    await state.set_state(JobForm.price)

@dp.message(JobForm.price)
async def process_price(message: types.Message, state: FSMContext):
    try:
        price = float(message.text)
        await state.update_data(price=price)
        await message.answer("Введите зарплату сотрудника (число):")
        await state.set_state(JobForm.salary)
    except ValueError:
        await message.answer("Пожалуйста, введите число.")

@dp.message(JobForm.salary)
async def process_salary(message: types.Message, state: FSMContext):
    try:
        salary = float(message.text)
        data = await state.get_data()
        
        profit = data['price'] - salary
        now = get_now()
        
        execute_query(
            "INSERT INTO jobs (employee, client, address, price, employee_salary, profit, date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (data['employee'], data['client'], data['address'], data['price'], salary, profit, now, now)
        )
        
        await message.answer(f"✅ **Заявка сохранена!**\n\n"
                             f"Сотрудник: {data['employee']}\n"
                             f"Клиент: {data['client']}\n"
                             f"Адрес: {data['address']}\n"
                             f"Цена: {data['price']}\n"
                             f"Зарплата: {salary}\n"
                             f"Прибыль: {profit}", parse_mode="Markdown")
        await state.clear()
    except ValueError:
        await message.answer("Пожалуйста, введите число.")

# --- Voice Processing ---

@dp.message(F.voice)
async def handle_voice(message: types.Message, bot: Bot):
    msg = await message.answer("⏳ Обработка голосового сообщения...")
    file_id = message.voice.file_id
    file = await bot.get_file(file_id)
    file_path = file.file_path
    
    ogg_io = io.BytesIO()
    await bot.download_file(file_path, destination=ogg_io)
    ogg_io.seek(0)
    
    try:
        audio = AudioSegment.from_file(ogg_io, format="ogg")
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_io) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="ru-RU")
            
        await msg.edit_text(f"🎤 Распознано: {text}")
        await process_text_message(message, text)
        
    except sr.UnknownValueError:
        await msg.edit_text("❌ Не удалось распознать речь.")
    except Exception as e:
        logging.error(f"Voice error: {e}")
        await msg.edit_text("❌ Ошибка при обработке аудио.")

# --- Text Fallback (Smart Parser) ---
@dp.message(F.text & ~F.text.startswith('/'))
async def handle_text(message: types.Message, state: FSMContext):
    # Ignore if in FSM
    current_state = await state.get_state()
    if current_state is not None:
        return
        
    await process_text_message(message, message.text)

async def main():
    if not BOT_TOKEN:
        logging.error("Cannot start bot without BOT_TOKEN")
        return
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
