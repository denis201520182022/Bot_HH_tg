import logging
import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.orm import Session
from aiogram.utils.formatting import Text, Bold, Italic, Code

from hr_bot.db.models import TelegramUser, TrackedRecruiter, AppSettings
# Убрали импорт TrackedVacancy, так как он больше не используется
from hr_bot.tg_bot.filters import AdminFilter
from hr_bot.tg_bot.keyboards import (
    create_management_keyboard,
    role_choice_keyboard,
    cancel_fsm_keyboard,
    limits_menu_keyboard,
    limit_options_keyboard,
    admin_keyboard
)

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(AdminFilter())

# --- FSM Состояния ---
class UserManagement(StatesGroup):
    add_id = State(); add_name = State(); add_role = State(); del_id = State()

# --- КЛАСС VacancyManagement УДАЛЕН ---

class RecruiterManagement(StatesGroup):
    add_id = State(); add_name = State(); add_refresh_token = State()
    add_access_token = State(); add_expires_in = State(); del_id = State()

class SettingsManagement(StatesGroup):
    set_limit = State(); set_tariff = State()

# --- Обработчики отмены ---
@router.message(Command("cancel"))
async def cancel_command_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нет активных действий для отмены.")
        return
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=admin_keyboard)

@router.callback_query(F.data == "cancel_fsm")
async def cancel_callback_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Действие отменено.")
    await callback.answer()

# --- УПРАВЛЕНИЕ ЛИМИТАМИ И ТАРИФАМИ ---
@router.message(F.text == "⚙️ Лимиты и Тариф")
async def limits_menu(message: Message, db_session: Session):
    settings = db_session.query(AppSettings).filter_by(id=1).first()
    if not settings:
        await message.answer("❌ Не удалось загрузить настройки.")
        return
    remaining = settings.limit_total - settings.limit_used
    cost = settings.limit_used * settings.cost_per_response
    content = Text(
        Bold("📊 Текущий статус:"), "\n\n",
        "Лимит: ", Bold(settings.limit_total), " откликов\n",
        "Использовано: ", Bold(settings.limit_used), " (на сумму: ", Bold(f"{cost:.2f}"), " руб.)\n",
        "Осталось: ", Bold(remaining), "\n\n",
        "Текущий тариф: ", Bold(f"{settings.cost_per_response:.2f}"), " руб. за отклик"
    )
    await message.answer(**content.as_kwargs(), reply_markup=limits_menu_keyboard)

@router.callback_query(F.data == "set_limit")
async def start_set_limit(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SettingsManagement.set_limit)
    await callback.message.answer("Введите новое значение лимита или выберите готовый вариант:", reply_markup=limit_options_keyboard)
    await callback.answer()

@router.message(SettingsManagement.set_limit)
async def process_set_limit(message: Message, state: FSMContext, db_session: Session):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Действие отменено.", reply_markup=admin_keyboard)
        return
    if not message.text or not message.text.isdigit() or int(message.text) < 0:
        await message.answer("❌ Лимит должен быть целым числом. Попробуйте еще раз.")
        return
    new_limit = int(message.text)
    settings = db_session.query(AppSettings).filter_by(id=1).first()
    settings.limit_total = new_limit
    if (settings.limit_total - settings.limit_used) >= 15:
        settings.low_limit_notified = False
    db_session.commit()
    await state.clear()
    content = Text("✅ Новый лимит установлен: ", Bold(new_limit), " откликов.")
    await message.answer(**content.as_kwargs(), reply_markup=admin_keyboard)

@router.callback_query(F.data == "set_tariff")
async def start_set_tariff(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SettingsManagement.set_tariff)
    await callback.message.answer("Введите новую стоимость одного отклика в рублях (например: `150.50`).", reply_markup=ReplyKeyboardRemove())
    await callback.answer()

@router.message(SettingsManagement.set_tariff)
async def process_set_tariff(message: Message, state: FSMContext, db_session: Session):
    try:
        new_tariff = float(message.text.replace(',', '.'))
        if new_tariff < 0: raise ValueError
    except (ValueError, TypeError):
        await message.answer("❌ Тариф должен быть положительным числом. Попробуйте еще раз.")
        return
    settings = db_session.query(AppSettings).filter_by(id=1).first()
    settings.cost_per_response = new_tariff
    db_session.commit()
    await state.clear()
    content = Text("✅ Новый тариф установлен: ", Bold(f"{new_tariff:.2f}"), " руб. за отклик.")
    await message.answer(**content.as_kwargs(), reply_markup=admin_keyboard)

# --- 1. УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ---
@router.message(F.text == "👤 Управление пользователями")
async def user_management_menu(message: Message, db_session: Session):
    users = db_session.query(TelegramUser).all()
    content_parts = [Bold("👥 Список пользователей:"), "\n\n"]
    if not users:
        content_parts.append(Italic("В системе пока нет пользователей."))
    else:
        for u in users:
            role_emoji = "✨" if u.role == 'admin' else "🧑‍💻"
            content_parts.extend([
                f"{role_emoji} ", Bold(u.username), " (ID: ", Code(u.telegram_id), ") - Роль: ", Italic(u.role), "\n"
            ])
    content_parts.append("\nВыберите действие:")
    content = Text(*content_parts)
    await message.answer(**content.as_kwargs(), reply_markup=create_management_keyboard([], "add_user", "del_user"))

@router.callback_query(F.data == "add_user")
async def start_add_user(callback: CallbackQuery, state: FSMContext):
    await state.set_state(UserManagement.add_id)
    content = Text("Введите Telegram ID нового пользователя.")
    await callback.message.edit_text(**content.as_kwargs(), reply_markup=cancel_fsm_keyboard)
    await callback.answer()

@router.message(UserManagement.add_id)
async def process_add_user_id(message: Message, state: FSMContext, db_session: Session):
    if not message.text or not message.text.isdigit():
        content = Text("❌ ID должен быть числом. Попробуйте еще раз.")
        await message.answer(**content.as_kwargs(), reply_markup=cancel_fsm_keyboard)
        return
    user_id = message.text
    if db_session.query(TelegramUser).filter_by(telegram_id=user_id).first():
        content = Text("⚠️ Пользователь с ID ", Code(user_id), " уже существует. Действие отменено.")
        await message.answer(**content.as_kwargs())
        await state.clear()
        return
    await state.update_data(user_id=user_id)
    await state.set_state(UserManagement.add_name)
    content = Text("Отлично. Теперь введите имя пользователя (например, ", Code("Иван Рекрутер"), ").")
    await message.answer(**content.as_kwargs(), reply_markup=cancel_fsm_keyboard)

@router.message(UserManagement.add_name)
async def process_add_user_name(message: Message, state: FSMContext):
    if not message.text:
        content = Text("❌ Имя не может быть пустым. Попробуйте еще раз.")
        await message.answer(**content.as_kwargs(), reply_markup=cancel_fsm_keyboard)
        return
    await state.update_data(user_name=message.text)
    await state.set_state(UserManagement.add_role)
    await message.answer("Имя принято. Теперь выберите роль:", reply_markup=role_choice_keyboard)

@router.callback_query(UserManagement.add_role)
async def process_add_user_role(callback: CallbackQuery, state: FSMContext, db_session: Session):
    role = "admin" if callback.data == "set_role_admin" else "user"
    user_data = await state.get_data()
    new_user = TelegramUser(telegram_id=user_data['user_id'], username=user_data['user_name'], role=role)
    db_session.add(new_user)
    db_session.commit()
    await state.clear()
    logger.info(f"Админ {callback.from_user.id} добавил пользователя {user_data['user_id']} с ролью {role}")
    content = Text("✅ ", Bold("Успех!"), " Пользователь ", Bold(user_data['user_name']), " добавлен с ролью ", Italic(role), ".")
    await callback.message.edit_text(**content.as_kwargs())

@router.callback_query(F.data == "del_user")
async def start_del_user(callback: CallbackQuery, state: FSMContext):
    await state.set_state(UserManagement.del_id)
    content = Text("Введите Telegram ID пользователя для удаления.")
    await callback.message.edit_text(**content.as_kwargs(), reply_markup=cancel_fsm_keyboard)
    await callback.answer()

@router.message(UserManagement.del_id)
async def process_del_user_id(message: Message, state: FSMContext, db_session: Session):
    if not message.text or not message.text.isdigit():
        content = Text("❌ ID должен быть числом. Попробуйте еще раз.")
        await message.answer(**content.as_kwargs(), reply_markup=cancel_fsm_keyboard)
        return
    user_id_to_delete = message.text
    if str(message.from_user.id) == user_id_to_delete:
        await message.answer("🤔 Вы не можете удалить самого себя. Действие отменено.")
        await state.clear()
        return
    user_to_delete = db_session.query(TelegramUser).filter_by(telegram_id=user_id_to_delete).first()
    if not user_to_delete:
        content = Text("⚠️ Пользователь с ID ", Code(user_id_to_delete), " не найден. Действие отменено.")
        await message.answer(**content.as_kwargs())
        await state.clear()
        return
    deleted_username = user_to_delete.username
    deleted_id = user_to_delete.telegram_id
    db_session.delete(user_to_delete)
    db_session.commit()
    await state.clear()
    logger.info(f"Админ {message.from_user.id} удалил пользователя {deleted_id}")
    content = Text("✅ Пользователь ", Bold(deleted_username), " (ID: ", Code(deleted_id), ") был удален.")
    await message.answer(**content.as_kwargs())

# --- БЛОК УПРАВЛЕНИЯ ВАКАНСИЯМИ ПОЛНОСТЬЮ УДАЛЕН ---

# --- 3. УПРАВЛЕНИЕ РЕКРУТЕРАМИ ---
@router.message(F.text == "👨‍💼 Управление рекрутерами")
async def recruiter_management_menu(message: Message, db_session: Session):
    recruiters = db_session.query(TrackedRecruiter).all()
    
    content_parts = [Bold("👨‍💼 Отслеживаемые рекрутеры:"), "\n\n"]
    if not recruiters:
        content_parts.append(Italic("Список пуст."))
    else:
        for r in recruiters:
            content_parts.extend(["- ", Bold(r.name), " (ID: ", Code(r.recruiter_id), ")\n"])
    content_parts.append("\nВыберите действие:")
    
    content = Text(*content_parts)
    await message.answer(**content.as_kwargs(), reply_markup=create_management_keyboard([], "add_recruiter", "del_recruiter"))

@router.callback_query(F.data == "add_recruiter")
async def start_add_recruiter(callback: CallbackQuery, state: FSMContext):
    await state.set_state(RecruiterManagement.add_id)
    content = Text("Шаг 1/5: Введите ID рекрутера (manager id) с hh.ru.")
    await callback.message.edit_text(**content.as_kwargs(), reply_markup=cancel_fsm_keyboard)
    await callback.answer()

@router.message(RecruiterManagement.add_id)
async def process_add_recruiter_id(message: Message, state: FSMContext, db_session: Session):
    if not message.text or not message.text.isdigit():
        content = Text("❌ ID должен быть числом. Попробуйте еще раз.")
        await message.answer(**content.as_kwargs(), reply_markup=cancel_fsm_keyboard)
        return
    recruiter_id = message.text
    if db_session.query(TrackedRecruiter).filter_by(recruiter_id=recruiter_id).first():
        content = Text("⚠️ Рекрутер с ID ", Code(recruiter_id), " уже отслеживается. Действие отменено.")
        await message.answer(**content.as_kwargs())
        await state.clear()
        return
    await state.update_data(recruiter_id=recruiter_id)
    await state.set_state(RecruiterManagement.add_name)
    content = Text("Шаг 2/5: Отлично. Теперь введите имя рекрутера (для вашего удобства).")
    await message.answer(**content.as_kwargs(), reply_markup=cancel_fsm_keyboard)

@router.message(RecruiterManagement.add_name)
async def process_add_recruiter_name(message: Message, state: FSMContext):
    if not message.text:
        content = Text("❌ Имя не может быть пустым. Попробуйте еще раз.")
        await message.answer(**content.as_kwargs(), reply_markup=cancel_fsm_keyboard)
        return
    await state.update_data(name=message.text)
    await state.set_state(RecruiterManagement.add_refresh_token)
    content = Text("Шаг 3/5: Имя принято. Теперь вставьте REFRESH TOKEN, полученный от hh.ru.")
    await message.answer(**content.as_kwargs(), reply_markup=cancel_fsm_keyboard)

@router.message(RecruiterManagement.add_refresh_token)
async def process_add_refresh_token(message: Message, state: FSMContext):
    if not message.text:
        content = Text("❌ Токен не может быть пустым. Попробуйте еще раз.")
        await message.answer(**content.as_kwargs(), reply_markup=cancel_fsm_keyboard)
        return
    await state.update_data(refresh_token=message.text)
    await state.set_state(RecruiterManagement.add_access_token)
    content = Text("Шаг 4/5: Refresh token принят. Теперь вставьте ACCESS TOKEN.")
    await message.answer(**content.as_kwargs(), reply_markup=cancel_fsm_keyboard)

@router.message(RecruiterManagement.add_access_token)
async def process_add_access_token(message: Message, state: FSMContext):
    if not message.text:
        content = Text("❌ Токен не может быть пустым. Попробуйте еще раз.")
        await message.answer(**content.as_kwargs(), reply_markup=cancel_fsm_keyboard)
        return
    await state.update_data(access_token=message.text)
    await state.set_state(RecruiterManagement.add_expires_in)
    content = Text("Шаг 5/5: Access token принят. Теперь введите время его жизни в секундах (expires_in).")
    await message.answer(**content.as_kwargs(), reply_markup=cancel_fsm_keyboard)

@router.message(RecruiterManagement.add_expires_in)
async def process_add_expires_in(message: Message, state: FSMContext, db_session: Session):
    if not message.text or not message.text.isdigit():
        content = Text("❌ Время жизни должно быть числом. Попробуйте еще раз.")
        await message.answer(**content.as_kwargs(), reply_markup=cancel_fsm_keyboard)
        return
    
    expires_in = int(message.text)
    data = await state.get_data()
    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=expires_in)
    
    new_recruiter = TrackedRecruiter(
        recruiter_id=data['recruiter_id'], name=data['name'],
        refresh_token=data['refresh_token'], access_token=data['access_token'],
        token_expires_at=expires_at
    )
    db_session.add(new_recruiter)
    db_session.commit()
    await state.clear()
    
    logger.info(f"Админ {message.from_user.id} добавил рекрутера {data['name']} ({data['recruiter_id']})")
    content = Text("✅ ", Bold("Успех!"), " Рекрутер ", Bold(data['name']), " добавлен в список отслеживания.")
    await message.answer(**content.as_kwargs())

@router.callback_query(F.data == "del_recruiter")
async def start_del_recruiter(callback: CallbackQuery, state: FSMContext):
    await state.set_state(RecruiterManagement.del_id)
    content = Text("Введите ID рекрутера для удаления из списка.")
    await callback.message.edit_text(**content.as_kwargs(), reply_markup=cancel_fsm_keyboard)
    await callback.answer()

@router.message(RecruiterManagement.del_id)
async def process_del_recruiter_id(message: Message, state: FSMContext, db_session: Session):
    if not message.text or not message.text.isdigit():
        content = Text("❌ ID должен быть числом. Попробуйте еще раз.")
        await message.answer(**content.as_kwargs(), reply_markup=cancel_fsm_keyboard)
        return
    recruiter_id = message.text
    recruiter_to_delete = db_session.query(TrackedRecruiter).filter_by(recruiter_id=recruiter_id).first()
    if not recruiter_to_delete:
        content = Text("⚠️ Рекрутер с ID ", Code(recruiter_id), " не найден. Действие отменено.")
        await message.answer(**content.as_kwargs())
        await state.clear()
        return
    
    deleted_name = recruiter_to_delete.name
    db_session.delete(recruiter_to_delete)
    db_session.commit()
    await state.clear()
    logger.info(f"Админ {message.from_user.id} удалил рекрутера {recruiter_id}")
    
    content = Text("✅ Рекрутер ", Bold(deleted_name), " (ID: ", Code(recruiter_id), ") удален.")
    await message.answer(**content.as_kwargs())