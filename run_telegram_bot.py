# run_telegram_bot.py

import asyncio
import logging
import os
import re # <-- Добавлен импорт для регулярных выражений
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

from hr_bot.utils.logger_config import setup_logging
from hr_bot.db.models import SessionLocal, TelegramUser, Candidate, NotificationQueue, Dialogue
from hr_bot.tg_bot.middlewares import DbSessionMiddleware
from hr_bot.tg_bot.handlers import main_router
from hr_bot.utils.formatters import mask_fio

logger = logging.getLogger(__name__)


# --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ДЛЯ ЭКРАНИРОВАНИЯ ---
def escape_markdown(text: str) -> str:
    """
    Экранирует специальные символы для Telegram Markdown (старый стиль).
    Это необходимо, чтобы переменные с точками, скобками или дефисами не ломали разметку.
    """
    if not isinstance(text, str):
        text = str(text)
    
    # Основные символы, которые нужно экранировать в старом Markdown
    escape_chars = r'_*`['
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)


async def check_and_send_notifications(bot: Bot):
    """
    Фоновая задача, которая проверяет очередь и рассылает уведомления рекрутерам.
    """
    db_session = SessionLocal()
    logger.info("Фоновый обработчик уведомлений запущен.")
    while True:
        try:
            tasks = db_session.query(NotificationQueue).filter_by(status='pending').limit(10).all()
            if tasks:
                logger.info(f"[Notification Sender] Найдено {len(tasks)} новых уведомлений для отправки.")
                recipients = db_session.query(TelegramUser).filter_by(role='user').all()

                if not recipients:
                    logger.warning("[Notification Sender] В БД нет пользователей (рекрутеров) для отправки.")
                    for task in tasks: task.status = 'error'
                    db_session.commit()
                    await asyncio.sleep(60)
                    continue

                for task in tasks:
                    candidate = db_session.query(Candidate).filter_by(id=task.candidate_id).first()
                    if not candidate or not candidate.dialogues:
                        task.status = 'error'
                        db_session.commit()
                        logger.error(f"Не найден кандидат или его диалог для задачи {task.id}.")
                        continue
                    
                    dialogue = candidate.dialogues[0]
                    vacancy = dialogue.vacancy
                    
                    # --- ИСПРАВЛЕНИЕ: Экранируем все данные перед вставкой в сообщение ---
                    safe_vacancy_title = escape_markdown(vacancy.title)
                    safe_masked_name = escape_markdown(mask_fio(candidate.full_name))
                    safe_age = escape_markdown(candidate.age or 'Не указан')
                    safe_citizenship = escape_markdown(candidate.citizenship or 'Не указано')
                    safe_city = escape_markdown(candidate.city or 'Не указан') 
                    # --- ДОБАВЛЯЕМ НОВОЕ ПОЛЕ ---
                    safe_readiness = escape_markdown(candidate.readiness_to_start or 'Не указано')
                    # -----------------------------
                    safe_phone_number = escape_markdown(candidate.phone_number or "—")

                    # Собираем финальное, безопасное для Markdown сообщение
                    message_text = (
                        f"📌 *Новый кандидат по вакансии:* {safe_vacancy_title}\n"
                        f"*ФИО:* {safe_masked_name}\n"
                        f"*Возраст:* {safe_age}\n"
                        f"*Гражданство:* {safe_citizenship}\n"
                        # --- ДОБАВЛЯЕМ НОВУЮ СТРОКУ В ШАБЛОН ---
                        f"*Готов приступить:* {safe_readiness}\n"
                        # --------------------------------------
                        f"*Город:* {safe_city}\n"
                        f"*Номер телефона:* {safe_phone_number}\n"
                        f"*Статус:* ✅ Прошёл квалификацию"
                    )
                    
                    sent_count = 0
                    for user in recipients:
                        try:
                            # parse_mode уже установлен по умолчанию в bot
                            await bot.send_message(chat_id=user.telegram_id, text=message_text)
                            sent_count += 1
                        except Exception as e:
                            logger.error(f"Не удалось отправить уведомление по задаче {task.id} пользователю {user.telegram_id}: {e}")
                    
                    task.status = 'sent'
                    db_session.commit()
                    logger.info(f"Уведомление по кандидату {candidate.id} отправлено {sent_count} пользователям.")
            
            await asyncio.sleep(10)
        except Exception as e:
            logger.critical(f"Критическая ошибка в фоновом обработчике: {e}", exc_info=True)
            db_session.rollback()
            await asyncio.sleep(30)
    db_session.close()


async def main():
    """Главная функция запуска бота."""
    setup_logging(log_filename="telegram_bot.log")
    load_dotenv()
    
    bot = Bot(
        token=os.getenv("TELEGRAM_BOT_TOKEN"),
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN) # Оставляем ваш режим по умолчанию
    )
    dp = Dispatcher()
    dp.update.middleware(DbSessionMiddleware(session_pool=SessionLocal))
    dp.include_router(main_router)
    
    logger.info("Управляющий Telegram-бот запускается...")
    notification_task = asyncio.create_task(check_and_send_notifications(bot))
    
    await bot.delete_webhook(drop_pending_updates=True)
    # bot.delete_my_commands() # Убрал, т.к. команды обычно не нужно удалять при каждом запуске
    
    await dp.start_polling(bot)
    
    notification_task.cancel()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную.")