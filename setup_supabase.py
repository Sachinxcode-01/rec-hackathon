import os
import psycopg2
from werkzeug.security import generate_password_hash

DATABASE_URL = "postgresql://postgres.ylkaqmoxhzzimoyppfqf:Admin%40Hack123@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"

def migrate():
    print(">>> Connecting to Supabase...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    c = conn.cursor()

    print(">>> Creating tables...")
    
    # Teams
    c.execute('''
        CREATE TABLE IF NOT EXISTS teams (
            id TEXT PRIMARY KEY,
            team_name TEXT,
            college TEXT,
            dept TEXT,
            theme TEXT,
            idea TEXT,
            created_at TEXT,
            checked_in INTEGER DEFAULT 0,
            lunch_checkin INTEGER DEFAULT 0,
            snack_checkin INTEGER DEFAULT 0,
            project_title TEXT,
            project_desc TEXT,
            github_link TEXT,
            demo_link TEXT,
            tech_stack TEXT,
            innovation_score INTEGER DEFAULT 0,
            ui_score INTEGER DEFAULT 0,
            tech_score INTEGER DEFAULT 0,
            upvotes INTEGER DEFAULT 0,
            utr_number TEXT,
            payment_screenshot TEXT,
            payment_status TEXT DEFAULT 'Pending'
        )
    ''')

    # Members
    c.execute('''
        CREATE TABLE IF NOT EXISTS members (
            id SERIAL PRIMARY KEY,
            team_id TEXT,
            name TEXT,
            year TEXT,
            phone TEXT,
            email TEXT,
            is_leader INTEGER DEFAULT 0,
            avatar_url TEXT,
            linkedin TEXT,
            github TEXT
        )
    ''')

    # Announcements
    c.execute('''
        CREATE TABLE IF NOT EXISTS announcements (
            id SERIAL PRIMARY KEY,
            message TEXT,
            created_at TEXT,
            active INTEGER DEFAULT 1
        )
    ''')

    # Help Requests
    c.execute('''
        CREATE TABLE IF NOT EXISTS help_requests (
            id SERIAL PRIMARY KEY,
            team_id TEXT,
            location TEXT,
            topic TEXT,
            status TEXT,
            screenshot TEXT,
            is_emergency INTEGER DEFAULT 0,
            suggested_mentor TEXT,
            created_at TEXT
        )
    ''')

    # Activity Feed
    c.execute('''
        CREATE TABLE IF NOT EXISTS activity_feed (
            id SERIAL PRIMARY KEY,
            message TEXT,
            type TEXT,
            created_at TEXT
        )
    ''')

    # Chat Messages
    c.execute('''
        CREATE TABLE IF NOT EXISTS chat_messages (
            id SERIAL PRIMARY KEY,
            team_id TEXT,
            sender_name TEXT,
            avatar_url TEXT,
            is_admin INTEGER DEFAULT 0,
            message TEXT,
            created_at TEXT
        )
    ''')

    # Hacker Seekers
    c.execute('''
        CREATE TABLE IF NOT EXISTS hacker_seekers (
            id SERIAL PRIMARY KEY,
            name TEXT,
            email TEXT,
            skills TEXT,
            bio TEXT,
            linkedin TEXT,
            github TEXT,
            created_at TEXT
        )
    ''')

    # Mentors
    c.execute('''
        CREATE TABLE IF NOT EXISTS mentors (
            id SERIAL PRIMARY KEY,
            name TEXT,
            expertise TEXT,
            bio TEXT,
            avatar_url TEXT,
            available INTEGER DEFAULT 1
        )
    ''')

    # Mentor Bookings
    c.execute('''
        CREATE TABLE IF NOT EXISTS mentor_bookings (
            id SERIAL PRIMARY KEY,
            mentor_id INTEGER,
            team_id TEXT,
            topic TEXT,
            status TEXT DEFAULT 'pending',
            booking_time TEXT,
            created_at TEXT
        )
    ''')

    # Judges
    c.execute('''
        CREATE TABLE IF NOT EXISTS judges (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE,
            password_hash TEXT
        )
    ''')

    # Judge Scores
    c.execute('''
        CREATE TABLE IF NOT EXISTS judge_scores (
            id SERIAL PRIMARY KEY,
            judge_id INTEGER,
            team_id TEXT,
            innovation INTEGER,
            impact INTEGER,
            tech INTEGER,
            ui INTEGER,
            total_score FLOAT,
            comments TEXT,
            created_at TEXT
        )
    ''')

    # Team Badges
    c.execute('''
        CREATE TABLE IF NOT EXISTS team_badges (
            id SERIAL PRIMARY KEY,
            team_id TEXT,
            badge_name TEXT,
            badge_icon TEXT,
            mentor_name TEXT,
            comment TEXT,
            created_at TEXT
        )
    ''')

    # Polls
    c.execute('''
        CREATE TABLE IF NOT EXISTS polls (
            id SERIAL PRIMARY KEY,
            question TEXT NOT NULL,
            options TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            created_at TEXT
        )
    ''')

    # Poll Votes
    c.execute('''
        CREATE TABLE IF NOT EXISTS poll_votes (
            id SERIAL PRIMARY KEY,
            poll_id INTEGER,
            option_index INTEGER,
            voter_hash TEXT,
            created_at TEXT
        )
    ''')

    # Gallery
    c.execute('''
        CREATE TABLE IF NOT EXISTS gallery_photos (
            id SERIAL PRIMARY KEY,
            team_id TEXT,
            team_name TEXT,
            caption TEXT,
            photo_data TEXT,
            approved INTEGER DEFAULT 1,
            created_at TEXT
        )
    ''')

    # Subscriptions
    c.execute('''
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id SERIAL PRIMARY KEY,
            subscription_json TEXT NOT NULL,
            ip_address TEXT,
            created_at TEXT
        )
    ''')

    # Login Codes
    c.execute('''
        CREATE TABLE IF NOT EXISTS login_codes (
            team_id TEXT PRIMARY KEY,
            code TEXT,
            expires_at TEXT
        )
    ''')

    print(">>> Creating indices...")
    c.execute("CREATE INDEX IF NOT EXISTS idx_members_team ON members(team_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_help_team ON help_requests(team_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_feed(created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_chat_team ON chat_messages(team_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_chat_created ON chat_messages(created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_mb_team ON mentor_bookings(team_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_teams_checked_in ON teams(checked_in)")

    # Ensure default judge
    c.execute('SELECT COUNT(*) FROM judges')
    if c.fetchone()[0] == 0:
        c.execute('INSERT INTO judges (username, password_hash) VALUES (%s, %s)', 
                  ('judge1', generate_password_hash('rec2026', method='pbkdf2:sha256')))
        print(">>> Default judge created.")

    print(">>> SCHEMA REPLICATION COMPLETE.")
    conn.close()

if __name__ == "__main__":
    migrate()
