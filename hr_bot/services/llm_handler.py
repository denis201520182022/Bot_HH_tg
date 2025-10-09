# hr_bot/services/llm_handler.py

import os
import json
import logging
from openai import AsyncOpenAI
from dotenv import load_dotenv
import httpx

load_dotenv()
logger = logging.getLogger(__name__)

# Загружаем настройки прокси из .env
SQUID_PROXY_HOST = os.getenv("SQUID_PROXY_HOST", "38.180.203.212")
SQUID_PROXY_PORT = os.getenv("SQUID_PROXY_PORT", "8787")
SQUID_PROXY_USER = os.getenv("SQUID_PROXY_USER", "zabota")
SQUID_PROXY_PASSWORD = os.getenv("SQUID_PROXY_PASSWORD", "zabota2000")

# Формируем URL прокси с аутентификацией
proxy_url = (
    f"http://{SQUID_PROXY_USER}:{SQUID_PROXY_PASSWORD}@"
    f"{SQUID_PROXY_HOST}:{SQUID_PROXY_PORT}"
)

# Создаем асинхронный HTTP клиент с настройками прокси
async_http_client = httpx.AsyncClient(
    proxy=proxy_url,
    timeout=30.0
)

# Создаем АСИНХРОННЫЙ OpenAI клиент и передаем ему наш HTTP клиент
client = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    http_client=async_http_client
)

logger.info(f"Клиент OpenAI настроен на работу через прокси: {SQUID_PROXY_HOST}:{SQUID_PROXY_PORT}")


# --- БЛОК ИНСТРУКЦИЙ ДЛЯ OPENAI ---
JSON_FORMAT_INSTRUCTION = """
\n\n[CRITICAL RULE] Твой ответ ВСЕГДА должен быть в формате JSON.
Структура JSON должна быть следующей:
{
  "response_text": "Твой текстовый ответ кандидату как рекрутер Анна.",
  "new_state": "новое_состояние_диалога",
  "extracted_data": { 
    "age": <число или null>, 
    "citizenship": "<строка или null>", 
    "full_name": "<строка или null>", 
    "city": "<строка или null>",
    "readiness_to_start": "<строка или null>" 
  }
}

[RULE] В 'extracted_data' помещай ТОЛЬКО те данные, которые кандидат явно сообщил в своем ПОСЛЕДНЕМ сообщении. Не добавляй туда ФИО или номер телефона.
[CRITICAL CONVERSATION RULE] Если вопрос кандидата содержит в себе ответ (например, на твой вопрос "Когда готовы приступить?" кандидат отвечает "А можно со следующей недели?"), твой ПЕРВЫЙ приоритет — вежливо ответить на его вопрос ("Да, конечно.", "Да, такой вариант возможен или "К сожалению нет" - для ответа ориентируйся на описание вакансии и FAQ), потом ОБЯЗАТЕЛЬНО убедись, что это итоговый вариант ответа от кандидата и ТОЛЬКО ПОТОМ переходить к следующему шагу сценария. При этом ты ДОЛЖЕН извлечь данные из его вопроса.
[RULE] Если кандидат задает вопрос, прерывая твой сценарий квалификации, ответь на его вопрос, а затем немедленно вернись к тому вопросу, который ты задавала до этого, и сохрани исходное состояние ('new_state').
[RULE] Если ты спросила гражданство и кандидат не ответил явно, что у него гражданство России (РФ) или гражданство стран ЕАЭС (Беларусь, Казахстан, Армения, Киргизия) или у него гражданство неподходящей страны, то используй состояние 'clarifying citizenship' и уточни, есть ли у кандидата ВНЖ (вид на жительство) России или РВП (разрешение на временное проживание) России. Принимай решение о квалификации и о переходе на следующий шаг сценария только после уточнения этой информации.
[RULE] Если в сообщении кандидата ты видишь текст '[ФИО ЗАМАСКИРОВАНО]', это означает, что кандидат предоставил свои полные фамилию, имя и отчество. Не переспрашивай их, а поблагодари и переходи к следующему шагу — запросу номера телефона. Установи 'new_state' в 'awaiting_phone'.
[RULE] Если в сообщении кандидата ты видишь текст '[ТЕЛЕФОН ЗАМАСКИРОВАН]', это означает, что кандидат предоставил свой номер телефона. Не переспрашивай его, а поблагодари и переходи к следующему шагу — запросу города. Установи 'new_state' в 'awaiting_city'.

[IMPORTANT] Используй ТОЛЬКО следующие значения для поля 'new_state':
- 'awaiting_questions': Если ты предложила задать вопросы.
- 'awaiting_age': Если ты только что спросила возраст.
- 'awaiting_citizenship': Если ты только что спросила гражданство.
- 'clarifying citizenship': Если кандидат сказал, что у него гражданство не России (РФ) и не стран ЕАЭС (Беларусь, Казахстан, Армения, Киргизия) и ты ждешь уточнение есть ли у него ВНЖ или РВП России (РФ)
- 'awaiting_readiness': Если ты только что спросила о готовности приступить к работе.
- 'awaiting_fio': Если ты только что спросила ФИО.
- 'awaiting_phone': Если ты только что спросила номер телефона.
- 'awaiting_city': Если ты только что спросила город для собеседования.
- 'qualification_failed': Если кандидат не прошел квалификацию и ты ему отказываешь.
- 'scheduling_spb_day': Если ты начала процесс записи в Санкт-Петербурге (спросила день).
- 'scheduling_spb_time': Если ты ждешь ответа про время в Санкт-Петербурге.
- 'interview_scheduled_spb': Если ты успешно записала кандидата в Санкт-Петербурге.
- 'forwarded_to_researcher': Если ты сообщила кандидату о передаче заявки ресёчерам.
- 'post_qualification_chat': Если кандидат уже прошел квалификацию и записан на собеседование. При этом состояниии ты просто отвечаешь на его вопросы, не добавляешь ничего в "extracted_data".
- 'dialogue_ongoing': Во всех остальных случаях, когда диалог продолжается без смены ключевого этапа.
"""


async def get_bot_response(system_prompt: str, dialogue_history: list, user_message: str) -> dict:
    """
    Асинхронно отправляет запрос в OpenAI через прокси и получает ответ.
    """
    full_system_prompt = system_prompt + JSON_FORMAT_INSTRUCTION
    messages = [
        {"role": "system", "content": full_system_prompt},
    ]
    messages.extend(dialogue_history)
    messages.append({"role": "user", "content": user_message})

    try:
        logger.info(f"Отправка запроса к LLM через прокси...")
        
        response = await client.chat.completions.create(
            model="gpt-4-turbo",
            messages=messages,
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        
        response_content = response.choices[0].message.content
        logger.info("Успешный ответ от LLM получен.")
        
        parsed_response = json.loads(response_content)
        return parsed_response

    except Exception as e:
        logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА при запросе к OpenAI через прокси: {e}", exc_info=True)
        return {
            "response_text": "К сожалению, у меня возникла техническая проблема с AI-моделью. Попробуйте написать позже.",
            "new_state": "error_state",
            "extracted_data": None
        }


async def cleanup():
    """
    Закрывает HTTP клиент при завершении работы приложения.
    Вызовите эту функцию в shutdown hook вашего приложения.
    """
    await async_http_client.aclose()
    logger.info("🔒 HTTP клиент закрыт")