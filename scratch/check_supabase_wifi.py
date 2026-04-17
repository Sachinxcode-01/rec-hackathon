import os
import psycopg2
from dotenv import load_dotenv

def check_supabase_wifi():
    load_dotenv()
    db_url = None
    with open('.env', 'r') as f:
        for line in f:
            if 'DATABASE_URL=postgresql' in line:
                db_url = line.strip().lstrip('#').strip().split('=', 1)[1]
                break
    
    if not db_url:
        print("ERROR Could not find DATABASE_URL in .env")
        return

    if 'sslmode' not in db_url:
        sep = '&' if '?' in db_url else '?'
        db_url += f"{sep}sslmode=require"
            
    try:
        conn = psycopg2.connect(db_url)
        with conn.cursor() as cur:
            cur.execute("SELECT key, value FROM system_settings WHERE key IN ('wifi_ssid', 'wifi_password')")
            settings = cur.fetchall()
            print("Current WiFi settings in Supabase:")
            for s in settings:
                print(f" - {s[0]}: {s[1]}")
        conn.close()
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    check_supabase_wifi()
