# hr_bot/services/hh_api_real.py
import requests
import os
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

CLIENT_ID = os.getenv('HH_CLIENT_ID')
CLIENT_SECRET = os.getenv('HH_CLIENT_SECRET')
REFRESH_TOKEN = os.getenv('HH_REFRESH_TOKEN')

_access_token = None # Кэш для access_token

def get_access_token():
    """Получает новый access_token, используя refresh_token."""
    global _access_token
    url = "https://hh.ru/oauth/token"
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': REFRESH_TOKEN
    }
    # Для этого запроса авторизация не нужна
    response = requests.post(url, data=data)
    
    if response.status_code == 200:
        _access_token = response.json()['access_token']
        logger.info("Успешно получен новый access_token для HH.ru API.")
        return _access_token
    else:
        logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось обновить access_token! Ответ: {response.text}")
        return None

def _make_request(method, endpoint, **kwargs):
    """Внутренняя функция для выполнения запросов с обработкой истекшего токена."""
    global _access_token
    if not _access_token:
        get_access_token()
    
    url = f"https://api.hh.ru/{endpoint}"
    headers = {"Authorization": f"Bearer {_access_token}"}
    
    response = requests.request(method, url, headers=headers, **kwargs)
    
    # Если токен протух, пробуем еще раз
    if response.status_code == 401:
        logger.warning("Access token истек. Пытаюсь получить новый...")
        get_access_token()
        headers["Authorization"] = f"Bearer {_access_token}"
        response = requests.request(method, url, headers=headers, **kwargs)
        
    response.raise_for_status() # Вызовет исключение для всех кодов ошибок 4xx/5xx
    return response.json()

# --- Реализация наших интерфейсных функций ---

def get_new_responses():
    """Получает новые (непросмотренные) отклики."""
    logger.info("REAL_API: Запрос новых откликов с hh.ru...")
    # GET /negotiations - эндпоинт для откликов
    # show_unread=True - параметр для получения только непрочитанных
    return _make_request("GET", "negotiations", params={"show_unread": "true"}).get('items', [])

def send_message(negotiation_id, message_text):
    """Отправляет сообщение в чат отклика."""
    logger.info(f"REAL_API: Отправка сообщения в диалог {negotiation_id}...")
    # POST /negotiations/{negotiation_id}/messages
    endpoint = f"negotiations/{negotiation_id}/messages"
    payload = {"message": message_text}
    _make_request("POST", endpoint, json=payload)
    logger.info(f"Сообщение для {negotiation_id} успешно отправлено.")
    return True

# Функция get_auth_token больше не нужна, но оставим ее для совместимости
def get_auth_token(client_id, secret):
    return "real-api-token"