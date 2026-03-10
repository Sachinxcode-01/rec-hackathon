import sqlite3
import os

db_path = 'hackathon.db'
if not os.path.exists(db_path):
    print("Database file not found.")
    exit()

conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [t[0] for t in c.fetchall() if t[0] != 'sqlite_sequence']

results = {}
for t in tables:
    try:
        c.execute(f"SELECT COUNT(*) FROM {t}")
        results[t] = c.fetchone()[0]
    except Exception as e:
        results[t] = f"Error: {e}"

print(results)
conn.close()
