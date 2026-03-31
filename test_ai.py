import requests

url = "http://127.0.0.1:5000/api/ai/chat"
payload = {"message": "Hello, is the RECKON 1.O AI Assistant online?"}
try:
    response = requests.post(url, json=payload, timeout=10)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
except Exception as e:
    print(f"Error: {e}")
