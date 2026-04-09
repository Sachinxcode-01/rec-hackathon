import os
import psycopg2
from dotenv import load_dotenv

def test_supabase_connection():
    load_dotenv()
    
    # The URL in .env is commented out, so we need to manually parse or uncomment it temporarily.
    # Alternatively, I'll search for it programmatically.
    db_url = None
    with open('.env', 'r') as f:
        for line in f:
            if 'DATABASE_URL=postgresql' in line:
                # Remove comment leading # and split by =
                db_url = line.strip().lstrip('#').strip().split('=', 1)[1]
                break
    
    if not db_url:
        print("❌ Could not find DATABASE_URL in .env (even commented out).")
        return

    print(f"🔍 Testing connection to: {db_url.split('@')[-1]}") # Print only the host part for security
    
    try:
        # Ensure SSL is enabled as required by Supabase
        if 'sslmode' not in db_url:
            sep = '&' if '?' in db_url else '?'
            db_url += f"{sep}sslmode=require&connect_timeout=10"
            
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute('SELECT version();')
            version = cur.fetchone()
            print(f"✅ Connection successful!")
            print(f"📦 Postgres version: {version[0]}")
            
            # Check for tables
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
            tables = cur.fetchall()
            print(f"📊 Found {len(tables)} tables in 'public' schema:")
            for t in tables:
                print(f"  - {t[0]}")
                
        conn.close()
    except Exception as e:
        print(f"❌ Connection failed: {e}")

if __name__ == "__main__":
    test_supabase_connection()
