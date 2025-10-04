import os
import requests
from dotenv import load_dotenv

# --- НАСТРОЙКА ---
# 
# Вариант 1 (ПРЕДПОЧТИТЕЛЬНЫЙ): Если у вас есть действующий access_token, вставьте его сюда.
# Скрипт пропустит шаг обновления и будет использовать его.
YOUR_ACCESS_TOKEN = "USERTKRTGKDCQRCVPQ8J8GAU0CKCB3J0AOO9S4MB92BNCHAF97QG4KL78CPAO7JC"

# Вариант 2: Если access_token точно истек, оставьте его пустым, но заполните refresh_token.
# Скрипт попытается его обновить.
YOUR_REFRESH_TOKEN = "USERJHJ67NB52SDKG0IN98TFI0MVR6PN1UR3G3025VGI3UL472V96U6M92NBBI2Q"
# -----------------


def get_new_access_token(refresh_token, client_id, client_secret):
    """Обменивает refresh_token на новый access_token."""
    print("[1] Попытка получить новый access_token...")
    # ... (код этой функции не меняется) ...
    url = "https://api.hh.ru/token"
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
        'client_id': client_id,
        'client_secret': client_secret,
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    
    response = requests.post(url, data=data, headers=headers)
    if response.status_code == 200:
        access_token = response.json().get('access_token')
        print("    ✅ Успешно! Новый access_token получен.")
        return access_token
    else:
        print(f"    ❌ ОШИБКА: Не удалось обновить токен. Статус: {response.status_code}")
        print(f"       Текст ошибки: {response.text}")
        return None

def get_employer_id(access_token):
    """Получает ID работодателя через эндпоинт /me."""
    print("\n[2] Попытка получить ID работодателя (employer_id)...")
    url = "https://api.hh.ru/me"
    headers = {
        'Authorization': f'Bearer {access_token}',
        # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
        'HH-User-Agent': 'ZaBota-Bot/1.0 (hbfys@mail.com)' 
    }
    
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        employer = data.get('employer')
        if employer and employer.get('id'):
            employer_id = employer['id']
            print(f"    ✅ Успешно! ID работодателя: {employer_id}")
            return employer_id
        else:
            print("    ❌ ОШИБКА: Ответ получен, но в нем нет информации о работодателе ('employer').")
            print("       Возможно, этот токен принадлежит соискателю, а не менеджеру.")
            return None
    else:
        print(f"    ❌ ОШИБКА: Не удалось получить данные о пользователе. Статус: {response.status_code}")
        print(f"       Текст ошибки: {response.text}")
        return None

def get_all_active_vacancies(access_token, employer_id):
    """Получает ВСЕ активные вакансии, обрабатывая пагинацию."""
    print(f"\n[3] Попытка получить все активные вакансии для работодателя {employer_id}...")
    
    all_vacancies = []
    page = 0
    
    while True:
        print(f"    - Запрашиваю страницу {page}...")
        url = f"https://api.hh.ru/employers/{employer_id}/vacancies/active"
        params = {'page': page, 'per_page': 50}
        headers = {
            'Authorization': f'Bearer {access_token}',
            # --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
            'HH-User-Agent': 'ZaBota-Bot/1.0 (hbfys@mail.com)'
        }
        
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code != 200:
            print(f"    ❌ ОШИБКА: Не удалось получить список вакансий. Статус: {response.status_code}")
            print(f"       Текст ошибки: {response.text}")
            return None
            
        data = response.json()
        vacancies_on_page = data.get('items', [])
        all_vacancies.extend(vacancies_on_page)
        
        print(f"      > Найдено {len(vacancies_on_page)} вакансий на этой странице.")

        if page >= data.get('pages', 1) - 1:
            break
        page += 1
        
    print(f"    ✅ Успешно! Всего найдено активных вакансий: {len(all_vacancies)}")
    return all_vacancies

def main():
    print("="*80)
    print("      Тестирование новых методов API hh.ru (Версия 2)")
    print("="*80)

    load_dotenv()
    client_id = os.getenv('HH_CLIENT_ID')
    client_secret = os.getenv('HH_CLIENT_SECRET')
    
    access_token = YOUR_ACCESS_TOKEN if YOUR_ACCESS_TOKEN != "СЮДА_ВСТАВЬТЕ_ВАШ_ДЕЙСТВУЮЩИЙ_ACCESS_TOKEN" else None

    if not access_token:
        print("\n[i] Действующий access_token не предоставлен. Попытка обновить через refresh_token...")
        # --- Шаг 1: Получаем access_token ---
        access_token = get_new_access_token(YOUR_REFRESH_TOKEN, client_id, client_secret)
        if not access_token:
            return
    else:
        print("\n[1] Используется предоставленный access_token.")

    # --- Шаг 2: Получаем employer_id ---
    employer_id = get_employer_id(access_token)
    if not employer_id:
        return
        
    # --- Шаг 3: Получаем список вакансий ---
    vacancies = get_all_active_vacancies(access_token, employer_id)
    if vacancies is not None:
        print("\n" + "="*80)
        print("                        РЕЗУЛЬТАТ")
        print("="*80)
        if vacancies:
            print("Список полученных вакансий:")
            for i, vacancy in enumerate(vacancies):
                print(f"  {i+1}. \"{vacancy.get('name')}\" (ID: {vacancy.get('id')}, Город: {vacancy.get('area', {}).get('name')})")
        else:
            print("Активных вакансий не найдено.")
    
    print("\nТестирование завершено.")

if __name__ == '__main__':
    main()