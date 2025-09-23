from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ID вашего гугл-документа. Его можно взять из URL:
# https://docs.google.com/document/d/THIS_IS_THE_ID/edit
DOCUMENT_ID = '1Z1qpG6bUP5JEDPONaf3VcivwLKgDPghL41vZJf1BHzs'
SCOPES = ['https://www.googleapis.com/auth/documents.readonly']
SERVICE_ACCOUNT_FILE = 'credentials.json'

_cached_prompt = None

def get_system_prompt():
    """
    Читает весь текст из Google Doc и возвращает его как одну строку.
    Кэширует результат, чтобы не читать файл при каждом запуске.
    """
    global _cached_prompt
    if _cached_prompt:
        return _cached_prompt

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
        
        print("База знаний из Google Docs успешно загружена.")
        _cached_prompt = text
        return text

    except Exception as e:
        print(f"!!! ОШИБКА при чтении Google Doc: {e}")
        # В случае ошибки возвращаем "запасной" промпт
        return "Ты — полезный ассистент."

if __name__ == '__main__':
    # Тестируем, что модуль работает
    prompt = get_system_prompt()
    print("\n--- Загруженный промпт (первые 300 символов) ---")
    print(prompt[:300] + "...")