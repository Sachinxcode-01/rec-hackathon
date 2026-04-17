import sqlite3
import os

db_path = 'hackathon.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = c.fetchall()
    print("Tables in hackathon.db:")
    for t in tables:
        print(f" - {t[0]}")
    
    # Check system_settings content
    c.execute("SELECT * FROM system_settings")
    settings = c.fetchall()
    print("\nSystem Settings:")
    for s in settings:
        print(f" - {s[0]}: {s[1]}")
    
    conn.close()
else:
    print("Database not found.")
