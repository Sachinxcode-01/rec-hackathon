import sqlite3
conn = sqlite3.connect('hackathon.db')
c = conn.cursor()
c.execute("SELECT * FROM system_settings WHERE value LIKE '%GUEST%' OR value LIKE '%HACKTHEPLANET%'")
print("System Settings matches:", c.fetchall())
c.execute("SELECT * FROM admin_logs WHERE details LIKE '%GUEST%' OR details LIKE '%HACKTHEPLANET%'")
print("Admin Logs matches:", c.fetchall())
conn.close()
