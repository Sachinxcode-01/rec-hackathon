import sqlite3
import os

db_path = 'hackathon.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("PRAGMA table_info(teams)")
    cols = [col[1] for col in c.fetchall()]
    print("Columns in 'teams' table:")
    print(cols)
    conn.close()
else:
    print("hackathon.db not found.")
