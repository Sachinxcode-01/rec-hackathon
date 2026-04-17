import sqlite3
import os
import psycopg2
from dotenv import load_dotenv

def migrate_local():
    print("Migrating local SQLite (hackathon.db)...")
    db_path = 'hackathon.db'
    if not os.path.exists(db_path):
        print("hackathon.db not found.")
        return
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # Check if columns exist
    cur.execute("PRAGMA table_info(teams)")
    cols = [col[1] for col in cur.fetchall()]
    
    if 'last_seen' not in cols:
        print("Adding column last_seen to teams table...")
        cur.execute("ALTER TABLE teams ADD COLUMN last_seen TEXT")
    
    if 'visit_count' not in cols:
        print("Adding column visit_count to teams table...")
        cur.execute("ALTER TABLE teams ADD COLUMN visit_count INTEGER DEFAULT 0")
        
    conn.commit()
    conn.close()
    print("Local migration complete.")

def migrate_supabase():
    print("\nMigrating Supabase PostgreSQL...")
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
            # Check columns in teams table
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'teams'")
            cols = [row[0] for row in cur.fetchall()]
            
            if 'last_seen' not in cols:
                print("Adding column last_seen to teams table (Supabase)...")
                cur.execute("ALTER TABLE teams ADD COLUMN last_seen TIMESTAMP WITH TIME ZONE")
            
            if 'visit_count' not in cols:
                print("Adding column visit_count to teams table (Supabase)...")
                cur.execute("ALTER TABLE teams ADD COLUMN visit_count INTEGER DEFAULT 0")
                
            print("Supabase migration complete.")
        conn.close()
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    migrate_local()
    migrate_supabase()
