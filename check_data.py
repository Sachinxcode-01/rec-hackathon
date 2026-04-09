import os
import psycopg2
from dotenv import load_dotenv

def check_data_counts():
    load_dotenv()
    db_url = None
    with open('.env', 'r') as f:
        for line in f:
            if 'DATABASE_URL=postgresql' in line:
                db_url = line.strip().lstrip('#').strip().split('=', 1)[1]
                break
    
    if not db_url:
        print("❌ Could not find DATABASE_URL in .env.")
        return

    try:
        if 'sslmode' not in db_url:
            sep = '&' if '?' in db_url else '?'
            db_url += f"{sep}sslmode=require&connect_timeout=10"
            
        conn = psycopg2.connect(db_url)
        with conn.cursor() as cur:
            tables = [
                'teams', 'members', 'announcements', 'help_requests', 
                'activity_feed', 'chat_messages', 'gallery_photos', 'admins'
            ]
            print(f"{'Table':<20} | {'Count':<10}")
            print("-" * 33)
            for table in tables:
                cur.execute(f"SELECT COUNT(*) FROM {table};")
                count = cur.fetchone()[0]
                print(f"{table:<20} | {count:<10}")
                    
        conn.close()
    except Exception as e:
        print(f"❌ Error checking data: {e}")

if __name__ == "__main__":
    check_data_counts()
