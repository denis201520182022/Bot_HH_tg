import os
import requests
from dotenv import load_dotenv

# --- НАСТРОЙКА ---
# 1. Скопируйте сюда ваш refresh_token из базы данных
OLD_REFRESH_TOKEN = "USERSD37914SOS8RJ51N68NTI4U830VT81EPLFM0TCIC4C66H41TC6MB1P9G42RL"
# -----------------


def refresh_token():
    """Пытается обменять старый refresh_token на новую пару токенов."""
    
    print("="*80)
    print("         Ручная проверка и обновление Refresh Token для hh.ru")
    print("="*80)

    # Загружаем переменные из .env файла (HH_CLIENT_ID и HH_CLIENT_SECRET)
    load_dotenv()
    client_id = os.getenv('HH_CLIENT_ID')
    client_secret = os.getenv('HH_CLIENT_SECRET')

    if not client_id or not client_secret:
        print("\n❌ ОШИБКА: Не могу найти HH_CLIENT_ID и HH_CLIENT_SECRET в файле .env")
        print("   Убедитесь, что файл .env находится в той же папке и содержит эти переменные.")
        return

    if OLD_REFRESH_TOKEN == "СЮДА_ВСТАВЬТЕ_ВАШ_СТАРЫЙ_REFRESH_TOKEN":
        print("\n❌ ОШИБКА: Вы не вставили ваш refresh_token в код.")
        print("   Откройте этот скрипт и замените placeholder на ваш токен из базы данных.")
        return

    print(f"\n[i] Пытаюсь обновить токен для Client ID: {client_id[:4]}... (скрыто)")
    
    url = "https://api.hh.ru/token"
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': OLD_REFRESH_TOKEN,
        'client_id': client_id,
        'client_secret': client_secret,
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    try:
        response = requests.post(url, data=data, headers=headers)

        if response.status_code == 200:
            tokens = response.json()
            print("\n" + "="*80)
            print("                ✅✅✅  УСПЕХ! Токен валиден!  ✅✅✅")
            print("="*80)
            print("\nПолучены новые токены. Используйте их для обновления базы данных:")
            print("-" * 60)
            print(f"  NEW ACCESS TOKEN:  {tokens['access_token']}")
            print(f"  NEW REFRESH TOKEN: {tokens['refresh_token']}")
            print(f"  EXPIRES IN (сек):  {tokens['expires_in']}")
            print("-" * 60)
        else:
            print("\n" + "="*80)
            print("            ❌❌❌  ОШИБКА! Токен НЕ валиден!  ❌❌❌")
            print("="*80)
            print("\nСервер hh.ru ответил с ошибкой. Это означает, что ваш refresh_token 'протух'.")
            print("Вам нужно сгенерировать новую пару токенов с помощью утилиты get_token_util.py")
            print("-" * 60)
            print(f"  Код ответа: {response.status_code}")
            print(f"  Текст ошибки от сервера: {response.text}")
            print("-" * 60)

    except requests.exceptions.RequestException as e:
        print("\n❌ ОШИБКА СЕТИ. Не удалось подключиться к api.hh.ru")
        print(f"   Подробности: {e}")


if __name__ == '__main__':
    refresh_token()