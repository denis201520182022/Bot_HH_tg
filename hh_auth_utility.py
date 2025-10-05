import requests
import webbrowser
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# --- Глобальные переменные ---
authorization_code = None
CONFIG_FILE = 'config.json'

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Класс для обработки редиректа от HH."""
    def do_GET(self):
        global authorization_code
        query_components = parse_qs(urlparse(self.path).query)
        if 'code' in query_components:
            authorization_code = query_components["code"][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b"<html><head><title>HH.ru Auth</title></head>")
            self.wfile.write(b"<body><h1>Code received!</h1><p>You can close this window and return to the utility.</p></body></html>")
            print(f"\n[SUCCESS] Authorization code received.")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Failed to get authorization code.")

def load_config():
    """Загружает конфигурацию из файла."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f: return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError): return None
    return None

def save_config(config):
    """Сохраняет конфигурацию в файл."""
    with open(CONFIG_FILE, 'w') as f: json.dump(config, f, indent=4)
    print(f"\n[INFO] Configuration saved to {CONFIG_FILE}")

def get_config_from_user():
    """Запрашивает данные конфигурации у пользователя."""
    client_id = input("Введите Client ID: ")
    client_secret = input("Введите Client Secret: ")
    redirect_uri = input("Введите Redirect URI (e.g., http://localhost:8010/): ")
    return {'CLIENT_ID': client_id, 'CLIENT_SECRET': client_secret, 'REDIRECT_URI': redirect_uri}

def get_tokens(config, code):
    """Обменивает код авторизации на токены."""
    url = "https://hh.ru/oauth/token"
    data = {'grant_type': 'authorization_code', 'client_id': config['CLIENT_ID'], 'client_secret': config['CLIENT_SECRET'], 'redirect_uri': config['REDIRECT_URI'], 'code': code}
    try:
        response = requests.post(url, data=data)
        response.raise_for_status()
        print("[SUCCESS] Tokens received!")
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Failed to get tokens: {e}")
        if 'response' in locals(): print(f"Server response: {response.text}")
        return None

def get_recruiter_info(access_token):
    """Получает информацию о рекрутере по его токену."""
    url = "https://api.hh.ru/me"
    headers = {'Authorization': f'Bearer {access_token}'}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        print("[SUCCESS] Recruiter info received!")
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Failed to get recruiter info: {e}")
        return None

def run_authorization_cycle(config):
    """Выполняет один полный цикл авторизации."""
    global authorization_code
    authorization_code = None
    try:
        parsed_uri = urlparse(config['REDIRECT_URI'])
        hostname, port = parsed_uri.hostname, parsed_uri.port
        if not (hostname and port): raise ValueError
    except (ValueError, AttributeError):
        print(f"\n[ERROR] Invalid Redirect URI format in config: {config['REDIRECT_URI']}")
        return False

    auth_url = f"https://hh.ru/oauth/authorize?response_type=code&client_id={config['CLIENT_ID']}&redirect_uri={config['REDIRECT_URI']}"
    print("\n" + "="*80 + "\nШаг 1: Сейчас откроется браузер для входа рекрутера...\n" + "="*80)
    webbrowser.open(auth_url)
    print(f"Шаг 2: Ожидание кода авторизации на {config['REDIRECT_URI']} ...")
    httpd = HTTPServer((hostname, port), OAuthCallbackHandler)
    httpd.handle_request()

    if authorization_code:
        tokens = get_tokens(config, authorization_code)
        if tokens:
            recruiter_info = get_recruiter_info(tokens['access_token'])
            print("\n" + "="*80)
            print("!!! ДАННЫЕ РЕКРУТЕРА ПОЛУЧЕНЫ. Используйте их для Telegram-бота. !!!")
            print("-" * 80)
            
            if recruiter_info:
                # --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
                # Безопасно извлекаем ID из вложенного объекта 'manager'
                manager_id = None
                manager_info = recruiter_info.get('manager')
                if manager_info:
                    manager_id = manager_info.get('id')
                # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

                full_name = f"{recruiter_info.get('last_name', '')} {recruiter_info.get('first_name', '')}".strip()
                
                print(f"MANAGER ID:     {manager_id if manager_id else '[Не найден]'}")
                print(f"RECRUITER NAME: {full_name}")
            else:
                print("MANAGER ID:     [Не удалось получить]")
                print("RECRUITER NAME: [Не удалось получить]")
            
            print("-" * 80)
            print(f"ACCESS TOKEN:   {tokens.get('access_token')}")
            print(f"REFRESH TOKEN:  {tokens.get('refresh_token')}")
            print(f"EXPIRES IN:     {tokens.get('expires_in')} секунд")
            print("="*80)
            return True
    else:
        print("\n[ОШИБКА] Код авторизации не был получен. Попробуйте снова.")
    return False

def main():
    """Основная функция для запуска утилиты."""
    print("="*80 + "\nУтилита для авторизации рекрутеров HeadHunter\n" + "="*80)
    config = load_config()
    if config:
        print("Найдена сохраненная конфигурация.")
        use_saved = input("Использовать эту конфигурацию? (Да/нет): ").lower()
        if use_saved not in ['yes', 'y', 'да', 'д', '']:
            config = get_config_from_user()
            save_config(config)
    else:
        print("Конфигурация не найдена. Пожалуйста, введите данные:")
        config = get_config_from_user()
        save_config(config)
        
    while True:
        run_authorization_cycle(config)
        another = input("\nАвторизовать еще одного рекрутера? (Да/нет): ").lower()
        if another not in ['yes', 'y', 'да', 'д', '']:
            break
            
    print("\nРабота утилиты завершена.")

if __name__ == "__main__":
    main()