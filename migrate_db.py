import sqlite3
import datetime

def migrate():
    conn = sqlite3.connect('hackathon.db')
    c = conn.cursor()
    
    print("MIGRATING DATABASE FOR REAL-TIME TRACKING...")
    
    # 1. Update help_requests table
    try:
        c.execute("ALTER TABLE help_requests ADD COLUMN status TEXT DEFAULT 'OPEN'")
        print(" - Added 'status' to help_requests.")
    except:
        print(" - 'status' column already exists in help_requests.")
        
    try:
        c.execute("ALTER TABLE help_requests ADD COLUMN assigned_to INTEGER")
        print(" - Added 'assigned_to' to help_requests.")
    except:
        print(" - 'assigned_to' column already exists in help_requests.")
        
    try:
        c.execute("ALTER TABLE help_requests ADD COLUMN resolved_at TIMESTAMP")
        print(" - Added 'resolved_at' to help_requests.")
    except:
        print(" - 'resolved_at' column already exists in help_requests.")

    try:
        c.execute("ALTER TABLE help_requests ADD COLUMN updated_at TIMESTAMP")
        print(" - Added 'updated_at' to help_requests.")
    except:
        print(" - 'updated_at' column already exists in help_requests.")

    # 2. Update mentors table
    try:
        c.execute("ALTER TABLE mentors ADD COLUMN is_online INTEGER DEFAULT 0")
        print(" - Added 'is_online' to mentors.")
    except:
        print(" - 'is_online' column already exists in mentors.")
        
    try:
        c.execute("ALTER TABLE mentors ADD COLUMN last_seen TIMESTAMP")
        print(" - Added 'last_seen' to mentors.")
    except:
        print(" - 'last_seen' column already exists in mentors.")

    conn.commit()
    conn.close()
    print("SUCCESS: DATABASE MIGRATION COMPLETED.")

if __name__ == '__main__':
    migrate()
