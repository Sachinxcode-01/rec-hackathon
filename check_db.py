
import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get('DATABASE_URL')
DB_PATH = 'hackathon.db'

def check_db():
    if DATABASE_URL:
        print(f"Checking Postgres at {DATABASE_URL[:15]}...")
        try:
            conn = psycopg2.connect(DATABASE_URL)
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute("SELECT COUNT(*) as count FROM teams")
            print(f"Teams count (Postgres): {c.fetchone()['count']}")
            conn.close()
        except Exception as e:
            print(f"Postgres Error: {e}")
    
    if os.path.exists(DB_PATH):
        print(f"Checking SQLite at {DB_PATH}...")
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT COUNT(*) as count FROM teams")
            print(f"Teams count (SQLite): {c.fetchone()['count']}")
            conn.close()
        except Exception as e:
            print(f"SQLite Error: {e}")
    else:
        print("SQLite DB not found.")

if __name__ == "__main__":
    check_db()
