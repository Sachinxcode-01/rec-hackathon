import sqlite3
import os

db_path = 'reckon.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = c.fetchall()
    print(f"Tables in {db_path}:")
    for t in tables:
        print(f" - {t[0]}")
    
    # Try to see if there's a system_settings table
    try:
        c.execute("SELECT * FROM system_settings")
        settings = c.fetchall()
        print("\nSystem Settings in reckon.db:")
        for s in settings:
            print(f" - {s[0]}: {s[1]}")
    except:
        print("\nNo system_settings table in reckon.db")
        
    conn.close()
else:
    print(f"{db_path} not found.")
