import os
import sqlite3
import datetime
try:
    import psycopg2
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

def get_db():
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if DATABASE_URL and HAS_POSTGRES:
        if DATABASE_URL.startswith("postgres://"):
            DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        conn = psycopg2.connect(DATABASE_URL)
        return conn, conn.cursor()
    else:
        conn = sqlite3.connect('hackathon.db')
        return conn, conn.cursor()

def migrate():
    conn, c = get_db()
    
    print("MIGRATING DATABASE FOR INDIVIDUAL MEAL TRACKING & REAL-TIME CHAT...")
    
    # 1. Update members table for meal tracking
    meal_columns = [
        'morning_checkin', 'lunch_checkin', 'snack_checkin', 'dinner_checkin',
        'd2_morning_checkin', 'd2_lunch_checkin', 'd2_snack_checkin'
    ]
    meal_timestamps = [
        'morning_at', 'lunch_at', 'snack_at', 'dinner_at',
        'd2_morning_at', 'd2_lunch_at', 'd2_snack_at'
    ]
    
    for col in meal_columns:
        try:
            c.execute(f"ALTER TABLE members ADD COLUMN {col} INTEGER DEFAULT 0")
            print(f" - Added '{col}' to members.")
        except Exception as e:
            print(f" - '{col}' column in members: already exists or error skip.")
            
    for col in meal_timestamps:
        try:
            c.execute(f"ALTER TABLE members ADD COLUMN {col} TEXT")
            print(f" - Added '{col}' to members.")
        except Exception as e:
            print(f" - '{col}' column in members: already exists or error skip.")

    # 2. Add chat support columns to help_requests
    try:
        c.execute("ALTER TABLE help_requests ADD COLUMN chat_id TEXT")
        print(" - Added 'chat_id' to help_requests.")
    except:
        pass

    try:
        c.execute("ALTER TABLE help_requests ADD COLUMN code_snippet TEXT")
        print(" - Added 'code_snippet' to help_requests.")
    except:
        pass

    # 3. Create ticket_messages table for mentor-team chat
    try:
        if DATABASE_URL and HAS_POSTGRES:
            c.execute('''CREATE TABLE IF NOT EXISTS ticket_messages (
                id SERIAL PRIMARY KEY,
                ticket_id INTEGER,
                sender_id TEXT,
                sender_name TEXT,
                sender_avatar TEXT,
                message TEXT,
                message_type TEXT DEFAULT 'text',
                created_at TEXT
            )''')
        else:
            c.execute('''CREATE TABLE IF NOT EXISTS ticket_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER,
                sender_id TEXT,
                sender_name TEXT,
                sender_avatar TEXT,
                message TEXT,
                message_type TEXT DEFAULT 'text',
                created_at TEXT
            )''')
        print(" - Table 'ticket_messages' ensured.")
    except Exception as e:
        print(f" - Error creating ticket_messages: {e}")

    conn.commit()
    conn.close()
    print("SUCCESS: DATABASE MIGRATION COMPLETED.")

if __name__ == '__main__':
    migrate()
