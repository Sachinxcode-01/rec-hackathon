import sqlite3
import psycopg2

SQLITE_DB = 'hackathon.db'
POSTGRES_URL = 'postgresql://postgres.ylkaqmoxhzzimoyppfqf:Admin%40Hack123@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres'

def migrate_data():
    s_conn = sqlite3.connect(SQLITE_DB)
    s_conn.row_factory = sqlite3.Row
    sc = s_conn.cursor()

    p_conn = psycopg2.connect(POSTGRES_URL)
    pc = p_conn.cursor()

    tables = ['teams', 'members', 'announcements', 'help_requests', 'activity_feed', 'mentors']

    for table in tables:
        print(f"Migrating {table}...")
        sc.execute(f"SELECT * FROM {table} LIMIT 1")
        row_example = sc.fetchone()
        if not row_example:
            continue
        
        sqlite_cols = set(row_example.keys())
        
        # Get Postgres columns and types
        pc.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name='{table}'")
        pg_info = {r[0]: r[1] for r in pc.fetchall()}
        pg_cols = set(pg_info.keys())
        
        # Intersection
        common_cols = list(sqlite_cols.intersection(pg_cols))
        
        print(f"  Common columns: {common_cols}")
        
        # Fetch all rows from SQLite
        cols_str = ', '.join(f'"{c}"' for c in common_cols)
        sc.execute(f"SELECT {cols_str} FROM {table}")
        rows = sc.fetchall()
        
        # Prepare insert query
        placeholders = []
        for c in common_cols:
            if pg_info[c] == 'boolean':
                placeholders.append('%s::boolean')
            elif pg_info[c] in ('integer', 'smallint', 'bigint'):
                placeholders.append('%s::integer')
            else:
                placeholders.append('%s')
                
        ph_str = ', '.join(placeholders)
        
        conflict_clause = ""
        if 'id' in common_cols:
            if table == 'teams':
                conflict_clause = 'ON CONFLICT (id) DO UPDATE SET ' + ', '.join([f'"{c}"=EXCLUDED."{c}"' for c in common_cols if c != 'id'])
            else:
                conflict_clause = 'ON CONFLICT (id) DO NOTHING'
        else:
             conflict_clause = 'ON CONFLICT DO NOTHING'

        insert_query = f'INSERT INTO "{table}" ({cols_str}) VALUES ({ph_str}) {conflict_clause}'

        for row in rows:
            # Convert values if needed (SQLite 0/1 to Boolean)
            vals = []
            for col in common_cols:
                val = row[col]
                if pg_info[col] == 'boolean':
                    vals.append(bool(val))
                else:
                    vals.append(val)
            pc.execute(insert_query, tuple(vals))
    
    p_conn.commit()
    print(">>> DATA MIGRATION COMPLETE.")
    s_conn.close()
    p_conn.close()

if __name__ == "__main__":
    migrate_data()
