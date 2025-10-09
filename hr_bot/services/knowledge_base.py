import time
import logging  # <--- ДОБАВЛЕНО
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# --- ДОБАВЛЕНО: Получаем логгер для этого модуля ---
logger = logging.getLogger(__name__)

# ID вашего гугл-документа
DOCUMENT_ID = '1injke_YH-E2RRHL4PYvXk7kOWPk58-S0cPzLDnzeRnA'
SCOPES = ['https://www.googleapis.com/auth/documents.readonly']
SERVICE_ACCOUNT_FILE = 'credentials.json'

# Время жизни кэша в секундах (5 минут)
CACHE_TTL_SECONDS = 120 

_cached_prompt = None
_cache_timestamp = 0

def get_system_prompt():
    """
    Читает весь текст из Google Doc и возвращает его как одну строку.
    Кэширует результат на CACHE_TTL_SECONDS секунд.
    """
    global _cached_prompt, _cache_timestamp

    is_cache_valid = _cached_prompt and (time.time() - _cache_timestamp < CACHE_TTL_SECONDS)

    if is_cache_valid:
        return _cached_prompt

    logger.debug("Кэш базы знаний устарел, обновляю из Google Docs...")
    try:
        creds = Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        
        service = build('docs', 'v1', credentials=creds)

        document = service.documents().get(documentId=DOCUMENT_ID).execute()
        content = document.get('body').get('content')
        
        text = ''
        for value in content:
            if 'paragraph' in value:
                elements = value.get('paragraph').get('elements')
                for elem in elements:
                    text += elem.get('textRun', {}).get('content', '')
        
        logger.debug("База знаний из Google Docs успешно загружена.")
        
        _cached_prompt = text
        _cache_timestamp = time.time()
        
        return text

    except Exception as e:
        # Ошибки всегда должны иметь высокий уровень, чтобы их было видно
        logger.error(f"ОШИБКА при чтении Google Doc: {e}", exc_info=True)
        
        if _cached_prompt:
            # Предупреждение о том, что мы используем старые данные - это важно
            logger.warning("Возвращаю старую версию промпта из кэша.")
            return _cached_prompt
        
        return "Ты - Hr компании ВкусВилл. Проводишь первичный отбор кандидатов на hh"

if __name__ == '__main__':
    # Для блоков ручного тестирования print - это нормально
    prompt = get_system_prompt()
    print("\n--- Загруженный промпт (первые 300 символов) ---")
    print(prompt[:300] + "...")