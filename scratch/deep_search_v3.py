import sqlite3
import os

db_path = 'hackathon.db'
target = 'RECKON-GUEST'

def search_db(path):
    if not os.path.exists(path):
        return
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in c.fetchall()]
    
    for table in tables:
        try:
            c.execute(f"SELECT * FROM {table}")
            rows = c.fetchall()
            for i, row in enumerate(rows):
                if any(target in str(col) for col in row):
                    print(f"MATCH in {path} -> Table: {table}, Row: {i}")
                    print(f"Content: {row}")
        except Exception as e:
            pass
    conn.close()

print("Searching hackathon.db...")
search_db('hackathon.db')
print("Searching reckon.db...")
search_db('reckon.db')
