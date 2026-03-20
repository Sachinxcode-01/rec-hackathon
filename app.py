# Optional high-performance concurrency - MUST BE FIRST for monkey_patching
try:
    import eventlet # type: ignore
    eventlet.monkey_patch()
    HAS_EVENTLET = True
except ImportError:
    HAS_EVENTLET = False

import os
import json
import threading
import csv
import io
import time
import datetime
import random
import string
import smtplib
import sqlite3
import traceback
import re
from functools import wraps
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import Any, Tuple, List, Dict, Optional, cast
import itertools
import requests # type: ignore

# Primary framework imports
try:
    from flask import Flask, request, jsonify, send_from_directory, session, redirect, url_for, g # type: ignore
    from flask_cors import CORS # type: ignore
    from flask_socketio import SocketIO, emit # type: ignore
    from werkzeug.security import generate_password_hash, check_password_hash # type: ignore
except ImportError:
    print("CRITICAL: Flask or core dependencies (CORS, SocketIO) not installed.")
    # We don't exit here to allow the script to be loaded for other purposes if needed

# Optional Gemini AI integration
try:
    from google import genai # type: ignore
    HAS_GEMINI = True
except ImportError:
    genai = None # type: ignore
    HAS_GEMINI = False

# Optional XLSX support
try:
    import openpyxl # type: ignore
    HAS_OPENPYXL = True
except ImportError:
    openpyxl = None # type: ignore
    HAS_OPENPYXL = False

# Optional Postgres support
try:
    import psycopg2 # type: ignore
    from psycopg2 import pool # type: ignore
    from psycopg2.extras import RealDictCursor # type: ignore
    try:
        from psycogreen.eventlet import patch_psycopg # type: ignore
        patch_psycopg()
    except (ImportError, AttributeError):
        pass
    HAS_POSTGRES = True
except ImportError:
    psycopg2 = None # type: ignore
    HAS_POSTGRES = False

# Optional compression
try:
    from flask_compress import Compress # type: ignore
    HAS_COMPRESS = True
except ImportError:
    HAS_COMPRESS = False

# Optional environment variables
try:
    from dotenv import load_dotenv # type: ignore
    load_dotenv()
except ImportError:
    pass

# Optional Web Push notifications
try:
    from pywebpush import webpush, WebPushException # type: ignore
    HAS_WEBPUSH = True
except ImportError:
    webpush = None # type: ignore
    WebPushException = Exception # type: ignore
    HAS_WEBPUSH = False

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
    """Clean and uppercase the ID. Ensures result is always a string or empty."""
    if tid is None: return ""
    return str(tid).strip().upper()

def find_team_in_db(cursor, raw_id):
    """Smart lookup: tries exact id, then with REC1- prefix, then without it."""
    tid = normalize_team_id(raw_id)
    if not (tid and isinstance(tid, str)): return None, ""

    # 1. Exact match
    db_execute(cursor, 'SELECT * FROM teams WHERE id = ?', (tid,))
    team = cursor.fetchone()
    if team: return team, tid
    
    # 2. Try adding prefix
    if not tid.startswith('REC1-'):
        prefixed = 'REC1-' + tid
        db_execute(cursor, 'SELECT * FROM teams WHERE id = ?', (prefixed,))
        team = cursor.fetchone()
        if team: return team, prefixed
        
    # 3. Try removing prefix
    if tid.startswith('REC1-'):
        stripped = tid.replace('REC1-', '', 1)
        db_execute(cursor, 'SELECT * FROM teams WHERE id = ?', (stripped,))
        team = cursor.fetchone()
        if team: return team, stripped
        
    return None, tid

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

# ── GLOBAL DB ERROR HANDLER ──────────────────────────────────────────────────
@app.errorhandler(sqlite3.Error)
def handle_sqlite_error(e):
    print(f"🔥 SQLite Error: {e}")
    return jsonify({'error': 'Local Database Error', 'details': str(e)}), 500

@app.errorhandler(Exception)
def handle_global_error(e):
    # Specialized handling for database related exceptions if they bubble up
    err_str = str(e).lower()
    if 'lock' in err_str or 'timeout' in err_str or 'connection' in err_str:
        print(f"🚨 DATABASE CONGESTION: {e}")
        return jsonify({'error': 'Database system is busy. Please try again in a few seconds.', 'type': 'db_congestion'}), 503
    
    print(f"💥 GLOBAL CRASH: {e}")
    # Return JSON for API routes, but might need something else for pages?
    # Usually better to be safe with JSON for this hackathon
    return jsonify({'error': 'Server Error', 'details': str(e)}), 500

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

def get_db() -> Tuple[Any, Any]:
    """Returns a database connection and cursor. Always returns valid objects or raises Exception."""
    conn, c = _get_db_core()
    if conn is None or c is None:
        raise RuntimeError("Database connection/cursor could not be initialized.")
    return conn, c

def _get_db_core():
    global pg_pool
    if DATABASE_URL and HAS_POSTGRES:
        if pg_pool is None:
            # Robust thread-safe connection pool for Postgres
            try:
                db_url = DATABASE_URL
                # Ensure SSL and timeout parameters are present
                if '?' not in db_url: db_url += '?sslmode=require&connect_timeout=10'
                else:
                    if 'sslmode' not in db_url: db_url += '&sslmode=require'
                    if 'connect_timeout' not in db_url: db_url += '&connect_timeout=10'
                
                # Using 2-20 connections for higher concurrency support
                pg_pool = pool.ThreadedConnectionPool(2, 20, dsn=db_url)
                print(">>> [POOL] Database Pool Initialized successfully.", flush=True)
            except Exception as e:
                print(f"✘ POOL ERROR: {e}", flush=True)
                # Keep pg_pool as None to ensure fallback below
        
        conn = None
        # Attempt to get connection from pool
        if pg_pool is not None:
            for attempt in range(3):
                try:
                    conn = pg_pool.getconn()
                    # CRITICAL: Always reset the connection state immediately
                    try:
                        conn.rollback()
                        conn.autocommit = True
                    except:
                        pass
                    # Verify connectivity quickly
                    with conn.cursor() as check_c: 
                        check_c.execute('SELECT 1')
                    break 
                except Exception as e:
                    print(f"⚠ Pool connection attempt {attempt+1} failed: {e}", flush=True)
                    if conn:
                        try: pg_pool.putconn(conn, close=True)
                        except: pass
                    conn = None
                    time.sleep(0.2)

        # Fallback if pool is exhausted or failed
        if not conn:
            if HAS_POSTGRES and psycopg2:
                try:
                    db_url = DATABASE_URL
                    # Ensure SSL for fallback too
                    if 'sslmode' not in db_url:
                        sep = '&' if '?' in db_url else '?'
                        db_url += f"{sep}sslmode=require&connect_timeout=10"
                    
                    print(">>> [DB] Fallback: Connecting directly...", flush=True)
                    conn = psycopg2.connect(db_url)
                    conn.autocommit = True # Ensure consistency with pooled connections
                except Exception as e:
                    print(f"✘ CRITICAL DB FAILURE: {e}", flush=True)
                    return None, None
            else:
                return None, None
             
        # Always use RealDictCursor for Postgres as the app depends on dict-access
        c = conn.cursor(cursor_factory=RealDictCursor)
    else:
        # SQLite Fallback (Development)
        try:
            conn = sqlite3.connect(DB_PATH, timeout=20, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
        except Exception as e:
            print(f"✘ SQLITE ERROR: {e}")
            return None, None

    try:
        if not hasattr(g, 'db_conns'): g.db_conns = []
        g.db_conns.append(conn)
    except RuntimeError: pass

    return conn, c

def close_db(conn):
    if not conn: return
    try:
        if hasattr(g, 'db_conns') and conn in g.db_conns:
            g.db_conns.remove(conn)
    except RuntimeError: pass

    if DATABASE_URL and HAS_POSTGRES and pg_pool:
        try:
            # Ensure we reset state and check autocommit before returning to pool
            try:
                if not conn.autocommit:
                    conn.rollback()
                conn.autocommit = True
            except:
                pass
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
        if hasattr(g, 'db_conns'):
            for dangling_conn in list(g.db_conns):
                try:
                    if DATABASE_URL and HAS_POSTGRES and pg_pool:
                        try:
                            # IMPORTANT: Reset transaction state
                            try: dangling_conn.rollback()
                            except: pass
                            # Try putting back to pool first
                            pg_pool.putconn(dangling_conn)
                        except:
                            # If not from pool or other issue, close it
                            try: dangling_conn.close()
                            except: pass
                    else:
                        try: dangling_conn.close()
                        except: pass
                except:
                    pass
            g.db_conns.clear()
    except Exception:
        pass


def db_execute(cursor: Any, query: str, params: Any = None):
    """Executes a SQL query with automatic retries for locks and timeouts."""
    if DATABASE_URL and HAS_POSTGRES:
        query = query.replace('?', '%s')
    
    max_retries = 3
    retry_count = 0
    while retry_count < max_retries:
        try:
            if not cursor:
                raise ValueError("Cursor is null or invalid")
            
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor
            
        except Exception as e:
            err_msg = str(e).lower()
            
            if DATABASE_URL and HAS_POSTGRES:
                try:
                    _conn = getattr(cursor, 'connection', None)
                    if _conn:
                        _conn.rollback()
                except:
                    pass

            # Retry on transient failures
            if ('lock' in err_msg or 'timeout' in err_msg or 'aborted' in err_msg or 'closed' in err_msg) and retry_count < max_retries - 1:
                retry_count += 1
                print(f"🔄 DB RETRY ({retry_count}/{max_retries}): {e}")
                time.sleep(0.5 * retry_count)
                continue
            
            # Final failure
            if "lock" in err_msg:
                print(f"✘ [LOCK FAILED] Final attempt failed: {e}")
            raise e
    
    return None # Should not be reachable due to raise e

_DB_INITIALIZED = False

def init_db():
    global _DB_INITIALIZED
    if _DB_INITIALIZED: return True, "Database already initialized"
    
    print(f">>> INITIALIZING DATABASE...", flush=True)
    try:
        conn, c = get_db()
        is_pg = DATABASE_URL and HAS_POSTGRES

        # Disable statement timeout for schema init — Supabase default is very short
        if is_pg:
            try: 
                c.execute("SET statement_timeout = '30s'") # 30s max per statement
                c.execute("SET idle_in_transaction_session_timeout = '30s'")
                c.execute("SET lock_timeout = '5s'") # 5s max wait for locks
                print(">>> [INIT] Postgres session settings applied.", flush=True)
            except Exception as _e:
                print(f"Warning: Could not set DDL timeouts: {_e}")
        
        # Helper to handle Postgres vs SQLite types
        def sql_compat(sql):
            if is_pg:
                # Replace SQLite specific 'AUTOINCREMENT' with Postgres 'SERIAL'
                sql = sql.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
                return sql
            return sql

        print(">>> [INIT] Ensuring table: teams", flush=True)
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
                payment_status TEXT DEFAULT 'Pending',
                checked_out INTEGER DEFAULT 0,
                status TEXT DEFAULT 'Verified',
                morning_at TEXT,
                lunch_at TEXT,
                snack_at TEXT,
                dinner_at TEXT,
                d2_morning_at TEXT,
                d2_lunch_at TEXT,
                d2_snack_at TEXT,
                checkout_at TEXT,
                dinner_checkin BOOLEAN DEFAULT FALSE,
                d2_morning_checkin BOOLEAN DEFAULT FALSE,
                d2_lunch_checkin BOOLEAN DEFAULT FALSE,
                d2_snack_checkin BOOLEAN DEFAULT FALSE
            )
        '''))
        if is_pg: conn.commit()
        print(">>> [INIT] Ensuring table: members", flush=True)
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
        if is_pg: conn.commit()

        print(">>> [INIT] Ensuring table: announcements", flush=True)
        db_execute(c, sql_compat('''
            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT,
                created_at TEXT,
                active INTEGER DEFAULT 1
            )
        '''))
        if is_pg: conn.commit()

        print(">>> [INIT] Ensuring table: help_requests", flush=True)
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
                priority TEXT DEFAULT 'med',
                description TEXT,
                created_at TEXT
            )
        '''))
        if is_pg: conn.commit()

        print(">>> [INIT] Ensuring table: activity_feed", flush=True)
        db_execute(c, sql_compat('''
            CREATE TABLE IF NOT EXISTS activity_feed (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT,
                type TEXT,
                team_id TEXT,
                created_at TEXT
            )
        '''))
        if is_pg: conn.commit()

        # --- MENTOR MARKETPLACE TABLES ---
        print(">>> [INIT] Ensuring MARKETPLACE tables...", flush=True)
        TABLES_EXTRA = [
            ("chat_messages", "CREATE TABLE IF NOT EXISTS chat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, team_id TEXT, sender_name TEXT, avatar_url TEXT, is_admin BOOLEAN DEFAULT FALSE, message TEXT, created_at TEXT)"),
            ("hacker_seekers", "CREATE TABLE IF NOT EXISTS hacker_seekers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, skills TEXT, bio TEXT, linkedin TEXT, github TEXT, created_at TEXT)"),
            ("mentors", "CREATE TABLE IF NOT EXISTS mentors (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, expertise TEXT, bio TEXT, avatar_url TEXT, available BOOLEAN DEFAULT TRUE)"),
            ("mentor_bookings", "CREATE TABLE IF NOT EXISTS mentor_bookings (id INTEGER PRIMARY KEY AUTOINCREMENT, mentor_id INTEGER, team_id TEXT, topic TEXT, status TEXT DEFAULT 'pending', booking_time TEXT, created_at TEXT)"),
            ("judges", "CREATE TABLE IF NOT EXISTS judges (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password_hash TEXT)"),
            ("judge_scores", "CREATE TABLE IF NOT EXISTS judge_scores (id INTEGER PRIMARY KEY AUTOINCREMENT, judge_id INTEGER, team_id TEXT, innovation INTEGER, impact INTEGER, tech INTEGER, ui INTEGER, total_score FLOAT, comments TEXT, created_at TEXT)"),
            ("team_badges", "CREATE TABLE IF NOT EXISTS team_badges (id INTEGER PRIMARY KEY AUTOINCREMENT, team_id TEXT, badge_name TEXT, badge_icon TEXT, mentor_name TEXT, comment TEXT, created_at TEXT)"),
            ("polls", "CREATE TABLE IF NOT EXISTS polls (id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT NOT NULL, options TEXT NOT NULL, active INTEGER DEFAULT 1, created_at TEXT)"),
            ("poll_votes", "CREATE TABLE IF NOT EXISTS poll_votes (id INTEGER PRIMARY KEY AUTOINCREMENT, poll_id INTEGER, option_index INTEGER, voter_hash TEXT, created_at TEXT)"),
            ("gallery_photos", "CREATE TABLE IF NOT EXISTS gallery_photos (id INTEGER PRIMARY KEY AUTOINCREMENT, team_id TEXT, team_name TEXT, caption TEXT, photo_data TEXT, approved INTEGER DEFAULT 1, created_at TEXT)"),
            ("push_subscriptions", "CREATE TABLE IF NOT EXISTS push_subscriptions (id INTEGER PRIMARY KEY AUTOINCREMENT, subscription_json TEXT NOT NULL, ip_address TEXT, created_at TEXT)"),
            ("login_codes", "CREATE TABLE IF NOT EXISTS login_codes (team_id TEXT PRIMARY KEY, code TEXT, expires_at TEXT)")
        ]
        
        for tn, ts in TABLES_EXTRA:
            try:
                db_execute(c, sql_compat(ts))
                if is_pg: conn.commit()
            except Exception as e:
                print(f"    ⚠ Table {tn} check failed (possible lock): {e}")
                if is_pg: conn.rollback()
        if is_pg: conn.commit()
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
        # Define ALL required columns: (table, column, type)
        REQUIRED_COLUMNS = [
            ("help_requests", "screenshot",           "TEXT"),
            ("help_requests", "is_emergency",         "INTEGER DEFAULT 0"),
            ("help_requests", "suggested_mentor",     "TEXT"),
            ("teams", "utr_number",                   "TEXT"),
            ("teams", "payment_status",               "TEXT DEFAULT 'Pending'"),
            ("teams", "checked_out",                  "INTEGER DEFAULT 0"),
            ("teams", "lunch_checkin",                "BOOLEAN DEFAULT FALSE"),
            ("teams", "snack_checkin",                "BOOLEAN DEFAULT FALSE"),
            ("teams", "status",                       "TEXT DEFAULT 'Verified'"),
            ("activity_feed", "team_id",              "TEXT"),
            ("teams", "morning_at",                   "TEXT"),
            ("teams", "lunch_at",                     "TEXT"),
            ("teams", "snack_at",                     "TEXT"),
            ("teams", "dinner_at",                    "TEXT"),
            ("teams", "d2_morning_at",                "TEXT"),
            ("teams", "d2_lunch_at",                  "TEXT"),
            ("teams", "d2_snack_at",                  "TEXT"),
            ("teams", "checkout_at",                  "TEXT"),
            ("teams", "dinner_checkin",               "BOOLEAN DEFAULT FALSE"),
            ("teams", "d2_morning_checkin",           "BOOLEAN DEFAULT FALSE"),
            ("teams", "d2_lunch_checkin",             "BOOLEAN DEFAULT FALSE"),
            ("teams", "d2_snack_checkin",             "BOOLEAN DEFAULT FALSE"),
            ("help_requests", "priority",             "TEXT DEFAULT 'med'"),
            ("help_requests", "description",          "TEXT"),
        ]

        print(f">>> [INIT] Checking schema for {len(REQUIRED_COLUMNS)} required columns...", flush=True)
        # We try each column individually for maximum reliability across different environments
        for tbl, col, col_type in REQUIRED_COLUMNS:
            try:
                # Use a specific check per column to avoid transaction aborts on Postgres
                if is_pg:
                    # Specific Postgres check
                    c.execute(f"""
                        SELECT COUNT(*) FROM information_schema.columns 
                        WHERE table_name = '{tbl}' AND column_name = '{col}'
                    """)
                    if c.fetchone()['count'] == 0:
                        print(f"    - Adding missing column {col} to {tbl}...", flush=True)
                        c.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {col_type}")
                        conn.commit()
                else:
                    # SQLite: just try and catch
                    try: 
                        c.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {col_type}")
                    except: 
                        pass 
            except Exception as e:
                print(f"    ⚠ Migration warning for {tbl}.{col}: {e}", flush=True)
                if is_pg: conn.rollback()

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
        print("OK: Database Initialized and Verified v2.")
        _DB_INITIALIZED = True
        return True, "Success"
    except Exception as e:
        print(f"ERR: Database Error during init: {e}")
        if conn:
            try: conn.rollback()
            except: pass
        import traceback
        traceback.print_exc()
        return False, str(e)
    finally:
        if conn:
            close_db(conn)
    
    return False, "Unknown initialization error"

@app.route('/api/admin/setup_db')
def manual_setup_db():
    success, msg = init_db()
    if success:
        return jsonify({'success': True, 'message': 'Database initialized successfully'})
    else:
        return jsonify({'success': False, 'error': msg}), 500

# Run DB init in background on first request so slow Supabase DDL never hangs the boot
_init_thread_started = False

# Shared initialization event for synchronization
_db_init_event = threading.Event()

@app.before_request
def startup_init():
    global _init_thread_started, _DB_INITIALIZED
    if not _init_thread_started:
        _init_thread_started = True
        print(">>> STARTING ASYNC DATABASE INIT...")
        def run_init():
            try:
                init_db()
                print(">>> ASYNC INIT COMPLETE.")
            except Exception as e:
                print(f">>> ASYNC INIT FAILED: {e}")
            finally:
                _db_init_event.set()
        
        thread = threading.Thread(target=run_init, daemon=True)
        thread.start()
    
    # Fast-path for initialized state
    if _DB_INITIALIZED:
        return

    # If first 5 seconds, wait. Otherwise just proceed and let background thread finish.
    # This prevents the site from being a blank page / hanging for 30s on cold starts.
    if not _db_init_event.is_set():
        _db_init_event.wait(timeout=3.0)

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
           <a href="{os.environ.get('WEBSITE_URL', 'https://rechackathon.up.railway.app')}/team-login.html" style="background:#00d4ff; color:#0a0f1e; padding:12px 24px; border-radius:8px; text-decoration:none; font-weight:bold; display:inline-block;">Login to Dashboard</a>
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
def send_universal_email(to_email, subject, html_content, log_tag="EMAIL", attachment_b64=None, attachment_name="RECKON-Pass.png"):
    smtp_user   = (os.environ.get('SMTP_USER') or '').strip()
    smtp_pass   = (os.environ.get('SMTP_PASS') or '').strip()
    smtp_server = (os.environ.get('SMTP_SERVER') or 'smtp.gmail.com').strip()
    smtp_port   = (os.environ.get('SMTP_PORT') or '587').strip()
    resend_key  = (os.environ.get('RESEND_API_KEY') or '').strip()
    brevo_key   = (os.environ.get('BREVO_API_KEY') or '').strip()
    sender_email = (os.environ.get('SENDER_EMAIL') or 'saxhin0708@gmail.com').strip()

    import json as _json

    # --- 1. TRY BREVO API ---
    if brevo_key:
        try:
            print(f"[{log_tag}] Trying Brevo API...")
            import urllib.request as _ur, urllib.error as _ue
            email_data = {
                "sender": {"name": "RECKON 1.O Hackathon", "email": sender_email},
                "to": [{"email": to_email}],
                "subject": subject,
                "htmlContent": html_content
            }
            if attachment_b64:
                # Brevo expects content as base64 string
                pure_b64 = attachment_b64.split(',')[-1] if ',' in attachment_b64 else attachment_b64
                email_data["attachment"] = [{"content": pure_b64, "name": attachment_name}]
            
            payload = _json.dumps(email_data).encode()
            req = _ur.Request('https://api.brevo.com/v3/smtp/email', data=payload,
                headers={'api-key': brevo_key, 'Content-Type': 'application/json'},
                method='POST')
            _ur.urlopen(req, timeout=12)
            print(f"[{log_tag}] SUCCESS via Brevo API")
            return True
        except Exception as e:
            err_details = str(e)
            # Use getattr to avoid lint errors on the generic Exception type
            read_fn = getattr(e, 'read', None)
            if read_fn:
                try: err_details += f" | Body: {read_fn().decode()}"
                except: pass
            else:
                resp = getattr(e, 'response', None)
                if resp and hasattr(resp, 'text'):
                    try: err_details += f" | Body: {resp.text}"
                    except: pass
            
            err_msg = f"Brevo API failed: {err_details}"
            print(f"[{log_tag}] {err_msg}")
            last_error = err_msg

    # --- 2. TRY SMTP ---
    last_error = "No delivery methods available"
    if smtp_user and smtp_pass:
        to_try = [(int(smtp_port), int(smtp_port) == 465)]
        if 587 not in [p[0] for p in to_try]: to_try.append((587, False))
        
        for p, is_ssl in to_try:
            try:
                print(f"[{log_tag}] Trying SMTP {smtp_server}:{p}...")
                if is_ssl: srv = smtplib.SMTP_SSL(smtp_server, p, timeout=12)
                else: 
                    srv = smtplib.SMTP(smtp_server, p, timeout=12)
                    srv.starttls()
                
                srv.login(smtp_user, smtp_pass)
                
                # 'mixed' is the standard for attachments
                msg = MIMEMultipart('mixed')
                msg['From']    = f'RECKON 1.O <{sender_email}>'
                msg['To']      = to_email
                msg['Subject'] = subject
                
                # Encapsulate body in alternative part (Text + HTML)
                body_part = MIMEMultipart('alternative')
                # Plain text version (stripping HTML tags for a basic version)
                text_content = re.sub(r'<[^>]+>', '', html_content)
                body_part.attach(MIMEText(text_content, 'plain'))
                body_part.attach(MIMEText(html_content, 'html'))
                msg.attach(body_part)
                
                if attachment_b64:
                    import base64
                    pure_b64 = attachment_b64.split(',')[-1] if ',' in attachment_b64 else attachment_b64
                    payload_size = len(pure_b64)
                    print(f"[{log_tag}] Attaching file ({attachment_name}), size: {payload_size} bytes")
                    
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(base64.b64decode(pure_b64))
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f'attachment; filename="{attachment_name}"')
                    msg.attach(part)

                srv.send_message(msg)
                srv.quit()
                print(f"[{log_tag}] SUCCESS via SMTP {p}")
                return True
            except Exception as e:
                last_error = f"SMTP {p} Error: {str(e)}"
                print(f"[{log_tag}] {last_error}")

    # --- 3. TRY RESEND API ---
    if resend_key:
        try:
            print(f"[{log_tag}] Trying Resend API...")
            import urllib.request as _ur
            resend_data = {
                'from': f"RECKON 1.O <{sender_email}>",
                'to': [to_email],
                'subject': subject,
                'html': html_content,
            }
            if attachment_b64:
                pure_b64 = attachment_b64.split(',')[-1] if ',' in attachment_b64 else attachment_b64
                resend_data['attachments'] = [{'content': pure_b64, 'filename': attachment_name}]
            
            payload = _json.dumps(resend_data).encode()
            req = _ur.Request('https://api.resend.com/emails', data=payload,
                headers={'Authorization': f'Bearer {resend_key}', 'Content-Type': 'application/json'},
                method='POST')
            _ur.urlopen(req, timeout=12)
            print(f"[{log_tag}] SUCCESS via Resend")
            return True
        except Exception as e:
            err_details = str(e)
            read_fn = getattr(e, 'read', None)
            if read_fn:
                try: err_details += f" | Body: {read_fn().decode()}"
                except: pass
            else:
                resp = getattr(e, 'response', None)
                if resp and hasattr(resp, 'text'):
                    try: err_details += f" | Body: {resp.text}"
                    except: pass
                
            err_msg = f"Resend Error: {err_details}"
            print(f"[{log_tag}] {err_msg}")
            last_error = err_msg

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
    try:
        conn, c = get_db()
        try:
            db_execute(c, 'SELECT * FROM activity_feed ORDER BY created_at DESC LIMIT 50')
            feed = [dict(row) for row in c.fetchall()]
            return jsonify(feed)
        finally:
            close_db(conn)
    except Exception as e:
        print(f"Feed error: {e}")
        return jsonify([])

@app.route('/api/pulse', methods=['GET'])
def get_tech_pulse():
    try:
        conn, c = get_db()
        if not c: return jsonify([])
        try:
            # Check if status column exists to avoid crash on legacy DBs
            query = "SELECT tech_stack FROM teams WHERE tech_stack IS NOT NULL"
            if DATABASE_URL and HAS_POSTGRES:
                db_execute(c, query + " AND status != 'Rejected'")
            else:
                db_execute(c, query + " AND status != 'Rejected'")
            
            raw_rows = c.fetchall()
            rows = list(raw_rows) if raw_rows else []
            tech_map = {}
            for row in rows:
                stack = row['tech_stack'] if isinstance(row, dict) else row[0]
                if not stack: continue
                for tech in str(stack).split(','):
                    tech = tech.strip().capitalize()
                    if not tech: continue
                    tech_map[tech] = tech_map.get(tech, 0) + 1
            
            all_sorted = sorted(tech_map.items(), key=lambda x: x[1], reverse=True)
            # Safe loop-based top 10 for strict linters
            top_10_list = []
            for i in range(min(10, len(all_sorted))):
                top_10_list.append(all_sorted[i])
            return jsonify([{'name': item[0], 'count': item[1]} for item in top_10_list])
        finally:
            close_db(conn)
    except Exception as e:
        print(f"Pulse error: {e}")
        return jsonify([])

@app.route('/api/stats', methods=['GET'])
def get_public_stats():
    try:
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
            
            # Photos
            try:
                db_execute(c, 'SELECT COUNT(*) as count FROM photos')
                photos = c.fetchone()['count']
            except:
                photos = 0

            # Mentors online - wrapping in try because table might be missing
            try:
                db_execute(c, 'SELECT COUNT(*) as count FROM mentors WHERE available = ?', (True,))
                mentors = c.fetchone()['count']
            except:
                mentors = 0
            
            return jsonify({
                'teams': teams,
                'hackers': hackers,
                'members': hackers, # Alias for frontend
                'checkins': checkins,
                'mentors': mentors,
                'photos': photos
            })
        finally:
            close_db(conn)
    except Exception as e:
        print(f"Stats error: {e}")
        return jsonify({'teams': 0, 'hackers': 0, 'members': 0, 'checkins': 0, 'mentors': 0, 'photos': 0})


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
    
    try:
        conn, c = get_db()
        db_execute(c, 'INSERT INTO judge_scores (judge_id, team_id, innovation, impact, tech, ui, total_score, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                  (judge_id, team_id, inn, imp, tec, ui, total, datetime.datetime.now().isoformat()))
        conn.commit()
        
        # Real-time: update leaderboard and notify admin of scoring activity
        emit_leaderboard_update()
        add_activity(f"Judge {session.get('judge_username')} scored Team {team_id}", "info")
        
        return jsonify({'success': True})
    except Exception as e:
        if conn: conn.rollback()
        print(f"ERROR Judge Score: {e}")
        return jsonify({'success': False, 'error': f"Database logic error: {str(e)}"}), 500
    finally:
        if conn: close_db(conn)

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

@app.route('/api/auth/me', methods=['GET'])
def get_me():
    return jsonify({
        'team_id': session.get('team_id'),
        'team_name': session.get('team_name'),
        'is_admin': session.get('is_admin', False)
    })

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
    team, team_id = find_team_in_db(c, team_id)
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

@app.route('/api/team/activity', methods=['GET'])
def get_team_activity():
    team_id = session.get('team_id')
    if not team_id:
        return jsonify([])
    
    conn, c = get_db()
    try:
        # Get activity for this team OR global activity (None)
        db_execute(c, 'SELECT * FROM activity_feed WHERE team_id = ? OR team_id IS NULL ORDER BY created_at DESC LIMIT 50', (team_id,))
        feed = [dict(row) for row in c.fetchall()]
        return jsonify(feed)
    finally:
        close_db(conn)

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

@app.route('/api/mentor/login', methods=['POST'])
def mentor_dashboard_login():
    """Simplified login for the Mentor Dashboard (No Captcha)"""
    pwd = request.json.get('password')
    # Default mentor password for the hackathon
    if pwd == 'reckonmentor': 
        session['is_admin'] = True
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Invalid override code.'}), 401

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
            team_item = cast(dict, t)
            team_id = str(team_item.get('id', ''))
            members = members_by_team.get(team_id, [])
            team_item['members'] = members
            
        return jsonify(teams)
    finally:
        close_db(conn)

@app.route('/api/admin/teams/bulk_delete', methods=['POST'])
@admin_required
def bulk_delete_teams():
    data = request.json
    team_ids = data.get('teamIds', [])
    if not team_ids:
        return jsonify({'error': 'No team IDs provided'}), 400
    
    conn, c = get_db()
    try:
        for team_id in team_ids:
            db_execute(c, 'DELETE FROM teams WHERE id = ?', (team_id,))
            db_execute(c, 'DELETE FROM members WHERE team_id = ?', (team_id,))
            db_execute(c, 'DELETE FROM help_requests WHERE team_id = ?', (team_id,))
            db_execute(c, 'DELETE FROM chat_messages WHERE team_id = ?', (team_id,))
            db_execute(c, 'DELETE FROM mentor_bookings WHERE team_id = ?', (team_id,))
            db_execute(c, 'DELETE FROM gallery_photos WHERE team_id = ?', (team_id,))
            db_execute(c, 'DELETE FROM judge_scores WHERE team_id = ?', (team_id,))
            db_execute(c, 'DELETE FROM team_badges WHERE team_id = ?', (team_id,))
            db_execute(c, 'DELETE FROM login_codes WHERE team_id = ?', (team_id,))
            db_execute(c, 'DELETE FROM activity_feed WHERE team_id = ?', (team_id,))
        conn.commit()
        return jsonify({'success': True, 'count': len(team_ids)})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        close_db(conn)

@app.route('/api/admin/teams/<team_id>', methods=['DELETE'])
@admin_required
def delete_team(team_id):
    conn, c = get_db()
    try:
        db_execute(c, 'DELETE FROM teams WHERE id = ?', (team_id,))
        db_execute(c, 'DELETE FROM members WHERE team_id = ?', (team_id,))
        db_execute(c, 'DELETE FROM help_requests WHERE team_id = ?', (team_id,))
        db_execute(c, 'DELETE FROM chat_messages WHERE team_id = ?', (team_id,))
        db_execute(c, 'DELETE FROM mentor_bookings WHERE team_id = ?', (team_id,))
        db_execute(c, 'DELETE FROM gallery_photos WHERE team_id = ?', (team_id,))
        db_execute(c, 'DELETE FROM judge_scores WHERE team_id = ?', (team_id,))
        db_execute(c, 'DELETE FROM team_badges WHERE team_id = ?', (team_id,))
        db_execute(c, 'DELETE FROM login_codes WHERE team_id = ?', (team_id,))
        db_execute(c, 'DELETE FROM activity_feed WHERE team_id = ?', (team_id,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        close_db(conn)

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
        # Flexible lookup for admin check-in
        res, team_id = find_team_in_db(c, team_id)
        team = dict(res or {})
        
        if not team:
            return jsonify({'error': 'Invalid Team ID. Team not found.'}), 404
            
        column = 'checked_in'
        ts_column = 'morning_at'
        if checkin_type == 'lunch':      column = 'lunch_checkin';      ts_column = 'lunch_at'
        if checkin_type == 'snack':      column = 'snack_checkin';      ts_column = 'snack_at'
        if checkin_type == 'dinner':     column = 'dinner_checkin';     ts_column = 'dinner_at'
        if checkin_type == 'd2_morning': column = 'd2_morning_checkin';  ts_column = 'd2_morning_at'
        if checkin_type == 'd2_lunch':   column = 'd2_lunch_checkin';    ts_column = 'd2_lunch_at'
        if checkin_type == 'd2_snack':   column = 'd2_snack_checkin';    ts_column = 'd2_snack_at'
        if checkin_type == 'checkout':   column = 'checked_out';        ts_column = 'checkout_at'
            
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

@app.route('/api/admin/qr_history', methods=['GET'])
@admin_required
def get_all_qr_history():
    conn, c = get_db()
    try:
        db_execute(c, '''
            SELECT id, team_name, checked_in, lunch_checkin, snack_checkin, dinner_checkin,
                   d2_morning_checkin, d2_lunch_checkin, d2_snack_checkin, checked_out,
                   morning_at, lunch_at, snack_at, dinner_at,
                   d2_morning_at, d2_lunch_at, d2_snack_at, checkout_at
            FROM teams
        ''')
        teams = [dict(row) for row in c.fetchall()]
        
        history = []
        for team in teams:
            def add_evt(flag, ts, typ, label, icon):
                if flag in [True, 1] and ts:
                    history.append({
                        'team_id': team['id'],
                        'team_name': team['team_name'],
                        'type': typ,
                        'label': label,
                        'icon': icon,
                        'timestamp': ts
                    })
            
            add_evt(team.get('checked_in'), team.get('morning_at'), 'morning', 'Day 1: Morning', '☀️')
            add_evt(team.get('lunch_checkin'), team.get('lunch_at'), 'lunch', 'Day 1: Lunch', '🥪')
            add_evt(team.get('snack_checkin'), team.get('snack_at'), 'snack', 'Day 1: Snack', '🥤')
            add_evt(team.get('dinner_checkin'), team.get('dinner_at'), 'dinner', 'Day 1: Dinner', '🍱')
            
            add_evt(team.get('d2_morning_checkin'), team.get('d2_morning_at'), 'd2_morning', 'Day 2: Morning', '☕')
            add_evt(team.get('d2_lunch_checkin'), team.get('d2_lunch_at'), 'd2_lunch', 'Day 2: Lunch', '🍛')
            add_evt(team.get('d2_snack_checkin'), team.get('d2_snack_at'), 'd2_snack', 'Day 2: Snack', '🍕')
            add_evt(team.get('checked_out'), team.get('checkout_at'), 'checkout', 'Final Checkout', '🚪')
            
        history.sort(key=lambda x: x['timestamp'], reverse=True)
        return jsonify(history)
    finally:
        close_db(conn)

@app.route('/api/team/checkin_history', methods=['GET'])
def get_team_checkin_history():
    """Returns the complete check-in history for the logged-in team with exact timestamps."""
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn, c = get_db()
    try:
        db_execute(c, '''
            SELECT checked_in, lunch_checkin, snack_checkin, dinner_checkin,
                   d2_morning_checkin, d2_lunch_checkin, d2_snack_checkin, checked_out,
                   morning_at, lunch_at, snack_at, dinner_at,
                   d2_morning_at, d2_lunch_at, d2_snack_at, checkout_at
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
        
        # Day 1
        if team.get('checked_in') in [True, 1]:
            history.append({'day': 1, 'type': 'morning',  'label': 'Day 1: Morning',  'icon': '☀️', 'color': '#00d4ff', 'time': fmt(team.get('morning_at'))})
        if team.get('lunch_checkin') in [True, 1]:
            history.append({'day': 1, 'type': 'lunch',    'label': 'Day 1: Lunch',    'icon': '🥪', 'color': '#00ff66', 'time': fmt(team.get('lunch_at'))})
        if team.get('snack_checkin') in [True, 1]:
            history.append({'day': 1, 'type': 'snack',    'label': 'Day 1: Snack',    'icon': '🥤', 'color': '#b44dff', 'time': fmt(team.get('snack_at'))})
        if team.get('dinner_checkin') in [True, 1]:
            history.append({'day': 1, 'type': 'dinner',   'label': 'Day 1: Dinner',   'icon': '🍱', 'color': '#ff2d78', 'time': fmt(team.get('dinner_at'))})
            
        # Day 2
        if team.get('d2_morning_checkin') in [True, 1]:
            history.append({'day': 2, 'type': 'morning',  'label': 'Day 2: Morning',  'icon': '☕', 'color': '#00d4ff', 'time': fmt(team.get('d2_morning_at'))})
        if team.get('d2_lunch_checkin') in [True, 1]:
            history.append({'day': 2, 'type': 'lunch',    'label': 'Day 2: Lunch',    'icon': '🍛', 'color': '#00ff66', 'time': fmt(team.get('d2_lunch_at'))})
        if team.get('d2_snack_checkin') in [True, 1]:
            history.append({'day': 2, 'type': 'snack',    'label': 'Day 2: Snack',    'icon': '🍕', 'color': '#b44dff', 'time': fmt(team.get('d2_snack_at'))})
        if team.get('checked_out') in [True, 1]:
            history.append({'day': 2, 'type': 'checkout', 'label': 'Final Checkout',  'icon': '🚪', 'color': '#ff2d78', 'time': fmt(team.get('checkout_at'))})
        
        return jsonify({
            'history': history,
            'total': len(history),
            'all_done': len(history) == 8
        })
    finally:
        close_db(conn)

@app.route('/api/admin/reset_checkins', methods=['POST'])
@admin_required
def reset_checkins():
    print(f"DEBUG: Resetting all check-ins and timestamps...", flush=True)
    conn, c = get_db()
    try:
        # 1. Reset all team check-in statuses and timestamp columns
        db_execute(c, '''
            UPDATE teams SET 
                checked_in = ?, lunch_checkin = ?, snack_checkin = ?, dinner_checkin = ?,
                d2_morning_checkin = ?, d2_lunch_checkin = ?, d2_snack_checkin = ?, checked_out = ?,
                morning_at = NULL, lunch_at = NULL, snack_at = NULL, dinner_at = NULL,
                d2_morning_at = NULL, d2_lunch_at = NULL, d2_snack_at = NULL, checkout_at = NULL
        ''', (False, False, False, False, False, False, False, 0))
        
        # 2. Clear check-in related activity from the feed to "reset" history
        db_execute(c, "DELETE FROM activity_feed WHERE message LIKE ? OR message LIKE ?", 
                  ('%checked in for%', '%checked out of%'))
        
        conn.commit()
        print(f"DEBUG: All check-ins and history cleared successfully.", flush=True)
    except Exception as e:
        if conn: conn.rollback()
        print(f"DEBUG: Reset error: {e}", flush=True)
        return jsonify({'error': str(e)}), 500
    finally:
        close_db(conn)
    
    add_activity("All team check-in statuses and history have been cleared by administrator.", "warning")
    return jsonify({'success': True, 'message': 'All check-ins and history have been reset.'})

@app.route('/api/admin/system_full_reset', methods=['POST'])
@admin_required
def system_full_reset():
    """⚠️ DANGER: Wipes all team, member, help, chat, and activity data."""
    conn, c = get_db()
    try:
        # Tables to clear (Dynamic Participant Data)
        tables = [
            'teams', 'members', 'help_requests', 'activity_feed', 
            'chat_messages', 'mentor_bookings', 'team_badges', 
            'poll_votes', 'gallery_photos', 'judge_scores', 
            'login_codes', 'hacker_seekers'
        ]
        
        for table in tables:
            db_execute(c, f"DELETE FROM {table}")
        
        conn.commit()
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        close_db(conn)
    
    return jsonify({'success': True, 'message': 'System data cleared successfully. Ready for new registrations.'})

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
    priority = data.get('priority', 'med')
    description = data.get('description', '')
    
    if not team_id or not location or not topic:
        return jsonify({'error': 'Missing fields'}), 400
        
    conn, c = get_db()
    try:
        db_execute(c, 'SELECT id FROM teams WHERE id = ?', (team_id,))
        if not c.fetchone():
            close_db(conn)
            return jsonify({'error': 'Invalid Team ID'}), 404
            
        # ══ MENTOR EXPERTISE MATCHING ══
        direct_mentor = data.get('directMentor')
        if direct_mentor:
            suggested = direct_mentor
        else:
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
                   (team_id, location, topic, status, screenshot, is_emergency, suggested_mentor, priority, description, created_at) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (team_id, location, topic, 'Pending', screenshot, is_emergency, suggested, priority, description, created_at))
        
        # Get team name for the realtime message
        db_execute(c, 'SELECT team_name FROM teams WHERE id = ?', (team_id,))
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

@app.route('/api/help/status', methods=['GET'])
def get_public_help_status():
    """Publicly accessible endpoint for the live status page."""
    conn, c = get_db()
    try:
        db_execute(c, '''
            SELECT hr.id, t.team_name, hr.topic, hr.status, hr.suggested_mentor, hr.created_at, hr.is_emergency
            FROM help_requests hr 
            LEFT JOIN teams t ON hr.team_id = t.id 
            ORDER BY hr.created_at DESC
            LIMIT 50
        ''')
        res = [dict(row) for row in c.fetchall()]
        return jsonify(res)
    finally:
        close_db(conn)

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
            add_activity(f"Mentor {mentor_name} endorsed Team {tn} with '{badge_name}'!", "success", tid)
            socketio.emit('new_badge', {'team_id': tid, 'badge': badge_name, 'icon': icon})

    conn.commit()
    close_db(conn)
    socketio.emit('help_status_update', {'id': hr_id, 'status': status, 'mentor_name': mentor_name})
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
        return jsonify({'success': False, 'error': 'No data rows found in the file.'}), 400

    print(f">>> [IMPORT] Starting import for {len(data_rows)} rows from {source_name}...", flush=True)
    conn, c = get_db()
    teams_added = 0
    members_added = 0
    
    try:
        # Pre-fetch existing teams to minimize queries
        db_execute(c, 'SELECT id FROM teams')
        existing_teams = {row['id'] for row in c.fetchall()}
        
        for idx, row in enumerate(data_rows):
            if idx % 50 == 0:
                print(f">>> [IMPORT] Processing row {idx}/{len(data_rows)}...", flush=True)
                
            header_map = {str(k).lower().replace(' ', '').replace('_', ''): k for k in row.keys() if k is not None}
            
            def get_val(possible_keys):
                for k in possible_keys:
                    clean_k = k.lower().replace(' ', '').replace('_', '')
                    real_key = header_map.get(clean_k)
                    if real_key:
                        val = row.get(real_key)
                        return str(val).strip() if val is not None else ''
                return ''

            team_id = get_val(['RegID', 'TeamID', 'ID', 'RegistrationID']).upper()
            if not team_id: continue
            
            if '-' not in team_id and not team_id.startswith('REC1-'):
                team_id = 'REC1-' + team_id
            
            team_name = get_val(['TeamName', 'Name', 'GroupName']) or f"Team {team_id}"
            college = get_val(['CollegeName', 'College', 'University']) or "RECC"
            dept = get_val(['Department', 'Dept', 'Branch'])
            theme = get_val(['ProjectDomain', 'Theme', 'Domain'])
            
            leader_name = get_val(['LeaderName', 'TeamLeader', 'Leader'])
            leader_email = get_val(['Email', 'EmailID'])
            leader_phone = get_val(['PhoneNumber', 'Phone', 'Contact'])
            
            utr = get_val(['UTRNumber', 'UTR', 'TransactionID'])
            payment_proof = get_val(['PaymentProofURL', 'PaymentScreenshot'])
            members_raw = get_val(['Members', 'TeamMembers', 'OtherMembers'])

            # 1. Team Entry
            if team_id not in existing_teams:
                created_at = datetime.datetime.now().isoformat()
                db_execute(c, '''
                    INSERT INTO teams (id, team_name, college, dept, theme, utr_number, payment_screenshot, created_at) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (team_id, team_name, college, dept, theme, utr, payment_proof, created_at))
                existing_teams.add(team_id)
                teams_added += 1
            
            # 2. Leader Entry
            if leader_name:
                db_execute(c, 'SELECT id FROM members WHERE team_id = ? AND LOWER(name) = ?', (team_id, leader_name.lower()))
                if not c.fetchone():
                    db_execute(c, 'INSERT INTO members (team_id, name, phone, email, is_leader) VALUES (?, ?, ?, ?, 1)',
                            (team_id, leader_name, leader_phone, leader_email))
                    members_added += 1
            
            # 3. Parsed Members
            if members_raw:
                potential_members = re.split(r'[\n,;]', str(members_raw))
                for m in potential_members:
                    m = m.strip()
                    if not m: continue
                    # Clean numbering like "1. Name"
                    m = re.sub(r'^[\d\.\-\)\s]+', '', m).strip()
                    if not m: continue
                    
                    m_str = str(m)
                    leader_str = str(leader_name or "")
                    if m_str.lower() != leader_str.lower():
                        db_execute(c, 'SELECT id FROM members WHERE team_id = ? AND LOWER(name) = ?', (team_id, m.lower()))
                        if not c.fetchone():
                            db_execute(c, 'INSERT INTO members (team_id, name, is_leader) VALUES (?, ?, 0)', (team_id, m))
                            members_added += 1
        
        conn.commit()
        print(f">>> [IMPORT] Success: Added {teams_added} teams and {members_added} members.", flush=True)
        add_activity(f"Admin imported {teams_added} teams and {members_added} students via {source_name}.", "info")
        return jsonify({
            'success': True, 
            'message': f'Successfully imported {teams_added} teams and {members_added} students.'
        })
        
    except Exception as e:
        if conn: conn.rollback()
        print(f"✘ [IMPORT] CRITICAL ERROR: {e}", flush=True)
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Import failed: {str(e)}'}), 500
    finally:
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
            
            headers: List[str] = []
            for cell in rows[0]:
                val = cell.value
                headers.append(str(val).strip() if val is not None else "")
            
            rows_list = list(rows)
            for i in range(1, len(rows_list)):
                row_item = cast(Any, rows_list[i])
                row_data = {}
                is_empty_row = True
                row_cells = list(row_item)
                for idx in range(len(row_cells)):
                    cell = cast(Any, row_cells[idx])
                    if idx < len(headers):
                        h_key_raw = cast(List[str], headers)[idx]
                        if h_key_raw:
                            h_key = str(h_key_raw)
                            c_val = cell.value
                            row_data[h_key] = c_val
                            if c_val is not None and str(c_val).strip() != '':
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
    to_email    = data.get('to_email')
    subject     = data.get('subject')
    body        = data.get('body')
    attach_b64  = data.get('attachment_b64')
    attach_name = data.get('attachment_name', 'RECKON-Pass.png')

    if not to_email or not subject or not body:
        return jsonify({'success': False, 'error': 'Missing fields'}), 400

    # Use the universal sender to handle SMTP blocks and API fallbacks
    res = send_universal_email(to_email, subject, body, "ADMIN-CUSTOM", attachment_b64=attach_b64, attachment_name=attach_name)
    
    if res is True:
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': str(res)})

@app.route('/hc')
def health_check():
    res = {
        'status': 'ok',
        'db': 'unknown',
        'has_eventlet': HAS_EVENTLET,
        'has_postgres': HAS_POSTGRES,
        'has_pg_pool': pg_pool is not None,
        'timestamp': datetime.datetime.now().isoformat(),
        'counts': {}
    }
    try:
        conn, c = get_db()
        try:
            db_execute(c, 'SELECT 1')
            res['db'] = 'connected'
            if DATABASE_URL and HAS_POSTGRES:
                res['db_type'] = 'postgres'
                res['db_provider'] = 'Supabase/Postgres'
            else:
                res['db_type'] = 'sqlite'
                res['db_provider'] = 'Local SQLite'
            
            # Simple counts to verify data presence safely
            counts = {}
            db_execute(c, 'SELECT COUNT(*) as count FROM teams')
            row_teams = c.fetchone()
            counts['teams'] = row_teams['count'] if row_teams else 0
            
            db_execute(c, 'SELECT COUNT(*) as count FROM members')
            row_members = c.fetchone()
            counts['members'] = row_members['count'] if row_members else 0
            
            res['counts'] = counts
            
        finally:
            close_db(conn)
    except Exception as e:
        res['db'] = 'failed'
        res['db_error'] = str(e)
        res['status'] = 'error'
    
    return jsonify(res)

@app.route('/api/admin/email_diagnostic', methods=['GET'])
@admin_required
def debug_email_config():
    """Diagnostic tool to check email credentials."""
    return jsonify({
        'SENDER_EMAIL': os.environ.get('SENDER_EMAIL'),
        'BREVO_API_KEY_PRESENT': bool(os.environ.get('BREVO_API_KEY')),
        'SMTP_USER': os.environ.get('SMTP_USER'),
        'SMTP_SERVER': os.environ.get('SMTP_SERVER') or 'smtp.gmail.com',
        'RESEND_API_KEY_PRESENT': bool(os.environ.get('RESEND_API_KEY')),
        'HAS_EVENTLET': HAS_EVENTLET
    })

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
    try:
        conn, c = get_db()
        try:
            db_execute(c, 'SELECT * FROM teams WHERE project_title IS NOT NULL ORDER BY upvotes DESC')
            projects = [dict(row) for row in c.fetchall()]
            return jsonify(projects)
        finally:
            close_db(conn)
    except Exception as e:
        print(f"Projects error: {e}")
        return jsonify([])

@app.route('/api/projects/<team_id>/upvote', methods=['POST'])
def upvote_project(team_id):
    conn = None
    try:
        conn, c = get_db()
        team, team_id = find_team_in_db(c, team_id)
        if not team:
            return jsonify({'error': 'Team not found'}), 404
        db_execute(c, 'UPDATE teams SET upvotes = upvotes + 1 WHERE id=?', (team_id,))
        conn.commit()
        emit_leaderboard_update()
        return jsonify({'success': True})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if conn: close_db(conn)

@app.route('/api/admin/projects/<team_id>/score', methods=['POST'])
@admin_required
def score_project(team_id):
    team_id = normalize_team_id(team_id)
    data = request.json
    inn = data.get('innovation', 0)
    ui = data.get('ui', 0)
    tech = data.get('tech', 0)
    conn = None
    try:
        conn, c = get_db()
        db_execute(c, 'UPDATE teams SET innovation_score=?, ui_score=?, tech_score=? WHERE id=?', (inn, ui, tech, team_id))
        conn.commit()
        emit_leaderboard_update()
        return jsonify({'success': True})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if conn: close_db(conn)

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




# Initialize DB before starting - REMOVED blocking call to prevent startup hang
# The DB will now be initialized via the startup_init background thread on first request.

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
        all_sorted = sorted(pulse.items(), key=lambda x: x[1], reverse=True)
        top_sorted_list = []
        for i in range(min(10, len(all_sorted))):
            top_sorted_list.append(all_sorted[i])
        return jsonify(dict(top_sorted_list))
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
            p_options = poll.get('options')
            p_opt_str = str(p_options)
            options_json = _json.loads(p_opt_str) if isinstance(p_options, str) else p_options
            # Fetch vote counts per option
            db_execute(c, "SELECT option_index, COUNT(*) as cnt FROM poll_votes WHERE poll_id = ? GROUP BY option_index", (poll['id'],))
            raw_votes = c.fetchall()
            votes_list = list(raw_votes) if raw_votes else []
            vote_map = {}
            for rv in votes_list:
                rv_dict = cast(dict, rv) if isinstance(rv, dict) else {'option_index': rv[0], 'cnt': rv[1]}
                vote_map[rv_dict.get('option_index')] = rv_dict.get('cnt')
            
            total_votes = sum(vote_map.values())
            options_final = cast(list, options_json) if isinstance(options_json, list) else []
            options_with_votes = [{'text': str(opt), 'votes': vote_map.get(o_idx, 0)} for o_idx, opt in enumerate(options_final)]
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
    raw_cap = data.get('caption', '')
    if raw_cap is None: raw_cap = ''
    str_cap = str(raw_cap)
    # Using join/islice as a universal slicing fallback for picky linters
    caption = "".join(itertools.islice(str_cap, 200))
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

@app.route('/api/team/photos/<int:photo_id>', methods=['DELETE'])
def team_delete_photo(photo_id):
    team_id = session.get('team_id')
    if not team_id:
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn, c = get_db()
    try:
        # Verify photo belongs to this team
        db_execute(c, "SELECT team_id FROM gallery_photos WHERE id = ?", (photo_id,))
        row = c.fetchone()
        if not row:
            return jsonify({'error': 'Photo not found'}), 404
        
        photo_owner = row['team_id'] if isinstance(row, dict) else row[0]
        if photo_owner != team_id:
            return jsonify({'error': 'You can only delete your own photos'}), 403
            
        db_execute(c, "DELETE FROM gallery_photos WHERE id = ?", (photo_id,))
        conn.commit()
        socketio.emit('photo_deleted', {'id': photo_id})
        return jsonify({'success': True})
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
    if not HAS_WEBPUSH or webpush is None:
        return jsonify({'error': 'Push notifications not configured on this server.'}), 503
        
    # webpush, WebPushException are imported at top
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
                if webpush:
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
        db_execute(c, 'SELECT COUNT(*) as cnt FROM push_subscriptions')
        res = c.fetchone()
        count = 0
        if res:
            if isinstance(res, dict): count = res.get('cnt', 0)
            else: count = res[0]
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
        return jsonify({'error': 'AI services are currently offline. (Missing API key)'}), 503
    
    data = request.json or {}
    idea_desc = data.get('idea', '')
    if not idea_desc or len(idea_desc) < 20:
        return jsonify({'error': 'Please provide a more detailed idea (min 20 chars).'}), 400
        
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{
                "parts": [{"text": f"Validate this project idea: {idea_desc}"}]
            }],
            "systemInstruction": {
                "parts": [{"text": "You are a professional hackathon mentor. Provide concise, critical, yet encouraging feedback on a hackathon project idea. Focus on: Feasibility (24h), Innovation, and Impact. Use bullet points."}]
            }
        }
        resp = requests.post(url, json=payload, timeout=10)
        resp_data = resp.json()
        
        if 'candidates' in resp_data:
            feedback = resp_data['candidates'][0]['content']['parts'][0]['text']
            return jsonify({'feedback': feedback})
        else:
            err_msg = resp_data.get('error', {}).get('message', 'No feedback generated.')
            return jsonify({'error': f"AI Error: {err_msg}"}), 500
            
    except requests.exceptions.ConnectionError:
        return jsonify({'error': 'Network Error: Could not reach AI brain. Check your internet/DNS.'}), 500
    except Exception as e:
        print(f"AI Validate Error: {e}")
        return jsonify({'error': f'AI Uplink Error: {str(e)}'}), 500

@app.route('/api/ai/chat', methods=['POST'])
def ai_chat():
    if not GEMINI_API_KEY:
        return jsonify({'error': 'AI chat is offline. (Missing API key)'}), 503
        
    data = request.json or {}
    user_msg = data.get('message', '')
    if not user_msg:
        return jsonify({'reply': 'I am listening...'})
    
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{
                "parts": [{"text": user_msg}]
            }],
            "systemInstruction": {
                "parts": [{"text": "You are 'RECKON 1.O AI Assistant'. Help hackers with technical queries, hackathon rules (24 hours, team size 1-4, focus on innovation), and encouragement. Be concise and use a cool cyberpunk tone."}]
            }
        }
        resp = requests.post(url, json=payload, timeout=10)
        resp_data = resp.json()
        
        if 'candidates' in resp_data:
            reply = resp_data['candidates'][0]['content']['parts'][0]['text']
            return jsonify({'reply': reply})
        else:
            err_msg = resp_data.get('error', {}).get('message', 'AI Uplink Disrupted.')
            return jsonify({'error': f"AI Error: {err_msg}"}), 500
            
    except requests.exceptions.ConnectionError:
        return jsonify({'error': 'Network Error: Could not resolve AI host. Check DNS.'}), 500
    except Exception as e:
        return jsonify({'error': f'Uplink Error: {str(e)}'}), 500

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
                send_confirmation_email(leader_email, team_id, team_name, leader_name)
            
            # Avoid slicing directly in the loop to satisfy some linters
            other_members = []
            if len(members) > 1:
                # Use range-based index access to avoid slicing issues
                for i in range(1, len(members)):
                    other_members.append(members[i])
            
            for m in other_members:
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
