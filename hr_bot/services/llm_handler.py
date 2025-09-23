# hr_bot/services/llm_handler.py

import os
import json
import logging
import openai
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# --- ИЗМЕНЕНИЕ 1: Создаем асинхронный клиент OpenAI ---
# Он будет использовать переменные окружения, которые мы задали:
# - OPENAI_API_KEY: Библиотека все еще может его читать для заголовков.
# - OPENAI_PROXY_URL: Это наш новый адрес для всех запросов.
client = openai.AsyncOpenAI(
    base_url=os.getenv("OPENAI_PROXY_URL"),
)

# Этот блок с инструкциями для модели остается без изменений.
JSON_FORMAT_INSTRUCTION = """
\n\n[CRITICAL RULE] Твой ответ ВСЕГДА должен быть в формате JSON.
Структура JSON:
{
  "response_text": "...",
  "new_state": "...",
  "extracted_data": { "age": <...>, "citizenship": "<...>", "full_name": "<...>", "city": "<...>" }
}

[RULE] В 'extracted_data' помещай ТОЛЬКО те данные, которые кандидат сообщил в своем ПОСЛЕДНЕМ сообщении.

[LOGIC FOR SPB]
- Если текущее состояние 'scheduling_spb_day' и кандидат назвал день, то твой 'response_text' должен предложить время (11:00, 12:00, 15:00), а 'new_state' должен стать 'scheduling_spb_time'.
- Если текущее состояние 'scheduling_spb_time' и кандидат выбрал время, то твой 'response_text' должен быть финальным подтверждением записи с адресом и напоминанием про удостоверение. А 'new_state' должен стать 'interview_scheduled_spb'.

[LOGIC FOR REGIONS]
- Если ты только что получила город ('city') и он НЕ Санкт-Петербург, то твой 'response_text' должен сообщить о передаче заявки. А 'new_state' должен стать 'forwarded_to_researcher'.
"""


# --- ИЗМЕНЕНИЕ 2: Функция теперь асинхронная ---
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
        logger.info(f"Отправка запроса к LLM через прокси для диалога...")
        
        # --- ИЗМЕНЕНИЕ 3: Вызов API через новый асинхронный клиент ---
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