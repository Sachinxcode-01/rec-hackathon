
import os
import psycopg2 # type: ignore
from dotenv import load_dotenv # type: ignore

# Path to the .env file in the project root
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)

db_url = os.getenv('DATABASE_URL')

print(f"Testing connection to: {db_url.split('@')[-1] if db_url else 'None'}")

if not db_url:
    print("❌ DATABASE_URL not found in .env")
    exit(1)

try:
    # Set a short timeout for the test
    conn = psycopg2.connect(db_url, connect_timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT version();")
    version = cursor.fetchone()
    print(f"✅ SUCCESS! Connected to Supabase.")
    print(f"Database Version: {version[0]}")
    
    cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
    tables = cursor.fetchall()
    print(f"Tables found: {[t[0] for t in tables]}")
    
    conn.close()
except Exception as e:
    print(f"❌ CONNECTION FAILED: {e}")
