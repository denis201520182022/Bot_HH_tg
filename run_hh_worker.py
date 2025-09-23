# run_hh_worker.py

"""
Основной "рабочий" процесс (воркер) для обработки откликов с hh.ru.
Этот скрипт должен быть запущен постоянно (24/7).
Он работает в бесконечном цикле, выполняя четыре основные задачи:
1. Проверяет и регистрирует новые отклики по отслеживаемым вакансиям.
2. Собирает новые сообщения от кандидатов в "очередь ожидания".
3. Обрабатывает "настоявшиеся" диалоги, объединяя сообщения и отвечая.
4. Проверяет "зависшие" диалоги и отправляет им напоминания.
"""

import asyncio
import time
import logging
import random
from datetime import datetime, timedelta, UTC
from dotenv import load_dotenv
from sqlalchemy.orm import Session

# Импорты из нашего пакета hr_bot
from hr_bot.utils.logger_config import setup_logging
from hr_bot.db.models import SessionLocal, Dialogue, Candidate, Vacancy, NotificationQueue, TrackedVacancy
from hr_bot.services import hh_api_mock as hh_api
from hr_bot.services import knowledge_base
from hr_bot.services import llm_handler
from hr_bot.db import statistics_manager
from hr_bot.utils.pii_masker import extract_and_mask_pii

logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ ---
DEBOUNCE_DELAY_SECONDS = 20
CYCLE_PAUSE_SECONDS = 15


def process_new_responses(db: Session, token: str):
    """(Этап 1) Ищет новые отклики и создает для них начальные записи в БД."""
    # Эту функцию нужно будет доработать для реального API,
    # чтобы она возвращала и данные отклика, и первое сообщение.
    # Пока оставляем ее как заглушку для создания новых диалогов в моке.
    pass


def save_pending_messages(db: Session, token: str):
    """Этап 2.1: Получает все новые сообщения и сохраняет их в "очередь" в БД."""
    logger.info("Этап 2.1: Проверка и сохранение входящих сообщений...")
    new_messages_by_response = hh_api.get_new_messages(token)

    if not new_messages_by_response:
        logger.info("Новых сообщений от кандидатов нет.")
        return

    for response_id, messages in new_messages_by_response.items():
        dialogue = db.query(Dialogue).filter(Dialogue.hh_response_id == response_id).first()
        if not dialogue:
            continue
        
        # Если кандидат ответил, сбрасываем счетчик напоминаний
        if dialogue.reminder_level > 0:
            logger.info(f"Кандидат в диалоге {response_id} ответил. Сбрасываю счетчик напоминаний.")
            dialogue.reminder_level = 0

        current_pending = dialogue.pending_messages or []
        dialogue.pending_messages = current_pending + messages
        dialogue.last_updated = datetime.now(UTC)
        db.commit()
        logger.info(f"Добавлено {len(messages)} сообщений в очередь для диалога {response_id}.")


async def process_pending_dialogues(db: Session, token: str, system_prompt: str):
    """Этап 2.2: Проверяет диалоги, которые "ждут" ответа, маскирует PII и отвечает."""
    logger.info("Этап 2.2: Обработка отложенных диалогов...")
    
    debounce_time = datetime.now(UTC) - timedelta(seconds=DEBOUNCE_DELAY_SECONDS)
    
    dialogues_to_process = db.query(Dialogue).filter(
        Dialogue.pending_messages != None, 
        Dialogue.last_updated <= debounce_time
    ).all()

    if not dialogues_to_process:
        logger.info("Нет диалогов, готовых к ответу.")
        return

    for dialogue in dialogues_to_process:
        logger.info(f"Начинаю обработку объединенных сообщений для диалога {dialogue.hh_response_id}...")
        
        pending_messages = dialogue.pending_messages
        combined_message = "\n".join(pending_messages)
        
        masked_message, extracted_fio, extracted_phone = extract_and_mask_pii(combined_message)
        
        if extracted_fio and not dialogue.candidate.full_name:
            dialogue.candidate.full_name = extracted_fio
            logger.info(f"Сохранен ФИО '{extracted_fio}' для кандидата {dialogue.candidate.id}")
        if extracted_phone and not dialogue.candidate.phone_number:
            dialogue.candidate.phone_number = extracted_phone
            logger.info(f"Сохранен номер телефона для кандидата {dialogue.candidate.id}")

        llm_response = await llm_handler.get_bot_response(
            system_prompt=system_prompt,
            dialogue_history=dialogue.history or [],
            user_message=masked_message
        )
        
        bot_response_text = llm_response.get("response_text", "Ошибка получения ответа.")
        new_state = llm_response.get("new_state", "error_state")
        extracted_data = llm_response.get("extracted_data")

        if extracted_data:
            if extracted_data.get("age"): dialogue.candidate.age = extracted_data["age"]
            if extracted_data.get("citizenship"): dialogue.candidate.citizenship = extracted_data["citizenship"]
            logger.info(f"Обновление данных для кандидата {dialogue.candidate.id}: {extracted_data}")

        if new_state == 'forwarded_to_researcher' or new_state == 'interview_scheduled_spb':
            dialogue.status = 'qualified'
            logger.info(f"Диалогу {dialogue.id} присвоен статус 'qualified'.")
            statistics_manager.update_stats(db, dialogue.vacancy_id, qualified=1)
            
            if not db.query(NotificationQueue).filter_by(candidate_id=dialogue.candidate_id, status='pending').first():
                db.add(NotificationQueue(candidate_id=dialogue.candidate_id, status='pending'))
                logger.info(f"Задача на отправку уведомления по кандидату {dialogue.candidate_id} добавлена в очередь.")
        elif new_state == 'qualification_failed':
            dialogue.status = 'rejected'
            logger.info(f"Диалогу {dialogue.id} присвоен статус 'rejected'.")

        delay = random.uniform(5, 10)
        logger.info(f"Имитация набора текста... Пауза на {delay:.1f} секунд.")
        await asyncio.sleep(delay)
        
        hh_api.send_message(token, dialogue.hh_response_id, bot_response_text)
        
        history_updates = []
        for user_msg in pending_messages:
            masked_msg, _, _ = extract_and_mask_pii(user_msg)
            history_updates.append({'role': 'user', 'content': masked_msg})
        history_updates.append({'role': 'assistant', 'content': bot_response_text, 'extracted_data': extracted_data})
        
        dialogue.dialogue_state = new_state
        dialogue.history = (dialogue.history or []) + history_updates
        dialogue.pending_messages = None
        
        db.commit()
        logger.info(f"Диалог {dialogue.hh_response_id} обработан и обновлен в БД.")


async def process_reminders(db: Session, token: str):
    """Этап 3: Проверяет "зависшие" диалоги и отправляет напоминания."""
    logger.info("Этап 3: Проверка необходимости напоминаний...")
    now = datetime.now(UTC)

    stale_dialogues = db.query(Dialogue).filter(
        Dialogue.status == 'new',
        Dialogue.reminder_level < 4
    ).all()

    if not stale_dialogues:
        logger.info("Нет диалогов, требующих напоминания.")
        return

    reminders_sent = 0
    for dialogue in stale_dialogues:
        time_since_update = now - (dialogue.last_updated or datetime.now(UTC))
        reminder_message = None
        next_reminder_level = dialogue.reminder_level

        if dialogue.reminder_level == 0 and time_since_update > timedelta(minutes=30):
            reminder_message = "Возвращаюсь к вам по поводу нашего диалога. У вас будет возможность продолжить?"
            next_reminder_level = 1
        elif dialogue.reminder_level == 1 and time_since_update > timedelta(hours=2):
            reminder_message = "Подскажите, актуален ли для вас наш диалог?"
            next_reminder_level = 2
        elif dialogue.reminder_level == 2 and time_since_update > timedelta(hours=24):
            reminder_message = "Здравствуйте!Если вам все еще интересно, пожалуйста, дайте знать."
            next_reminder_level = 3
        elif dialogue.reminder_level == 3 and time_since_update > timedelta(hours=48):
            logger.info(f"Диалог {dialogue.hh_response_id} просрочен. Статус изменен на 'timed_out'.")
            dialogue.status = 'timed_out'
            dialogue.reminder_level = 4
            db.commit()
            continue

        if reminder_message:
            reminders_sent += 1
            logger.info(f"Отправка напоминания уровня {next_reminder_level} для диалога {dialogue.hh_response_id}.")
            hh_api.send_message(token, dialogue.hh_response_id, reminder_message)
            dialogue.reminder_level = next_reminder_level
            dialogue.history = (dialogue.history or []) + [{'role': 'assistant', 'content': reminder_message}]
            db.commit()

    if reminders_sent > 0:
        logger.info(f"Всего отправлено напоминаний: {reminders_sent}.")


async def run_worker_cycle():
    """Выполняет один полный асинхронный цикл работы воркера."""
    db = SessionLocal()
    try:
        logger.debug("Начало нового цикла воркера.")
        system_prompt = knowledge_base.get_system_prompt()
        token = hh_api.get_auth_token("client_id", "secret")
        
        # process_new_responses(db, token) # Пока закомментировано, т.к. требует доработки мока
        save_pending_messages(db, token)
        await process_pending_dialogues(db, token, system_prompt)
        await process_reminders(db, token)
        
    except Exception as e:
        logger.critical("Критическая ошибка в главном цикле воркера!", exc_info=True)
        db.rollback()
    finally:
        db.close()
        logger.debug("Сессия БД закрыта.")

if __name__ == "__main__":
    setup_logging(log_filename="hh_worker.log")
    load_dotenv()
    logger.info("HH-Worker запускается...")
    
    while True:
        try:
            asyncio.run(run_worker_cycle())
            logger.info(f"Цикл завершен. Пауза {CYCLE_PAUSE_SECONDS} секунд.")
            time.sleep(CYCLE_PAUSE_SECONDS)
        except (KeyboardInterrupt, SystemExit):
            logger.info("HH-Worker остановлен вручную.")
            break
        except Exception as e:
            logger.critical(f"Неперехваченная ошибка в main-цикле: {e}", exc_info=True)
            logger.info("Произошла критическая ошибка. Пауза 120 секунд перед перезапуском.")
            time.sleep(120)