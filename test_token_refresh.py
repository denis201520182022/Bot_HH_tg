import os
import requests
from dotenv import load_dotenv

# --- НАСТРОЙКА ---
# Убедитесь, что в вашем файле .env есть HH_CLIENT_ID и HH_CLIENT_SECRET

# Вставьте сюда ваш СВЕЖИЙ, ТОЧНО РАБОТАЮЩИЙ refresh_token
# Это должен быть тот токен, который соответствует вашему действующему access_token
YOUR_CURRENT_REFRESH_TOKEN = "USERTTGRQG4BKDRL1K3S7IL02DHRUPAL91JEBA659HTG2HBLCEJ6A7702JH5IGU0"
# -----------------


def attempt_early_refresh():
    """
    Пытается обновить пару токенов, используя действующий refresh_token,
    в то время как соответствующий access_token еще НЕ истек.
    """
    print("="*80)
    print("      Тестирование преждевременного обновления токена")
    print("="*80)

    # Загружаем ID и секрет клиента из .env файла
    load_dotenv()
    client_id = os.getenv('HH_CLIENT_ID')
    client_secret = os.getenv('HH_CLIENT_SECRET')

    if not all([client_id, client_secret, YOUR_CURRENT_REFRESH_TOKEN]):
        print("❌ ОШИБКА: Пожалуйста, заполните HH_CLIENT_ID, HH_CLIENT_SECRET в .env и YOUR_CURRENT_REFRESH_TOKEN в скрипте.")
        return

    print(f"[*] Используем refresh_token: ...{YOUR_CURRENT_REFRESH_TOKEN[-6:]}")
    print("[*] Отправляем запрос на https://api.hh.ru/token...")

    url = "https://api.hh.ru/token"
    
    # Собираем тело запроса в точности по документации
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': YOUR_CURRENT_REFRESH_TOKEN,
        'client_id': client_id,
        'client_secret': client_secret,
    }

    # Отправляем POST-запрос
    response = requests.post(url, data=data)

    print(f"\n[!] Сервер ответил со статусом: {response.status_code}")
    
    # Анализируем ответ
    if response.status_code == 200:
        print("\n✅ УСПЕШНОЕ ОБНОВЛЕНИЕ!")
        print("   Это доказывает, что сервер ПОЗВОЛЯЕТ обновлять токен, даже если старый access_token еще не истек.")
        
        tokens = response.json()
        print("\n   Получена новая пара токенов:")
        print(f"   - Новый access_token:  ...{tokens.get('access_token', '')[-6:]}")
        print(f"   - Новый refresh_token: ...{tokens.get('refresh_token', '')[-6:]}")
        print(f"   - Срок жизни (сек):   {tokens.get('expires_in')}")

    else:
        print("\n❌ ОШИБКА ОБНОВЛЕНИЯ!")
        print("   Это доказывает, что сервер БЛОКИРУЕТ преждевременное обновление.")
        print("   Теперь нужно проверить, 'сгорел' ли ваш refresh_token.")
        
        print("\n   Полный ответ от сервера:")
        # Используем try-except на случай, если ответ не в формате JSON
        try:
            print(response.json())
        except requests.exceptions.JSONDecodeError:
            print(response.text)

    print("\n" + "="*80)
    print("Тест завершен.")


if __name__ == '__main__':
    attempt_early_refresh()