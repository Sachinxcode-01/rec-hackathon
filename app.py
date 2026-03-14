import os
import json
# Disable eventlet's green DNS which causes 'Lookup timed out' on Windows
os.environ['EVENTLET_NO_GREENDNS'] = 'yes'

import eventlet
eventlet.monkey_patch()
import sqlite3
import random
import string
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import threading
import csv
import io
try:
    import openpyxl
except ImportError:
    openpyxl = None
try:
    import psycopg2
    from psycopg2 import pool
    from psycopg2.extras import RealDictCursor
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

try:
    from flask_compress import Compress
    HAS_COMPRESS = True
except ImportError:
    HAS_COMPRESS = False

# Load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("python-dotenv not installed. Run: pip install python-dotenv")

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)
if HAS_COMPRESS:
    Compress(app)
app.secret_key = os.environ.get('SECRET_KEY', 'REC1O_SUPER_SECRET_KEY_DEVELOPMENT')

# Explicitly serve images and assets to avoid issues with static_folder='.'
@app.route('/images/<path:filename>')
def serve_images(filename):
    return send_from_directory(os.path.join(app.root_path, 'images'), filename)

@app.route('/assets/<path:filename>')
def serve_assets(filename):
    return send_from_directory(os.path.join(app.root_path, 'assets'), filename)

# Debug route to check file sizes on production server
@app.route('/debug/file-check')
def debug_file_check():
    import os
    try:
        res = {}
        target_dir = os.path.join(app.root_path, 'images')
        if os.path.exists(target_dir):
            for f in os.listdir(target_dir):
                p = os.path.join(target_dir, f)
                if os.path.isfile(p):
                    stats = os.stat(p)
                    res[f] = {
                        'size': stats.st_size,
                        'mode': oct(stats.st_mode),
                        'uid': stats.st_uid,
                        'gid': stats.st_gid
                    }
        return jsonify({
            'root': app.root_path,
            'images_dir': target_dir,
            'files': res
        })
    except Exception as e:
        return jsonify({'error': str(e)})

# Initialize SocketIO with extended timeouts for stable connections over proxies/mobile
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=120, ping_interval=25, logger=False, engineio_logger=False)

ADMIN_USERNAME = "admin"

def emit_announcement(ann):
    """Broadcast new announcement to all clients."""
    socketio.emit('new_announcement', ann)

def normalize_team_id(tid):
    """Ensure consistency across all team lookups by adding REC1- prefix if missing."""
    if not tid: return tid
    tid = str(tid).strip().upper()
    if tid and not tid.startswith('REC1-'):
        return 'REC1-' + tid
    return tid

def emit_feed_update(message, act_type="info", team_id=None):
    """Broadcast activity feed update."""
    socketio.emit('feed_update', {
        'message': message,
        'type': act_type,
        'team_id': team_id,
        'created_at': datetime.datetime.now().isoformat()
    })

def emit_leaderboard_update():
    """Notify clients that the leaderboard data has changed."""
    socketio.emit('leaderboard_update')

def emit_chat_message(msg):
    """Broadcast chat message."""
    socketio.emit('new_chat_message', msg)

def emit_help_request(req):
    """Broadcast help request to admins."""
    socketio.emit('new_help_request', req)

# Global cache for the hash to avoid re-generating on every import/worker fork
_ADMIN_HASH = None

def get_admin_hash():
    global _ADMIN_HASH
    if _ADMIN_HASH is None:
        # Using a memory-safe method for cloud containers
        _ADMIN_HASH = generate_password_hash("Admin@Hack123", method='pbkdf2:sha256')
    return _ADMIN_HASH

# Ensure DB path is absolute for cloud environments
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'hackathon.db')
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Global Postgres Pool
pg_pool = None

def get_db():
    global pg_pool
    if DATABASE_URL and HAS_POSTGRES:
        if pg_pool is None:
            db_url = DATABASE_URL
            if '?' not in db_url:
                db_url += '?sslmode=require'
            elif 'sslmode' not in db_url:
                db_url += '&sslmode=require'
            
            # Robust thread-safe connection pool for Postgres
            try:
                pg_pool = pool.ThreadedConnectionPool(1, 40, db_url, client_encoding='utf8')
                print(">>> Postgres Threaded Connection Pool Initialized [Max 40].")
            except Exception as e:
                print(f"✘ FAILED TO INITIALIZE POSTGRES POOL: {e}")
                # Fallback to single connection if pool fails
                conn = psycopg2.connect(db_url, client_encoding='utf8')
                return conn, conn.cursor(cursor_factory=RealDictCursor)
        
        # Robust connection retrieval with retry
        conn = None
        for _ in range(3):
            try:
                conn = pg_pool.getconn()
                # Verify connection is still alive
                with conn.cursor() as check_c:
                    check_c.execute('SELECT 1')
                break # Success
            except Exception as e:
                if conn:
                    try: pg_pool.putconn(conn, close=True)
                    except: pass
                print(f">>> DB Connection Stale, retrying... ({e})")
                conn = None
        
        if not conn:
             # Final fallback attempt
             conn = psycopg2.connect(DATABASE_URL, client_encoding='utf8')
             
        c = conn.cursor(cursor_factory=RealDictCursor)
    else:
        # SQLite performance & concurrency optimization for high traffic
        conn = sqlite3.connect(DB_PATH, timeout=20, check_same_thread=False)
        try:
            conn.execute('PRAGMA journal_mode=WAL;') # Write-Ahead Logging for non-blocking reads
            conn.execute('PRAGMA synchronous=NORMAL;') # Faster writes, safe in WAL
            conn.execute('PRAGMA cache_size=-64000;') # 64MB Cache size
            conn.execute('PRAGMA temp_store=MEMORY;') # Memory-based temporary tables
            conn.execute('PRAGMA busy_timeout=20000;') # Wait longer for DB locks
        except Exception as e:
            print(f"Warning: Couldn't set PRAGMA: {e}")
            
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

    try:
        from flask import g
        if not hasattr(g, 'db_conns'):
            g.db_conns = []
        g.db_conns.append(conn)
    except RuntimeError:
        pass # Not running in request context

    return conn, c

def close_db(conn):
    try:
        from flask import g
        if hasattr(g, 'db_conns') and conn in g.db_conns:
            g.db_conns.remove(conn)
    except RuntimeError:
        pass

    if DATABASE_URL and HAS_POSTGRES and pg_pool:
        try:
            pg_pool.putconn(conn)
        except Exception:
            pass
    else:
        try:
            conn.close()
        except:
            pass

@app.teardown_appcontext
def teardown_db_connections(exception):
    try:
        from flask import g
        if hasattr(g, 'db_conns'):
            for dangling_conn in list(g.db_conns):
                if DATABASE_URL and HAS_POSTGRES and pg_pool:
                    try:
                        pg_pool.putconn(dangling_conn)
                    except Exception:
                        pass
                else:
                    try:
                        dangling_conn.close()
                    except Exception:
                        pass
            g.db_conns.clear()
    except Exception:
        pass


def db_execute(cursor, query, params=None):
    if DATABASE_URL and HAS_POSTGRES:
        query = query.replace('?', '%s')
    if params:
        cursor.execute(query, params)
    else:
        cursor.execute(query)
    return cursor

_DB_INITIALIZED = False

def init_db():
    global _DB_INITIALIZED
    if _DB_INITIALIZED: return True, "Database already initialized"
    
    print(f">>> INITIALIZING DATABASE...", flush=True)
    try:
        conn, c = get_db()
        is_pg = DATABASE_URL and HAS_POSTGRES
        
        # Helper to handle Postgres vs SQLite types
        def sql_compat(sql):
            if is_pg:
                # Replace SQLite specific 'AUTOINCREMENT' with Postgres 'SERIAL'
                sql = sql.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
                return sql
            return sql

        db_execute(c, sql_compat('''
            CREATE TABLE IF NOT EXISTS teams (
                id TEXT PRIMARY KEY,
                team_name TEXT,
                college TEXT,
                dept TEXT,
                theme TEXT,
                idea TEXT,
                created_at TEXT,
                checked_in BOOLEAN DEFAULT FALSE,
                lunch_checkin BOOLEAN DEFAULT FALSE,
                snack_checkin BOOLEAN DEFAULT FALSE,
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
                checked_out INTEGER DEFAULT 0
            )
        '''))
        db_execute(c, sql_compat('''
            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        '''))
        db_execute(c, sql_compat('''
            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT,
                created_at TEXT,
                active INTEGER DEFAULT 1
            )
        '''))
        db_execute(c, sql_compat('''
            CREATE TABLE IF NOT EXISTS help_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id TEXT,
                location TEXT,
                topic TEXT,
                status TEXT,
                screenshot TEXT,
                is_emergency INTEGER DEFAULT 0,
                suggested_mentor TEXT,
                created_at TEXT
            )
        '''))
        db_execute(c, sql_compat('''
            CREATE TABLE IF NOT EXISTS activity_feed (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT,
                type TEXT,
                team_id TEXT,
                created_at TEXT
            )
        '''))
        db_execute(c, sql_compat('''
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id TEXT,
                sender_name TEXT,
                avatar_url TEXT,
                is_admin BOOLEAN DEFAULT FALSE,
                message TEXT,
                created_at TEXT
            )
        '''))
        db_execute(c, sql_compat('''
            CREATE TABLE IF NOT EXISTS hacker_seekers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT,
                skills TEXT,
                bio TEXT,
                linkedin TEXT,
                github TEXT,
                created_at TEXT
            )
        '''))
        db_execute(c, sql_compat('''
            CREATE TABLE IF NOT EXISTS mentors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                expertise TEXT,
                bio TEXT,
                avatar_url TEXT,
                available BOOLEAN DEFAULT TRUE
            )
        '''))
        db_execute(c, sql_compat('''
            CREATE TABLE IF NOT EXISTS mentor_bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mentor_id INTEGER,
                team_id TEXT,
                topic TEXT,
                status TEXT DEFAULT 'pending', -- pending, approved, rejected
                booking_time TEXT,
                created_at TEXT
            )
        '''))
        db_execute(c, sql_compat('''
            CREATE TABLE IF NOT EXISTS judges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password_hash TEXT
            )
        '''))
        db_execute(c, sql_compat('''
            CREATE TABLE IF NOT EXISTS judge_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        '''))
        db_execute(c, sql_compat('''
            CREATE TABLE IF NOT EXISTS team_badges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id TEXT,
                badge_name TEXT,
                badge_icon TEXT,
                mentor_name TEXT,
                comment TEXT,
                created_at TEXT
            )
        '''))
        db_execute(c, sql_compat('''
            CREATE TABLE IF NOT EXISTS polls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                options TEXT NOT NULL,
                active INTEGER DEFAULT 1,
                created_at TEXT
            )
        '''))
        db_execute(c, sql_compat('''
            CREATE TABLE IF NOT EXISTS poll_votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                poll_id INTEGER,
                option_index INTEGER,
                voter_hash TEXT,
                created_at TEXT
            )
        '''))
        db_execute(c, sql_compat('''
            CREATE TABLE IF NOT EXISTS gallery_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id TEXT,
                team_name TEXT,
                caption TEXT,
                photo_data TEXT,
                approved INTEGER DEFAULT 1,
                created_at TEXT
            )
        '''))
        db_execute(c, sql_compat('''
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_json TEXT NOT NULL,
                ip_address TEXT,
                created_at TEXT
            )
        '''))
        # Schema Migrations and Performance Indices
        # Indices for common LOOKUP columns
        if not is_pg:
            try: db_execute(c, "CREATE INDEX IF NOT EXISTS idx_members_team_id ON members(team_id)")
            except: pass
            try: db_execute(c, "CREATE INDEX IF NOT EXISTS idx_hr_team_id ON help_requests(team_id)")
            except: pass
            try: db_execute(c, "CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_feed(created_at)")
            except: pass
        else:
            # Postgres supports CREATE INDEX IF NOT EXISTS
            db_execute(c, "CREATE INDEX IF NOT EXISTS idx_members_team_id ON members(team_id)")
            db_execute(c, "CREATE INDEX IF NOT EXISTS idx_hr_team_id ON help_requests(team_id)")
            db_execute(c, "CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_feed(created_at)")
            
        # Schema Migrations for existing DBs
        def add_column_if_not_exists(table, col, col_type):
            if is_pg:
                # In Postgres, check if column exists first to avoid failing the transaction
                db_execute(c, f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}' AND column_name='{col.lower()}'")
                if not c.fetchone():
                    db_execute(c, f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            else:
                # In SQLite, try-except is fine as it doesn't abort the transaction
                try: db_execute(c, f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                except: pass

        add_column_if_not_exists("help_requests", "screenshot", "TEXT")
        add_column_if_not_exists("help_requests", "is_emergency", "INTEGER DEFAULT 0")
        add_column_if_not_exists("help_requests", "suggested_mentor", "TEXT")
        add_column_if_not_exists("teams", "utr_number", "TEXT")
        add_column_if_not_exists("teams", "payment_screenshot", "TEXT")
        add_column_if_not_exists("teams", "payment_status", "TEXT DEFAULT 'Pending'")
        add_column_if_not_exists("teams", "checked_out", "INTEGER DEFAULT 0")
        add_column_if_not_exists("teams", "lunch_checkin", "BOOLEAN DEFAULT FALSE")
        add_column_if_not_exists("teams", "snack_checkin", "BOOLEAN DEFAULT FALSE")
        add_column_if_not_exists("teams", "status", "TEXT DEFAULT 'Verified'")
        add_column_if_not_exists("activity_feed", "team_id", "TEXT")
        # Check-in timestamp columns (exact time of each scan)
        add_column_if_not_exists("teams", "morning_at", "TEXT")
        add_column_if_not_exists("teams", "lunch_at", "TEXT")
        add_column_if_not_exists("teams", "snack_at", "TEXT")
        add_column_if_not_exists("teams", "checkout_at", "TEXT")

        db_execute(c, sql_compat('''
            CREATE TABLE IF NOT EXISTS login_codes (
                team_id TEXT PRIMARY KEY,
                code TEXT,
                expires_at TEXT
            )
        '''))
        
        # Ensure default judge exists
        db_execute(c, 'SELECT COUNT(*) as count FROM judges')
        row = c.fetchone()
        count = row['count']
        if count == 0:
            db_execute(c, 'INSERT INTO judges (username, password_hash) VALUES (?, ?)', 
                      ('judge1', generate_password_hash('rec2026', method='pbkdf2:sha256')))
            
        # Extended Performance Indices for fast querying
        try:
            db_execute(c, "CREATE INDEX IF NOT EXISTS idx_members_team ON members(team_id)")
            db_execute(c, "CREATE INDEX IF NOT EXISTS idx_help_team ON help_requests(team_id)")
            db_execute(c, "CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_feed(created_at)")
            db_execute(c, "CREATE INDEX IF NOT EXISTS idx_chat_team ON chat_messages(team_id)")
            db_execute(c, "CREATE INDEX IF NOT EXISTS idx_chat_created ON chat_messages(created_at)")
            db_execute(c, "CREATE INDEX IF NOT EXISTS idx_mb_team ON mentor_bookings(team_id)")
            db_execute(c, "CREATE INDEX IF NOT EXISTS idx_teams_checked_in ON teams(checked_in)")
        except Exception as e:
            print(f"Warning: Failed to create some indices: {e}")

        conn.commit()
        close_db(conn)
        print("OK: Database Initialized and Verified.")
        _DB_INITIALIZED = True
        return True, "Success"
    except Exception as e:
        print(f"ERR: Database Error during init: {e}")
        import traceback
        traceback.print_exc()
        return False, str(e)

@app.route('/api/admin/setup_db')
def manual_setup_db():
    success, msg = init_db()
    if success:
        return jsonify({'success': True, 'message': 'Database initialized successfully'})
    else:
        return jsonify({'success': False, 'error': msg}), 500

# Removed global init_db() call to prevent Gunicorn timeout
# Instead, we initialize on the first request
@app.before_request
def startup_init():
    init_db()

ADMIN_USERNAME = "admin"

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized access'}), 401
        return f(*args, **kwargs)
    return decorated_function

def send_confirmation_email(to_email, team_id, team_name, leader_name="Participant"):
    # Build the HTML
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&color=000000&bgcolor=ffffff&data={team_id}&margin=10"
    body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Registration Confirmed</title></head>
<body style="margin:0;padding:0;background:#0a0f1e;font-family:Arial,sans-serif;">
  <div style="max-width:600px;margin:20px auto;background:#0d1426;border-radius:16px;border:1px solid #1e2d50;overflow:hidden;color:#fff;">
    <div style="background:linear-gradient(135deg,#7c3aed,#00d4ff);padding:30px;text-align:center;">
       <h1 style="margin:0;font-size:28px;">RECKON 1.O</h1>
       <p style="margin:5px 0 0;font-size:12px;letter-spacing:2px;">REGISTRATION CONFIRMED</p>
    </div>
    <div style="padding:30px;">
       <p style="font-size:18px;">Hello <b>{leader_name}</b>,</p>
       <p>Successfully registered team: <b style="color:#00d4ff;">{team_name}</b></p>
       <div style="background:rgba(0,212,255,0.1);border:1px solid #00d4ff;padding:20px;text-align:center;border-radius:10px;margin:20px 0;">
          <p style="margin:0 0 5px;font-size:10px;color:rgba(255,255,255,0.5);">YOUR TEAM ID</p>
          <h2 style="margin:0;font-size:32px;letter-spacing:5px;color:#00d4ff;">{team_id}</h2>
       </div>
        <div style="text-align:center; margin-top: 20px;">
           <a href="{os.environ.get('WEBSITE_URL', 'https://rechackathon.up.railway.app')}/login.html" style="background:#00d4ff; color:#0a0f1e; padding:12px 24px; border-radius:8px; text-decoration:none; font-weight:bold; display:inline-block;">Login to Dashboard</a>
           <p style="font-size:11px;color:rgba(255,255,255,0.4); margin-top:10px;">Visit: {os.environ.get('WEBSITE_URL', 'https://rechackathon.up.railway.app')}</p>
        </div>
       <div style="text-align:center;">
          <img src="{qr_url}" width="150" height="150" style="background:#fff;padding:10px;border-radius:10px;">
          <p style="font-size:11px;color:rgba(255,255,255,0.4);">Present this QR at the desk</p>
       </div>
    </div>
  </div>
</body></html>"""

    def task():
        print(f"[REG] Sending confirmation to {to_email}...")
        subject = f"🎉 [{team_id}] Registration Confirmed — RECKON 1.O"
        
        # Capture error message
        try:
            res = send_universal_email(to_email, subject, body, "REG")
            if res is True:
                add_activity(f"Team {team_name} ({team_id}) registered! Email: {to_email}", "success")
            else:
                add_activity(f"Email FAILED to {to_email}: {res}", "warning")
        except Exception as e:
            add_activity(f"Email CRASH: {str(e)}", "error")
        
        # BIG LOG for manual rescue
        print(f"\n" + "!"*60)
        print(f"NEW TEAM REGISTERED: {team_name}")
        print(f"ID: {team_id} | LEADER: {leader_name} | EMAIL: {to_email}")
        print("!"*60 + "\n")

    threading.Thread(target=task).start()

# --- UNIVERSAL EMAIL SENDER ---
def send_universal_email(to_email, subject, html_content, log_tag="EMAIL"):
    smtp_user   = (os.environ.get('SMTP_USER') or '').strip()
    smtp_pass   = (os.environ.get('SMTP_PASS') or '').strip()
    smtp_server = (os.environ.get('SMTP_SERVER') or 'smtp.gmail.com').strip()
    smtp_port   = (os.environ.get('SMTP_PORT') or '587').strip()
    resend_key  = (os.environ.get('RESEND_API_KEY') or '').strip()
    brevo_key   = (os.environ.get('BREVO_API_KEY') or '').strip()
    sender_email = (os.environ.get('SENDER_EMAIL') or 'saxhin0708@gmail.com').strip()

    # Clean credentials (Gmail App Passwords can have spaces, but APIs shouldn't)
    if brevo_key: brevo_key = brevo_key.replace(' ', '')
    if resend_key: resend_key = resend_key.replace(' ', '')
    # For Gmail SMTP, we keep spaces as my test showed it works, but we'll try both if it fails.


    # Fallback to standard ports if needed
    to_try = [(int(smtp_port), int(smtp_port) == 465)]
    if 587 not in [p[0] for p in to_try]: to_try.append((587, False))
    if 465 not in [p[0] for p in to_try]: to_try.append((465, True))

    # --- 1. TRY BREVO API (Best for Railway/No Domain) ---
    if brevo_key:
        try:
            print(f"[{log_tag}] Trying Brevo API...")
            import urllib.request as _ur, json as _json, urllib.error as _ue
            payload = _json.dumps({
                "sender": {"name": "RECKON 1.O Hackathon", "email": sender_email},
                "to": [{"email": to_email}],
                "subject": subject,
                "htmlContent": html_content
            }).encode()
            
            req = _ur.Request('https://api.brevo.com/v3/smtp/email', data=payload,
                headers={'api-key': brevo_key, 'Content-Type': 'application/json'},
                method='POST')
            _ur.urlopen(req, timeout=10)
            print(f"[{log_tag}] SUCCESS via Brevo API")
            return True
        except _ue.HTTPError as e:
            print(f"[{log_tag}] Brevo API Error {e.code}: {e.read().decode()}")
        except Exception as e:
            print(f"[{log_tag}] Brevo API failed: {e}")
    # --- 2. TRY SMTP ---
    last_error = "No delivery methods available"
    if smtp_user and smtp_pass:
        for p, is_ssl in to_try:
            try:
                print(f"[{log_tag}] Trying SMTP {smtp_server}:{p}...")
                if is_ssl:
                    srv = smtplib.SMTP_SSL(smtp_server, p, timeout=10)
                else:
                    srv = smtplib.SMTP(smtp_server, p, timeout=10)
                    srv.starttls()
                srv.login(smtp_user, smtp_pass)
                
                msg = MIMEMultipart('alternative')
                msg['From']    = f'RECKON 1.O <{sender_email}>'
                msg['To']      = to_email
                msg['Subject'] = subject
                msg.attach(MIMEText(html_content, 'html'))
                srv.send_message(msg)
                srv.quit()
                print(f"[{log_tag}] SUCCESS via SMTP {p}")
                return True
            except Exception as e:
                last_error = f"SMTP {p} Error: {str(e)}"
                print(f"[{log_tag}] {last_error}")
                if "srv" in locals():
                    try: srv.close()
                    except: pass

    # Try Resend
    if resend_key:
        try:
            print(f"[{log_tag}] Trying Resend fallback...")
            import urllib.request as _ur, json as _json, urllib.error as _ue
            from_display = f"RECKON 1.O <{sender_email}>"
            
            payload = _json.dumps({
                'from': from_display,
                'to': [to_email],
                'subject': subject,
                'html': html_content,
            }).encode()
            
            req = _ur.Request('https://api.resend.com/emails', data=payload,
                headers={'Authorization': f'Bearer {resend_key}', 'Content-Type': 'application/json'},
                method='POST')
            _ur.urlopen(req, timeout=10)
            print(f"[{log_tag}] SUCCESS via Resend")
            return True
        except Exception as e:
            last_error = f"Resend Error: {str(e)}"
            print(f"[{log_tag}] {last_error}")

    return last_error



@app.route('/api/admin/debug_email')
def debug_email():
    email = request.args.get('email', 'kalinganavarsachin@gmail.com')
    send_confirmation_email(email, "DEBUG-123", "Debug Team", "Developer")
    return jsonify({"message": f"Instruction sent! Check the 'Activity Feed' on the homepage in 10 seconds to see if it worked or failed.", "target": email})

def add_activity(message, act_type="info", team_id=None):
    conn = None
    try:
        conn, c = get_db()
        created_at = datetime.datetime.now().isoformat()
        db_execute(c, 'INSERT INTO activity_feed (message, type, created_at, team_id) VALUES (?, ?, ?, ?)', 
                  (message, act_type, created_at, team_id))
        conn.commit()
        # Realtime broadcast
        emit_feed_update(message, act_type, team_id)
    except Exception as e:
        print(f"Failed to add activity: {e}")
    finally:
        if conn:
            close_db(conn)

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'timestamp': datetime.datetime.now().isoformat()})

@app.route('/admin')
def admin_redirect():
    return redirect('/admin.html')

# --- ERROR HANDLERS ---
@app.errorhandler(404)
def page_not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not Found', 'path': request.path}), 404
    return send_from_directory('.', 'index.html'), 404

@app.errorhandler(500)
def server_error(e):
    print(f"!!! INTERNAL SERVER ERROR: {e}")
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Internal Server Error'}), 500
    return "<h1>500 - Internal Server Error</h1><p>Something went wrong on our end. Please try again later.</p>", 500

# --- CACHING & CORS ---
@app.after_request
def add_header(response):
    # Cache static assets for 1 week
    if request.path.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.woff2', '.ico')):
        response.headers['Cache-Control'] = 'public, max-age=604800'
    else:
        # Don't cache API or HTML to ensure real-time updates
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    return response

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

@app.route('/api/feed', methods=['GET'])
def get_feed():
    conn, c = get_db()
    try:
        db_execute(c, 'SELECT * FROM activity_feed ORDER BY created_at DESC LIMIT 50')
        feed = [dict(row) for row in c.fetchall()]
        return jsonify(feed)
    finally:
        close_db(conn)

@app.route('/api/pulse', methods=['GET'])
def get_tech_pulse():
    conn, c = get_db()
    try:
        if DATABASE_URL and HAS_POSTGRES:
            db_execute(c, "SELECT tech_stack FROM teams WHERE tech_stack IS NOT NULL AND status != 'Rejected'")
        else:
            db_execute(c, 'SELECT tech_stack FROM teams WHERE tech_stack IS NOT NULL AND status != "Rejected"')
        rows = c.fetchall()
        tech_map = {}
        for row in rows:
            stack = row['tech_stack']
            if not stack: continue
            for tech in stack.split(','):
                tech = tech.strip().capitalize()
                if not tech: continue
                tech_map[tech] = tech_map.get(tech, 0) + 1
        
        # Sort and take top 10
        sorted_pulse = sorted(tech_map.items(), key=lambda x: x[1], reverse=True)[:10]
        return jsonify([{'name': k, 'count': v} for k, v in sorted_pulse])
    finally:
        close_db(conn)

@app.route('/api/stats', methods=['GET'])
def get_public_stats():
    conn, c = get_db()
    try:
        # Total Teams
        db_execute(c, 'SELECT COUNT(*) as count FROM teams')
        teams = c.fetchone()['count']
        
        # Total Hackers
        db_execute(c, 'SELECT COUNT(*) as count FROM members')
        hackers = c.fetchone()['count']
        
        # Check-ins
        db_execute(c, 'SELECT COUNT(*) as count FROM teams WHERE checked_in = ?', (True,))
        checkins = c.fetchone()['count']
        
        # Mentors online
        db_execute(c, 'SELECT COUNT(*) as count FROM mentors WHERE available = ?', (True,))
        mentors = c.fetchone()['count']
        
        return jsonify({
            'teams': teams,
            'hackers': hackers,
            'checkins': checkins,
            'mentors': mentors
        })
    finally:
        close_db(conn)

# --- SKILL-BASED TEAM FORMATION ---
@app.route('/api/seekers', methods=['GET', 'POST'])
def handle_hacker_seekers():
    conn, c = get_db()
    try:
        if request.method == 'GET':
            db_execute(c, 'SELECT * FROM hacker_seekers ORDER BY created_at DESC')
            res = [dict(row) for row in c.fetchall()]
            return jsonify(res)
        elif request.method == 'POST':
            data = request.json
            db_execute(c, 'INSERT INTO hacker_seekers (name, email, skills, bio, linkedin, github, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                      (data.get('name'), data.get('email'), data.get('skills'), data.get('bio'), data.get('linkedin'), data.get('github'), datetime.datetime.now().isoformat()))
            conn.commit()
            add_activity(f"Hacker {data.get('name')} is looking for a team!", "info")
            return jsonify({'success': True})
    finally:
        close_db(conn)

@app.route('/api/team/activity', methods=['GET'])
def get_team_activity():
    team_id = session.get('team_id')
    if not team_id: return jsonify({'error': 'Unauthorized'}), 401
    
    conn, c = get_db()
    try:
        db_execute(c, 'SELECT * FROM activity_feed WHERE team_id = ? ORDER BY created_at DESC', (team_id,))
        feed = [dict(row) for row in c.fetchall()]
        return jsonify(feed)
    finally:
        close_db(conn)

# --- MENTOR MARKETPLACE ---
@app.route('/api/mentors', methods=['GET', 'POST'])
def handle_mentors():
    conn, c = get_db()
    try:
        if request.method == 'GET':
            db_execute(c, 'SELECT * FROM mentors WHERE available = ?', (True,))
            res = [dict(row) for row in c.fetchall()]
            return jsonify(res)
        elif request.method == 'POST':
            # Admin only for adding mentors
            if not session.get('is_admin'): return jsonify({'error': 'Unauthorized'}), 401
            data = request.json
            db_execute(c, 'INSERT INTO mentors (name, expertise, bio, avatar_url) VALUES (?, ?, ?, ?)',
                      (data.get('name'), data.get('expertise'), data.get('bio'), data.get('avatar_url')))
            conn.commit()
            return jsonify({'success': True})
    finally:
        close_db(conn)

# --- TEAM DEV LOGS ---
@app.route('/api/team/devlog', methods=['POST'])
def handle_devlog():
    team_id = session.get('team_id')
    if not team_id: return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    message = data.get('message')
    if not message: return jsonify({'error': 'Message required'}), 400
    if len(message) > 200: return jsonify({'error': 'Message too long'}), 400
    
    add_activity(f"DEVLOG [Team {team_id}]: {message}", "info")
    return jsonify({'success': True})

# --- JUDGE PORTAL ---
@app.route('/api/judge/login', methods=['POST'])
def judge_login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    conn, c = get_db()
    db_execute(c, 'SELECT * FROM judges WHERE username = ?', (username,))
    judge = c.fetchone()
    close_db(conn)
    
    if judge and check_password_hash(judge['password_hash'], password):
        session['judge_id'] = judge['id']
        session['judge_username'] = judge['username']
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Invalid credentials'}), 401

@app.route('/api/judge/logout', methods=['POST'])
def judge_logout():
    session.pop('judge_id', None)
    session.pop('judge_username', None)
    return jsonify({'success': True})

@app.route('/api/judge/check_auth', methods=['GET'])
def judge_check_auth():
    if session.get('judge_id'):
        return jsonify({'authenticated': True, 'username': session.get('judge_username')})
    return jsonify({'authenticated': False}), 401

@app.route('/api/judge/score', methods=['POST'])
def judge_score():
    judge_id = session.get('judge_id')
    if not judge_id: return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    team_id = normalize_team_id(data.get('teamId'))
    inn = data.get('innovation', 0)
    imp = data.get('impact', 0)
    tec = data.get('tech', 0)
    ui = data.get('ui', 0)
    
    total = (float(inn) + float(imp) + float(tec) + float(ui)) / 4.0
    
    conn, c = get_db()
    db_execute(c, 'INSERT INTO judge_scores (judge_id, team_id, innovation, impact, tech, ui, total_score, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
              (judge_id, team_id, inn, imp, tec, ui, total, datetime.datetime.now().isoformat()))
    conn.commit()
    close_db(conn)
    return jsonify({'success': True})

# --- ADVANCED ANALYTICS ---
@app.route('/api/admin/analytics', methods=['GET'])
@admin_required
def get_analytics():
    conn, c = get_db()
    
    # Check-in velocity (by hour)
    if DATABASE_URL and HAS_POSTGRES:
        db_execute(c, "SELECT TO_CHAR(created_at::TIMESTAMP, 'HH24') as hour, COUNT(*) as count FROM teams WHERE checked_in = ? GROUP BY hour", (True,))
    else:
        db_execute(c, "SELECT STRFTIME('%H', created_at) as hour, COUNT(*) as count FROM teams WHERE checked_in = ? GROUP BY hour", (True,))
    checkin_velocity = [dict(row) for row in c.fetchall()]
    
    # Help Request Heatmap (by topic)
    db_execute(c, "SELECT topic, COUNT(*) as count FROM help_requests GROUP BY topic")
    help_heatmap = [dict(row) for row in c.fetchall()]
    
    # College-wise participation
    db_execute(c, "SELECT college, COUNT(*) as count FROM teams GROUP BY college")
    college_stats = [dict(row) for row in c.fetchall()]
    
    close_db(conn)
    return jsonify({
        'checkinVelocity': checkin_velocity,
        'helpHeatmap': help_heatmap,
        'collegeStats': college_stats
    })

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    team_name = data.get('teamName')
    college = data.get('college')
    dept = data.get('dept')
    theme = data.get('theme')
    idea = data.get('idea')
    utr_number = data.get('utrNumber')
    payment_screenshot = data.get('paymentScreenshot')
    members = data.get('members', [])
    
    if not team_name or not college or not members:
        return jsonify({'error': 'Missing required fields'}), 400
        
    reg_id = 'REC1-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    created_at = datetime.datetime.now().isoformat()
    
    conn, c = get_db()
    try:
        db_execute(c, 'INSERT INTO teams (id, team_name, college, dept, theme, idea, created_at, utr_number, payment_screenshot) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', 
                  (reg_id, team_name, college, dept, theme, idea, created_at, utr_number, payment_screenshot))
        
        leader_email = None
        for idx, m in enumerate(members):
            is_leader = 1 if idx == 0 else 0
            if is_leader:
                leader_email = m.get('email')
            db_execute(c, 'INSERT INTO members (team_id, name, year, phone, email, is_leader, avatar_url) VALUES (?, ?, ?, ?, ?, ?, ?)', 
                      (reg_id, m.get('name'), m.get('year'), m.get('phone'), m.get('email'), is_leader, m.get('avatar_url')))
            
        if conn:
            conn.commit()
        add_activity(f"Team {team_name} from {college} has joined RECKON 1.O!", "success")
    except Exception as e:
        if conn:
            conn.rollback()
            close_db(conn)
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            close_db(conn)

    # Send confirmation emails in background to avoid lag
    if members:
        leader_name  = members[0].get('name', 'Team Leader')
        leader_email = members[0].get('email')

        def send_all_emails():
            # Full email with QR + login guide → leader
            if leader_email:
                send_confirmation_email(leader_email, reg_id, team_name, leader_name)

            # Brief welcome email → other members
            for m in members[1:]:
                m_email = m.get('email')
                m_name  = m.get('name', 'Participant')
                if not m_email: continue

                m_subject = f"🎉 You're part of Team {team_name}! — RECKON 1.O Hackathon"
                m_qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=180x180&color=000000&bgcolor=ffffff&data={reg_id}&margin=10"
                
                m_html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0a0f1e;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" bgcolor="#0a0f1e">
    <tr><td align="center" style="padding:40px 20px;">
      <table width="580" cellpadding="0" cellspacing="0" style="max-width:580px;width:100%;background:#0d1426;border-radius:16px;overflow:hidden;border:1px solid #1e2d50;">
        <tr><td style="background:linear-gradient(135deg,#7c3aed,#00d4ff);padding:30px;text-align:center;">
          <h1 style="margin:0;font-size:28px;font-weight:900;color:#fff;letter-spacing:2px;">RECKON 1.O</h1>
          <p style="margin:6px 0 0;font-size:12px;color:rgba(255,255,255,0.8);letter-spacing:3px;text-transform:uppercase;">National Level Hackathon</p>
        </td></tr>
        <tr><td style="padding:28px 32px 0 32px;">
          <p style="margin:0;font-size:19px;font-weight:700;color:#fff;">Welcome to the team, {m_name}! 🚀</p>
          <p style="margin:12px 0 0 0;font-size:14px;color:rgba(255,255,255,0.6);line-height:1.7;">You are now officially a member of <strong style="color:#00d4ff;">{team_name}</strong>. Get ready to build!</p>
        </td></tr>
        <tr><td style="padding:20px 32px 0 32px;">
          <table width="100%" cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,rgba(124,58,237,0.15),rgba(0,212,255,0.1));border:2px solid rgba(0,212,255,0.4);border-radius:12px;">
            <tr><td style="padding:18px;text-align:center;">
              <p style="margin:0 0 6px;font-size:11px;letter-spacing:3px;color:rgba(255,255,255,0.5);text-transform:uppercase;">Team ID</p>
              <p style="margin:0;font-size:30px;font-weight:900;color:#00d4ff;letter-spacing:6px;font-family:'Courier New',monospace;">{reg_id}</p>
            </td></tr>
          </table>
        </td></tr>
        <tr><td style="padding:20px 32px 0 32px;text-align:center;">
          <p style="margin:0 0 10px 0;font-size:12px;color:rgba(255,255,255,0.4);letter-spacing:2px;text-transform:uppercase;">Entry QR Code</p>
          <div style="display:inline-block;background:#fff;padding:10px;border-radius:8px;">
            <img src="{m_qr_url}" alt="QR" width="160" height="160" />
          </div>
        </td></tr>
        <tr><td style="padding:24px 32px 32px 32px;text-align:center;border-top:1px solid rgba(255,255,255,0.07);margin-top:20px;">
          <p style="margin:0;font-size:13px;font-weight:700;color:rgba(255,255,255,0.55);">— The RECKON 1.O Organizing Team</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
                send_universal_email(m_email, m_subject, m_html, f"MEMBER-{m_name}")


        # Remove threading start here; emails will be sent on Admin approval
        # threading.Thread(target=send_all_emails).start()

    return jsonify({'success': True, 'regId': reg_id})


# ── CAPTCHA SYSTEM ───────────────────────────────────────────────────────────
@app.route('/api/get_captcha')
def get_captcha():
    # Simple alphanumeric captcha
    captcha_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    session['captcha_code'] = captcha_code
    return jsonify({'success': True, 'captcha': captcha_code})

@app.route('/api/team/request_login_code', methods=['POST'])
@app.route('/api/team/login', methods=['POST'])
def team_login_route():
    data = request.json
    team_id = normalize_team_id(data.get('teamId'))
    user_captcha = (data.get('captcha') or '').strip().upper()
    
    # ── Security Check: Captcha ──
    stored_captcha = session.get('captcha_code')
    if not user_captcha or user_captcha != stored_captcha:
        return jsonify({'error': 'Invalid CAPTCHA. Please try again.'}), 400
    
    # Clear captcha after use for security
    session.pop('captcha_code', None)
    
    if not team_id:
        return jsonify({'error': 'Team ID required'}), 400
        
    conn, c = get_db()
    db_execute(c, 'SELECT * FROM teams WHERE id = ?', (team_id,))
    team = c.fetchone()
    close_db(conn)
    
    if not team:
        return jsonify({'error': 'Invalid Team ID. Check your registration ID.'}), 404
        
    # Successful direct login
    session['team_id'] = team_id
    add_activity(f"Team {dict(team)['team_name']} logged in via Team ID.", "info")
    return jsonify({'success': True})




@app.route('/api/team/logout', methods=['POST'])
def team_logout():
    session.pop('team_id', None)
    return jsonify({'success': True})

@app.route('/api/team/check_auth', methods=['GET'])
def team_check_auth():
    if session.get('team_id'):
        return jsonify({'authenticated': True})
    return jsonify({'authenticated': False}), 401

@app.route('/api/team/me', methods=['GET'])
def get_my_team():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({'error': 'Unauthorized'}), 401
        
    conn, c = get_db()
    db_execute(c, 'SELECT * FROM teams WHERE id = ?', (team_id,))
    res = c.fetchone()
    team = dict(res or {})
    
    if team:
        db_execute(c, 'SELECT * FROM members WHERE team_id = ?', (team_id,))
        team['members'] = [dict(row) for row in c.fetchall()]
        
    close_db(conn)
    return jsonify(team)

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    user_captcha = (data.get('captcha') or '').strip().upper()
    
    # Validate Captcha
    if not user_captcha or user_captcha != session.get('captcha_code'):
        return jsonify({'success': False, 'error': 'Invalid CAPTCHA. Please try again.'}), 400
    
    # Clear captcha
    session.pop('captcha_code', None)
    
    if username == ADMIN_USERNAME and check_password_hash(get_admin_hash(), password):
        session['is_admin'] = True
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Invalid credentials'}), 401

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('is_admin', None)
    return jsonify({'success': True})

@app.route('/api/admin/check_auth', methods=['GET'])
def check_auth():
    if session.get('is_admin'):
        return jsonify({'authenticated': True})
    return jsonify({'authenticated': False}), 401

@app.route('/api/admin/teams', methods=['GET'])
@admin_required
def get_teams():
    conn, c = get_db()
    try:
        db_execute(c, 'SELECT * FROM teams ORDER BY created_at DESC')
        teams = [dict(row) for row in c.fetchall()]
        
        # FETCH ALL MEMBERS IN ONE QUERY TO AVOID N+1 PERFORMANCE ISSUE
        db_execute(c, 'SELECT * FROM members')
        all_members = [dict(row) for row in c.fetchall()]
        
        # Group by team_id
        from collections import defaultdict
        members_by_team = defaultdict(list)
        for m in all_members:
            members_by_team[m['team_id']].append(m)
            
        for t in teams:
            t.update({'members': members_by_team.get(t['id'], [])})
            
        return jsonify(teams)
    finally:
        close_db(conn)

@app.route('/api/admin/teams/<team_id>', methods=['DELETE'])
@admin_required
def delete_team(team_id):
    conn, c = get_db()
    db_execute(c, 'DELETE FROM teams WHERE id = ?', (team_id,))
    db_execute(c, 'DELETE FROM members WHERE team_id = ?', (team_id,))
    db_execute(c, 'DELETE FROM help_requests WHERE team_id = ?', (team_id,))
    conn.commit()
    close_db(conn)
    return jsonify({'success': True})

@app.route('/api/admin/checkin', methods=['POST'])
@admin_required
def checkin_team():
    data = request.json
    team_id = normalize_team_id(data.get('teamId'))
    checkin_type = data.get('type', 'morning') # morning, lunch, snack
    
    if not team_id:
        return jsonify({'error': 'Team ID is required'}), 400
    
    # Standard boolean constants for SQLite/Postgres compatibility
    ST_TRUE = True
    ST_FALSE = False

    conn, c = get_db()
    try:
        # Check if team exists
        db_execute(c, 'SELECT * FROM teams WHERE id = ?', (team_id,))
        res = c.fetchone()
        team = dict(res or {})
        
        if not team:
            return jsonify({'error': 'Invalid Team ID. Team not found.'}), 404
            
        column = 'checked_in'
        ts_column = 'morning_at'
        if checkin_type == 'lunch':    column = 'lunch_checkin';    ts_column = 'lunch_at'
        if checkin_type == 'snack':    column = 'snack_checkin';    ts_column = 'snack_at'
        if checkin_type == 'checkout': column = 'checked_out';      ts_column = 'checkout_at'
            
        # Determine strict status value based on column name & DB type
        status_val = ST_TRUE
        if column == 'checked_out':
            status_val = 1 # Force integer for checked_out column (int4 in Supabase)

        if checkin_type != 'checkout' and team.get(column) in [ST_TRUE, 1]:
            return jsonify({'error': f'Team {team["team_name"]} ({team_id}) is already checked in for {checkin_type}.'}), 400
        
        if checkin_type == 'checkout' and team.get(column) in [ST_TRUE, 1]:
             return jsonify({'error': f'Team {team["team_name"]} ({team_id}) is already checked out.'}), 400

        # Mark with appropriate status AND record exact timestamp
        now_iso = datetime.datetime.now().isoformat()
        try:
            db_execute(c, f'UPDATE teams SET {column} = ?, {ts_column} = ? WHERE id = ?', (status_val, now_iso, team_id))
            conn.commit()
        except Exception as e:
            if conn: conn.rollback()
            print(f"Checkout/Checkin Error: {e}")
            return jsonify({'error': f'Database error during {checkin_type}: {str(e)}'}), 500
    finally:
        close_db(conn)
    
    # Fetch updated team details and members for the front-end pop-up
    conn, c = get_db()
    try:
        db_execute(c, 'SELECT * FROM teams WHERE id = ?', (team_id,))
        team_data = dict(c.fetchone() or {})
        
        db_execute(c, 'SELECT name, avatar_url, is_leader FROM members WHERE team_id = ?', (team_id,))
        members = [dict(m) for m in c.fetchall()]
        team_data['members'] = members
    finally:
        close_db(conn)

    if checkin_type == 'checkout':
        add_activity(f"Team {team['team_name']} has checked out of the venue.", "warning", team_id)
    else:
        add_activity(f"Team {team['team_name']} checked in for {checkin_type}!", "info", team_id)
    return jsonify({
        'success': True, 
        'team_name': team['team_name'],
        'team_details': team_data
    })

@app.route('/api/team/checkin_history', methods=['GET'])
def get_team_checkin_history():
    """Returns the complete check-in history for the logged-in team with exact timestamps."""
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn, c = get_db()
    try:
        db_execute(c, '''
            SELECT checked_in, lunch_checkin, snack_checkin, checked_out,
                   morning_at, lunch_at, snack_at, checkout_at
            FROM teams WHERE id = ?
        ''', (team_id,))
        row = c.fetchone()
        if not row:
            return jsonify({'error': 'Team not found'}), 404
        
        team = dict(row)
        history = []
        
        def fmt(iso):
            """Format ISO timestamp to readable string."""
            if not iso: return None
            try:
                dt = datetime.datetime.fromisoformat(iso)
                return {
                    'iso': iso,
                    'date': dt.strftime('%d %b %Y'),
                    'time': dt.strftime('%I:%M:%S %p'),
                    'full': dt.strftime('%d %b %Y, %I:%M %p')
                }
            except:
                return {'iso': iso, 'date': '', 'time': iso, 'full': iso}
        
        if team.get('checked_in') in [True, 1]:
            history.append({'type': 'morning',  'label': 'Morning Check-In',  'icon': '☀️', 'color': '#00d4ff', 'time': fmt(team.get('morning_at'))})
        if team.get('lunch_checkin') in [True, 1]:
            history.append({'type': 'lunch',    'label': 'Lunch Check-In',    'icon': '🥪', 'color': '#00ff66', 'time': fmt(team.get('lunch_at'))})
        if team.get('snack_checkin') in [True, 1]:
            history.append({'type': 'snack',    'label': 'Snack Check-In',    'icon': '🌙', 'color': '#b44dff', 'time': fmt(team.get('snack_at'))})
        if team.get('checked_out') in [True, 1]:
            history.append({'type': 'checkout', 'label': 'Checkout / Exit',   'icon': '🚪', 'color': '#ff2d78', 'time': fmt(team.get('checkout_at'))})
        
        return jsonify({
            'history': history,
            'total': len(history),
            'all_done': len(history) == 4
        })
    finally:
        close_db(conn)

@app.route('/api/admin/reset_checkins', methods=['POST'])
@admin_required
def reset_checkins():
    print(f"DEBUG: Resetting all check-ins...", flush=True)
    conn, c = get_db()
    try:
        db_execute(c, 'UPDATE teams SET checked_in = ?, lunch_checkin = ?, snack_checkin = ?, checked_out = ?, morning_at = NULL, lunch_at = NULL, snack_at = NULL, checkout_at = NULL', (False, False, False, 0))
        conn.commit()
        print(f"DEBUG: All check-ins updated successfully.", flush=True)
    except Exception as e:
        print(f"DEBUG: Reset error: {e}", flush=True)
        return jsonify({'error': str(e)}), 500
    finally:
        close_db(conn)
    add_activity("All team check-in statuses have been reset by administrator.", "warning")
    return jsonify({'success': True, 'message': 'All check-ins have been reset.'})

@app.route('/api/announcements', methods=['GET'])
def get_announcements():
    conn, c = get_db()
    try:
        # Fetching only active announcements, limited to the latest 5 for the ticker
        db_execute(c, 'SELECT * FROM announcements WHERE active = ? ORDER BY created_at DESC LIMIT 5', (1,))
        announcements = [dict(row) for row in c.fetchall()]
        return jsonify(announcements)
    finally:
        close_db(conn)

@app.route('/api/admin/announcements', methods=['GET', 'POST'])
@admin_required
def admin_announcements():
    if request.method == 'GET':
        conn, c = get_db()
        db_execute(c, 'SELECT * FROM announcements ORDER BY created_at DESC')
        announcements = [dict(row) for row in c.fetchall()]
        close_db(conn)
        return jsonify(announcements)
    elif request.method == 'POST':
        data = request.json
        message = data.get('message')
        if not message:
            return jsonify({'error': 'Message required'}), 400
        conn, c = get_db()
        created_at = datetime.datetime.now().isoformat()
        db_execute(c, 'INSERT INTO announcements (message, created_at, active) VALUES (?, ?, ?)', 
                  (message, created_at, 1))
        conn.commit()
        
        # Get the ID of the inserted announcement
        if DATABASE_URL and HAS_POSTGRES:
            db_execute(c, "SELECT currval(pg_get_serial_sequence('announcements','id'))")
            ann_id = c.fetchone()['currval']
        else:
            ann_id = c.lastrowid
            
        close_db(conn)
        
        # Realtime broadcast
        emit_announcement({'id': ann_id, 'message': message, 'created_at': created_at})
        return jsonify({'success': True})

@app.route('/api/admin/announcements/<int:id>', methods=['DELETE'])
@admin_required
def delete_announcement(id):
    conn, c = get_db()
    db_execute(c, 'DELETE FROM announcements WHERE id = ?', (id,))
    conn.commit()
    close_db(conn)
    return jsonify({'success': True})

@app.route('/api/help', methods=['POST'])
def request_help():
    data = request.json
    team_id = normalize_team_id(data.get('teamId'))
    location = data.get('location')
    topic = data.get('topic')
    screenshot = data.get('screenshot') # base64 string
    is_emergency = 1 if data.get('isEmergency') else 0
    
    if not team_id or not location or not topic:
        return jsonify({'error': 'Missing fields'}), 400
        
    conn, c = get_db()
    try:
        db_execute(c, 'SELECT id FROM teams WHERE id = ?', (team_id,))
        if not c.fetchone():
            close_db(conn)
            return jsonify({'error': 'Invalid Team ID'}), 404
            
        # ══ MENTOR EXPERTISE MATCHING ══
        suggested = "General Staff"
        if DATABASE_URL and HAS_POSTGRES:
            db_execute(c, 'SELECT name, expertise FROM mentors WHERE available = TRUE')
        else:
            db_execute(c, 'SELECT name, expertise FROM mentors WHERE available = 1')
        available_mentors = c.fetchall()
        
        # Simple string matching logic
        best_match = None
        topic_lower = topic.lower()
        for m in available_mentors:
            exp = m['expertise'].lower()
            if any(term in exp or term in topic_lower for term in ['frontend', 'ui', 'ux', 'css', 'react']) and ('frontend' in topic_lower or 'ui' in topic_lower):
                best_match = m['name']
                break
            if any(term in exp or term in topic_lower for term in ['backend', 'database', 'api', 'scaling', 'python', 'go']) and ('backend' in topic_lower or 'database' in topic_lower or 'api' in topic_lower):
                best_match = m['name']
                break
            if any(term in exp or term in topic_lower for term in ['ai', 'machine learning', 'data science']) and ('ai' in topic_lower or 'ml' in topic_lower):
                best_match = m['name']
                break

        if best_match:
            suggested = best_match

        created_at = datetime.datetime.now().isoformat()
        db_execute(c, '''INSERT INTO help_requests 
                   (team_id, location, topic, status, screenshot, is_emergency, suggested_mentor, created_at) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                 (team_id, location, topic, 'Pending', screenshot, is_emergency, suggested, created_at))
        
        # Get team name for the realtime message
        c = db_execute(c, 'SELECT team_name FROM teams WHERE id = ?', (team_id,))
        team_row = c.fetchone()
        team_name = team_id
        if team_row:
            if isinstance(team_row, dict):
                team_name = team_row.get('team_name', team_id)
            else:
                team_name = team_row[0]
        
        conn.commit()
        
        # Realtime broadcast
        emit_help_request({
            'team_id': team_id,
            'team_name': team_name,
            'location': location,
            'topic': topic,
            'status': 'Pending',
            'is_emergency': is_emergency,
            'suggested_mentor': suggested,
            'screenshot': screenshot,
            'created_at': created_at
        })

        if is_emergency:
            add_activity(f"🚨 EMERGENCY: Team {team_name} needs immediate help at {location}!", "error")
        else:
            add_activity(f"Help Request: Team {team_name} ({topic})", "info")

    except Exception as e:
        if conn: conn.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if conn: close_db(conn)
    return jsonify({'success': True})

@app.route('/api/help/stats', methods=['GET'])
def get_help_stats():
    conn, c = get_db()
    if DATABASE_URL and HAS_POSTGRES:
        db_execute(c, 'SELECT COUNT(*) as count FROM mentors WHERE available = TRUE')
    else:
        db_execute(c, 'SELECT COUNT(*) as count FROM mentors WHERE available = 1')
    res = c.fetchone()
    mentors_online = res['count'] if res else 0
    close_db(conn)
    return jsonify({'mentorsOnline': mentors_online})

# --- ADMIN MENTOR MANAGEMENT ---
@app.route('/api/admin/mentors', methods=['GET'])
@admin_required
def admin_get_mentors():
    conn, c = get_db()
    db_execute(c, 'SELECT * FROM mentors ORDER BY name ASC')
    mentors = [dict(row) for row in c.fetchall()]
    close_db(conn)
    return jsonify(mentors)

@app.route('/api/admin/mentors/<int:id>', methods=['DELETE'])
@admin_required
def admin_delete_mentor(id):
    conn, c = get_db()
    db_execute(c, 'DELETE FROM mentors WHERE id = ?', (id,))
    conn.commit()
    close_db(conn)
    return jsonify({'success': True})

@app.route('/api/admin/mentors/<int:id>/toggle', methods=['POST'])
@admin_required
def admin_toggle_mentor(id):
    conn, c = get_db()
    db_execute(c, 'SELECT available FROM mentors WHERE id = ?', (id,))
    m = c.fetchone()
    if m:
        new_val = 0 if m['available'] else 1
        db_execute(c, 'UPDATE mentors SET available = ? WHERE id = ?', (new_val, id))
        conn.commit()
    close_db(conn)
    return jsonify({'success': True})

@app.route('/api/admin/help', methods=['GET'])
@admin_required
def get_help_requests():
    conn, c = get_db()
    db_execute(c, '''
        SELECT hr.*, t.team_name 
        FROM help_requests hr 
        LEFT JOIN teams t ON hr.team_id = t.id 
        ORDER BY hr.created_at DESC
    ''')
    res = [dict(row) for row in c.fetchall()]
    close_db(conn)
    return jsonify(res)

@app.route('/api/admin/help/resolve', methods=['POST'])
@admin_required
def resolve_help_request():
    data = request.json
    hr_id = data.get('id')
    status = data.get('status')
    badge_name = data.get('badge_name')
    mentor_name = data.get('mentor_name', 'Mentor')
    comment = data.get('comment', '')
    
    conn, c = get_db()
    # Update status
    db_execute(c, 'UPDATE help_requests SET status=? WHERE id=?', (status, hr_id))
    
    # Award Badge if selected
    if badge_name and status == 'Resolved':
        db_execute(c, 'SELECT team_id FROM help_requests WHERE id=?', (hr_id,))
        hr = c.fetchone()
        if hr:
            tid = hr['team_id'] if isinstance(hr, dict) else hr[0]
            icon = "🏆"
            if "Code" in badge_name: icon = "💻"
            if "Database" in badge_name: icon = "🗄️"
            if "Design" in badge_name: icon = "🎨"
            if "Speed" in badge_name: icon = "⚡"
            
            ts = datetime.datetime.now().isoformat()
            db_execute(c, 'INSERT INTO team_badges (team_id, badge_name, badge_icon, mentor_name, comment, created_at) VALUES (?, ?, ?, ?, ?, ?)',
                      (tid, badge_name, icon, mentor_name, comment, ts))
            db_execute(c, 'SELECT team_name FROM teams WHERE id=?', (tid,))
            team = c.fetchone()
            tn = team['team_name'] if isinstance(team, dict) else team[0]
            add_activity(f"Mentor {mentor_name} endorsed Team {tn} with '{badge_name}'!", "success")
            socketio.emit('new_badge', {'team_id': tid, 'badge': badge_name, 'icon': icon})

    conn.commit()
    close_db(conn)
    socketio.emit('help_status_update', {'id': hr_id, 'status': status})
    return jsonify({'success': True})


@app.route('/api/team/badges', methods=['GET'])
def get_team_badges():
    tid = session.get('team_id')
    if not tid: return jsonify({'error': 'Unauthorized'}), 401
    conn, c = get_db()
    db_execute(c, 'SELECT * FROM team_badges WHERE team_id = ? ORDER BY created_at DESC', (tid,))
    badges = [dict(row) for row in c.fetchall()]
    close_db(conn)
    return jsonify(badges)

def process_imported_rows(data_rows, source_name):
    if not data_rows:
        return jsonify({'success': False, 'error': 'No data rows found in the file. Check your file content.'}), 400

    conn, c = get_db()
    teams_added = 0
    members_added = 0
    
    # Log detected headers for first row to help debug
    first_row_keys = list(data_rows[0].keys())
    print(f"[DEBUG] Import Headers Detected: {first_row_keys}")

    for row in data_rows:
        # Clean headers: lowercase, no spaces, no special chars
        header_map = {str(k).lower().replace(' ', '').replace('_', ''): k for k in row.keys() if k is not None}
        
        def get_val(possible_keys):
            for k in possible_keys:
                clean_k = k.lower().replace(' ', '').replace('_', '')
                real_key = header_map.get(clean_k)
                if real_key:
                    val = row.get(real_key)
                    if val is not None:
                        return str(val).strip()
            return ''

        # Try common variations of headers
        team_id = get_val(['RegID', 'TeamID', 'ID', 'RegistrationID']).upper()
        if not team_id: continue
        
        # Ensure consistency: add prefix if missing
        if not team_id.startswith('REC1-'):
            team_id = 'REC1-' + team_id
        
        team_name = get_val(['TeamName', 'Name', 'GroupName', 'Teamname']) or f"Team {team_id}"
        college = get_val(['CollegeName', 'College', 'University']) or "RECC"
        dept = get_val(['Department', 'Dept', 'Branch'])
        theme = get_val(['ProjectDomain', 'Theme', 'Domain', 'Category'])
        
        # Leader Info
        leader_name = get_val(['LeaderName', 'TeamLeader', 'Leader'])
        leader_email = get_val(['Email', 'EmailID', 'UserEmail'])
        leader_phone = get_val(['PhoneNumber', 'Phone', 'Mobile', 'Contact'])
        
        # Payment Info
        utr = get_val(['UTRNumber', 'UTR', 'TransactionID'])
        payment_proof = get_val(['PaymentProofURL', 'PaymentScreenshot', 'Proof'])
        
        # Members Info (Column with multiple members)
        members_raw = get_val(['Members', 'TeamMembers', 'OtherMembers'])

        # Check if team already exists
        db_execute(c, 'SELECT id FROM teams WHERE id = ?', (team_id,))
        if not c.fetchone():
            created_at = datetime.datetime.now().isoformat()
            db_execute(c, '''
                INSERT INTO teams (id, team_name, college, dept, theme, utr_number, payment_screenshot, created_at) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (team_id, team_name, college, dept, theme, utr, payment_proof, created_at))
            teams_added += 1
        
        # 1. Add Leader as a member
        if leader_name:
            db_execute(c, 'INSERT INTO members (team_id, name, phone, email, is_leader) VALUES (?, ?, ?, ?, 1)',
                      (team_id, leader_name, leader_phone, leader_email))
            members_added += 1
        
        # 2. Parse and add other members
        if members_raw:
            # Split by newline, comma, or semi-colon
            m_list = []
            import re
            # Split and clean up
            potential_members = re.split(r'[\n,;]', str(members_raw))
            for m in potential_members:
                m = m.strip()
                if not m: continue
                
                # Remove leading numbers like "1. ", "2) ", "1-"
                m = re.sub(r'^[\d\.\-\)\s]+', '', m).strip()
                
                if m and m.lower() != (leader_name or "").lower():
                    m_list.append(m)
            
            for member_name in m_list:
                # Check if already added (simple name check within team)
                db_execute(c, 'SELECT id FROM members WHERE team_id = ? AND LOWER(name) = ?', (team_id, member_name.lower()))
                if not c.fetchone():
                    db_execute(c, 'INSERT INTO members (team_id, name, is_leader) VALUES (?, ?, 0)',
                              (team_id, member_name))
                    members_added += 1
    
    conn.commit()
    close_db(conn)
    
    add_activity(f"Admin imported {teams_added} teams and {members_added} students via {source_name}.", "info")
    return jsonify({
        'success': True, 
        'message': f'Successfully imported {teams_added} teams and {members_added} students.'
    })


@app.route('/api/admin/import_csv', methods=['POST'])
@admin_required
def admin_import_csv():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400
    
    filename = file.filename.lower()
    
    try:
        data_rows = []
        if filename.endswith('.csv'):
            # Use 'utf-8-sig' to handle files with BOM (common in Excel-exported CSVs)
            content = file.stream.read().decode("utf-8-sig")
            stream = io.StringIO(content, newline=None)
            csv_input = csv.DictReader(stream)
            data_rows = list(csv_input)
        elif filename.endswith('.xlsx'):
            if not openpyxl:
                return jsonify({'success': False, 'error': 'Excel support (openpyxl) not installed on server'}), 500
            
            # Load workbook from stream
            wb = openpyxl.load_workbook(file)
            sheet = wb.worksheets[0] # Take first sheet
            rows = list(sheet.rows)
            if not rows or len(rows) < 2:
                return jsonify({'success': False, 'error': 'Excel file is empty or has no data rows'}), 400
            
            headers = [str(cell.value).strip() if cell.value is not None else None for cell in rows[0]]
            for row in rows[1:]:
                row_data = {}
                is_empty_row = True
                for idx, cell in enumerate(row):
                    if idx < len(headers) and headers[idx] is not None:
                        val = cell.value
                        row_data[headers[idx]] = val
                        if val is not None and str(val).strip() != '':
                            is_empty_row = False
                if not is_empty_row:
                    data_rows.append(row_data)
        else:
            return jsonify({'success': False, 'error': 'Unsupported file format. Use CSV or XLSX.'}), 400

        file_type = "Excel" if filename.endswith('.xlsx') else "CSV"
        return process_imported_rows(data_rows, file_type)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Import failed: {str(e)}'}), 500

@app.route('/api/admin/import_csv_url', methods=['POST'])
@admin_required
def admin_import_csv_url():
    data = request.json
    url = data.get('url')
    if not url:
        return jsonify({'success': False, 'error': 'No URL provided'}), 400

    try:
        import urllib.request
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            content = response.read().decode('utf-8-sig')

        stream = io.StringIO(content, newline=None)
        csv_input = csv.DictReader(stream)
        data_rows = list(csv_input)

        return process_imported_rows(data_rows, "URL")
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Failed to fetch or parse URL: {str(e)}'}), 500

@app.route('/api/admin/send_email', methods=['POST'])
@admin_required
def send_custom_email():
    data = request.json
    to_email = data.get('to_email')
    subject  = data.get('subject')
    body     = data.get('body')

    if not to_email or not subject or not body:
        return jsonify({'success': False, 'error': 'Missing fields'}), 400

    # Use the universal sender to handle SMTP blocks and API fallbacks
    res = send_universal_email(to_email, subject, body, "ADMIN-CUSTOM")
    
    if res is True:
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': f'Failed: {res}'}), 500

@app.route('/api/team/project', methods=['POST'])
def submit_project():
    if not session.get('team_id'): return jsonify({'error': 'Unauthorized'}), 401
    data = request.json
    team_id = session.get('team_id')
    github = data.get('github_link')
    demo = data.get('demo_link')
    tech = data.get('tech_stack')
    title = data.get('project_title')
    desc = data.get('project_desc')

    conn, c = get_db()
    db_execute(c, 'UPDATE teams SET github_link=?, demo_link=?, tech_stack=?, project_title=?, project_desc=? WHERE id=?', (github, demo, tech, title, desc, team_id))
    conn.commit()
    close_db(conn)
    
    add_activity(f"Team {team_id} just submitted their project: {title}!", "success")
    emit_leaderboard_update()
    return jsonify({'success': True})

@app.route('/api/projects', methods=['GET'])
def get_projects():
    conn, c = get_db()
    db_execute(c, 'SELECT * FROM teams WHERE project_title IS NOT NULL ORDER BY upvotes DESC')
    projects = [dict(row) for row in c.fetchall()]
    close_db(conn)
    return jsonify(projects)

@app.route('/api/projects/<team_id>/upvote', methods=['POST'])
def upvote_project(team_id):
    team_id = normalize_team_id(team_id)
    conn, c = get_db()
    db_execute(c, 'UPDATE teams SET upvotes = upvotes + 1 WHERE id=?', (team_id,))
    conn.commit()
    close_db(conn)
    emit_leaderboard_update()
    return jsonify({'success': True})

@app.route('/api/admin/projects/<team_id>/score', methods=['POST'])
@admin_required
def score_project(team_id):
    team_id = normalize_team_id(team_id)
    data = request.json
    inn = data.get('innovation', 0)
    ui = data.get('ui', 0)
    tech = data.get('tech', 0)
    conn, c = get_db()
    db_execute(c, 'UPDATE teams SET innovation_score=?, ui_score=?, tech_score=? WHERE id=?', (inn, ui, tech, team_id))
    conn.commit()
    close_db(conn)
    emit_leaderboard_update()
    return jsonify({'success': True})

@app.route('/api/team/members/<int:member_id>', methods=['PATCH'])
def update_member(member_id):
    if not session.get('team_id'): return jsonify({'error': 'Unauthorized'}), 401
    team_id = session.get('team_id')
    data = request.json
    
    conn, c = get_db()
    db_execute(c, 'SELECT team_id FROM members WHERE id=?', (member_id,))
    res = c.fetchone()
    if not res:
        close_db(conn)
        return jsonify({'error': 'Member not found'}), 404
        
    # Handle dict (Postgres) or tuple (SQLite)
    m_team_id = res['team_id'] if isinstance(res, dict) else res[0]
    
    if m_team_id != team_id:
        close_db(conn)
        return jsonify({'error': 'Unauthorized'}), 401

    if 'avatar_url' in data: db_execute(c, 'UPDATE members SET avatar_url=? WHERE id=?', (data['avatar_url'], member_id))
    if 'linkedin' in data: db_execute(c, 'UPDATE members SET linkedin=? WHERE id=?', (data['linkedin'], member_id))
    if 'github' in data: db_execute(c, 'UPDATE members SET github=? WHERE id=?', (data['github'], member_id))
    if 'name' in data: db_execute(c, 'UPDATE members SET name=? WHERE id=?', (data['name'], member_id))
    if 'email' in data: db_execute(c, 'UPDATE members SET email=? WHERE id=?', (data['email'], member_id))
    if 'phone' in data: db_execute(c, 'UPDATE members SET phone=? WHERE id=?', (data['phone'], member_id))
    
    return jsonify({'success': True})

@app.route('/api/team/update', methods=['PATCH'])
def update_team_details():
    if not session.get('team_id'): return jsonify({'error': 'Unauthorized'}), 401
    team_id = session.get('team_id')
    data = request.json
    
    conn, c = get_db()
    if 'team_name' in data:
        db_execute(c, 'UPDATE teams SET team_name=? WHERE id=?', (data['team_name'], team_id))
    
    conn.commit()
    close_db(conn)
    return jsonify({'success': True})

@app.route('/api/team/help', methods=['GET'])
def team_help_requests():
    if not session.get('team_id'): return jsonify({'error': 'Unauthorized'}), 401
    
    conn, c = get_db()
    db_execute(c, '''
        SELECT * 
        FROM help_requests 
        WHERE team_id = ? 
        ORDER BY created_at DESC
    ''', (session.get('team_id'),))
    requests = [dict(row) for row in c.fetchall()]
    close_db(conn)
    return jsonify(requests)

@app.route('/api/chat', methods=['GET'])
def get_chat():
    conn, c = get_db()
    db_execute(c, 'SELECT * FROM chat_messages ORDER BY created_at ASC LIMIT 200')
    messages = [dict(row) for row in c.fetchall()]
    close_db(conn)
    return jsonify(messages)

@app.route('/api/chat', methods=['POST'])
def post_chat():
    if not session.get('team_id') and not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    message = data.get('message')
    if not message: return jsonify({'error': 'Empty message'}), 400
    
    is_admin_flag = session.get('is_admin', False)
    team_id = session.get('team_id')
    
    conn, c = get_db()
    
    sender_name = "Admin"
    avatar_url = "logo.jpg"
    
    if not is_admin_flag and team_id:
        db_execute(c, 'SELECT team_name FROM teams WHERE id = ?', (team_id,))
        team_res = c.fetchone()
        if not team_res:
            close_db(conn)
            return jsonify({'error': 'Team not found'}), 404
        sender_name = team_res['team_name'] if isinstance(team_res, dict) else team_res[0]
        
        db_execute(c, 'SELECT avatar_url FROM members WHERE team_id = ? AND is_leader = ?', (team_id, 1))
        lead_res = c.fetchone()
        if lead_res:
            a_url = lead_res['avatar_url'] if isinstance(lead_res, dict) else lead_res[0]
            if a_url and a_url != 'null': avatar_url = a_url
            else: avatar_url = ""
    
    created_at = datetime.datetime.now().isoformat()
    db_execute(c, 'INSERT INTO chat_messages (team_id, sender_name, avatar_url, is_admin, message, created_at) VALUES (?, ?, ?, ?, ?, ?)',
              (team_id if team_id else "ADMIN", sender_name, avatar_url, True if is_admin_flag else False, message, created_at))
    conn.commit()
    close_db(conn)
    
    emit_chat_message({
        'team_id': team_id if team_id else "ADMIN",
        'sender_name': sender_name,
        'avatar_url': avatar_url,
        'is_admin': True if is_admin_flag else False,
        'message': message,
        'created_at': created_at
    })
    return jsonify({'success': True})



# Initialize DB before starting (ensures tables exist in production/Gunicorn)
init_db()

@app.route('/api/admin/tech_pulse', methods=['GET'])
def get_tech_pulse_admin():
    if not session.get('is_admin'): return jsonify({'error': 'Unauthorized'}), 401
    conn, c = get_db()
    try:
        db_execute(c, 'SELECT tech_stack FROM teams WHERE tech_stack IS NOT NULL')
        rows = c.fetchall()
        
        pulse = {}
        for row in rows:
            s = row['tech_stack'] if isinstance(row, dict) else row[0]
            if not s: continue
            # Assume tech_stack is comma or space separated
            techs = [t.strip().lower() for t in s.replace(',', ' ').split() if len(t.strip()) > 1]
            for t in techs:
                pulse[t] = pulse.get(t, 0) + 1
        
        # Sort and take top 10
        sorted_pulse = sorted(pulse.items(), key=lambda x: x[1], reverse=True)[:10]
        return jsonify(dict(sorted_pulse))
    finally:
        close_db(conn)


# ═══════════════════════════════════════════════════════
#  ANONYMOUS POLLING  ─ routes
# ═══════════════════════════════════════════════════════

@app.route('/api/polls', methods=['GET'])
def get_polls():
    conn, c = get_db()
    try:
        db_execute(c, "SELECT * FROM polls WHERE active = ? ORDER BY created_at DESC", (1,))
        polls = [dict(r) for r in c.fetchall()]
        result = []
        for poll in polls:
            import json as _json
            options = _json.loads(poll['options']) if isinstance(poll['options'], str) else poll['options']
            # Fetch vote counts per option
            db_execute(c, "SELECT option_index, COUNT(*) as cnt FROM poll_votes WHERE poll_id = ? GROUP BY option_index", (poll['id'],))
            votes_raw = c.fetchall()
            vote_map = {r['option_index'] if isinstance(r, dict) else r[0]: r['cnt'] if isinstance(r, dict) else r[1] for r in votes_raw}
            total_votes = sum(vote_map.values())
            options_with_votes = [{'text': opt, 'votes': vote_map.get(i, 0)} for i, opt in enumerate(options)]
            result.append({
                'id': poll['id'],
                'question': poll['question'],
                'options': options_with_votes,
                'total_votes': total_votes,
                'active': poll['active'],
                'created_at': poll['created_at'],
            })
        return jsonify(result)
    finally:
        close_db(conn)

@app.route('/api/polls/vote', methods=['POST'])
def vote_poll():
    import json as _json, hashlib
    data = request.json or {}
    poll_id = data.get('poll_id')
    option_index = data.get('option_index')
    if poll_id is None or option_index is None:
        return jsonify({'error': 'Missing fields'}), 400

    # Deduplicate by hashed IP + poll_id
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown').split(',')[0].strip()
    voter_hash = hashlib.sha256(f"{ip}_{poll_id}".encode()).hexdigest()

    conn, c = get_db()
    try:
        # Check already voted
        db_execute(c, "SELECT id FROM poll_votes WHERE poll_id = ? AND voter_hash = ?", (poll_id, voter_hash))
        if c.fetchone():
            return jsonify({'error': 'Already voted'}), 409

        created_at = datetime.datetime.now().isoformat()
        db_execute(c, "INSERT INTO poll_votes (poll_id, option_index, voter_hash, created_at) VALUES (?, ?, ?, ?)",
                   (poll_id, option_index, voter_hash, created_at))
        conn.commit()
        socketio.emit('poll_update', {'poll_id': poll_id})
        return jsonify({'success': True})
    finally:
        close_db(conn)

@app.route('/api/admin/polls', methods=['POST'])
@admin_required
def create_poll():
    import json as _json
    data = request.json or {}
    question = data.get('question', '').strip()
    options = data.get('options', [])
    if not question or len(options) < 2:
        return jsonify({'error': 'Need question and at least 2 options'}), 400

    created_at = datetime.datetime.now().isoformat()
    conn, c = get_db()
    try:
        db_execute(c, "INSERT INTO polls (question, options, active, created_at) VALUES (?, ?, ?, ?)",
                   (question, _json.dumps(options), 1, created_at))
        conn.commit()
        socketio.emit('new_poll', {})
        return jsonify({'success': True})
    finally:
        close_db(conn)

@app.route('/api/admin/polls/<int:poll_id>/close', methods=['POST'])
@admin_required
def close_poll(poll_id):
    conn, c = get_db()
    try:
        db_execute(c, "UPDATE polls SET active = ? WHERE id = ?", (0, poll_id))
        conn.commit()
        socketio.emit('poll_update', {'poll_id': poll_id})
        return jsonify({'success': True})
    finally:
        close_db(conn)

@app.route('/api/admin/polls/<int:poll_id>', methods=['DELETE'])
@admin_required
def delete_poll(poll_id):
    conn, c = get_db()
    try:
        db_execute(c, "DELETE FROM poll_votes WHERE poll_id = ?", (poll_id,))
        db_execute(c, "DELETE FROM polls WHERE id = ?", (poll_id,))
        conn.commit()
        socketio.emit('poll_update', {'poll_id': poll_id})
        return jsonify({'success': True})
    finally:
        close_db(conn)

# ═══════════════════════════════════════════════════════
#  PHOTO WALL  ─ routes
# ═══════════════════════════════════════════════════════

@app.route('/api/photos', methods=['GET'])
def get_photos():
    conn, c = get_db()
    try:
        db_execute(c, "SELECT * FROM gallery_photos WHERE approved = ? ORDER BY created_at DESC LIMIT 100", (1,))
        photos = [dict(r) for r in c.fetchall()]
        return jsonify(photos)
    finally:
        close_db(conn)

@app.route('/api/photos/upload', methods=['POST'])
def upload_photo():
    import base64 as _b64
    data = request.json or {}
    team_id = session.get('team_id') or data.get('team_id', 'anonymous')
    team_name = data.get('team_name', 'Anonymous')
    caption = data.get('caption', '')[:200]
    photo_data = data.get('photo_data', '')  # base64 data URL

    if not photo_data:
        return jsonify({'error': 'No photo data'}), 400
    if len(photo_data) > 5 * 1024 * 1024 * 4 // 3:  # ~5MB base64 limit
        return jsonify({'error': 'Photo too large (max 5MB)'}), 400

    created_at = datetime.datetime.now().isoformat()
    conn, c = get_db()
    try:
        db_execute(c, "INSERT INTO gallery_photos (team_id, team_name, caption, photo_data, approved, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                   (team_id, team_name, caption, photo_data, 1, created_at))
        conn.commit()
        db_execute(c, "SELECT id FROM gallery_photos ORDER BY created_at DESC LIMIT 1")
        row = c.fetchone()
        new_id = row['id'] if isinstance(row, dict) else row[0]
        socketio.emit('new_photo', {'id': new_id, 'team_name': team_name, 'caption': caption, 'created_at': created_at})
        return jsonify({'success': True, 'id': new_id})
    finally:
        close_db(conn)

@app.route('/api/admin/photos/<int:photo_id>', methods=['DELETE'])
@admin_required
def delete_photo(photo_id):
    conn, c = get_db()
    try:
        db_execute(c, "DELETE FROM gallery_photos WHERE id = ?", (photo_id,))
        conn.commit()
        socketio.emit('photo_deleted', {'id': photo_id})
        return jsonify({'success': True})
    finally:
        close_db(conn)

@app.route('/api/team/public/<team_id>', methods=['GET'])
def get_public_team_info(team_id):
    team_id = normalize_team_id(team_id)
    conn, c = get_db()
    try:
        db_execute(c, "SELECT team_name FROM teams WHERE id = ?", (team_id,))
        team = c.fetchone()
        if team:
            return jsonify({'success': True, 'team_name': team['team_name'] if isinstance(team, dict) else team[0]})
        return jsonify({'success': False, 'error': 'Team not found'})
    finally:
        close_db(conn)

@app.route('/api/team/photos', methods=['GET'])
def get_team_photos_endpoint():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    conn, c = get_db()
    try:
        db_execute(c, "SELECT * FROM gallery_photos WHERE team_id = ? ORDER BY created_at DESC", (team_id,))
        photos = [dict(r) for r in c.fetchall()]
        return jsonify({'success': True, 'photos': photos})
    finally:
        close_db(conn)


# ═══════════════════════════════════════════════════════
#  PUSH NOTIFICATIONS  ─ routes
# ═══════════════════════════════════════════════════════

VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY')
VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY')
VAPID_CLAIMS = {"sub": "mailto:saxhin0708@gmail.com"}

@app.route('/api/push/public-key', methods=['GET'])
def get_push_public_key():
    return jsonify({'public_key': VAPID_PUBLIC_KEY})

@app.route('/api/push/subscribe', methods=['POST'])
def push_subscribe():
    data = request.json
    if not data: return jsonify({'error': 'Invalid endpoint'}), 400
    
    conn, c = get_db()
    try:
        # Check if already exists
        sub_json = json.dumps(data)
        db_execute(c, 'SELECT id FROM push_subscriptions WHERE subscription_json = ?', (sub_json,))
        if c.fetchone():
            return jsonify({'success': True, 'message': 'Already subscribed'})
            
        ip = request.remote_addr
        created_at = datetime.datetime.now().isoformat()
        db_execute(c, 'INSERT INTO push_subscriptions (subscription_json, ip_address, created_at) VALUES (?, ?, ?)',
                   (sub_json, ip, created_at))
        conn.commit()
        return jsonify({'success': True})
    finally:
        close_db(conn)

@app.route('/api/admin/push/broadcast', methods=['POST'])
@admin_required
def push_broadcast():
    from pywebpush import webpush, WebPushException
    data = request.json or {}
    title = data.get('title', 'RECKON 1.O Hackathon')
    body = data.get('body', 'Update available')
    url = data.get('url', '/')
    image = data.get('image')
    urgent = data.get('urgent', False)
    
    payload = {
        'title': title,
        'body': body,
        'url': url,
        'image': image,
        'urgent': urgent
    }
    
    conn, c = get_db()
    try:
        db_execute(c, 'SELECT subscription_json FROM push_subscriptions')
        subs = c.fetchall()
        
        results = {'success': 0, 'failure': 0}
        for sub_row in subs:
            sub_json = sub_row['subscription_json'] if isinstance(sub_row, dict) else sub_row[0]
            try:
                webpush(
                    subscription_info=json.loads(sub_json),
                    data=json.dumps(payload),
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims=VAPID_CLAIMS
                )
                results['success'] += 1
            except WebPushException:
                results['failure'] += 1
                # Could optionally delete old/invalid subscriptions here
        
        return jsonify(results)
    finally:
        close_db(conn)

@app.route('/api/admin/push/stats', methods=['GET'])
@admin_required
def get_push_stats():
    conn, c = get_db()
    try:
        db_execute(c, 'SELECT COUNT(*) FROM push_subscriptions')
        res = c.fetchone()
        count = res[0] if isinstance(res, tuple) else res['COUNT(*)']
        return jsonify({'count': count})
    finally:
        close_db(conn)

# ═══════════════════════════════════════════════════════
#  AI ASSISTANT (FEAT. AI IDEA VALIDATOR)
# ═══════════════════════════════════════════════════════

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

@app.route('/api/ai/validate_idea', methods=['POST'])
def ai_validate_idea():
    if not GEMINI_API_KEY:
        return jsonify({'error': 'AI services are currently offline. (No API key)'}), 503
    
    data = request.json or {}
    idea_desc = data.get('idea', '')
    if not idea_desc or len(idea_desc) < 20:
        return jsonify({'error': 'Please provide a more detailed idea (min 20 chars).'}), 400
        
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash',
            system_instruction="You are a professional hackathon mentor. Provide concise, critical, yet encouraging feedback on a hackathon project idea. Focus on: Feasibility (24h), Innovation, and Impact. Use bullet points."
        )
        
        response = model.generate_content(f"Validate this project idea: {idea_desc}")
        feedback = response.text
        return jsonify({'feedback': feedback})
    except Exception as e:
        print(f"AI Error: {e}")
        return jsonify({'error': 'Could not reach the AI brain.'}), 500

@app.route('/api/ai/chat', methods=['POST'])
def ai_chat():
    if not GEMINI_API_KEY:
        return jsonify({'error': 'AI services are offline.'}), 503
        
    data = request.json or {}
    user_msg = data.get('message', '')
    
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash',
            system_instruction="You are 'RECKON 1.O AI Assistant'. Help hackers with technical queries, hackathon rules (24 hours, team size 1-4, focus on innovation), and encouragement. Be concise and use a cool cyberpunk tone."
        )
        
        response = model.generate_content(user_msg)
        reply = response.text
        return jsonify({'reply': reply})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ═══════════════════════════════════════════════════════
#  MENTOR BOOKING SYSTEM
# ═══════════════════════════════════════════════════════

@app.route('/api/mentors', methods=['GET'])
def get_mentors_list():
    conn, c = get_db()
    try:
        db_execute(c, 'SELECT * FROM mentors WHERE available = ?', (True,))
        mentors = c.fetchall()
        return jsonify(mentors)
    finally:
        close_db(conn)

@app.route('/api/mentor/book', methods=['POST'])
def book_mentor():
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json or {}
    mentor_id = data.get('mentor_id')
    topic = data.get('topic', '')
    
    if not mentor_id:
        return jsonify({'error': 'No mentor selected'}), 400
        
    conn, c = get_db()
    try:
        db_execute(c, '''
            INSERT INTO mentor_bookings (mentor_id, team_id, topic, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
        ''', (mentor_id, session['team_id'], topic, datetime.datetime.now().isoformat()))
        conn.commit()
        return jsonify({'message': 'Booking request sent!'})
    finally:
        close_db(conn)

@app.route('/api/mentor/bookings', methods=['GET'])
def get_team_bookings():
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
        
    conn, c = get_db()
    try:
        db_execute(c, '''
            SELECT mb.*, m.name as mentor_name 
            FROM mentor_bookings mb
            JOIN mentors m ON mb.mentor_id = m.id
            WHERE mb.team_id = ?
            ORDER BY mb.created_at DESC
        ''', (session['team_id'],))
        bookings = c.fetchall()
        return jsonify(bookings)
    finally:
        close_db(conn)

@app.route('/api/admin/mentor/bookings', methods=['GET'])
@admin_required
def admin_get_all_bookings():
    conn, c = get_db()
    try:
        db_execute(c, '''
            SELECT mb.*, m.name as mentor_name, t.team_name
            FROM mentor_bookings mb
            JOIN mentors m ON mb.mentor_id = m.id
            JOIN teams t ON mb.team_id = t.id
            ORDER BY mb.created_at DESC
        ''')
        bookings = c.fetchall()
        return jsonify(bookings)
    finally:
        close_db(conn)

@app.route('/api/admin/mentor/bookings/<int:booking_id>/status', methods=['POST'])
@admin_required
def update_booking_status(booking_id):
    data = request.json or {}
    status = data.get('status')
    
    if status not in ['approved', 'rejected']:
        return jsonify({'error': 'Invalid status'}), 400
        
    conn, c = get_db()
    try:
        db_execute(c, 'UPDATE mentor_bookings SET status = ? WHERE id = ?', (status, booking_id))
        conn.commit()
        return jsonify({'message': f'Booking {status}'})
    finally:
        close_db(conn)

@app.route('/api/admin/teams/<team_id>/approve_payment', methods=['POST'])
@admin_required
def approve_team_payment(team_id):
    conn, c = get_db()
    try:
        db_execute(c, "SELECT * FROM teams WHERE id = ?", (team_id,))
        team = c.fetchone()
        if not team:
            return jsonify({'error': 'Team not found'}), 404
            
        db_execute(c, "UPDATE teams SET payment_status = 'Approved' WHERE id = ?", (team_id,))
        db_execute(c, "SELECT * FROM members WHERE team_id = ?", (team_id,))
        members = [dict(row) for row in c.fetchall()]
        conn.commit()
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        close_db(conn)

    # Send confirmation emails in background
    if members:
        team_name = team['team_name']
        leader_name  = members[0].get('name', 'Team Leader')
        leader_email = members[0].get('email')

        def send_all_emails():
            if leader_email:
                res = send_confirmation_email(leader_email, team_id, team_name, leader_name)
            for m in members[1:]:
                m_email = m.get('email')
                m_name  = m.get('name', 'Participant')
                if not m_email: continue

                m_subject = f"🎉 You're part of Team {team_name}! — RECKON 1.O Hackathon"
                m_qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=180x180&color=000000&bgcolor=ffffff&data={team_id}&margin=10"
                m_html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0a0f1e;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" bgcolor="#0a0f1e">
    <tr><td align="center" style="padding:40px 20px;">
      <table width="580" cellpadding="0" cellspacing="0" style="max-width:580px;width:100%;background:#0d1426;border-radius:16px;overflow:hidden;border:1px solid #1e2d50;">
        <tr><td style="background:linear-gradient(135deg,#7c3aed,#00d4ff);padding:30px;text-align:center;">
          <h1 style="margin:0;font-size:28px;font-weight:900;color:#fff;letter-spacing:2px;">RECKON 1.O</h1>
          <p style="margin:6px 0 0;font-size:12px;color:rgba(255,255,255,0.8);letter-spacing:3px;text-transform:uppercase;">National Level Hackathon</p>
        </td></tr>
        <tr><td style="padding:28px 32px 0 32px;">
          <p style="margin:0;font-size:19px;font-weight:700;color:#fff;">Welcome to the team, {m_name}! 🚀</p>
          <p style="margin:12px 0 0 0;font-size:14px;color:rgba(255,255,255,0.6);line-height:1.7;">You are now officially a member of <strong style="color:#00d4ff;">{team_name}</strong>. Get ready to build!</p>
        </td></tr>
        <tr><td style="padding:20px 32px 0 32px;">
          <table width="100%" cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,rgba(124,58,237,0.15),rgba(0,212,255,0.1));border:2px solid rgba(0,212,255,0.4);border-radius:12px;">
            <tr><td style="padding:18px;text-align:center;">
              <p style="margin:0 0 6px;font-size:11px;letter-spacing:3px;color:rgba(255,255,255,0.5);text-transform:uppercase;">Team ID</p>
              <p style="margin:0;font-size:30px;font-weight:900;color:#00d4ff;letter-spacing:6px;font-family:'Courier New',monospace;">{team_id}</p>
            </td></tr>
          </table>
        </td></tr>
        <tr><td style="padding:20px 32px 0 32px;text-align:center;">
          <p style="margin:0 0 10px 0;font-size:12px;color:rgba(255,255,255,0.4);letter-spacing:2px;text-transform:uppercase;">Entry QR Code</p>
          <div style="display:inline-block;background:#fff;padding:10px;border-radius:8px;">
            <img src="{m_qr_url}" alt="QR" width="160" height="160" />
          </div>
        </td></tr>
        <tr><td style="padding:24px 32px 32px 32px;text-align:center;border-top:1px solid rgba(255,255,255,0.07);margin-top:20px;">
          <p style="margin:0;font-size:13px;font-weight:700;color:rgba(255,255,255,0.55);">— The RECKON 1.O Organizing Team</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
                send_universal_email(m_email, m_subject, m_html, f"MEMBER-{m_name}")
        threading.Thread(target=send_all_emails).start()
    
    add_activity(f"Admin verified payment for Team {team['team_name']}.", "success")
    return jsonify({'success': True})

if __name__ == '__main__':
    # Use eventlet for WebSocket support
    # Disabling reloader on Windows to prevent port conflict with eventlet
    socketio.run(app, debug=True, use_reloader=False, port=int(os.environ.get('PORT', 5000)))
