# hr_bot/tg_bot/keyboards.py

from aiogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton
)
from typing import List, Any

# --- Основные Reply-клавиатуры (под полем ввода) ---

# Клавиатура для обычного пользователя
user_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="⚙️ Лимиты")],
        [KeyboardButton(text="❓ Помощь")]
    ],
    resize_keyboard=True
)

# Клавиатура для администратора
admin_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="⚙️ Лимиты и Тариф")],
        [KeyboardButton(text="👤 Управление пользователями")],
        [KeyboardButton(text="📝 Управление вакансиями"), KeyboardButton(text="👨‍💼 Управление рекрутерами")],
        [KeyboardButton(text="❓ Помощь")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие:"
)


# --- Inline-клавиатуры (встроенные в сообщения) ---

# Клавиатура для первоначального выбора периода статистики
stats_period_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 За сегодня", callback_data="stats_today"),
            InlineKeyboardButton(text="🗓️ За всё время", callback_data="stats_all_time")
        ]
    ]
)

def create_stats_export_keyboard(period: str) -> InlineKeyboardMarkup:
    """Создает клавиатуру для отчета со статистикой, включая кнопку для экспорта."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 Выгрузить в Excel", callback_data=f"export_stats_{period}")]
        ]
    )

# Клавиатура для отмены любого FSM-действия
cancel_fsm_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_fsm")]
    ]
)

# Клавиатура для выбора роли при добавлении пользователя через FSM
role_choice_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="Пользователь 🧑‍💻", callback_data="set_role_user"),
            InlineKeyboardButton(text="Администратор ✨", callback_data="set_role_admin")
        ]
    ]
)

# Клавиатура для меню управления лимитами (только для админов)
limits_menu_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Установить лимит", callback_data="set_limit")],
        [InlineKeyboardButton(text="💰 Установить тариф", callback_data="set_tariff")]
    ]
)

# Клавиатура с готовыми вариантами лимитов
limit_options_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="50"), KeyboardButton(text="100"), KeyboardButton(text="150")],
        [KeyboardButton(text="❌ Отмена")]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

# --- ВОТ ЗАБЫТАЯ ФУНКЦИЯ ---
def create_management_keyboard(
    items: List[Any], 
    add_callback: str, 
    del_callback: str
) -> InlineKeyboardMarkup:
    """
    Создает универсальное inline-меню для управления списком.
    Показывает кнопки "Добавить" / "Удалить".
    """
    buttons = []
    action_buttons = [
        InlineKeyboardButton(text="➕ Добавить", callback_data=add_callback),
        InlineKeyboardButton(text="➖ Удалить", callback_data=del_callback)
    ]
    buttons.append(action_buttons)
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)