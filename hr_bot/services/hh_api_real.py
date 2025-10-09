import os
import logging
import datetime
import asyncio
import json # <--- ДОБАВЛЕН ИМПОРТ
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from hr_bot.db.models import TrackedRecruiter
from hr_bot.utils.api_logger import setup_api_logger
import httpx

load_dotenv()
logger = logging.getLogger(__name__)
api_raw_logger = setup_api_logger()

CLIENT_ID = os.getenv('HH_CLIENT_ID')
CLIENT_SECRET = os.getenv('HH_CLIENT_SECRET')

# Устанавливаем лимит на количество одновременных запросов к API hh.ru.
MAX_CONCURRENT_REQUESTS = 10
API_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)


async def get_access_token(recruiter: TrackedRecruiter, db: Session) -> str | None:
    """Асинхронно получает или обновляет access_token для рекрутера."""
    now = datetime.datetime.now(datetime.timezone.utc)

    if recruiter.access_token and recruiter.token_expires_at and recruiter.token_expires_at > now:
        return recruiter.access_token

    logger.info(f"Токен для рекрутера {recruiter.name} истек или отсутствует. Обновляю...")

    if not recruiter.refresh_token:
        logger.error(f"У рекрутера {recruiter.name} (ID: {recruiter.recruiter_id}) нет refresh_token!")
        return None

    url = "https://api.hh.ru/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": recruiter.refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }

    async with API_SEMAPHORE:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, data=data)

    if response.status_code == 200:
        tokens = response.json()
        recruiter.access_token = tokens["access_token"]
        if "refresh_token" in tokens:
            recruiter.refresh_token = tokens["refresh_token"]
        # Рассчитываем новое время с запасом в 5 минут, чтобы избежать проблем на границе времени
        recruiter.token_expires_at = now + datetime.timedelta(seconds=tokens["expires_in"] - 300)
        db.commit()
        logger.info(f"Успешно получен новый access_token для рекрутера {recruiter.name}.")
        return recruiter.access_token
    else:
        # --- НОВАЯ, УМНАЯ ЛОГИКА ОБРАБОТКИ ОШИБОК ---
        try:
            error_data = response.json()
            error_description = error_data.get("error_description")

            if error_description == "token not expired":
                logger.error(
                    f"Попытка обновить токен для {recruiter.name} отклонена: токен еще не истек. "
                    f"Возвращаем старый токен, так как он все еще действителен."
                )
                # Сервер подтвердил, что старый токен жив. Возвращаем его.
                # Чтобы разорвать цикл, если дата в БД неверна, искусственно продлеваем 
                # жизнь токена в нашей БД на 5 минут. За это время он точно истечет.
                recruiter.token_expires_at = now + datetime.timedelta(minutes=5)
                db.commit()
                return recruiter.access_token
            else:
                # Другая ошибка (refresh_token отозван, невалиден и т.д.)
                logger.critical(f"Ошибка обновления токена для {recruiter.name}: {response.text}")
                recruiter.access_token = None # Обнуляем только access_token
                db.commit()
                return None

        except Exception:
            # На случай, если ответ от сервера был не в формате JSON
            logger.critical(f"Критическая ошибка при обработке неудачного обновления токена для {recruiter.name}: {response.text}")
            recruiter.access_token = None
            db.commit()
            return None


async def _make_request(
    recruiter: TrackedRecruiter,
    db: Session,
    method: str,
    endpoint: str,
    full_url: str = None,
    # Параметр add_user_agent полностью удален
    **kwargs,
):
    """Асинхронный универсальный запрос с ограничением по конкурентности."""
    token = await get_access_token(recruiter, db)
    if not token:
        raise ConnectionError(f"Нет валидного токена для {recruiter.name}.")

    url = full_url or f"https://api.hh.ru/{endpoint}"
    headers = kwargs.pop('headers', {})
    headers["Authorization"] = f"Bearer {token}"

    # --- ИСПРАВЛЕНИЕ: Заголовок HH-User-Agent добавляется всегда ---
    # Рекомендуется использовать email, связанный с вашим приложением на hh.ru
    headers["HH-User-Agent"] = "ZaBota-Bot/1.0 (hbfys@mail.com)"
    # -------------------------------------------------------------

    request_log = (
        f"REQUEST -->\n  Method: {method}\n  URL: {url}\n  Headers: {headers}\n"
        f"  Params: {kwargs.get('params')}\n  Data: {kwargs.get('data')}\n  JSON: {kwargs.get('json')}"
    )
    api_raw_logger.debug(request_log)

    async with API_SEMAPHORE:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(method, url, headers=headers, **kwargs)

        response_log = (
            f"<-- RESPONSE\n  Status Code: {response.status_code}\n"
            f"  Headers: {response.headers}\n  Body: {response.text}"
        )
        api_raw_logger.debug(response_log)

        if response.status_code == 403:
            logger.warning(f"Токен для {recruiter.name} протух. Повторная попытка...")
            recruiter.access_token = None
            db.commit()
            token = await get_access_token(recruiter, db)
            if not token:
                raise ConnectionError(f"Не удалось повторно получить токен для {recruiter.name}")
            
            headers["Authorization"] = f"Bearer {token}"
            # --- ИСПРАВЛЕНИЕ: Повторно добавляем заголовок и здесь ---
            headers["HH-User-Agent"] = "ZaBota-Bot/1.0 (hbfys@mail.com)"
            # ---------------------------------------------------------
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.request(method, url, headers=headers, **kwargs)

    if response.status_code in [201, 204]:
        return None
        
    response.raise_for_status()
    return response.json() if response.content else None


# hr_bot/services/hh_api_real.py

async def get_responses_from_folder(
    recruiter: TrackedRecruiter, db: Session, folder_id: str, vacancy_ids: list
) -> list:
    """
    Асинхронно получает список откликов из указанной папки,
    делая ОТДЕЛЬНЫЙ запрос для КАЖДОЙ вакансии и "помечая" каждый отклик
    ID его вакансии.
    """
    logger.debug(
        f"REAL_API: Запрос откликов из папки '{folder_id}' для {len(vacancy_ids)} вакансий..."
    )
    
    tasks = []
    
    for vacancy_id in vacancy_ids:
        if not vacancy_id:
            continue
            
        async def fetch_for_vacancy(vid):
            try:
                params = {"vacancy_id": str(vid), "page": "0", "per_page": "50"}
                response_data = await _make_request(
                    recruiter, db, "GET", f"negotiations/{folder_id}", params=params
                )
                items = response_data.get("items", []) if response_data else []
                
                # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
                # Возвращаем не просто список откликов, а список пар (отклик, ID вакансии)
                return [(item, str(vid)) for item in items]
                # -------------------------

            except Exception as e:
                logger.error(f"Ошибка при запросе откликов для вакансии {vid} в папке '{folder_id}': {e}")
                return []

        tasks.append(fetch_for_vacancy(vacancy_id))

    results_from_all_vacancies = await asyncio.gather(*tasks)
    
    all_responses_with_vacancy_id = []
    for single_vacancy_responses in results_from_all_vacancies:
        all_responses_with_vacancy_id.extend(single_vacancy_responses)
        
    # Теперь лог более точный
    logger.debug(f"Суммарно найдено {len(all_responses_with_vacancy_id)} откликов в папке '{folder_id}'.")
    return all_responses_with_vacancy_id

async def get_messages(recruiter: TrackedRecruiter, db: Session, messages_url: str) -> list:
    """Асинхронно получает ПОЛНУЮ историю сообщений постранично."""
    logger.info(f"REAL_API: Запрос ВСЕХ сообщений по {messages_url}...")
    all_messages, page = [], 0

    while True:
        try:
            params = {"page": page, "per_page": 50}
            response_data = await _make_request(recruiter, db, "GET", "", full_url=messages_url, params=params)

            if not response_data or not response_data.get("items"):
                break

            all_messages.extend(response_data["items"])

            if page >= response_data.get("pages", 1) - 1:
                break
            page += 1
        except Exception as e:
            logger.error(f"Ошибка при получении страницы {page} сообщений: {e}")
            break

    all_messages.sort(key=lambda x: x.get("created_at", ""))
    return all_messages


async def send_message(recruiter: TrackedRecruiter, db: Session, negotiation_id: str, message_text: str) -> bool:
    """Асинхронно отправляет сообщение в чат отклика."""
    logger.info(f"REAL_API: Отправка сообщения в диалог {negotiation_id} от {recruiter.name}...")
    try:
        await _make_request(
            recruiter,
            db,
            "POST",
            f"negotiations/{negotiation_id}/messages",
            data={"message": message_text},
        )
        return True
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение в диалог {negotiation_id}: {e}", exc_info=True)
        return False


# hr_bot/services/hh_api_real.py

async def move_response_to_folder(recruiter: TrackedRecruiter, db: Session, negotiation_id: str, folder_id: str):
    """Асинхронно перемещает отклик в указанную папку, используя правильный PUT-запрос."""
    logger.info(f"REAL_API: Перемещение отклика {negotiation_id} в папку '{folder_id}'...")
    try:
        endpoint = f"negotiations/{folder_id}/{negotiation_id}"
        await _make_request(recruiter, db, "PUT", endpoint)
        
        # --- ВАШЕ ДОПОЛНЕНИЕ ---
        # Добавляем лог, который подтверждает успешное выполнение операции
        logger.info(f"УСПЕХ: Отклик {negotiation_id} был успешно перемещен в папку '{folder_id}'.")
        # -------------------------

    except Exception as e:
        logger.error(f"Не удалось переместить отклик {negotiation_id} в папку {folder_id}: {e}", exc_info=True)
        # Перевыбрасываем исключение, чтобы код, который вызвал эту функцию, 
        # знал о проблеме и мог откатить транзакцию в БД.
        raise e