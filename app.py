import os
import sqlite3
import random
import string
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, session, redirect
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
import threading
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

# Load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("python-dotenv not installed. Run: pip install python-dotenv")

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)
app.secret_key = os.environ.get('SECRET_KEY', 'REC1O_SUPER_SECRET_KEY_DEVELOPMENT')
ADMIN_USERNAME = "admin"

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

def get_db():
    if DATABASE_URL and HAS_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        # For Postgres, we use RealDictCursor to match sqlite3.Row behavior
        return conn, conn.cursor(cursor_factory=RealDictCursor)
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn, conn.cursor()

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

        c.execute(sql_compat('''
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
                upvotes INTEGER DEFAULT 0
            )
        '''))
        c.execute(sql_compat('''
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
        c.execute(sql_compat('''
            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT,
                created_at TEXT,
                active INTEGER DEFAULT 1
            )
        '''))
        c.execute(sql_compat('''
            CREATE TABLE IF NOT EXISTS help_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id TEXT,
                location TEXT,
                topic TEXT,
                status TEXT,
                created_at TEXT
            )
        '''))
        c.execute(sql_compat('''
            CREATE TABLE IF NOT EXISTS activity_feed (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT,
                type TEXT,
                created_at TEXT
            )
        '''))
        c.execute(sql_compat('''
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id TEXT,
                sender_name TEXT,
                avatar_url TEXT,
                is_admin INTEGER DEFAULT 0,
                message TEXT,
                created_at TEXT
            )
        '''))
        c.execute(sql_compat('''
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
        c.execute(sql_compat('''
            CREATE TABLE IF NOT EXISTS mentors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                expertise TEXT,
                bio TEXT,
                avatar_url TEXT,
                available INTEGER DEFAULT 1
            )
        '''))
        c.execute(sql_compat('''
            CREATE TABLE IF NOT EXISTS judges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password_hash TEXT
            )
        '''))
        c.execute(sql_compat('''
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
        c.execute(sql_compat('''
            CREATE TABLE IF NOT EXISTS login_codes (
                team_id TEXT PRIMARY KEY,
                code TEXT,
                expires_at TEXT
            )
        '''))
        
        # Ensure default judge exists
        c.execute('SELECT COUNT(*) FROM judges')
        row = c.fetchone()
        count = row['count'] if is_pg else row[0]
        if count == 0:
            db_execute(c, 'INSERT INTO judges (username, password_hash) VALUES (?, ?)', 
                      ('judge1', generate_password_hash('rec2026', method='pbkdf2:sha256')))
            
        conn.commit()
        conn.close()
        print("✓ Database Initialized and Verified.")
        _DB_INITIALIZED = True
        return True, "Success"
    except Exception as e:
        print(f"✘ Database Error during init: {e}")
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
    smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port   = int(os.environ.get('SMTP_PORT', 587))
    smtp_user   = os.environ.get('SMTP_USER')
    smtp_pass   = os.environ.get('SMTP_PASS')
    if smtp_pass:
        smtp_pass = smtp_pass.strip().replace(" ", "")

    smtp_user_val = smtp_user or ""
    smtp_pass_val = smtp_pass or ""

    if not smtp_user_val or not smtp_pass_val:
        msg = "!!! Email Error: SMTP_USER or SMTP_PASS not configured in Render environment."
        print(msg)
        add_activity(msg, "warning")
        return

    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&color=000000&bgcolor=ffffff&data={team_id}&margin=10"

    try:
        msg = MIMEMultipart('alternative')
        msg['From']    = f"REC 1.O Hackathon <{smtp_user_val}>"
        msg['To']      = str(to_email)
        msg['Subject'] = f"🎉 [{team_id}] You're In! — REC 1.O Registration Confirmed"

        body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Registration Confirmed - REC 1.O</title></head>
<body style="margin:0;padding:0;background:#0a0f1e;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" bgcolor="#0a0f1e">
    <tr><td align="center" style="padding:40px 20px;">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#0d1426;border-radius:16px;overflow:hidden;border:1px solid #1e2d50;">

        <!-- HEADER BANNER -->
        <tr>
          <td style="background:linear-gradient(135deg,#7c3aed,#00d4ff);padding:36px 30px;text-align:center;">
            <p style="margin:0 0 6px 0;font-size:11px;letter-spacing:4px;color:rgba(255,255,255,0.75);text-transform:uppercase;">Registration Confirmed</p>
            <h1 style="margin:0;font-size:32px;font-weight:900;color:#fff;letter-spacing:2px;">REC 1.O</h1>
            <p style="margin:8px 0 0 0;font-size:13px;color:rgba(255,255,255,0.8);letter-spacing:3px;text-transform:uppercase;">National Level Hackathon</p>
          </td>
        </tr>

        <!-- GREETING -->
        <tr>
          <td style="padding:32px 36px 0 36px;">
            <p style="margin:0;font-size:20px;font-weight:700;color:#fff;">Hello, {leader_name}! 🚀</p>
            <p style="margin:12px 0 0 0;font-size:15px;color:rgba(255,255,255,0.65);line-height:1.7;">
              Your team <strong style="color:#00d4ff;">{team_name}</strong> has been <strong style="color:#00ff88;">successfully registered</strong> for REC 1.O Hackathon.
              Keep the details below safe — you'll need them on the event day.
            </p>
          </td>
        </tr>

        <!-- TEAM ID BOX -->
        <tr>
          <td style="padding:24px 36px 0 36px;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,rgba(124,58,237,0.15),rgba(0,212,255,0.1));border:2px solid rgba(0,212,255,0.4);border-radius:12px;">
              <tr>
                <td style="padding:20px;text-align:center;">
                  <p style="margin:0 0 8px 0;font-size:11px;letter-spacing:3px;color:rgba(255,255,255,0.5);text-transform:uppercase;">Your Official Team ID</p>
                  <p style="margin:0;font-size:34px;font-weight:900;color:#00d4ff;letter-spacing:6px;font-family:'Courier New',monospace;">{team_id}</p>
                  <p style="margin:10px 0 0 0;font-size:12px;color:rgba(255,255,255,0.4);">Use this ID to log into the Participant Portal</p>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- QR CODE BOX -->
        <tr>
          <td style="padding:24px 36px 0 36px;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);border-radius:12px;">
              <tr>
                <td style="padding:24px;text-align:center;">
                  <p style="margin:0 0 4px 0;font-size:11px;letter-spacing:3px;color:rgba(255,255,255,0.5);text-transform:uppercase;">Event Check-in QR Code</p>
                  <p style="margin:0 0 16px 0;font-size:13px;color:rgba(255,255,255,0.45);">Show this at the registration desk on event day</p>
                  <div style="display:inline-block;background:#fff;padding:12px;border-radius:8px;box-shadow:0 0 30px rgba(0,212,255,0.3);">
                    <img src="{qr_url}" alt="QR Code for {team_id}" width="180" height="180" style="display:block;border:0;" />
                  </div>
                  <p style="margin:14px 0 0 0;font-size:13px;color:rgba(255,255,255,0.5);">Encoded ID: <strong style="color:#00d4ff;letter-spacing:2px;">{team_id}</strong></p>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- HOW TO LOGIN -->
        <tr>
          <td style="padding:24px 36px 0 36px;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background:rgba(0,255,136,0.05);border:1px solid rgba(0,255,136,0.2);border-radius:12px;">
              <tr>
                <td style="padding:20px 24px;">
                  <p style="margin:0 0 12px 0;font-size:13px;font-weight:700;color:#00ff88;letter-spacing:2px;text-transform:uppercase;">📱 How to Login to Your Dashboard</p>
                  <p style="margin:0 0 6px 0;font-size:14px;color:rgba(255,255,255,0.7);"><strong style="color:#fff;">Step 1:</strong> Go to the Participant Portal login page.</p>
                  <p style="margin:0 0 6px 0;font-size:14px;color:rgba(255,255,255,0.7);"><strong style="color:#fff;">Step 2:</strong> Enter your Team ID <strong style="color:#00d4ff;">{team_id}</strong> or scan the QR code above.</p>
                  <p style="margin:0 0 6px 0;font-size:14px;color:rgba(255,255,255,0.7);"><strong style="color:#fff;">Step 3:</strong> A 6-digit OTP will be sent to this email address.</p>
                  <p style="margin:0;font-size:14px;color:rgba(255,255,255,0.7);"><strong style="color:#fff;">Step 4:</strong> Enter the OTP to access your team dashboard.</p>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- FOOTER -->
        <tr>
          <td style="padding:32px 36px 36px 36px;text-align:center;border-top:1px solid rgba(255,255,255,0.07);margin-top:24px;">
            <p style="margin:24px 0 6px 0;font-size:13px;color:rgba(255,255,255,0.35);">Good luck &amp; keep hacking!</p>
            <p style="margin:0;font-size:14px;font-weight:700;color:rgba(255,255,255,0.6);">— The REC 1.O Organizing Team</p>
            <p style="margin:16px 0 0 0;font-size:11px;color:rgba(255,255,255,0.2);">If you didn't register for this event, please ignore this email.</p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

        msg.attach(MIMEText(body, 'html'))

        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(str(smtp_user_val), str(smtp_pass_val))
        server.send_message(msg)

        # Admin copy
        try:
            admin_email = "kalinganavarsachin@gmail.com"
            msg.replace_header('To', admin_email)
            msg.replace_header('Subject', f"ADMIN COPY: [{team_id}] {team_name} Registered")
            server.send_message(msg)
        except Exception as admin_err:
            print(f"!!! Failed to send admin copy: {admin_err}")

        server.quit()
        print(f"✓ Confirmation email sent to {to_email}")
        add_activity(f"✓ Registration email sent to Team {team_name} ({to_email})", "success")
    except Exception as e:
        err_msg = f"✘ Failed to send email to {to_email}: {str(e)}"
        print(err_msg)
        add_activity(err_msg, "error")
        import traceback
        traceback.print_exc()



@app.route('/api/admin/debug_email')
def debug_email():
    email = request.args.get('email', 'kalinganavarsachin@gmail.com')
    send_confirmation_email(email, "DEBUG-123", "Debug Team", "Developer")
    return jsonify({"message": f"Instruction sent! Check the 'Activity Feed' on the homepage in 10 seconds to see if it worked or failed.", "target": email})

def add_activity(message, act_type="info"):
    try:
        conn, c = get_db()
        db_execute(c, 'INSERT INTO activity_feed (message, type, created_at) VALUES (?, ?, ?)', 
                  (message, act_type, datetime.datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Failed to add activity: {e}")

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'timestamp': datetime.datetime.now().isoformat()})

@app.route('/admin')
def admin_redirect():
    return redirect('/admin.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

@app.route('/api/feed', methods=['GET'])
def get_feed():
    conn, c = get_db()
    db_execute(c, 'SELECT * FROM activity_feed ORDER BY created_at DESC LIMIT 50')
    feed = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(feed)

# --- SKILL-BASED TEAM FORMATION ---
@app.route('/api/seekers', methods=['GET', 'POST'])
def handle_hacker_seekers():
    if request.method == 'GET':
        conn, c = get_db()
        db_execute(c, 'SELECT * FROM hacker_seekers ORDER BY created_at DESC')
        res = [dict(row) for row in c.fetchall()]
        conn.close()
        return jsonify(res)
    elif request.method == 'POST':
        data = request.json
        conn, c = get_db()
        db_execute(c, 'INSERT INTO hacker_seekers (name, email, skills, bio, linkedin, github, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                  (data.get('name'), data.get('email'), data.get('skills'), data.get('bio'), data.get('linkedin'), data.get('github'), datetime.datetime.now().isoformat()))
        conn.commit()
        conn.close()
        add_activity(f"Hacker {data.get('name')} is looking for a team!", "info")
        return jsonify({'success': True})

# --- MENTOR MARKETPLACE ---
@app.route('/api/mentors', methods=['GET', 'POST'])
def handle_mentors():
    if request.method == 'GET':
        conn, c = get_db()
        db_execute(c, 'SELECT * FROM mentors WHERE available = ?', (1,))
        res = [dict(row) for row in c.fetchall()]
        conn.close()
        return jsonify(res)
    elif request.method == 'POST':
        # Admin only for adding mentors
        if not session.get('is_admin'): return jsonify({'error': 'Unauthorized'}), 401
        data = request.json
        conn, c = get_db()
        db_execute(c, 'INSERT INTO mentors (name, expertise, bio, avatar_url) VALUES (?, ?, ?, ?)',
                  (data.get('name'), data.get('expertise'), data.get('bio'), data.get('avatar_url')))
        conn.commit()
        conn.close()
        return jsonify({'success': True})

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
    conn.close()
    
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
    team_id = data.get('teamId')
    inn = data.get('innovation', 0)
    imp = data.get('impact', 0)
    tec = data.get('tech', 0)
    ui = data.get('ui', 0)
    
    total = (float(inn) + float(imp) + float(tec) + float(ui)) / 4.0
    
    conn, c = get_db()
    db_execute(c, 'INSERT INTO judge_scores (judge_id, team_id, innovation, impact, tech, ui, total_score, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
              (judge_id, team_id, inn, imp, tec, ui, total, datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# --- ADVANCED ANALYTICS ---
@app.route('/api/admin/analytics', methods=['GET'])
@admin_required
def get_analytics():
    conn, c = get_db()
    
    # Check-in velocity (by hour)
    db_execute(c, "SELECT STRFTIME('%H', created_at) as hour, COUNT(*) as count FROM teams WHERE checked_in = 1 GROUP BY hour")
    checkin_velocity = [dict(row) for row in c.fetchall()]
    
    # Help Request Heatmap (by topic)
    db_execute(c, "SELECT topic, COUNT(*) as count FROM help_requests GROUP BY topic")
    help_heatmap = [dict(row) for row in c.fetchall()]
    
    # College-wise participation
    db_execute(c, "SELECT college, COUNT(*) as count FROM teams GROUP BY college")
    college_stats = [dict(row) for row in c.fetchall()]
    
    conn.close()
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
    members = data.get('members', [])
    
    if not team_name or not college or not members:
        return jsonify({'error': 'Missing required fields'}), 400
        
    reg_id = 'REC1-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    created_at = datetime.datetime.now().isoformat()
    
    conn, c = get_db()
    try:
        db_execute(c, 'INSERT INTO teams (id, team_name, college, dept, theme, idea, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)', 
                  (reg_id, team_name, college, dept, theme, idea, created_at))
        
        leader_email = None
        for idx, m in enumerate(members):
            is_leader = 1 if idx == 0 else 0
            if is_leader:
                leader_email = m.get('email')
            db_execute(c, 'INSERT INTO members (team_id, name, year, phone, email, is_leader, avatar_url) VALUES (?, ?, ?, ?, ?, ?, ?)', 
                      (reg_id, m.get('name'), m.get('year'), m.get('phone'), m.get('email'), is_leader, m.get('avatar_url')))
            
        if conn:
            conn.commit()
        add_activity(f"Team {team_name} from {college} has joined REC 1.O!", "success")
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            conn.close()

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
                if not m_email:
                    continue
                try:
                    smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
                    smtp_port   = int(os.environ.get('SMTP_PORT', 587))
                    smtp_user   = os.environ.get('SMTP_USER', '')
                    smtp_pass   = os.environ.get('SMTP_PASS', '')
                    if smtp_pass: smtp_pass = smtp_pass.strip().replace(" ", "")
                    if not smtp_user or not smtp_pass: continue

                    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=180x180&color=000000&bgcolor=ffffff&data={reg_id}&margin=10"

                    from email.mime.multipart import MIMEMultipart as MIME_MP
                    from email.mime.text import MIMEText as MIME_T
                    member_msg = MIME_MP('alternative')
                    member_msg['From']    = f"REC 1.O Hackathon <{smtp_user}>"
                    member_msg['To']      = m_email
                    member_msg['Subject'] = f"🎉 You're part of Team {team_name}! — REC 1.O Hackathon"

                    member_body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0a0f1e;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" bgcolor="#0a0f1e">
    <tr><td align="center" style="padding:40px 20px;">
      <table width="580" cellpadding="0" cellspacing="0" style="max-width:580px;width:100%;background:#0d1426;border-radius:16px;overflow:hidden;border:1px solid #1e2d50;">
        <tr>
          <td style="background:linear-gradient(135deg,#7c3aed,#00d4ff);padding:30px;text-align:center;">
            <h1 style="margin:0;font-size:28px;font-weight:900;color:#fff;letter-spacing:2px;">REC 1.O</h1>
            <p style="margin:6px 0 0 0;font-size:12px;color:rgba(255,255,255,0.8);letter-spacing:3px;text-transform:uppercase;">National Level Hackathon</p>
          </td>
        </tr>
        <tr>
          <td style="padding:28px 32px 0 32px;">
            <p style="margin:0;font-size:19px;font-weight:700;color:#fff;">Welcome to the team, {m_name}! 🚀</p>
            <p style="margin:12px 0 0 0;font-size:14px;color:rgba(255,255,255,0.6);line-height:1.7;">
              You are now officially a member of <strong style="color:#00d4ff;">{team_name}</strong> at REC 1.O Hackathon. Get ready to build something amazing!
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 32px 0 32px;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,rgba(124,58,237,0.15),rgba(0,212,255,0.1));border:2px solid rgba(0,212,255,0.4);border-radius:12px;">
              <tr>
                <td style="padding:18px;text-align:center;">
                  <p style="margin:0 0 6px 0;font-size:11px;letter-spacing:3px;color:rgba(255,255,255,0.5);text-transform:uppercase;">Team ID</p>
                  <p style="margin:0;font-size:30px;font-weight:900;color:#00d4ff;letter-spacing:6px;font-family:'Courier New',monospace;">{reg_id}</p>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 32px 0 32px;text-align:center;">
            <p style="margin:0 0 10px 0;font-size:12px;color:rgba(255,255,255,0.4);letter-spacing:2px;text-transform:uppercase;">Event Check-in QR Code</p>
            <div style="display:inline-block;background:#fff;padding:10px;border-radius:8px;">
              <img src="{qr_url}" alt="QR Code" width="160" height="160" style="display:block;" />
            </div>
          </td>
        </tr>
        <tr>
          <td style="padding:24px 32px 32px 32px;text-align:center;border-top:1px solid rgba(255,255,255,0.07);margin-top:20px;">
            <p style="margin:24px 0 4px 0;font-size:13px;color:rgba(255,255,255,0.35);">Good luck &amp; keep hacking!</p>
            <p style="margin:0;font-size:13px;font-weight:700;color:rgba(255,255,255,0.55);">— The REC 1.O Organizing Team</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body></html>"""

                    member_msg.attach(MIME_T(member_body, 'html'))
                    server = smtplib.SMTP(smtp_server, smtp_port)
                    server.starttls()
                    server.login(smtp_user, smtp_pass)
                    server.send_message(member_msg)
                    server.quit()
                    print(f"✓ Member email sent to {m_name} ({m_email})")
                    add_activity(f"✓ Member welcome email sent to {m_name}", "success")
                except Exception as e:
                    print(f"✘ Failed to send email to {m_name} ({m_email}): {e}")

        threading.Thread(target=send_all_emails).start()

    return jsonify({'success': True, 'regId': reg_id})


@app.route('/api/team/request_login_code', methods=['POST'])
def request_login_code():
    data = request.json
    team_id = data.get('teamId')
    
    if not team_id:
        return jsonify({'error': 'Team ID required'}), 400
        
    conn, c = get_db()
    db_execute(c, 'SELECT * FROM teams WHERE id = ?', (team_id,))
    team = c.fetchone()
    
    if not team:
        conn.close()
        return jsonify({'error': 'Invalid Team ID'}), 404
        
    # Get leader email
    db_execute(c, 'SELECT email, name FROM members WHERE team_id = ? AND is_leader = ?', (team_id, 1))
    leader = c.fetchone()
    
    if not leader:
        conn.close()
        return jsonify({'error': 'No leader found for this team'}), 404
        
    leader_email = leader['email']
    leader_name = leader['name']
    
    # Generate 6-digit code
    code = ''.join(random.choices(string.digits, k=6))
    expires = (datetime.datetime.now() + datetime.timedelta(minutes=10)).isoformat()
    
    # Save to DB (replace if exists)
    db_execute(c, 'INSERT INTO login_codes (team_id, code, expires_at) VALUES (?, ?, ?) ON CONFLICT(team_id) DO UPDATE SET code=excluded.code, expires_at=excluded.expires_at',
              (team_id, code, expires))
    conn.commit()
    conn.close()

    # ── Build OTP email HTML ──────────────────────────────────────────────────
    otp_html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0a0f1e;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" bgcolor="#0a0f1e">
    <tr><td align="center" style="padding:40px 20px;">
      <table width="520" cellpadding="0" cellspacing="0" style="max-width:520px;width:100%;background:#0d1426;border-radius:16px;overflow:hidden;border:1px solid #1e2d50;">
        <tr><td style="background:linear-gradient(135deg,#7c3aed,#00d4ff);padding:28px;text-align:center;">
          <h1 style="margin:0;font-size:26px;font-weight:900;color:#fff;letter-spacing:2px;">REC 1.O</h1>
          <p style="margin:4px 0 0;font-size:11px;color:rgba(255,255,255,0.8);letter-spacing:3px;text-transform:uppercase;">Login Verification</p>
        </td></tr>
        <tr><td style="padding:28px 32px 0 32px;">
          <p style="margin:0;font-size:16px;color:#fff;">Hello <strong>{leader_name}</strong>!</p>
          <p style="margin:10px 0 0;font-size:14px;color:rgba(255,255,255,0.6);line-height:1.6;">Your one-time login code for REC 1.O Participant Portal:</p>
        </td></tr>
        <tr><td style="padding:24px 32px 0 32px;">
          <table width="100%" cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,rgba(124,58,237,0.2),rgba(0,212,255,0.1));border:2px solid rgba(0,212,255,0.5);border-radius:12px;">
            <tr><td style="padding:20px;text-align:center;">
              <p style="margin:0 0 6px;font-size:11px;letter-spacing:3px;color:rgba(255,255,255,0.5);text-transform:uppercase;">Your Access Code</p>
              <p style="margin:0;font-size:42px;font-weight:900;color:#00d4ff;letter-spacing:12px;font-family:'Courier New',monospace;">{code}</p>
              <p style="margin:8px 0 0;font-size:12px;color:rgba(255,255,255,0.35);">Expires in 10 minutes</p>
            </td></tr>
          </table>
        </td></tr>
        <tr><td style="padding:20px 32px 28px 32px;text-align:center;">
          <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.3);">If you didn't request this, ignore this email.</p>
          <p style="margin:8px 0 0;font-size:13px;font-weight:700;color:rgba(255,255,255,0.5);">— REC 1.O Organizing Team</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""

    # ── Send email in background thread so we return instantly ───────────────
    def send_email_bg():
        smtp_user  = (os.environ.get('SMTP_USER') or '').strip()
        smtp_pass  = (os.environ.get('SMTP_PASS') or '').strip().replace(' ', '')
        resend_key = (os.environ.get('RESEND_API_KEY') or '').strip()

        # Method 1: SMTP (port 587 → 465 fallback)
        if smtp_user and smtp_pass:
            for port, use_ssl in [(587, False), (465, True)]:
                try:
                    srv = smtplib.SMTP_SSL('smtp.gmail.com', port, timeout=12) if use_ssl \
                          else smtplib.SMTP('smtp.gmail.com', port, timeout=12)
                    if not use_ssl:
                        srv.starttls()
                    srv.login(smtp_user, smtp_pass)
                    m = MIMEMultipart('alternative')
                    m['From']    = f'REC 1.O <{smtp_user}>'
                    m['To']      = leader_email
                    m['Subject'] = f'{code} — Your REC 1.O Login Code'
                    m.attach(MIMEText(otp_html, 'html'))
                    srv.send_message(m)
                    srv.quit()
                    print(f'[OTP] Sent via SMTP port {port} to {leader_email}')
                    return
                except Exception as e:
                    print(f'[OTP] SMTP port {port} failed: {e}')

        # Method 2: Resend HTTP API (works on Railway/Render, port 443)
        if resend_key:
            try:
                import urllib.request as _ur, json as _json
                payload = _json.dumps({
                    'from': f'REC 1.O <onboarding@resend.dev>',
                    'to': [leader_email],
                    'subject': f'{code} — Your REC 1.O Login Code',
                    'html': otp_html,
                }).encode()
                req = _ur.Request('https://api.resend.com/emails', data=payload,
                    headers={'Authorization': f'Bearer {resend_key}', 'Content-Type': 'application/json'},
                    method='POST')
                _ur.urlopen(req, timeout=15)
                print(f'[OTP] Sent via Resend API to {leader_email}')
                return
            except Exception as e:
                print(f'[OTP] Resend failed: {e}')

        print(f'[OTP] All email methods failed. Code for {team_id}: {code}')

    # Fire-and-forget — respond to user immediately
    threading.Thread(target=send_email_bg, daemon=True).start()

    # Obfuscate email for response
    parts = leader_email.split('@')
    obf   = parts[0][0] + '*' * (len(parts[0]) - 1) + '@' + parts[1]
    return jsonify({'success': True, 'email': obf})



@app.route('/api/team/verify_login_code', methods=['POST'])
def verify_login_code():
    data = request.json
    team_id = data.get('teamId')
    code = data.get('code')
    
    if not team_id or not code:
        return jsonify({'error': 'Missing Team ID or Code'}), 400
        
    conn, c = get_db()
    db_execute(c, 'SELECT * FROM login_codes WHERE team_id = ?', (team_id,))
    record = c.fetchone()
    
    if not record or record['code'] != code:
        conn.close()
        return jsonify({'error': 'Invalid verification code'}), 401
        
    expires = datetime.datetime.fromisoformat(record['expires_at'])
    if datetime.datetime.now() > expires:
        conn.close()
        return jsonify({'error': 'Code expired. Please request a new one.'}), 401
    
    # Successful login - clear code and set session
    db_execute(c, 'DELETE FROM login_codes WHERE team_id = ?', (team_id,))
    conn.commit()
    conn.close()
    
    session['team_id'] = team_id
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
        
    conn.close()
    return jsonify(team)

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
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
    db_execute(c, 'SELECT * FROM teams ORDER BY created_at DESC')
    teams = [dict(row) for row in c.fetchall()]
    for t in teams:
        db_execute(c, 'SELECT * FROM members WHERE team_id = ?', (t['id'],))
        t['members'] = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(teams)

@app.route('/api/admin/teams/<team_id>', methods=['DELETE'])
@admin_required
def delete_team(team_id):
    conn, c = get_db()
    db_execute(c, 'DELETE FROM teams WHERE id = ?', (team_id,))
    db_execute(c, 'DELETE FROM members WHERE team_id = ?', (team_id,))
    db_execute(c, 'DELETE FROM help_requests WHERE team_id = ?', (team_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/checkin', methods=['POST'])
@admin_required
def checkin_team():
    data = request.json
    team_id = data.get('teamId')
    checkin_type = data.get('type', 'morning') # morning, lunch, snack
    
    if not team_id:
        return jsonify({'error': 'Team ID is required'}), 400
        
    conn, c = get_db()
    
    # Check if team exists
    db_execute(c, 'SELECT * FROM teams WHERE id = ?', (team_id,))
    res = c.fetchone()
    team = dict(res or {})
    
    if not team:
        conn.close()
        return jsonify({'error': 'Invalid Team ID. Team not found.'}), 404
        
    column = 'checked_in'
    if checkin_type == 'lunch': column = 'lunch_checkin'
    if checkin_type == 'snack': column = 'snack_checkin'
        
    if team.get(column):
        conn.close()
        return jsonify({'error': f'Team {team["team_name"]} ({team_id}) is already checked in for {checkin_type}.'}), 400

    # Mark as checked in
    db_execute(c, f'UPDATE teams SET {column} = ? WHERE id = ?', (1, team_id))
    conn.commit()
    conn.close()
    
    add_activity(f"Team {team['team_name']} checked in for {checkin_type}!", "info")
    return jsonify({'success': True, 'team_name': team['team_name']})

@app.route('/api/admin/reset_checkins', methods=['POST'])
@admin_required
def reset_checkins():
    conn, c = get_db()
    db_execute(c, f'UPDATE teams SET checked_in = ?, lunch_checkin = ?, snack_checkin = ?', 
               (0, 0, 0))
    conn.commit()
    conn.close()
    add_activity("All team check-in statuses have been reset by administrator.", "warning")
    return jsonify({'success': True, 'message': 'All check-ins have been reset.'})

@app.route('/api/announcements', methods=['GET'])
def get_announcements():
    conn, c = get_db()
    db_execute(c, 'SELECT * FROM announcements WHERE active = ? ORDER BY created_at DESC', (1,))
    announcements = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(announcements)

@app.route('/api/admin/announcements', methods=['GET', 'POST'])
@admin_required
def admin_announcements():
    if request.method == 'GET':
        conn, c = get_db()
        db_execute(c, 'SELECT * FROM announcements ORDER BY created_at DESC')
        announcements = [dict(row) for row in c.fetchall()]
        conn.close()
        return jsonify(announcements)
    elif request.method == 'POST':
        data = request.json
        message = data.get('message')
        if not message:
            return jsonify({'error': 'Message required'}), 400
        conn, c = get_db()
        db_execute(c, 'INSERT INTO announcements (message, created_at, active) VALUES (?, ?, ?)', 
                  (message, datetime.datetime.now().isoformat(), 1))
        conn.commit()
        conn.close()
        return jsonify({'success': True})

@app.route('/api/admin/announcements/<int:id>', methods=['DELETE'])
@admin_required
def delete_announcement(id):
    conn, c = get_db()
    db_execute(c, 'DELETE FROM announcements WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/help', methods=['POST'])
def request_help():
    data = request.json
    team_id = data.get('teamId')
    location = data.get('location')
    topic = data.get('topic')
    
    if not team_id or not location or not topic:
        return jsonify({'error': 'Missing fields'}), 400
        
    conn, c = get_db()
    try:
        db_execute(c, 'SELECT id FROM teams WHERE id = ?', (team_id,))
        if not c.fetchone():
            return jsonify({'error': 'Invalid Team ID'}), 404
            
        db_execute(c, 'INSERT INTO help_requests (team_id, location, topic, status, created_at) VALUES (?, ?, ?, ?, ?)',
                 (team_id, location, topic, 'Pending', datetime.datetime.now().isoformat()))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/help', methods=['GET'])
@admin_required
def get_help_requests():
    conn, c = get_db()
    db_execute(c, '''
        SELECT h.*, t.team_name 
        FROM help_requests h 
        LEFT JOIN teams t ON h.team_id = t.id 
        ORDER BY 
            CASE status WHEN 'Pending' THEN 1 WHEN 'Claimed' THEN 2 ELSE 3 END,
            h.created_at DESC
    ''')
    res = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(res)

@app.route('/api/admin/help/<int:id>', methods=['PATCH'])
@admin_required
def update_help_status(id):
    data = request.json
    status = data.get('status')
    if status not in ['Pending', 'Claimed', 'Resolved']:
        return jsonify({'error': 'Invalid status'}), 400
        
    conn, c = get_db()
    db_execute(c, 'UPDATE help_requests SET status = ? WHERE id = ?', (status, id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/send_email', methods=['POST'])
@admin_required
def send_custom_email():
    data = request.json
    to_email = data.get('to_email')
    subject  = data.get('subject')
    body     = data.get('body')

    if not to_email or not subject or not body:
        return jsonify({'success': False, 'error': 'Missing fields'}), 400

    smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port   = int(os.environ.get('SMTP_PORT', 587))
    smtp_user   = os.environ.get('SMTP_USER')
    smtp_pass   = os.environ.get('SMTP_PASS')
    if smtp_pass:
        smtp_pass = smtp_pass.strip().replace(" ", "")

    if not smtp_user or not smtp_pass:
        return jsonify({'success': False, 'error': 'SMTP not configured'}), 500

    try:
        msg = MIMEMultipart()
        msg['From']    = str(smtp_user or "")
        msg['To']      = str(to_email or "")
        msg['Subject'] = str(subject or "")

        html_body = f"""
        <html><body style="font-family:Arial,sans-serif;line-height:1.6;color:#333;">
          <div style="max-width:600px;margin:0 auto;padding:20px;border:1px solid #ddd;border-top:4px solid #00d4ff;">
            <p style="white-space:pre-line;">{body}</p>
            <br><p style="color:#888;font-size:12px;">â€”<br>REC 1.O Organizing Team</p>
          </div>
        </body></html>
        """
        msg.attach(MIMEText(html_body, 'html'))

        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(str(smtp_user or ""), str(smtp_pass or ""))
        server.send_message(msg)
        server.quit()
        return jsonify({'success': True})
    except Exception as e:
        print(f"!!! Error in send_custom_email: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

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
    conn.close()
    
    add_activity(f"Team {team_id} just submitted their project: {title}!", "success")
    return jsonify({'success': True})

@app.route('/api/projects', methods=['GET'])
def get_projects():
    conn, c = get_db()
    db_execute(c, 'SELECT * FROM teams WHERE project_title IS NOT NULL ORDER BY upvotes DESC')
    projects = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(projects)

@app.route('/api/projects/<team_id>/upvote', methods=['POST'])
def upvote_project(team_id):
    conn, c = get_db()
    db_execute(c, 'UPDATE teams SET upvotes = upvotes + 1 WHERE id=?', (team_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/projects/<team_id>/score', methods=['POST'])
@admin_required
def score_project(team_id):
    data = request.json
    inn = data.get('innovation', 0)
    ui = data.get('ui', 0)
    tech = data.get('tech', 0)
    conn, c = get_db()
    db_execute(c, 'UPDATE teams SET innovation_score=?, ui_score=?, tech_score=? WHERE id=?', (inn, ui, tech, team_id))
    conn.commit()
    conn.close()
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
        conn.close()
        return jsonify({'error': 'Member not found'}), 404
        
    # Handle dict (Postgres) or tuple (SQLite)
    m_team_id = res['team_id'] if isinstance(res, dict) else res[0]
    
    if m_team_id != team_id:
        conn.close()
        return jsonify({'error': 'Unauthorized'}), 401

    if 'avatar_url' in data: db_execute(c, 'UPDATE members SET avatar_url=? WHERE id=?', (data['avatar_url'], member_id))
    if 'linkedin' in data: db_execute(c, 'UPDATE members SET linkedin=? WHERE id=?', (data['linkedin'], member_id))
    if 'github' in data: db_execute(c, 'UPDATE members SET github=? WHERE id=?', (data['github'], member_id))
    
    conn.commit()
    conn.close()
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
    conn.close()
    return jsonify(requests)

@app.route('/api/chat', methods=['GET'])
def get_chat():
    conn, c = get_db()
    db_execute(c, 'SELECT * FROM chat_messages ORDER BY created_at ASC LIMIT 200')
    messages = [dict(row) for row in c.fetchall()]
    conn.close()
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
            conn.close()
            return jsonify({'error': 'Team not found'}), 404
        sender_name = team_res['team_name'] if isinstance(team_res, dict) else team_res[0]
        
        db_execute(c, 'SELECT avatar_url FROM members WHERE team_id = ? AND is_leader = ?', (team_id, 1))
        lead_res = c.fetchone()
        if lead_res:
            a_url = lead_res['avatar_url'] if isinstance(lead_res, dict) else lead_res[0]
            if a_url and a_url != 'null': avatar_url = a_url
            else: avatar_url = ""
    
    db_execute(c, 'INSERT INTO chat_messages (team_id, sender_name, avatar_url, is_admin, message, created_at) VALUES (?, ?, ?, ?, ?, ?)',
              (team_id if team_id else "ADMIN", sender_name, avatar_url, 1 if is_admin_flag else 0, message, datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({'success': True})



if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"Server starting on port {port}...")
    app.run(debug=True, host='0.0.0.0', port=port)
