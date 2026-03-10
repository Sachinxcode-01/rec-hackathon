import psycopg2
POSTGRES_URL = 'postgresql://postgres.ylkaqmoxhzzimoyppfqf:Admin%40Hack123@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres'
conn = psycopg2.connect(POSTGRES_URL)
c = conn.cursor()

def add_col(table, col, ctype):
    try:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ctype}")
        print(f"Added {col} to {table}")
    except Exception as e:
        print(f"Skipped {col} in {table}: {e}")
        conn.rollback()
    else:
        conn.commit()

add_col("teams", "payment_status", "TEXT DEFAULT 'Pending'")
add_col("help_requests", "screenshot", "TEXT")
add_col("help_requests", "is_emergency", "INTEGER DEFAULT 0")
add_col("help_requests", "suggested_mentor", "TEXT")

conn.close()
