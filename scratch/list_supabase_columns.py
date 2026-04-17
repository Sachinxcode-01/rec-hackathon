import os
import psycopg2
from dotenv import load_dotenv

def get_columns():
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
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'admin_logs'")
            cols = cur.fetchall()
            print("Columns in admin_logs (Supabase):")
            for c in cols:
                print(f" - {c[0]}")
        conn.close()
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    get_columns()
