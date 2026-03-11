import os
from app import get_db, DATABASE_URL

print("Using database URL:", DATABASE_URL)

def sync_sequences():
    conn, c = get_db()
    
    # List of tables that have sequences
    tables = [
        ('teams', 'teams_id_seq'),
        ('members', 'members_id_seq'),
        ('help_requests', 'help_requests_id_seq'),
        ('activity_feed', 'activity_feed_id_seq'),
        ('announcements', 'announcements_id_seq'),
        ('analytics', 'analytics_id_seq'),
        ('team_photos', 'team_photos_id_seq'),
        ('mentors', 'mentors_id_seq'),
        ('mentor_feedback', 'mentor_feedback_id_seq'),
        ('mentor_messages', 'mentor_messages_id_seq'),
        ('polls', 'polls_id_seq'),
        ('poll_options', 'poll_options_id_seq'),
        ('push_subscriptions', 'push_subscriptions_id_seq')
    ]
    
    print("Syncing sequences...")
    for table, seq in tables:
        try:
            # Check if table has rows
            c.execute(f"SELECT COALESCE(MAX(id), 1) AS max_id FROM {table};")
            max_id = c.fetchone()['max_id']
            
            # Reset sequence to max_id
            c.execute(f"SELECT setval('{seq}', %s, true);", (max_id,))
            print(f"Synced sequence for {table} to {max_id}")
        except Exception as e:
            # Table might not exist or sequence is named differently
            conn.rollback()
            try:
                # Some tables may have sequence automatically handled differently by Postgres for SERIAL vs IDENTITY,
                # Or sequence name could be formed differently. Let's use pg_get_serial_sequence
                c.execute(f"SELECT pg_get_serial_sequence('{table}', 'id');")
                actual_seq = c.fetchone()['pg_get_serial_sequence']
                if actual_seq:
                    c.execute(f"SELECT COALESCE(MAX(id), 1) AS max_id FROM {table};")
                    max_id = c.fetchone()['max_id']
                    c.execute(f"SELECT setval(%s, %s, true);", (actual_seq, max_id))
                    print(f"Synced actual sequence {actual_seq} for {table} to {max_id}")
                else:
                    print(f"Failed to find sequence for {table}: {e}")
            except Exception as e2:
                conn.rollback()
                print(f"Failed again for {table}: {e2}")
    
    conn.commit()
    conn.close()

if __name__ == '__main__':
    sync_sequences()
