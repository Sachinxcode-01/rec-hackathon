import os
import psycopg2
from dotenv import load_dotenv

def update_supabase_wifi():
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
        conn.autocommit = True
        with conn.cursor() as cur:
            # Update WiFi settings
            cur.execute("""
                UPDATE system_settings 
                SET value = 'RECHKT-AP-26 / 27 / 28' 
                WHERE key = 'wifi_ssid'
            """)
            cur.execute("""
                UPDATE system_settings 
                SET value = 'Rechkt!2026 / 2027 / 2028' 
                WHERE key = 'wifi_password'
            """)
            
            # Also clear admin action logs in Supabase if any exist with old credentials
            cur.execute("DELETE FROM admin_logs WHERE details LIKE '%RECKON-GUEST%'")
            
            print("SUCCESS: Updated WiFi credentials in Supabase PostgreSQL.")
            
        conn.close()
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    update_supabase_wifi()
