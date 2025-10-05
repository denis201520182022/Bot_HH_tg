import asyncio
import logging
import os
import re
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

from hr_bot.utils.logger_config import setup_logging
from hr_bot.db.models import SessionLocal, Candidate, NotificationQueue
from hr_bot.tg_bot.middlewares import DbSessionMiddleware
from hr_bot.tg_bot.handlers import main_router
from hr_bot.utils.formatters import mask_fio

logger = logging.getLogger(__name__)


def escape_markdown(text: str) -> str:
    """
    Экранирует специальные символы для Telegram Markdown (старый стиль).
    """
    if not isinstance(text, str):
        text = str(text)
    
    escape_chars = r'_*`['
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)


async def check_and_send_notifications(bot: Bot):
    """
    Фоновая задача, которая проверяет очередь и рассылает уведомления 
    в определенный групповой чат.
    """
    db_session = SessionLocal()
    # --- ИЗМЕНЕНИЕ 1: Получаем ID чата из переменных окружения ---
    # Убедитесь, что вы добавили GROUP_CHAT_ID в ваш .env файл
    try:
        # ID чата должен быть числом (целым)
        group_chat_id = int(os.getenv("GROUP_CHAT_ID"))
    except (TypeError, ValueError):
        logger.critical("Переменная GROUP_CHAT_ID не найдена или имеет неверный формат. Уведомления не будут отправляться.")
        return # Завершаем работу функции, если ID не задан

    logger.info(f"Фоновый обработчик уведомлений запущен. Отправка будет в чат: {group_chat_id}")
    
    while True:
        # --- НАЧАЛО ИЗМЕНЕНИЙ: Создаем новую сессию для каждой итерации ---
        db_session = SessionLocal()
        try:
            tasks = db_session.query(NotificationQueue).filter_by(status='pending').limit(10).all()
            if not tasks:
                # Пауза, если нет задач
                await asyncio.sleep(10)
                continue

            logger.info(f"[Notification Sender] Найдено {len(tasks)} новых уведомлений для отправки.")

            for task in tasks:
                # Получаем связанные данные в той же сессии
                candidate = db_session.query(Candidate).filter_by(id=task.candidate_id).first()
                if not candidate or not candidate.dialogues:
                    task.status = 'error'
                    logger.error(f"Не найден кандидат или его диалог для задачи {task.id}.")
                    db_session.commit() # Сохраняем ошибку
                    continue
                
                dialogue = candidate.dialogues[0]
                vacancy = dialogue.vacancy
                
                # Экранируем все данные перед вставкой в сообщение
                safe_vacancy_title = escape_markdown(vacancy.title)
                safe_masked_name = escape_markdown(mask_fio(candidate.full_name))
                safe_age = escape_markdown(candidate.age or 'Не указан')
                safe_citizenship = escape_markdown(candidate.citizenship or 'Не указано')
                safe_readiness = escape_markdown(candidate.readiness_to_start or 'Не указано')
                safe_city = escape_markdown(candidate.city or 'Не указан') 
                safe_phone_number = escape_markdown(candidate.phone_number or "—")

                # Собираем финальное, безопасное для Markdown сообщение
                message_text = (
                    f"📌 *Новый кандидат по вакансии:* {safe_vacancy_title}\n"
                    f"*ФИО:* {safe_masked_name}\n"
                    f"*Возраст:* {safe_age}\n"
                    f"*Гражданство:* {safe_citizenship}\n"
                    f"*Готов приступить:* {safe_readiness}\n"
                    f"*Город:* {safe_city}\n"
                    f"*Номер телефона:* {safe_phone_number}\n"
                    f"*Статус:* ✅ Прошёл квалификацию"
                )
                
                try:
                    await bot.send_message(chat_id=group_chat_id, text=message_text)
                    task.status = 'sent'
                    logger.info(f"Уведомление по кандидату {candidate.id} успешно отправлено.")
                
                except Exception as e:
                    task.status = 'error'
                    logger.error(f"Не удалось отправить уведомление по задаче {task.id}: {e}")
                
                finally:
                    db_session.commit() # Сохраняем изменения статуса задачи
            
            # Небольшая пауза после обработки пачки задач
            await asyncio.sleep(5)

        except Exception as e:
            logger.critical(f"Критическая ошибка в фоновом обработчике: {e}", exc_info=True)
            db_session.rollback()
            await asyncio.sleep(30) # Пауза в случае критической ошибки
            
        finally:
            # --- КОНЕЦ ИЗМЕНЕНИЙ: Гарантированно закрываем сессию ---
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
    await dp.start_polling(bot)
    
    notification_task.cancel()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную.")