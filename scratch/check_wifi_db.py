import sqlite3
import os

db_path = 'hackathon.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT * FROM system_settings WHERE key LIKE 'wifi_%';")
    rows = c.fetchall()
    for row in rows:
        print(row)
    conn.close()
else:
    print("hackathon.db not found")
