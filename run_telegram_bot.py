# run_telegram_bot.py

import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, BotCommandScopeChat
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
import os

from hr_bot.utils.logger_config import setup_logging
from hr_bot.db.models import SessionLocal, TelegramUser, Candidate, NotificationQueue
from hr_bot.tg_bot.middlewares import DbSessionMiddleware
from hr_bot.tg_bot.handlers import main_router
from hr_bot.utils.formatters import mask_fio

logger = logging.getLogger(__name__)


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
                    last_message_history = dialogue.history[-1] if dialogue.history else {}
                    city = last_message_history.get('extracted_data', {}).get('city', 'Не указан')

                    # --- ИЗМЕНЕНИЕ: Формируем карточку с номером из БД ---
                    masked_name = mask_fio(candidate.full_name)
                    phone_number = candidate.phone_number or "—" # Берем номер из БД

                    message_text = (
                        f"📌 *Новый кандидат по вакансии:* {vacancy.title}\n"
                        f"*ФИО:* {masked_name}\n"
                        f"*Возраст:* {candidate.age or 'Не указан'}\n"
                        f"*Гражданство:* {candidate.citizenship or 'Не указано'}\n"
                        f"*Город:* {city}\n"
                        f"*Номер телефона:* {phone_number}\n" # <-- Подставляем реальный номер
                        f"*Статус:* ✅ Прошёл квалификацию"
                    )
                    
                    for user in recipients:
                        try:
                            await bot.send_message(chat_id=user.telegram_id, text=message_text)
                        except Exception as e:
                            logger.error(f"Не удалось отправить уведомление по задаче {task.id} пользователю {user.telegram_id}: {e}")
                    
                    task.status = 'sent'
                    db_session.commit()
                    logger.info(f"Уведомление по кандидату {candidate.id} отправлено {len(recipients)} пользователям.")
            
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
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    dp = Dispatcher()
    dp.update.middleware(DbSessionMiddleware(session_pool=SessionLocal))
    dp.include_router(main_router)
    
    logger.info("Управляющий Telegram-бот запускается...")
    notification_task = asyncio.create_task(check_and_send_notifications(bot))
    
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.delete_my_commands()
    
    await dp.start_polling(bot)
    
    notification_task.cancel()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную.")