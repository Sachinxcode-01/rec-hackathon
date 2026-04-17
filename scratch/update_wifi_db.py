import sqlite3
import os

db_path = 'hackathon.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("UPDATE system_settings SET value = ? WHERE key = ?", ('RECHKT-AP-26 / 27 / 28', 'wifi_ssid'))
    c.execute("UPDATE system_settings SET value = ? WHERE key = ?", ('Rechkt!2026 / 2027 / 2028', 'wifi_password'))
    conn.commit()
    conn.close()
    print("Database WiFi settings updated successfully.")
else:
    print("hackathon.db not found, skipping manual update.")
