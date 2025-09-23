# hr_bot/services/hh_api_mock.py
import time

# --- Сценарий 3: Кандидат пишет сообщения с перерывами ---
# Это "лента" с сообщениями. Каждый элемент списка - это то, 
# что бот получит за один цикл проверки.
_MOCKED_MESSAGES_SCRIPT = [
    # Цикл 1: Кандидат пишет первое сообщение
    {"12348": ["Здравствуйте!"]},
    
    # Цикл 2: Кандидат пишет второе сообщение (прошло 15 сек)
    {"12348": ["Это снова я. Хотел уточнить по поводу графика."]},
    
    # Цикл 3: Кандидат молчит (прошло еще 15 сек, итого 15 с момента последнего сообщения)
    # Бот должен продолжать ждать, т.к. 15 < 20 (DEBOUNCE_DELAY)
    {}, 

    # Цикл 4: Кандидат снова молчит (прошло еще 15 сек, итого 30 с момента последнего сообщения)
    # Теперь бот должен сработать, объединить первые два сообщения и ответить.
    {},
]

def get_auth_token(client_id, client_secret):
    return "fake-bearer-token-12345"

def get_new_responses(token):
    """Имитируем ОДИН новый отклик, чтобы не было путаницы."""
    return [
        {
            "id": "12348", 
            "vacancy": {"id": "v4", "name": "Бариста"}, 
            "resume": {"id": "r4", "first_name": "Мария"}
        }
    ]

def send_message(token, negotiation_id, message_text):
    print("="*50)
    print(f"MOCK_API: Бот 'Анна' пишет кандидату ({negotiation_id}):")
    print(f"  -> '{message_text}'")
    print("="*50)
    time.sleep(0.5)
    return True

def get_new_messages(token):
    """
    "Проигрывает" следующий шаг из нашего сценария.
    """
    print("\nMOCK_API: Проверка входящих сообщений от кандидатов...")
    time.sleep(1)
    
    if _MOCKED_MESSAGES_SCRIPT:
        # Берем следующий "кадр" из сценария и удаляем его
        next_messages = _MOCKED_MESSAGES_SCRIPT.pop(0)
        return next_messages
    else:
        # Сценарий закончился
        return {}