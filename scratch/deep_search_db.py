import sqlite3

def check_db(db_name):
    print(f"--- Checking {db_name} ---")
    try:
        conn = sqlite3.connect(db_name)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = c.fetchall()
        for table in tables:
            t_name = table[0]
            print(f"Table: {t_name}")
            try:
                c.execute(f"SELECT * FROM {t_name}")
                rows = c.fetchall()
                for row in rows:
                    if any("RECKON-GUEST-5G" in str(col) for col in row):
                        print(f"FOUND IN {t_name}: {row}")
            except Exception as e:
                print(f"Error reading {t_name}: {e}")
        conn.close()
    except Exception as e:
        print(f"Error connecting to {db_name}: {e}")

check_db('hackathon.db')
check_db('reckon.db')
