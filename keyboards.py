from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import get_db_connection
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Moscow')

def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Панель", callback_data="menu_panel"), InlineKeyboardButton(text="🧹 Заявки", callback_data="menu_jobs")],
        [InlineKeyboardButton(text="👥 Сотрудники", callback_data="menu_employees"), InlineKeyboardButton(text="💰 Зарплаты", callback_data="menu_salaries")],
        [InlineKeyboardButton(text="📉 Расходы", callback_data="menu_expenses"), InlineKeyboardButton(text="📈 Доходы", callback_data="menu_income")],
        [InlineKeyboardButton(text="📦 Склад", callback_data="menu_inventory"), InlineKeyboardButton(text="📑 Отчет", callback_data="menu_reports")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="menu_statistics")]
    ])

def back_to_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main")]
    ])

def jobs_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить заявку", callback_data="job_add")],
        [InlineKeyboardButton(text="📋 Просмотр заявок", callback_data="job_view")],
        [InlineKeyboardButton(text="❌ Удалить заявку", callback_data="job_del")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])

def employees_menu_kb():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить сотрудника", callback_data="emp_add")],
        [InlineKeyboardButton(text="📋 Просмотр списка", callback_data="emp_view")],
        [InlineKeyboardButton(text="📈 Статистика сотрудника", callback_data="emp_stats")],
        [InlineKeyboardButton(text="❌ Удалить сотрудника", callback_data="emp_del")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])
    return kb

def finance_menu_kb(type_name):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить", callback_data=f"{type_name}_add")],
        [InlineKeyboardButton(text="📋 Просмотр", callback_data=f"{type_name}_view")],
        [InlineKeyboardButton(text="❌ Удалить", callback_data=f"{type_name}_del")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])

def select_employee_kb(prefix="sel_emp_"):
    conn = get_db_connection()
    employees = conn.execute("SELECT id, name FROM employees").fetchall()
    conn.close()
    kb = []
    for emp in employees:
        kb.append([InlineKeyboardButton(text=emp['name'], callback_data=f"{prefix}{emp['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def date_kb(prefix="date_"):
    today = datetime.now(TZ).strftime("%d.%m.%Y")
    tomorrow = (datetime.now(TZ) + timedelta(days=1)).strftime("%d.%m.%Y")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Сегодня ({today})", callback_data=f"{prefix}{today}")],
        [InlineKeyboardButton(text=f"Завтра ({tomorrow})", callback_data=f"{prefix}{tomorrow}")],
        [InlineKeyboardButton(text="Ввести вручную", callback_data=f"{prefix}manual")]
    ])
