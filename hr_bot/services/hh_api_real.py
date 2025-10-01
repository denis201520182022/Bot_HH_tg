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

    # --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
    # Используем новый, правильный URL для всех операций с токенами
    url = "https://api.hh.ru/token" 
    # -------------------------
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
        recruiter.token_expires_at = now + datetime.timedelta(seconds=tokens["expires_in"])
        db.commit()
        logger.info(f"Успешно получен новый access_token для рекрутера {recruiter.name}.")
        return recruiter.access_token
    else:
        logger.critical(f"Ошибка обновления токена для {recruiter.name}: {response.text}")
        recruiter.access_token = None
        recruiter.refresh_token = None
        db.commit()
        return None


async def _make_request(
    recruiter: TrackedRecruiter,
    db: Session,
    method: str,
    endpoint: str,
    full_url: str = None,
    add_user_agent: bool = False, # <--- НОВЫЙ ПАРАМЕТР
    **kwargs,
):
    """Асинхронный универсальный запрос с ограничением по конкурентности."""
    token = await get_access_token(recruiter, db)
    if not token:
        raise ConnectionError(f"Нет валидного токена для {recruiter.name}.")

    url = full_url or f"https://api.hh.ru/{endpoint}"
    headers = kwargs.pop('headers', {})
    headers["Authorization"] = f"Bearer {token}"

    # --- ИЗМЕНЕНИЕ: УСЛОВНОЕ ДОБАВЛЕНИЕ ЗАГОЛОВКА ---
    if add_user_agent and "HH-User-Agent" not in headers:
        headers["HH-User-Agent"] = "HRBot/1.0 (dev@example.com)"
    # ----------------------------------------------------

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

        if response.status_code == 401:
            logger.warning(f"Токен для {recruiter.name} протух. Повторная попытка...")
            recruiter.access_token = None
            db.commit()
            token = await get_access_token(recruiter, db)
            if not token:
                raise ConnectionError(f"Не удалось повторно получить токен для {recruiter.name}")
            headers["Authorization"] = f"Bearer {token}"
            # Повторно добавляем заголовок, если он был нужен
            if add_user_agent and "HH-User-Agent" not in headers:
                headers["HH-User-Agent"] = "HRBot/1.0 (dev@example.com)"
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.request(method, url, headers=headers, **kwargs)

    if response.status_code in [201, 204]:
        return None
        
    response.raise_for_status()
    return response.json() if response.content else None

async def get_responses_from_folder(
    recruiter: TrackedRecruiter, db: Session, folder_id: str, vacancy_ids: list
) -> list:
    """Асинхронно получает список откликов из указанной папки и сохраняет ответ в файл."""
    logger.info(f"REAL_API: Запрос откликов из папки '{folder_id}' для {recruiter.name}...")
    try:
        str_vacancy_ids = [str(vid) for vid in vacancy_ids if vid]

        if not str_vacancy_ids:
            logger.warning(f"В get_responses_from_folder передан пустой список ID вакансий для папки '{folder_id}'.")
            return []

        params = [("vacancy_id", vid) for vid in str_vacancy_ids]
        params.append(("page", "0"))
        params.append(("per_page", "50"))

        response_data = await _make_request(
            recruiter, db, "GET", f"negotiations/{folder_id}", params=params
        )
        
        # --- БЛОК ДЛЯ СОХРАНЕНИЯ В ФАЙЛ ---
        ### if response_data:
         #   try:
        #      # Открываем файл test99.json на запись (w) с кодировкой utf-8
        #     with open("test99.json", 'w', encoding='utf-8') as f:
        #        # Сохраняем весь объект response_data в файл
        #       # ensure_ascii=False - для корректного отображения кириллицы
        #      # indent=2 - для красивого форматирования с отступами
        #   '''  json.dump(response_data, f, ensure_ascii=False, indent=2)''''
        ###logger.info("Сырой ответ от API успешно сохранен в файл test99.json")
            #except Exception as file_error:
             #  # #logger.error(f"Не удалось сохранить ответ в файл test99.json: {file_error}")
        # --- КОНЕЦ БЛОКА ---

        return response_data.get("items", []) if response_data else []

    except Exception as e:
        logger.error(f"Не удалось получить отклики из папки '{folder_id}': {e}", exc_info=True)
        return []

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


async def move_response_to_folder(recruiter: TrackedRecruiter, db: Session, negotiation_id: str, folder_id: str):
    """Асинхронно перемещает отклик в указанную папку, используя правильный PUT-запрос."""
    logger.info(f"REAL_API: Перемещение отклика {negotiation_id} в папку '{folder_id}'...")
    try:
        endpoint = f"negotiations/{folder_id}/{negotiation_id}"
        # --- ИЗМЕНЕНИЕ: ПЕРЕДАЕМ ПАРАМЕТР, ЧТОБЫ ДОБАВИТЬ ЗАГОЛОВОК ---
        await _make_request(recruiter, db, "PUT", endpoint, add_user_agent=True)
        # --------------------------------------------------------------------
        logger.info(f"Отклик {negotiation_id} успешно перемещен в '{folder_id}'.")
    except Exception as e:
        logger.error(f"Не удалось переместить отклик {negotiation_id} в папку {folder_id}: {e}", exc_info=True)
        raise e