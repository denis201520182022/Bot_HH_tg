# hr_bot/services/llm_handler.py

import os
import json
import logging
import openai
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Асинхронный клиент OpenAI, настроенный на работу через прокси
client = openai.AsyncOpenAI(
    base_url=os.getenv("OPENAI_PROXY_URL"),
)

# --- ОБНОВЛЕННЫЙ БЛОК ИНСТРУКЦИЙ ДЛЯ OPENAI ---
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
[RULE] Если кандидат задает вопрос, прерывая твой сценарий квалификации, ответь на его вопрос, а затем немедленно вернись к тому вопросу, который ты задавала до этого, и сохрани исходное состояние ('new_state').
[RULE] Если в сообщении кандидата ты видишь текст '[ФИО ЗАМАСКИРОВАНО]', это означает, что кандидат предоставил свои полные фамилию, имя и отчество. Не переспрашивай их, а поблагодари и переходи к следующему шагу — запросу номера телефона. Установи 'new_state' в 'awaiting_phone'.
[RULE] Если в сообщении кандидата ты видишь текст '[ТЕЛЕФОН ЗАМАСКИРОВАН]', это означает, что кандидат предоставил свой номер телефона. Не переспрашивай его, а поблагодари и переходи к следующему шагу — запросу города. Установи 'new_state' в 'awaiting_city'.

[IMPORTANT] Используй ТОЛЬКО следующие значения для поля 'new_state':
- 'awaiting_questions': Если ты предложила задать вопросы.
- 'awaiting_age': Если ты только что спросила возраст.
- 'awaiting_citizenship': Если ты только что спросила гражданство.
- 'awaiting_readiness': Если ты только что спросила о готовности приступить к работе.
- 'awaiting_fio': Если ты только что спросила ФИО.
- 'awaiting_phone': Если ты только что спросила номер телефона.
- 'awaiting_city': Если ты только что спросила город для собеседования.
- 'qualification_failed': Если кандидат не прошел квалификацию и ты ему отказываешь.
- 'scheduling_spb_day': Если ты начала процесс записи в Санкт-Петербурге (спросила день).
- 'scheduling_spb_time': Если ты ждешь ответа про время в Санкт-Петербурге.
- 'interview_scheduled_spb': Если ты успешно записала кандидата в Санкт-Петербурге.
- 'forwarded_to_researcher': Если ты сообщила кандидату о передаче заявки ресёчерам.
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