import psycopg2
import sys

url = 'postgresql://postgres.ylkaqmoxhzzimoyppfqf:Admin%40Hack123@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres'

try:
    conn = psycopg2.connect(url, connect_timeout=5)
    print("SUCCESS")
    conn.close()
except Exception as e:
    print(f"ERROR: {e}")
