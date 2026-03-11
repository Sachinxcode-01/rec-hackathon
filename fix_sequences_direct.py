import os
import psycopg2

db_url = os.environ.get('DATABASE_URL', "postgresql://postgres.ylkaqmoxhzzimoyppfqf:Admin%40Hack123@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres")

print("Connecting to:", db_url)

conn = psycopg2.connect(db_url)
conn.autocommit = True
c = conn.cursor()

tables = [
    'teams', 'members', 'help_requests', 'activity_feed', 'announcements', 
    'team_photos', 'mentors', 'analytics', 'push_subscriptions', 'polls', 'poll_options'
]

for table in tables:
    try:
        # Check if table exists
        c.execute(f"SELECT pg_get_serial_sequence('{table}', 'id');")
        seq = c.fetchone()[0]
        if seq:
            c.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table};")
            max_id = c.fetchone()[0]
            if max_id > 0:
                c.execute(f"SELECT setval(%s, %s);", (seq, max_id))
                print(f"Synced sequence {seq} for {table} to {max_id}")
            else:
                print(f"No rows in {table}, skipping sequence update.")
        else:
            print(f"No serial sequence found for {table}")
    except Exception as e:
        print(f"Failed to sync sequence for {table}: {e}")

c.close()
conn.close()
print("Done.")
