
import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor

# Manual setup from .env for testing
SUPABASE_URL = "postgresql://postgres.ylkaqmoxhzzimoyppfqf:Admin%40Hack123@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"
DB_PATH = 'hackathon.db'

def check_db():
    print(f"Checking Supabase at {SUPABASE_URL[:30]}...")
    try:
        # Add SSL mode for Supabase
        db_url = SUPABASE_URL
        if 'sslmode' not in db_url:
            db_url += "?sslmode=require"
            
        conn = psycopg2.connect(db_url)
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute("SELECT COUNT(*) as count FROM teams")
        print(f"✅ Teams count (Supabase): {c.fetchone()['count']}")
        
        c.execute("SELECT COUNT(*) as count FROM members")
        print(f"✅ Members count (Supabase): {c.fetchone()['count']}")
        
        conn.close()
    except Exception as e:
        print(f"✘ Supabase Error: {e}")
    
    if os.path.exists(DB_PATH):
        print(f"\nChecking local SQLite at {DB_PATH}...")
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT COUNT(*) as count FROM teams")
            print(f"✅ Teams count (SQLite): {c.fetchone()['count']}")
            conn.close()
        except Exception as e:
            print(f"✘ SQLite Error: {e}")

if __name__ == "__main__":
    check_db()
