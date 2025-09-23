from aiogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton
)
from typing import List, Any

# --- Основные Reply-клавиатуры ---
user_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="❓ Помощь")]
    ],
    resize_keyboard=True
)

admin_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="❓ Помощь")],
        [KeyboardButton(text="👤 Управление пользователями")],
        [KeyboardButton(text="📝 Управление вакансиями")],
        [KeyboardButton(text="👨‍💼 Управление рекрутерами")],
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
    """
    Создает клавиатуру для отчета со статистикой,
    включая кнопку для экспорта в Excel.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 Выгрузить в Excel", callback_data=f"export_stats_{period}")]
        ]
    )

# --- ВОЗВРАЩАЕМ УДАЛЕННУЮ КЛАВИАТУРУ ---
# Инлайн-клавиатура для выбора роли при добавлении пользователя через FSM
role_choice_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="Пользователь 🧑‍💻", callback_data="set_role_user"),
            InlineKeyboardButton(text="Администратор ✨", callback_data="set_role_admin")
        ]
    ]
)

def create_management_keyboard(
    items: List[Any], 
    add_callback: str, 
    del_callback: str
) -> InlineKeyboardMarkup:
    """
    Создает универсальное inline-меню для управления списком.
    Показывает список и кнопки "Добавить" / "Удалить".
    """
    buttons = []
    # (Функционал показа списка пока уберем, чтобы не перегружать сообщение)
    # for item in items:
    #     buttons.append([InlineKeyboardButton(text=f"📄 {item.title or item.name}", callback_data=f"view_{item.id}")])
    
    action_buttons = [
        InlineKeyboardButton(text="➕ Добавить", callback_data=add_callback),
        InlineKeyboardButton(text="➖ Удалить", callback_data=del_callback)
    ]
    buttons.append(action_buttons)
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

cancel_fsm_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_fsm")]
    ]
)