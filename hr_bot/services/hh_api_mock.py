# hr_bot/services/hh_api_mock.py
import time

# --- Глобальное состояние для имитации "прочитанных" откликов ---
_initial_responses_sent = False

def get_new_responses(recruiter=None, vacancy_ids=None, db=None):
    """
    Имитирует реальное API: возвращает новые отклики ТОЛЬКО ПРИ ПЕРВОМ ВЫЗОВЕ.
    На все последующие вызовы возвращает пустой список.
    """
    global _initial_responses_sent
    
    print("MOCK_API: Запрос новых откликов...")
    
    if not _initial_responses_sent:
        print("MOCK_API: Найдены новые отклики, отправляю...")
        _initial_responses_sent = True # <-- Ставим флаг, что мы их "отдали"
        return [
            {
                "id": "resp_001",
                "vacancy": {"id": "112233", "name": "Продавец-консультант"},
                "resume": {"id": "res_A", "first_name": "Тестовый"},
                "messages": [{"text": "Добрый день! Хотел бы узнать подробнее."}]
            },
            {
                "id": "resp_002",
                "vacancy": {"id": "445566", "name": "Бариста"},
                "resume": {"id": "res_B", "first_name": "Тестовая"},
                "messages": [{"text": "Здравствуйте, откликаюсь на вакансию Бариста."}]
            },
            {
                "id": "resp_003", # Этот отклик будет проигнорирован, т.к. его нет в tracked_vacancies
                "vacancy": {"id": "999999", "name": "Уборщица"},
                "resume": {"id": "res_C", "first_name": "Лишний"},
                "messages": [{"text": "test"}]
            }
        ]
    else:
        print("MOCK_API: Новых откликов нет.")
        return []

def get_new_messages(token):
    """
    Для чистоты теста эта функция пока не будет возвращать ничего,
    чтобы мы протестировали только логику новых откликов.
    """
    return {}

def send_message(recruiter, db, negotiation_id, message_text):
    print("="*50)
    print(f"MOCK_API: Рекрутер '{recruiter.name}' пишет кандидату ({negotiation_id}):")
    print(f"  -> '{message_text}'")
    print("="*50)
    return True