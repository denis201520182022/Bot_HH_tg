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
from hr_bot.db.models import SessionLocal, Dialogue, Candidate, Vacancy, NotificationQueue, TrackedRecruiter, AppSettings
from hr_bot.services import hh_api_real as hh_api
from hr_bot.services import knowledge_base
from hr_bot.services import llm_handler
from hr_bot.db import statistics_manager
from hr_bot.utils.pii_masker import extract_and_mask_pii
from hr_bot.utils.system_notifier import send_system_alert
import signal
import sys
from hr_bot.services.llm_handler import cleanup

logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ ---
DEBOUNCE_DELAY_SECONDS = 10
CYCLE_PAUSE_SECONDS = 3
TEST_NEGOTIATION_ID = None # Установите в None для боевого режима

# Флаг для graceful shutdown
shutdown_requested = False

def signal_handler(sig, frame):
    """Обработчик сигналов для graceful shutdown"""
    global shutdown_requested
    logger.info("Получен сигнал остановки. Завершаем работу...")
    shutdown_requested = True

async def get_all_active_vacancies_for_recruiter(recruiter: TrackedRecruiter, db: Session) -> list:
    """
    Асинхронно получает список всех активных вакансий для рекрутера,
    и синхронизирует их с локальной базой данных.
    """
    logger.debug(f"Получение и синхронизация списка активных вакансий для рекрутера {recruiter.name}...")
    try:
        me_data = await hh_api._make_request(recruiter, db, "GET", "me")
        if not me_data or not me_data.get('employer') or not me_data['employer'].get('id'):
            logger.error(f"Не удалось получить employer_id для рекрутера {recruiter.name}.")
            return []
        employer_id = me_data['employer']['id']

        all_vacancies_from_api = []
        page = 0
        while True:
            vacancies_page = await hh_api._make_request(
                recruiter, db, "GET", f"employers/{employer_id}/vacancies/active",
                params={'page': page, 'per_page': 50}
            )
            if not vacancies_page or not vacancies_page.get('items'):
                break
            
            all_vacancies_from_api.extend(vacancies_page['items'])
            
            if page >= vacancies_page.get('pages', 1) - 1:
                break
            page += 1
        
        # --- НАЧАЛО НОВОЙ ЛОГИКИ СИНХРОНИЗАЦИИ ---
        if not all_vacancies_from_api:
            logger.error(f"Не найдено активных вакансий для рекрутера {recruiter.name}.")
            return []

        logger.debug(f"Найдено {len(all_vacancies_from_api)} активных вакансий. Синхронизация с БД...")
        
        for vacancy_data in all_vacancies_from_api:
            hh_vacancy_id = str(vacancy_data.get("id"))
            
            # Ищем, есть ли уже такая вакансия в нашей БД
            vacancy_in_db = db.query(Vacancy).filter_by(hh_vacancy_id=hh_vacancy_id).first()
            
            if not vacancy_in_db:
                # Если нет - создаем новую запись
                new_vacancy = Vacancy(
                    hh_vacancy_id=hh_vacancy_id,
                    title=vacancy_data.get("name", "Без названия"),
                    city=vacancy_data.get("area", {}).get("name") # Извлекаем город из 'area'
                )
                db.add(new_vacancy)
                logger.debug(f"  -> Добавлена новая вакансия в БД: '{new_vacancy.title}' (ID: {hh_vacancy_id})")
            else:
                # Если есть - проверяем, не изменились ли данные (название или город)
                if (vacancy_in_db.title != vacancy_data.get("name") or 
                    vacancy_in_db.city != vacancy_data.get("area", {}).get("name")):
                    
                    vacancy_in_db.title = vacancy_data.get("name", "Без названия")
                    vacancy_in_db.city = vacancy_data.get("area", {}).get("name")
                    logger.debug(f"  -> Обновлены данные для вакансии: '{vacancy_in_db.title}' (ID: {hh_vacancy_id})")

        db.commit() # Сохраняем все добавления и обновления
        # --- КОНЕЦ НОВОЙ ЛОГИКИ СИНХРОНИЗАЦИИ ---

        return all_vacancies_from_api

    except Exception as e:
        logger.error(f"Ошибка при получении списка вакансий для рекрутера {recruiter.name}: {e}", exc_info=True)
        db.rollback() # Откатываем изменения в БД в случае ошибки
        return []

# Замените вашу старую process_new_responses на эту:

async def process_new_responses(recruiter_id: int, vacancy_ids: list):
    """Этап 1: Ищет новые отклики по СПИСКУ вакансий."""
    db = SessionLocal()
    try:
        recruiter = db.get(TrackedRecruiter, recruiter_id)
        if not recruiter:
            logger.warning(f"process_new_responses: Рекрутер с ID {recruiter_id} не найден.")
            return

        if not vacancy_ids:
            logger.error("Этап 1: Нет активных вакансий для проверки 'Неразобранных'.")
            return
            
        logger.debug(f"Этап 1: Проверка 'Неразобранных' для {len(vacancy_ids)} вакансий...")
        # Теперь эта функция возвращает список пар: [(отклик_1, id_вакансии_1), (отклик_2, id_вакансии_1), ...]
        new_responses_with_vacancy_ids = await hh_api.get_responses_from_folder(recruiter, db, 'response', vacancy_ids)

        # --- ИЗМЕНЕНИЕ №1: Меняем цикл, чтобы он распаковывал пару ---
        for resp, associated_vacancy_id_str in new_responses_with_vacancy_ids:
            response_id = resp.get('id')
            if not response_id or (TEST_NEGOTIATION_ID and response_id != TEST_NEGOTIATION_ID):
                continue
            if db.query(Dialogue).filter_by(hh_response_id=response_id).first():
                continue

            settings = db.query(AppSettings).filter_by(id=1).first()
            if not settings or settings.limit_used >= settings.limit_total:
                logger.warning(f"Лимиты исчерпаны. Отклик {response_id} не будет обработан.")
                continue
            
            # --- ИЗМЕНЕНИЕ №2: Полностью новая, надежная логика ---
            logger.info(f"Найден новый отклик {response_id} от {resp['resume']['first_name']} на вакансию ID {associated_vacancy_id_str}.")
            
            # Мы больше не пытаемся извлечь ID из отклика. Мы его уже знаем.
            # Просто находим соответствующую вакансию в нашей базе данных.
            vacancy_in_db = db.query(Vacancy).filter(Vacancy.hh_vacancy_id == associated_vacancy_id_str).first()

            # Защитная проверка на случай, если вакансия не была синхронизирована ранее.
            if not vacancy_in_db:
                logger.error(
                    f"КРИТИЧЕСКАЯ ОШИБКА: Вакансия с hh_vacancy_id={associated_vacancy_id_str} не найдена в БД, "
                    f"хотя должна была быть создана ранее. Отклик {response_id} будет пропущен."
                )
                continue
            # --- КОНЕЦ ИЗМЕНЕНИЙ ---

            candidate = db.query(Candidate).filter(Candidate.hh_resume_id == resp['resume']['id']).first() or Candidate(hh_resume_id=resp['resume']['id'], full_name=f"{resp['resume']['first_name']} {resp['resume']['last_name']}")
            db.add(candidate)
            db.flush()
            
            dialogue = Dialogue(
                hh_response_id=response_id, 
                candidate_id=candidate.id, 
                vacancy_id=vacancy_in_db.id,
                recruiter_id=recruiter_id, # Используем ID из аргумента функции для 100% надежности
                status='new', 
                dialogue_state='initial_processing'
            )
            db.add(dialogue)

            await hh_api.move_response_to_folder(recruiter, db, response_id, 'consider')
            
            settings.limit_used += 1
            logger.info(f"Лимит: {settings.limit_used}/{settings.limit_total}")
            
            statistics_manager.update_stats(db, vacancy_in_db.id, responses=1, started_dialogs=1)
            
            messages_data = await hh_api.get_messages(recruiter, db, resp['messages_url'])
            messages = [{'message_id': str(m.get('id')), 'role': 'user', 'content': m['text']} for m in messages_data if m.get('text')]
            if not messages:
                messages = [{'message_id': f'no_msg_{response_id}', 'role': 'user', 'content': "Кандидат откликнулся без сопроводительного письма."}]
            
            dialogue.pending_messages = messages
            dialogue.last_updated = func.now()
            db.commit()
            logger.info(f"Диалог {response_id} создан и поставлен в очередь на обработку.")
    except Exception as e:
        logger.error(f"Ошибка в process_new_responses: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

        
async def process_ongoing_responses(recruiter_id: int, vacancy_ids: list):
    """Этап 2: Ищет новые сообщения в папках 'Подумать' и 'Собеседование'."""
    db = SessionLocal()
    try:
        recruiter = db.get(TrackedRecruiter, recruiter_id)
        if not recruiter:
            logger.warning(f"process_ongoing_responses: Рекрутер с ID {recruiter_id} не найден.")
            return

        if not vacancy_ids:
            logger.warning("Этап 2: Нет активных вакансий для проверки обновлений.")
            return

        # --- НАЧАЛО ИЗМЕНЕНИЙ ---
        logger.debug(f"Этап 2: Проверка обновлений в папках 'Подумать' и 'Собеседование' для {len(vacancy_ids)} вакансий...")
        
        # Создаем асинхронные задачи для запроса откликов из обеих папок параллельно
        consider_task = hh_api.get_responses_from_folder(recruiter, db, 'consider', vacancy_ids)
        interview_task = hh_api.get_responses_from_folder(recruiter, db, 'interview', vacancy_ids)
        
        # Ожидаем завершения обеих задач и объединяем их результаты в один общий список
        all_ongoing_responses = []
        results = await asyncio.gather(consider_task, interview_task)
        for result_list in results:
            all_ongoing_responses.extend(result_list)
        # --- КОНЕЦ ИЗМЕНЕНИЙ ---

        # Распаковываем кортеж (отклик, id_вакансии) прямо в цикле for.
        # Нам нужен только сам объект отклика, поэтому ID вакансии игнорируем (переменная `_`).
        for resp, _ in all_ongoing_responses:
            response_id = resp.get('id')
            
            if not response_id or (TEST_NEGOTIATION_ID and response_id != TEST_NEGOTIATION_ID) or not resp.get('has_updates'):
                continue

            dialogue = db.query(Dialogue).filter_by(hh_response_id=response_id).first()
            if not dialogue:
                logger.debug(f"Найдено обновление для отклика {response_id}, которого нет в нашей БД. Пропускаем.")
                continue

            all_messages_from_api = await hh_api.get_messages(recruiter, db, resp['messages_url'])
            
            saved_message_ids = {str(h.get('message_id')) for h in (dialogue.history or [])}
            pending_message_ids = {str(p.get('message_id')) for p in (dialogue.pending_messages or []) if isinstance(p, dict)}
            seen_ids = saved_message_ids.union(pending_message_ids)
            
            new_messages_for_pending = [
                {'message_id': str(msg.get('id')), 'role': 'user', 'content': msg['text']}
                for msg in all_messages_from_api
                if msg.get('text') and str(msg.get('id')) not in seen_ids and msg.get('author', {}).get('participant_type') == 'applicant'
            ]
            
            if new_messages_for_pending:
                if dialogue.reminder_level > 0:
                    dialogue.reminder_level = 0
                dialogue.pending_messages = (dialogue.pending_messages or []) + new_messages_for_pending
                dialogue.last_updated = func.now()
                db.commit()
                logger.info(f"Добавлено {len(new_messages_for_pending)} новых сообщений в диалог {response_id}.")
                
    except Exception as e:
        logger.error(f"Ошибка в process_ongoing_responses: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

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
            logger.warning(f"Диалог {dialogue.id}: нет сообщений в pending_messages, обработка отменена.")
            return

        # Шаг 1: Подготовка сообщений кандидата и маскирование PII
        user_entries_to_history = []
        all_masked_content = []
        for pm in pending_messages:
            original_content = pm.get('content', '') if isinstance(pm, dict) else str(pm)
            masked_content, extracted_fio, extracted_phone = extract_and_mask_pii(original_content)
            
            # Если маскер извлек ФИО, мы ВСЕГДА его обновляем, так как оно более полное.
            if extracted_fio:
                dialogue.candidate.full_name = extracted_fio
    
            # Телефон обновляем, только если он был пуст (чтобы не затереть случайно).
            if extracted_phone:
                dialogue.candidate.phone_number = extracted_phone

            message_id = pm.get('message_id') if isinstance(pm, dict) else f'legacy_{int(time.time())}'
            user_entries_to_history.append({'message_id': message_id, 'role': 'user', 'content': masked_content})
            all_masked_content.append(masked_content)
        
        combined_masked_message = "\n".join(all_masked_content)
        
        # Шаг 2: Формирование динамического промпта с названием вакансии и городом
        final_system_prompt = ""
        extracted_data_bool = True
        vacancy_title = dialogue.vacancy.title
        vacancy_city = dialogue.vacancy.city or "город не указан" # Берем город из связанной вакансии
        if dialogue.status == 'qualified':
            context_prefix = (
                f"[ИНСТРУКЦИЯ] Ты общаешься с кандидатом по вакансии '{vacancy_title}' в городе '{vacancy_city}'. "
                f"Данный кандидат уже прошел квалификацию и ему назначено собеседование."
                f"[RULE] Заново проводить квалификацию не нужно. Добавлять что либо в extracted_data запрещено. Просто отвечай на вопросы кандидата (в рамках вакансии), если он задает."
                f"Веди диалог строго в контексте этой вакансии и города.\n\n"
            )
            extracted_data_bool = False
        else:
            context_prefix = (
                f"[ИНСТРУКЦИЯ] Ты общаешься с кандидатом по вакансии '{vacancy_title}' в городе '{vacancy_city}'. "
                f"Веди диалог строго в контексте этой вакансии и города.\n\n"
            )
        final_system_prompt = context_prefix + system_prompt
        
        # Шаг 3: Запрос к LLM
        llm_response = await llm_handler.get_bot_response(
            system_prompt=final_system_prompt,
            dialogue_history=dialogue.history or [],
            user_message=combined_masked_message
        )
        
        bot_response_text = llm_response.get("response_text", "Скоро вернусь к вам с ответом.")
        new_state = llm_response.get("new_state", "error_state")
        extracted_data = llm_response.get("extracted_data")
        
        # Шаг 4: Обновление статусов и данных кандидата
        if dialogue.status == 'new':
            dialogue.status = 'in_progress'
        
        if extracted_data and extracted_data_bool:
            if extracted_data.get("age"): dialogue.candidate.age = extracted_data["age"]
            if extracted_data.get("citizenship"): dialogue.candidate.citizenship = extracted_data["citizenship"]
            if extracted_data.get("city"): dialogue.candidate.city = extracted_data["city"]
            if extracted_data.get("readiness_to_start"): dialogue.candidate.readiness_to_start = extracted_data["readiness_to_start"]

        # Шаг 5: Обработка финальных состояний диалога
        if new_state in ['forwarded_to_researcher', 'interview_scheduled_spb'] and dialogue.status != 'qualified':
            dialogue.status = 'qualified'
            statistics_manager.update_stats(db, dialogue.vacancy_id, qualified=1)
            if not db.query(NotificationQueue).filter_by(candidate_id=dialogue.candidate_id, status='pending').first():
                db.add(NotificationQueue(candidate_id=dialogue.candidate_id, status='pending'))
            
            logger.info(f"Кандидат {dialogue.hh_response_id} прошел квалификацию. Перемещаю в папку 'interview'.")
            await hh_api.move_response_to_folder(recruiter, db, dialogue.hh_response_id, 'interview')

        elif new_state == 'qualification_failed':
            dialogue.status = 'rejected'
            
            logger.info(f"Кандидат {dialogue.hh_response_id} не прошел квалификацию. Перемещаю в папку 'discard_by_employer'.")
            await hh_api.move_response_to_folder(recruiter, db, dialogue.hh_response_id, 'discard_by_employer')
        
        # Шаг 6: Отправка ответа кандидату
        delay = random.uniform(1, 3)
        await asyncio.sleep(delay)
        
        await hh_api.send_message(recruiter, db, dialogue.hh_response_id, bot_response_text)
        
        # Шаг 7: Сохранение результатов в БД
        bot_message_entry = {'message_id': f'bot_{time.time()}', 'role': 'assistant', 'content': bot_response_text, 'extracted_data': extracted_data}
        dialogue.dialogue_state = new_state
        dialogue.history = (dialogue.history or []) + user_entries_to_history + [bot_message_entry]
        dialogue.pending_messages = None
        dialogue.last_updated = func.now() # Используем func.now() для установки времени на стороне БД
        
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
        logger.debug(f"Этап 3: Поиск отложенных диалогов для рекрутера ID {recruiter_id}...")
        debounce_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=DEBOUNCE_DELAY_SECONDS)
        # ОТЛАДКА: Смотрим ВСЕ диалоги с pending_messages
        all_pending = [
                d for d in db.query(Dialogue).filter(
                    Dialogue.recruiter_id == recruiter_id,
                    Dialogue.last_updated <= debounce_time
                ).all()
                if d.pending_messages and len(d.pending_messages) > 0
            ]
        
        logger.debug(f"[DEBUG] Всего диалогов с pending_messages: {len(all_pending)}")
        for d in all_pending:
            logger.info(f"[DEBUG] Диалог {d.hh_response_id}: last_updated={d.last_updated}, debounce_time={debounce_time}, готов={(d.last_updated <= debounce_time)}")
        
        dialogues_to_process = [
                d for d in db.query(Dialogue).filter(
                    Dialogue.recruiter_id == recruiter_id,
                    Dialogue.last_updated <= debounce_time
                ).all()
                if d.pending_messages and len(d.pending_messages) > 0
            ]

        if not dialogues_to_process:
            logger.debug(f"Нет диалогов, готовых к ответу, для рекрутера ID {recruiter_id}.")
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
        logger.debug(f"Этап 4: Проверка напоминаний для рекрутера {recruiter.name}...")
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
                reminder_message, next_reminder_level = "Возвращаюсь к вам по поводу нашего диалога. У вас будет возможность продолжить?", 1
            elif dialogue.reminder_level == 1 and time_since_update > datetime.timedelta(hours=2):
                reminder_message, next_reminder_level = "Хотела бы уточнить, актуален ли для вас наш диалог?", 2
            elif dialogue.reminder_level == 2 and time_since_update > datetime.timedelta(hours=24):
                reminder_message, next_reminder_level = "Здравствуйте! Если вам все еще интересно, пожалуйста, дайте знать.", 3
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


# --- ФИНАЛЬНАЯ, ИСПРАВЛЕННАЯ ВЕРСИЯ ---
async def handle_single_recruiter(rec: TrackedRecruiter, system_prompt: str):
    """Обрабатывает полный цикл для одного рекрутера."""
    db_session = SessionLocal()
    try:
        logger.debug(f"--- Начинаю работу с рекрутером: {rec.name} (ID: {rec.id}) ---")
        
        active_vacancies = await get_all_active_vacancies_for_recruiter(rec, db_session)
        
        if active_vacancies:
            vacancy_ids = [v['id'] for v in active_vacancies]
            
            scan_tasks = [
                process_new_responses(rec.id, vacancy_ids),
                process_ongoing_responses(rec.id, vacancy_ids)
            ]
            await asyncio.gather(*scan_tasks)
            
            # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Полностью закрываем и пересоздаём сессию
            db_session.close()
            db_session = SessionLocal()
            # Явно сбрасываем кэш
            db_session.expire_all()
        else:
            logger.warning(f"Для рекрутера {rec.name} не найдено активных вакансий.")

        await process_pending_dialogues(rec.id, system_prompt)
        await process_reminders(rec.id)
        
    except Exception as e:
        logger.error(f"Ошибка при обработке рекрутера {rec.name}: {e}", exc_info=True)
    finally:
        db_session.close()


async def run_worker_cycle():
    """Главный цикл, который запускает независимые асинхронные задачи."""
    try:
        logger.debug("Начало нового цикла воркера.")
        system_prompt = knowledge_base.get_system_prompt()
        
        db = SessionLocal()
        try:
            all_recruiters = db.query(TrackedRecruiter).all()
        finally:
            db.close()

        if not all_recruiters:
            logger.warning("Нет отслеживаемых рекрутеров в БД. Цикл пропущен.")
            return
        
        # Теперь мы создаем список задач, вызывая нашу внешнюю функцию
        tasks = [handle_single_recruiter(recruiter, system_prompt) for recruiter in all_recruiters]
        
        await asyncio.gather(*tasks)

    except Exception as e:
        logger.critical("Критическая ошибка в главном цикле воркера!", exc_info=True)
    finally:
        logger.debug("Цикл воркера завершен.")



async def main():
    """Главная асинхронная функция."""
    from hr_bot.services.llm_handler import cleanup
    
    # Регистрируем обработчики сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("HH-Worker запускается...")
    
    try:
        while not shutdown_requested:
            try:
                # ИСПРАВЛЕНИЕ: Убрали asyncio.run(), просто вызываем await
                await run_worker_cycle()
                
                logger.debug(f"Пауза {CYCLE_PAUSE_SECONDS} секунд перед следующим циклом.")
                
                # Асинхронная пауза с проверкой флага
                for _ in range(CYCLE_PAUSE_SECONDS):
                    if shutdown_requested:
                        break
                    await asyncio.sleep(1)
                    
            except Exception as e:
                logger.critical(f"Неперехваченная критическая ошибка в главном цикле: {e}", exc_info=True)
                if not shutdown_requested:
                    await asyncio.sleep(120)
    finally:
        logger.info("Закрываем соединения...")
        await cleanup()
        logger.info("HH-Worker полностью остановлен.")


if __name__ == "__main__":
    setup_logging(log_filename="hh_worker.log")
    load_dotenv()
    
    # ИСПРАВЛЕНИЕ: Запускаем main() ОДИН раз через asyncio.run()
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Приложение принудительно завершено.")