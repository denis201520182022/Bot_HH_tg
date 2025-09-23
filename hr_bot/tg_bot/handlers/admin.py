# hr_bot/tg_bot/handlers/admin.py

import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.orm import Session
from hr_bot.db.models import TelegramUser, TrackedVacancy, TrackedRecruiter
from hr_bot.tg_bot.filters import AdminFilter
from hr_bot.tg_bot.keyboards import create_management_keyboard, role_choice_keyboard, cancel_fsm_keyboard

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(AdminFilter()) # Защищаем все хэндлеры в этом файле

# --- FSM Состояния ---
class UserManagement(StatesGroup):
    add_id = State()
    add_name = State()
    add_role = State()
    del_id = State()

class VacancyManagement(StatesGroup):
    add_id = State()
    add_title = State()
    del_id = State()

class RecruiterManagement(StatesGroup):
    add_id = State()
    add_name = State()
    del_id = State()

# --- Единый обработчик отмены (команда + кнопка) ---
@router.message(Command("cancel"))
async def cancel_command_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нет активных действий для отмены.")
        return
    logger.info(f"Админ {message.from_user.id} отменил действие командой.")
    await state.clear()
    await message.answer("Действие отменено.")

@router.callback_query(F.data == "cancel_fsm")
async def cancel_callback_handler(callback: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await callback.answer("Нет активных действий.", show_alert=True)
        return
    logger.info(f"Админ {callback.from_user.id} отменил действие кнопкой.")
    await state.clear()
    await callback.message.edit_text("Действие отменено.")
    await callback.answer()

# --- 1. УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ---

@router.message(F.text == "👤 Управление пользователями")
async def user_management_menu(message: Message, db_session: Session):
    users = db_session.query(TelegramUser).all()
    user_list = "\n".join([f"- *{u.username}* (ID: `{u.telegram_id}`) - _{u.role}_" for u in users])
    if not user_list:
        user_list = "В системе пока нет пользователей."
    await message.answer(
        f"👥 *Список пользователей:*\n{user_list}\n\nВыберите действие:",
        reply_markup=create_management_keyboard([], "add_user", "del_user")
    )

@router.callback_query(F.data == "add_user")
async def start_add_user(callback: CallbackQuery, state: FSMContext):
    await state.set_state(UserManagement.add_id)
    await callback.message.edit_text("Введите Telegram ID нового пользователя.", reply_markup=cancel_fsm_keyboard)
    await callback.answer()

@router.message(UserManagement.add_id)
async def process_add_user_id(message: Message, state: FSMContext, db_session: Session):
    if not message.text or not message.text.isdigit():
        await message.answer("❌ ID должен быть числом. Попробуйте еще раз.", reply_markup=cancel_fsm_keyboard)
        return
    user_id = message.text
    if db_session.query(TelegramUser).filter_by(telegram_id=user_id).first():
        await message.answer(f"⚠️ Пользователь с ID `{user_id}` уже существует. Действие отменено.")
        await state.clear()
        return
    await state.update_data(user_id=user_id)
    await state.set_state(UserManagement.add_name)
    await message.answer("Отлично. Теперь введите имя пользователя (например, `Иван Рекрутер`).", reply_markup=cancel_fsm_keyboard)

@router.message(UserManagement.add_name)
async def process_add_user_name(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Имя не может быть пустым. Попробуйте еще раз.", reply_markup=cancel_fsm_keyboard)
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
    await callback.message.edit_text(f"✅ *Успех!* Пользователь *{user_data['user_name']}* добавлен с ролью *{role}*.")

@router.callback_query(F.data == "del_user")
async def start_del_user(callback: CallbackQuery, state: FSMContext):
    await state.set_state(UserManagement.del_id)
    await callback.message.edit_text("Введите Telegram ID пользователя для удаления.", reply_markup=cancel_fsm_keyboard)
    await callback.answer()

@router.message(UserManagement.del_id)
async def process_del_user_id(message: Message, state: FSMContext, db_session: Session):
    if not message.text or not message.text.isdigit():
        await message.answer("❌ ID должен быть числом. Попробуйте еще раз.", reply_markup=cancel_fsm_keyboard)
        return
    user_id_to_delete = message.text
    if str(message.from_user.id) == user_id_to_delete:
        await message.answer("🤔 Вы не можете удалить самого себя. Действие отменено.")
        await state.clear()
        return
    user_to_delete = db_session.query(TelegramUser).filter_by(telegram_id=user_id_to_delete).first()
    if not user_to_delete:
        await message.answer(f"⚠️ Пользователь с ID `{user_id_to_delete}` не найден. Действие отменено.")
        await state.clear()
        return
    db_session.delete(user_to_delete)
    db_session.commit()
    await state.clear()
    logger.info(f"Админ {message.from_user.id} удалил пользователя {user_id_to_delete}")
    await message.answer(f"✅ Пользователь *{user_to_delete.username}* (ID: `{user_id_to_delete}`) был удален.")

# --- 2. УПРАВЛЕНИЕ ВАКАНСИЯМИ ---

@router.message(F.text == "📝 Управление вакансиями")
async def vacancy_management_menu(message: Message, db_session: Session):
    vacancies = db_session.query(TrackedVacancy).all()
    vacancy_list = "\n".join([f"- *{v.title}* (ID: `{v.vacancy_id}`)" for v in vacancies])
    if not vacancy_list: vacancy_list = "Список пуст."
    await message.answer(
        f"📝 *Отслеживаемые вакансии:*\n{vacancy_list}\n\nВыберите действие:",
        reply_markup=create_management_keyboard([], "add_vacancy", "del_vacancy")
    )

@router.callback_query(F.data == "add_vacancy")
async def start_add_vacancy(callback: CallbackQuery, state: FSMContext):
    await state.set_state(VacancyManagement.add_id)
    await callback.message.edit_text("Введите ID вакансии с hh.ru для отслеживания.", reply_markup=cancel_fsm_keyboard)
    await callback.answer()

@router.message(VacancyManagement.add_id)
async def process_add_vacancy_id(message: Message, state: FSMContext, db_session: Session):
    if not message.text or not message.text.isdigit():
        await message.answer("❌ ID должен быть числом. Попробуйте еще раз.", reply_markup=cancel_fsm_keyboard)
        return
    vacancy_id = message.text
    if db_session.query(TrackedVacancy).filter_by(vacancy_id=vacancy_id).first():
        await message.answer(f"⚠️ Вакансия с ID `{vacancy_id}` уже отслеживается. Действие отменено.")
        await state.clear()
        return
    await state.update_data(vacancy_id=vacancy_id)
    await state.set_state(VacancyManagement.add_title)
    await message.answer("Отлично. Теперь введите название этой вакансии (для вашего удобства).", reply_markup=cancel_fsm_keyboard)

@router.message(VacancyManagement.add_title)
async def process_add_vacancy_title(message: Message, state: FSMContext, db_session: Session):
    if not message.text:
        await message.answer("❌ Название не может быть пустым. Попробуйте еще раз.", reply_markup=cancel_fsm_keyboard)
        return
    data = await state.get_data()
    vacancy_id = data['vacancy_id']
    title = message.text
    new_vacancy = TrackedVacancy(vacancy_id=vacancy_id, title=title)
    db_session.add(new_vacancy)
    db_session.commit()
    await state.clear()
    logger.info(f"Админ {message.from_user.id} добавил вакансию {title} ({vacancy_id})")
    await message.answer(f"✅ Вакансия *{title}* (ID: `{vacancy_id}`) добавлена в список.")

@router.callback_query(F.data == "del_vacancy")
async def start_del_vacancy(callback: CallbackQuery, state: FSMContext):
    await state.set_state(VacancyManagement.del_id)
    await callback.message.edit_text("Введите ID вакансии для удаления из списка.", reply_markup=cancel_fsm_keyboard)
    await callback.answer()

@router.message(VacancyManagement.del_id)
async def process_del_vacancy_id(message: Message, state: FSMContext, db_session: Session):
    if not message.text or not message.text.isdigit():
        await message.answer("❌ ID должен быть числом. Попробуйте еще раз.", reply_markup=cancel_fsm_keyboard)
        return
    vacancy_id = message.text
    vacancy_to_delete = db_session.query(TrackedVacancy).filter_by(vacancy_id=vacancy_id).first()
    if not vacancy_to_delete:
        await message.answer(f"⚠️ Вакансия с ID `{vacancy_id}` не найдена. Действие отменено.")
        await state.clear()
        return
    db_session.delete(vacancy_to_delete)
    db_session.commit()
    await state.clear()
    logger.info(f"Админ {message.from_user.id} удалил вакансию {vacancy_id}")
    await message.answer(f"✅ Вакансия *{vacancy_to_delete.title}* (ID: `{vacancy_id}`) удалена.")

# --- 3. УПРАВЛЕНИЕ РЕКРУТЕРАМИ ---

@router.message(F.text == "👨‍💼 Управление рекрутерами")
async def recruiter_management_menu(message: Message, db_session: Session):
    recruiters = db_session.query(TrackedRecruiter).all()
    recruiter_list = "\n".join([f"- *{r.name}* (ID: `{r.recruiter_id}`)" for r in recruiters])
    if not recruiter_list: recruiter_list = "Список пуст."
    await message.answer(
        f"👨‍💼 *Отслеживаемые рекрутеры:*\n{recruiter_list}\n\nВыберите действие:",
        reply_markup=create_management_keyboard([], "add_recruiter", "del_recruiter")
    )

@router.callback_query(F.data == "add_recruiter")
async def start_add_recruiter(callback: CallbackQuery, state: FSMContext):
    await state.set_state(RecruiterManagement.add_id)
    await callback.message.edit_text("Введите ID рекрутера с hh.ru для отслеживания.", reply_markup=cancel_fsm_keyboard)
    await callback.answer()

@router.message(RecruiterManagement.add_id)
async def process_add_recruiter_id(message: Message, state: FSMContext, db_session: Session):
    if not message.text or not message.text.isdigit():
        await message.answer("❌ ID должен быть числом. Попробуйте еще раз.", reply_markup=cancel_fsm_keyboard)
        return
    recruiter_id = message.text
    if db_session.query(TrackedRecruiter).filter_by(recruiter_id=recruiter_id).first():
        await message.answer(f"⚠️ Рекрутер с ID `{recruiter_id}` уже отслеживается. Действие отменено.")
        await state.clear()
        return
    await state.update_data(recruiter_id=recruiter_id)
    await state.set_state(RecruiterManagement.add_name)
    await message.answer("Отлично. Теперь введите имя рекрутера (для вашего удобства).", reply_markup=cancel_fsm_keyboard)

@router.message(RecruiterManagement.add_name)
async def process_add_recruiter_name(message: Message, state: FSMContext, db_session: Session):
    if not message.text:
        await message.answer("❌ Имя не может быть пустым. Попробуйте еще раз.", reply_markup=cancel_fsm_keyboard)
        return
    data = await state.get_data()
    recruiter_id = data['recruiter_id']
    name = message.text
    new_recruiter = TrackedRecruiter(recruiter_id=recruiter_id, name=name)
    db_session.add(new_recruiter)
    db_session.commit()
    await state.clear()
    logger.info(f"Админ {message.from_user.id} добавил рекрутера {name} ({recruiter_id})")
    await message.answer(f"✅ Рекрутер *{name}* (ID: `{recruiter_id}`) добавлен в список.")

@router.callback_query(F.data == "del_recruiter")
async def start_del_recruiter(callback: CallbackQuery, state: FSMContext):
    await state.set_state(RecruiterManagement.del_id)
    await callback.message.edit_text("Введите ID рекрутера для удаления из списка.", reply_markup=cancel_fsm_keyboard)
    await callback.answer()

@router.message(RecruiterManagement.del_id)
async def process_del_recruiter_id(message: Message, state: FSMContext, db_session: Session):
    if not message.text or not message.text.isdigit():
        await message.answer("❌ ID должен быть числом. Попробуйте еще раз.", reply_markup=cancel_fsm_keyboard)
        return
    recruiter_id = message.text
    recruiter_to_delete = db_session.query(TrackedRecruiter).filter_by(recruiter_id=recruiter_id).first()
    if not recruiter_to_delete:
        await message.answer(f"⚠️ Рекрутер с ID `{recruiter_id}` не найден. Действие отменено.")
        await state.clear()
        return
    db_session.delete(recruiter_to_delete)
    db_session.commit()
    await state.clear()
    logger.info(f"Админ {message.from_user.id} удалил рекрутера {recruiter_id}")
    await message.answer(f"✅ Рекрутер *{recruiter_to_delete.name}* (ID: `{recruiter_id}`) удален.")