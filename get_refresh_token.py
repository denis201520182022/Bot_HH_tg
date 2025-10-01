# get_refresh_token.py
import requests
import os
from dotenv import load_dotenv
from http.server import HTTPServer, BaseHTTPRequestHandler
import webbrowser

load_dotenv()

CLIENT_ID = os.getenv('HH_CLIENT_ID')
CLIENT_SECRET = os.getenv('HH_CLIENT_SECRET')
REDIRECT_URI = "http://localhost:8010/"

authorization_code = None

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global authorization_code
        if 'code=' in self.path:
            authorization_code = self.path.split('code=')[1].split('&')[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Got the code! You can close this window now.")
            print(f"\n[SUCCESS] Authorization Code received: {authorization_code}")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Failed to get authorization code.")

def get_tokens(code):
    url = "https://hh.ru/oauth/token"
    data = {
        'grant_type': 'authorization_code',
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri': REDIRECT_URI,
        'code': code
    }
    response = requests.post(url, data=data)
    if response.status_code == 200:
        print("[SUCCESS] Tokens received!")
        return response.json()
    else:
        print(f"[ERROR] Failed to get tokens: {response.text}")
        return None

if __name__ == "__main__":
    auth_url = f"https://hh.ru/oauth/authorize?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
    
    print("="*80)
    print("Step 1: Open the following URL in your browser, log in, and grant access:")
    print(auth_url)
    print("="*80)
    
    webbrowser.open(auth_url)
    
    print("Step 2: Waiting for the authorization code on http://localhost:8010/ ...")
    
    httpd = HTTPServer(('localhost', 8010), OAuthCallbackHandler)
    httpd.handle_request() # This will handle one request and then stop.
    
    if authorization_code:
        tokens = get_tokens(authorization_code)
        if tokens:
            print("\n" + "="*80)
            print("!!! ПОЛУЧЕНЫ НОВЫЕ ТОКЕНЫ. Сохраните их в БД !!!")
            print("-" * 80)
            print(f"ACCESS TOKEN:  {tokens['access_token']}")
            print(f"REFRESH TOKEN: {tokens['refresh_token']}")
            print(f"EXPIRES IN (сек): {tokens['expires_in']}")
            print("-" * 80)
            print("Выполните SQL-запрос в pgAdmin, подставив эти значения:")
            print(f"""
UPDATE tracked_recruiters
SET 
    access_token = '{tokens['access_token']}',
    refresh_token = '{tokens['refresh_token']}',
    token_expires_at = NOW() + INTERVAL '{tokens['expires_in']} seconds'
WHERE 
    recruiter_id = 'ВАШ_RECRUITER_ID';
            """)
            print("="*80)