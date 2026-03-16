
import os
import psycopg2 # type: ignore
from dotenv import load_dotenv # type: ignore

# Path to the .env file in the project root
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(env_path)

db_url = os.getenv('DATABASE_URL')

try:
    conn = psycopg2.connect(db_url)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM teams;")
    teams_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM mentors;")
    mentors_count = cursor.fetchone()[0]
    
    print(f"Current Stats - Teams: {teams_count}, Mentors: {mentors_count}")
    
    if mentors_count == 0:
        print("💡 Suggestion: Seed some mentors for the expertise matching system.")
    if teams_count == 0:
        print("💡 Suggestion: Import a test CSV to populate teams.")
    
    conn.close()
except Exception as e:
    print(f"Error: {e}")
