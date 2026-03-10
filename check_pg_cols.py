import psycopg2
POSTGRES_URL = 'postgresql://postgres.ylkaqmoxhzzimoyppfqf:Admin%40Hack123@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres'
conn = psycopg2.connect(POSTGRES_URL)
c = conn.cursor()
c.execute("SELECT column_name FROM information_schema.columns WHERE table_name='teams'")
print([r[0] for r in c.fetchall()])
conn.close()
