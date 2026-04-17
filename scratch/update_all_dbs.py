import sqlite3
import os

db_files = ['hackathon.db', 'reckon.db']
new_ssid = 'RECHKT-AP-26 / 27 / 28'
new_pass = 'Rechkt!2026 / 2027 / 2028'

for db_path in db_files:
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            # Ensure the table exists
            c.execute("CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)")
            # Update SSID
            c.execute("INSERT INTO system_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", ('wifi_ssid', new_ssid))
            # SQLite fallback for ON CONFLICT
            if c.rowcount == 0:
                c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", ('wifi_ssid', new_ssid))
            
            # Update Password
            c.execute("INSERT INTO system_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", ('wifi_password', new_pass))
            if c.rowcount == 0:
                c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", ('wifi_password', new_pass))
                
            conn.commit()
            conn.close()
            print(f"Successfully updated {db_path}")
        except Exception as e:
            print(f"Error updating {db_path}: {e}")
    else:
        print(f"{db_path} not found")
