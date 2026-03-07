import sqlite3
import os

DB_NAME = 'hackathon.db'

def populate():
    if not os.path.exists(DB_NAME):
        print("Database not found. Please run app.py first.")
        return

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Add Mentors
    mentors = [
        ('Siddharth', 'AI & Machine Learning', 'Researcher at AI Labs. Loves tinkering with neural networks.', 'https://github.com/identicons/sid.png'),
        ('Ananya', 'UI/UX & Frontend', 'Design Enthusiast. Specialist in React and CSS-in-JS.', 'https://github.com/identicons/ananya.png'),
        ('Deepak', 'Backend & Scaling', 'Full-stack wizard. Ask me about Go, Python, and Microservices.', 'https://github.com/identicons/deepak.png')
    ]
    c.executemany("INSERT OR IGNORE INTO mentors (name, expertise, bio, avatar_url) VALUES (?, ?, ?, ?)", mentors)

    # Add Seeker
    seekers = [
        ('Rohan Das', 'rohan@example.com', 'React, Firebase, Tailwind', 'Full-stack dev looking for a team working on EdTech.', 'https://linkedin.com/in/rohan', 'https://github.com/rohan')
    ]
    c.executemany("INSERT OR IGNORE INTO hacker_seekers (name, email, skills, bio, linkedin, github) VALUES (?, ?, ?, ?, ?, ?)", seekers)

    # Add Judge
    # For now, simplistic password for demo
    c.execute("INSERT OR IGNORE INTO judges (username, password) VALUES (?, ?)", ('judge1', 'rec2026'))

    conn.commit()
    conn.close()
    print("Database populated with demo data!")

if __name__ == "__main__":
    populate()
