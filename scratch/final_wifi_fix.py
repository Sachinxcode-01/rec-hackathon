import sqlite3
import os

db_path = 'hackathon.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    updates = [
        ('wifi_ssid', 'RECHKT-AP-26 / 27 / 28'),
        ('wifi_password', 'Rechkt!2026 / 2027 / 2028')
    ]
    
    for key, val in updates:
        cursor.execute("UPDATE system_settings SET value = ? WHERE key = ?", (val, key))
        if cursor.rowcount == 0:
            cursor.execute("INSERT INTO system_settings (key, value) VALUES (?, ?)", (key, val))
            print(f"Inserted {key} -> {val}")
        else:
            print(f"Updated {key} -> {val}")
            
    conn.commit()
    conn.close()
    print("Database updated successfully.")
else:
    print("Database not found.")
