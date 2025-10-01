import os
import sys
import webbrowser
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

# --- Настройки ---
# Этот адрес должен ТОЧНО совпадать с тем, что указан в настройках приложения на hh.ru
REDIRECT_URI = "http://localhost:8010/"
PORT = 8010

# Глобальные переменные для обмена данными между сервером и основной логикой
authorization_code = None
error_message = None

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """
    Мини-веб-сервер для перехвата редиректа от hh.ru после авторизации.
    """
    def do_GET(self):
        global authorization_code, error_message
        
        query_components = parse_qs(urlparse(self.path).query)
        
        if 'code' in query_components:
            authorization_code = query_components["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><head><title>Success</title></head>")
            self.wfile.write(b"<body><h1>Успешно!</h1><p>&_#10004; Код авторизации получен. Можете закрыть это окно и вернуться в консоль.</p></body></html>")
            print("\n[✓] Успешно получен временный код авторизации.")
        elif 'error' in query_components:
            error_code = query_components['error'][0]
            error_message = f"Авторизация не удалась. HH.ru вернул ошибку: {error_code}"
            self.send_response(400)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><head><title>Error</title></head>")
            self.wfile.write(f"<body><h1>Ошибка!</h1><p>{error_message.encode('utf-8')}</p><p>Пожалуйста, закройте это окно и проверьте консоль.</p></body></html>".encode('utf-8'))
            print(f"\n[!] ОШИБКА: {error_message}")
        else:
            error_message = "Не удалось получить код авторизации в ответе от hh.ru."
            self.send_response(400)
            self.end_headers()
            self.wfile.write(f"<body><h1>Ошибка!</h1><p>{error_message.encode('utf-8')}</p></body></html>".encode('utf-8'))
            print(f"\n[!] ОШИБКА: {error_message}")

def get_tokens_from_hh(code, client_id, client_secret):
    """
    Обменивает временный код авторизации на постоянные токены.
    """
    print("[→] Обмениваю временный код на постоянный токен...")
    url = "https://api.hh.ru/token" # Используем актуальный URL
    data = {
        'grant_type': 'authorization_code',
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': REDIRECT_URI,
        'code': code
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    
    try:
        response = requests.post(url, data=data, headers=headers)
        if response.status_code == 200:
            print("[✓] Токены успешно получены от hh.ru!")
            return response.json()
        else:
            print(f"\n[!] КРИТИЧЕСКАЯ ОШИБКА: Не удалось получить токены от hh.ru.")
            print(f"    Статус ответа: {response.status_code}")
            print(f"    Текст ошибки: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"\n[!] КРИТИЧЕСКАЯ ОШИБКА: Ошибка сети при попытке получить токены.")
        print(f"    Подробности: {e}")
        return None

def main():
    """Главная функция-оркестратор."""
    print("="*80)
    print("      Утилита для получения Refresh Token из аккаунта hh.ru")
    print("="*80)

    # Загружаем переменные из .env файла
    load_dotenv()
    CLIENT_ID = os.getenv('HH_CLIENT_ID')
    CLIENT_SECRET = os.getenv('HH_CLIENT_SECRET')

    if not CLIENT_ID or not CLIENT_SECRET:
        print("[!] ОШИБКА: Не найдены HH_CLIENT_ID и HH_CLIENT_SECRET.")
        print("    Убедитесь, что рядом с программой лежит файл '.env' с таким содержанием:")
        print("    HH_CLIENT_ID=ваш_id")
        print("    HH_CLIENT_SECRET=ваш_секретный_ключ")
        input("\nНажмите Enter для выхода...")
        sys.exit(1)

    auth_url = f"https://hh.ru/oauth/authorize?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
    
    print("\n--- Шаг 1: Авторизация в браузере ---")
    print("\nСейчас в вашем браузере откроется страница hh.ru.")
    print("Пожалуйста, войдите в свой рабочий аккаунт и нажмите кнопку 'Разрешить'.")
    input("\nНажмите Enter, когда будете готовы...")
    
    webbrowser.open(auth_url)
    
    print(f"\n--- Шаг 2: Ожидание ответа от hh.ru ---")
    print(f"\n[i] Запущен временный сервер на http://localhost:{PORT}/ ...")
    
    httpd = HTTPServer(('localhost', PORT), OAuthCallbackHandler)
    httpd.handle_request() # Обработать один запрос и остановиться
    httpd.server_close()
    
    if error_message:
        input("\nНажмите Enter для выхода...")
        sys.exit(1)
        
    if authorization_code:
        tokens = get_tokens_from_hh(authorization_code, CLIENT_ID, CLIENT_SECRET)
        if tokens:
            refresh_token = tokens.get('refresh_token')
            print("\n" + "="*80)
            print("                ✅✅✅  ЗАДАЧА ВЫПОЛНЕНА  ✅✅✅")
            print("="*80)
            print("\nПожалуйста, скопируйте ТОЛЬКО строку с REFRESH TOKEN ниже")
            print("и отправьте ее вашему техническому специалисту.\n")
            print("-" * 50)
            print(f"  REFRESH TOKEN: {refresh_token}")
            print("-" * 50)
            print("\nЭто все, что нужно. Спасибо!")
        else:
            print("\nНе удалось завершить процесс. Попробуйте еще раз.")
            
    input("\nНажмите Enter, чтобы закрыть программу...")

if __name__ == "__main__":
    main()