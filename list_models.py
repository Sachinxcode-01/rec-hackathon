import requests
import os
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("No GEMINI_API_KEY found in .env")
else:
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    resp = requests.get(url)
    if resp.status_code == 200:
        models = resp.json().get('models', [])
        for m in models:
            print(m.get('name'))
    else:
        print(f"Error listing models: {resp.status_code}")
        print(resp.text)
