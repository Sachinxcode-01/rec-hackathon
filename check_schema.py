import os
import psycopg2
from dotenv import load_dotenv

def check_schema_details():
    load_dotenv()
    db_url = None
    with open('.env', 'r') as f:
        for line in f:
            if 'DATABASE_URL=postgresql' in line:
                db_url = line.strip().lstrip('#').strip().split('=', 1)[1]
                break
    
    if not db_url:
        print("❌ Could not find DATABASE_URL in .env.")
        return

    try:
        if 'sslmode' not in db_url:
            sep = '&' if '?' in db_url else '?'
            db_url += f"{sep}sslmode=require&connect_timeout=10"
            
        conn = psycopg2.connect(db_url)
        with conn.cursor() as cur:
            tables_to_check = ['teams', 'gallery_photos', 'help_requests']
            for table in tables_to_check:
                print(f"\n--- Columns in {table} ---")
                cur.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table}' ORDER BY ordinal_position;")
                columns = cur.fetchall()
                for c in columns:
                    print(f"  {c[0]} ({c[1]})")
                    
        conn.close()
    except Exception as e:
        print(f"❌ Error checking schema: {e}")

if __name__ == "__main__":
    check_schema_details()
