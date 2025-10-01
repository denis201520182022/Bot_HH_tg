import asyncio
import time
import logging
import random
import datetime
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from sqlalchemy import func

# Импорты
from hr_bot.utils.logger_config import setup_logging
from hr_bot.db.models import SessionLocal, Dialogue, Candidate, Vacancy, NotificationQueue, TrackedVacancy, TrackedRecruiter, AppSettings
from hr_bot.services import hh_api_real as hh_api
from hr_bot.services import knowledge_base
from hr_bot.services import llm_handler
from hr_bot.db import statistics_manager
from hr_bot.utils.pii_masker import extract_and_mask_pii
from hr_bot.utils.system_notifier import send_system_alert

logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ ---
DEBOUNCE_DELAY_SECONDS = 10
CYCLE_PAUSE_SECONDS = 3
TEST_NEGOTIATION_ID = "4784948954" # Установите в None для боевого режима

# --- НАЧАЛО ФИНАЛЬНОГО РЕФАКТОРИНГА ---

async def process_new_responses(recruiter_id: int, vacancy_id: str, vacancy_title: str):
    """Этап 1: Ищет новые отклики. Работает в собственной сессии БД."""
    db = SessionLocal()
    try:
        recruiter = db.get(TrackedRecruiter, recruiter_id) # ИСПРАВЛЕНО: Новый синтаксис get()
        if not recruiter:
            logger.warning(f"process_new_responses: Рекрутер с ID {recruiter_id} не найден.")
            return

        logger.info(f"Этап 1: Проверка 'Неразобранных' для вакансии '{vacancy_title}'...")
        new_responses = await hh_api.get_responses_from_folder(recruiter, db, 'response', [vacancy_id])

        for resp in new_responses:
            response_id = resp.get('id')
            if not response_id or (TEST_NEGOTIATION_ID and response_id != TEST_NEGOTIATION_ID):
                continue
            if db.query(Dialogue).filter_by(hh_response_id=response_id).first():
                continue

            settings = db.query(AppSettings).filter_by(id=1).first()
            if not settings or settings.limit_used >= settings.limit_total:
                logger.warning(f"Лимиты исчерпаны. Отклик {response_id} не будет обработан.")
                continue
            
            logger.info(f"Найден новый отклик {response_id} от {resp['resume']['first_name']}.")
            
            vacancy_in_db = db.query(Vacancy).filter(Vacancy.hh_vacancy_id == vacancy_id).first()
            if not vacancy_in_db:
                vacancy_in_db = Vacancy(hh_vacancy_id=vacancy_id, title=vacancy_title)
                db.add(vacancy_in_db)
            
            candidate = db.query(Candidate).filter(Candidate.hh_resume_id == resp['resume']['id']).first() or Candidate(hh_resume_id=resp['resume']['id'], full_name=f"{resp['resume']['first_name']} {resp['resume']['last_name']}")
            db.add(candidate); db.flush()
            
            dialogue = Dialogue(
                hh_response_id=response_id, candidate_id=candidate.id, vacancy_id=vacancy_in_db.id,
                recruiter_id=recruiter.id, status='new', dialogue_state='initial_processing'
            )
            db.add(dialogue)

            await hh_api.move_response_to_folder(recruiter, db, response_id, 'consider')
            
            settings.limit_used += 1; logger.info(f"Лимит: {settings.limit_used}/{settings.limit_total}")
            
            statistics_manager.update_stats(db, vacancy_in_db.id, responses=1, started_dialogs=1)
            
            messages_data = await hh_api.get_messages(recruiter, db, resp['messages_url'])
            messages = []
            for m in messages_data:
                if m.get('text'):
                    messages.append({'message_id': str(m.get('id', f'noid_{time.time()}')), 'role': 'user', 'content': m['text']})
            if not messages:
                messages = [{'message_id': f'no_msg_{response_id}', 'role': 'user', 'content': "Кандидат откликнулся без сопроводительного письма."}]
            
            dialogue.pending_messages = messages
            dialogue.last_updated = datetime.datetime.now(datetime.timezone.utc)
            db.commit()
            logger.info(f"Диалог {response_id} создан и поставлен в очередь на обработку.")
    except Exception as e:
        logger.error(f"Ошибка в process_new_responses для вакансии {vacancy_id}: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


async def process_ongoing_responses(recruiter_id: int, vacancy_id: str, vacancy_title: str):
    """Этап 2: Ищет новые сообщения. Работает в собственной сессии БД."""
    db = SessionLocal()
    try:
        recruiter = db.get(TrackedRecruiter, recruiter_id) # ИСПРАВЛЕНО: Новый синтаксис get()
        if not recruiter:
            logger.warning(f"process_ongoing_responses: Рекрутер с ID {recruiter_id} не найден.")
            return

        logger.info(f"Этап 2: Проверка 'Подумать' для вакансии '{vacancy_title}'...")
        ongoing_responses = await hh_api.get_responses_from_folder(recruiter, db, 'consider', [vacancy_id])

        for resp in ongoing_responses:
            response_id = resp.get('id')
            if not response_id or (TEST_NEGOTIATION_ID and response_id != TEST_NEGOTIATION_ID) or not resp.get('has_updates'):
                continue

            dialogue = db.query(Dialogue).filter_by(hh_response_id=response_id).first()
            
            if not dialogue:
                logger.warning(f"Найдено обновление для отклика {response_id}, которого нет в БД. Создаю диалог...")
                vacancy_in_db = db.query(Vacancy).filter_by(hh_vacancy_id=vacancy_id).first() or Vacancy(hh_vacancy_id=vacancy_id, title=vacancy_title)
                db.add(vacancy_in_db)
                candidate = db.query(Candidate).filter(Candidate.hh_resume_id == resp['resume']['id']).first() or Candidate(hh_resume_id=resp['resume']['id'], full_name=f"{resp['resume']['first_name']} {resp['resume']['last_name']}")
                db.add(candidate); db.flush()
                dialogue = Dialogue(
                    hh_response_id=response_id, candidate_id=candidate.id, vacancy_id=vacancy_in_db.id,
                    recruiter_id=recruiter.id, status='in_progress', dialogue_state='ongoing_processing'
                )
                db.add(dialogue); db.commit()

            logger.info(f"Найдено обновление в диалоге {response_id}. Получаю полный чат для анализа...")
            all_messages_from_api = await hh_api.get_messages(recruiter, db, resp['messages_url'])
            
            if not dialogue.history:
                logger.info(f"Диалог {response_id}: выполняю первичную синхронизацию истории.")
                full_history_to_save = []
                for msg in all_messages_from_api:
                    if not msg.get('text'): continue
                    author_role = 'user' if msg.get('author', {}).get('participant_type') == 'applicant' else 'assistant'
                    content_to_save = msg['text']
                    if author_role == 'user':
                        masked_content, fio, phone = extract_and_mask_pii(msg['text'])
                        content_to_save = masked_content
                        if fio and not dialogue.candidate.full_name: dialogue.candidate.full_name = fio
                        if phone and not dialogue.candidate.phone_number: dialogue.candidate.phone_number = phone

                    full_history_to_save.append({'message_id': str(msg.get('id')), 'role': author_role, 'content': content_to_save})

                dialogue.history = full_history_to_save
                
                last_unanswered_messages = []
                # Эта логика ищет ПОСЛЕДНЮЮ пачку неотвеченных сообщений
                for msg in reversed(full_history_to_save):
                    if msg['role'] == 'user':
                        last_unanswered_messages.insert(0, msg)
                    else: # Нашли последнее сообщение от ассистента, останавливаемся
                        break
                
                if last_unanswered_messages:
                    dialogue.pending_messages = last_unanswered_messages
                    dialogue.last_updated = datetime.datetime.now(datetime.timezone.utc)
                db.commit()
                continue

            saved_message_ids = {str(h.get('message_id')) for h in (dialogue.history or [])}
            pending_items = dialogue.pending_messages or []
            pending_message_ids = {str(pm.get('message_id')) for pm in pending_items if isinstance(pm, dict)}
            seen_ids = saved_message_ids.union(pending_message_ids)
            new_messages_for_pending = []
            for msg in all_messages_from_api:
                if not msg.get('text'): continue
                mid = str(msg.get('id'))
                if mid in seen_ids: continue
                if msg.get('author', {}).get('participant_type') == 'applicant':
                    new_messages_for_pending.append({'message_id': mid, 'role': 'user', 'content': msg['text']})
            
            if new_messages_for_pending:
                if dialogue.reminder_level > 0: dialogue.reminder_level = 0
                dialogue.pending_messages = (dialogue.pending_messages or []) + new_messages_for_pending
                dialogue.last_updated = datetime.datetime.now(datetime.timezone.utc)
                logger.info(f"Добавлено {len(new_messages_for_pending)} новых сообщений от кандидата в очередь на ответ.")
                db.commit()
    except Exception as e:
        logger.error(f"Ошибка в process_ongoing_responses для вакансии {vacancy_id}: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


# run_hh_worker.py

async def _process_single_dialogue(dialogue_id: int, recruiter_id: int, system_prompt: str):
    """Вспомогательная функция для обработки ОДНОГО диалога в своей сессии."""
    db = SessionLocal()
    try:
        dialogue = db.get(Dialogue, dialogue_id)
        recruiter = db.get(TrackedRecruiter, recruiter_id)

        if not dialogue or not recruiter:
            logger.error(f"Не удалось найти диалог {dialogue_id} или рекрутера {recruiter_id} в БД.")
            return

        logger.info(f"Начинаю обработку сообщений для диалога {dialogue.hh_response_id}...")
        
        pending_messages = dialogue.pending_messages or []
        if not pending_messages:
            logger.warning(f"Диалог {dialogue.id}: нет сообщений в pending_messages.")
            return

        user_entries_to_history, all_masked_content = [], []
        for pm in pending_messages:
            original_content = pm.get('content', '') if isinstance(pm, dict) else str(pm)
            masked_content, extracted_fio, extracted_phone = extract_and_mask_pii(original_content)
            
            if extracted_fio and not dialogue.candidate.full_name: dialogue.candidate.full_name = extracted_fio
            if extracted_phone and not dialogue.candidate.phone_number: dialogue.candidate.phone_number = extracted_phone

            message_id = pm.get('message_id') if isinstance(pm, dict) else f'legacy_{int(time.time())}'
            user_entries_to_history.append({'message_id': message_id, 'role': 'user', 'content': masked_content})
            all_masked_content.append(masked_content)
        
        combined_masked_message = "\n".join(all_masked_content)

        vacancy_title = dialogue.vacancy.title
        context_prefix = f"[ИНСТРУКЦИЯ] Ты общаешься с кандидатом по вакансии '{vacancy_title}'. Веди диалог строго в контексте этой вакансии.\n\n"
        final_system_prompt = context_prefix + system_prompt
        
        llm_response = await llm_handler.get_bot_response(
            system_prompt=final_system_prompt,
            dialogue_history=dialogue.history or [],
            user_message=combined_masked_message
        )
        
        bot_response_text = llm_response.get("response_text", "Ошибка.")
        new_state = llm_response.get("new_state", "error_state")
        extracted_data = llm_response.get("extracted_data")
        
        if dialogue.status == 'new':
            dialogue.status = 'in_progress'
        if extracted_data:
            if extracted_data.get("age"): dialogue.candidate.age = extracted_data["age"]
            if extracted_data.get("citizenship"): dialogue.candidate.citizenship = extracted_data["citizenship"]
            if extracted_data.get("city"): dialogue.candidate.city = extracted_data["city"]
            if extracted_data.get("readiness_to_start"): dialogue.candidate.readiness_to_start = extracted_data["readiness_to_start"]

        # --- БЛОК ИЗМЕНЕНИЙ ЗДЕСЬ ---
        if new_state in ['forwarded_to_researcher', 'interview_scheduled_spb'] and dialogue.status != 'qualified':
            dialogue.status = 'qualified'
            statistics_manager.update_stats(db, dialogue.vacancy_id, qualified=1)
            if not db.query(NotificationQueue).filter_by(candidate_id=dialogue.candidate_id, status='pending').first():
                db.add(NotificationQueue(candidate_id=dialogue.candidate_id, status='pending'))
            
            # --- НОВОЕ ДЕЙСТВИЕ: Перемещаем успешного кандидата в папку "Собеседование" ---
            logger.info(f"Кандидат {dialogue.hh_response_id} прошел квалификацию. Перемещаю в папку 'interview'.")
            await hh_api.move_response_to_folder(recruiter, db, dialogue.hh_response_id, 'interview')
            # --------------------------------------------------------------------------

        elif new_state == 'qualification_failed':
            dialogue.status = 'rejected'
            
            # --- НОВОЕ ДЕЙСТВИЕ: Перемещаем неуспешного кандидата в папку "Отказ" ---
            logger.info(f"Кандидат {dialogue.hh_response_id} не прошел квалификацию. Перемещаю в папку 'discard_by_employer'.")
            await hh_api.move_response_to_folder(recruiter, db, dialogue.hh_response_id, 'discard_by_employer')
            # -----------------------------------------------------------------------
        # --- КОНЕЦ БЛОКА ИЗМЕНЕНИЙ ---
        
        delay = random.uniform(1, 3)
        await asyncio.sleep(delay)
        
        await hh_api.send_message(recruiter, db, dialogue.hh_response_id, bot_response_text)
        
        bot_message_entry = {'message_id': f'bot_{time.time()}', 'role': 'assistant', 'content': bot_response_text, 'extracted_data': extracted_data}
        dialogue.dialogue_state = new_state
        dialogue.history = (dialogue.history or []) + user_entries_to_history + [bot_message_entry]
        dialogue.pending_messages = None
        dialogue.last_updated = datetime.datetime.now(datetime.timezone.utc)
        
        db.commit()
        logger.info(f"Диалог {dialogue.hh_response_id} успешно обработан.")

    except Exception as e:
        logger.error(f"Критическая ошибка при обработке диалога с ID {dialogue_id}: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

async def process_pending_dialogues(recruiter_id: int, system_prompt: str):
    """Этап 3: Находит диалоги и запускает их параллельную обработку."""
    db = SessionLocal()
    try:
        logger.info(f"Этап 3: Поиск отложенных диалогов для рекрутера ID {recruiter_id}...")
        debounce_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=DEBOUNCE_DELAY_SECONDS)
        
        dialogues_to_process = [
            d for d in db.query(Dialogue).filter(
                Dialogue.recruiter_id == recruiter_id,
                Dialogue.last_updated <= debounce_time
            ).all()
            if d.pending_messages and len(d.pending_messages) > 0
        ]

        if not dialogues_to_process:
            logger.info(f"Нет диалогов, готовых к ответу, для рекрутера ID {recruiter_id}.")
            return

        logger.info(f"Найдено {len(dialogues_to_process)} диалогов для параллельной обработки.")
        tasks = [_process_single_dialogue(d.id, recruiter_id, system_prompt) for d in dialogues_to_process]
        await asyncio.gather(*tasks)
        logger.info(f"Пакетная обработка {len(tasks)} диалогов завершена.")
    finally:
        db.close()


# ИСПРАВЛЕНИЕ: Функция теперь принимает ID и создает свою сессию
async def process_reminders(recruiter_id: int):
    """Этап 4: Отправляет напоминания. Работает в собственной сессии БД."""
    db = SessionLocal()
    try:
        recruiter = db.get(TrackedRecruiter, recruiter_id) # ИСПРАВЛЕНО: Новый синтаксис get()
        if not recruiter: return
        logger.info(f"Этап 4: Проверка напоминаний для рекрутера {recruiter.name}...")
        now = datetime.datetime.now(datetime.timezone.utc)
        stale_dialogues = db.query(Dialogue).filter(
            Dialogue.recruiter_id == recruiter.id,
            Dialogue.status == 'in_progress',
            Dialogue.reminder_level < 4
        ).all()
        if not stale_dialogues: return
        
        for dialogue in stale_dialogues:
            time_since_update = now - (dialogue.last_updated or now)
            reminder_message, next_reminder_level = None, dialogue.reminder_level
            if dialogue.reminder_level == 0 and time_since_update > datetime.timedelta(minutes=30):
                reminder_message, next_reminder_level = "Здравствуйте! Возвращаюсь к вам по поводу нашего диалога. У вас будет возможность продолжить?", 1
            elif dialogue.reminder_level == 1 and time_since_update > datetime.timedelta(hours=2):
                reminder_message, next_reminder_level = "Добрый день! Просто хотел уточнить, актуален ли для вас наш диалог?", 2
            elif dialogue.reminder_level == 2 and time_since_update > datetime.timedelta(hours=24):
                reminder_message, next_reminder_level = "Здравствуйте! Это последнее напоминание по нашему диалогу. Если вам все еще интересно, пожалуйста, дайте знать.", 3
            elif dialogue.reminder_level == 3 and time_since_update > datetime.timedelta(hours=48):
                dialogue.status = 'timed_out'; dialogue.reminder_level = 4
                db.commit(); continue
            if reminder_message:
                logger.info(f"Отправка напоминания уровня {next_reminder_level} для диалога {dialogue.hh_response_id}.")
                await hh_api.send_message(recruiter, db, dialogue.hh_response_id, reminder_message)
                dialogue.reminder_level = next_reminder_level
                dialogue.history = (dialogue.history or []) + [{'role': 'assistant', 'content': reminder_message}]
                db.commit()
    finally:
        db.close()


async def run_worker_cycle():
    """Главный цикл, который запускает независимые асинхронные задачи."""
    try:
        logger.info("Начало нового цикла воркера.")
        system_prompt = knowledge_base.get_system_prompt()
        
        db = SessionLocal()
        try:
            all_recruiters = db.query(TrackedRecruiter).all()
            all_vacancies = db.query(TrackedVacancy).all()
        finally:
            db.close()

        if not all_recruiters:
            logger.info("Нет отслеживаемых рекрутеров в БД.")
            return
        
        main_tasks = []
        for recruiter in all_recruiters:
            async def handle_recruiter(rec):
                try:
                    logger.info(f"--- Начинаю работу с рекрутером: {rec.name} (ID: {rec.id}) ---")
                    
                    scan_tasks = []
                    if all_vacancies:
                        for vacancy in all_vacancies:
                            scan_tasks.append(process_new_responses(rec.id, vacancy.vacancy_id, vacancy.title))
                            scan_tasks.append(process_ongoing_responses(rec.id, vacancy.vacancy_id, vacancy.title))
                        await asyncio.gather(*scan_tasks)
                    else:
                        logger.warning(f"Для рекрутера {rec.name} нет отслеживаемых вакансий.")

                    await process_pending_dialogues(rec.id, system_prompt)
                    await process_reminders(rec.id)
                except Exception as e:
                    logger.error(f"Ошибка при обработке рекрутера {rec.name}: {e}", exc_info=True)

            main_tasks.append(handle_recruiter(recruiter))
        
        await asyncio.gather(*main_tasks)

    except Exception as e:
        logger.critical("Критическая ошибка в главном цикле воркера!", exc_info=True)
    finally:
        logger.info("Цикл воркера завершен.")


if __name__ == "__main__":
    setup_logging(log_filename="hh_worker.log")
    load_dotenv()
    logger.info("HH-Worker запускается...")
    while True:
        try:
            asyncio.run(run_worker_cycle())
            logger.info(f"Пауза {CYCLE_PAUSE_SECONDS} секунд перед следующим циклом.")
            time.sleep(CYCLE_PAUSE_SECONDS)
        except (KeyboardInterrupt, SystemExit):
            logger.info("HH-Worker остановлен вручную.")
            break
        except Exception as e:
            logger.critical(f"Неперехваченная критическая ошибка в главном цикле: {e}", exc_info=True)
            time.sleep(120)