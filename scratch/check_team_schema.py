import sqlite3

def check_schema():
    conn = sqlite3.connect('hackathon.db')
    c = conn.cursor()
    
    # Check teams table
    c.execute("PRAGMA table_info(teams)")
    print("Teams table columns:")
    for col in c.fetchall():
        print(f" - {col[1]} ({col[2]})")
        
    # Check profiles table (if it exists)
    try:
        c.execute("PRAGMA table_info(profiles)")
        print("\nProfiles table columns:")
        for col in c.fetchall():
            print(f" - {col[1]} ({col[2]})")
    except:
        pass
        
    conn.close()

if __name__ == "__main__":
    check_schema()
