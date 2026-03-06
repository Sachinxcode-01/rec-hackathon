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

# Load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("python-dotenv not installed. Run: pip install python-dotenv")

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)
app.secret_key = os.environ.get('SECRET_KEY', 'REC1O_SUPER_SECRET_KEY_DEVELOPMENT')

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

_DB_INITIALIZED = False

def init_db():
    global _DB_INITIALIZED
    if _DB_INITIALIZED: return
    
    print(f">>> INITIALIZING DATABASE AT: {DB_PATH}", flush=True)
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        print("Connected to SQLite.", flush=True)
        c.execute('''
            CREATE TABLE IF NOT EXISTS teams (
                id TEXT PRIMARY KEY,
                team_name TEXT,
                college TEXT,
                dept TEXT,
                theme TEXT,
                idea TEXT,
                created_at TEXT,
                checked_in BOOLEAN DEFAULT 0,
                lunch_checkin BOOLEAN DEFAULT 0,
                snack_checkin BOOLEAN DEFAULT 0,
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
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id TEXT,
                name TEXT,
                year TEXT,
                phone TEXT,
                email TEXT,
                is_leader INTEGER,
                avatar_url TEXT,
                linkedin TEXT,
                github TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT,
                created_at TEXT,
                active INTEGER
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS help_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id TEXT,
                location TEXT,
                topic TEXT,
                status TEXT,
                created_at TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS activity_feed (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT,
                type TEXT,
                created_at TEXT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id TEXT,
                sender_name TEXT,
                avatar_url TEXT,
                is_admin BOOLEAN DEFAULT 0,
                message TEXT,
                created_at TEXT
            )
        ''')
        conn.commit()
        conn.close()
        print("âœ“ Database Initialized and Verified.")
    except Exception as e:
        print(f"âœ— Database Error: {e}")

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

def send_confirmation_email(to_email, team_id, team_name):
    smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    smtp_user = os.environ.get('SMTP_USER')
    smtp_pass = os.environ.get('SMTP_PASS')
    
    if not smtp_user or not smtp_pass:
        print("Email not sent: SMTP_USER or SMTP_PASS not configured. To enable emails, configure these environment variables.")
        return
        
    try:
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = to_email
        msg['Subject'] = "Registration Confirmed - REC 1.O Hackathon"
        
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-top: 4px solid #00d4ff;">
                <h2 style="color: #060b18;">Welcome to REC 1.O Hackathon, Team {team_name}!</h2>
                <p>Your registration was successfully processed.</p>
                <div style="background: #f4f4f4; padding: 15px; text-align: center; border-radius: 5px; margin: 20px 0;">
                    <p style="margin: 0; font-size: 16px;"><strong>Your Official Team ID:</strong></p>
                    <h1 style="color: #7c3aed; margin: 10px 0;">{team_id}</h1>
                </div>
                <p>Please keep this ID safe as you will need it for project submissions and if you need to request mentor help during the event.</p>
                <div style="background: #e0f2fe; padding: 15px; text-align: center; border-radius: 5px; margin: 20px 0;">
                    <p style="margin: 0; font-size: 16px; color: #0369a1;"><strong>Event Check-in QR Code</strong></p>
                    <p style="margin: 5px 0 10px 0; font-size: 13px; color: #0c4a6e;">Show this QR code at the registration desk on the day of the event.</p>
                    <img src="https://api.qrserver.com/v1/create-qr-code/?size=150x150&data={team_id}" alt="QR Code" style="display:inline-block; border: 4px solid white; border-radius: 4px;" />
                </div>
                <p>Don't forget to join our Discord Server for all virtual communications: <a href="#" style="color: #00d4ff;">discord.gg/placeholder</a></p>
                <br>
                <p>Good luck!<br><strong>REC 1.O Organizing Team</strong></p>
            </div>
        </body>
        </html>
        """
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        print(f"Confirmation email successfully sent to {to_email}")
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")

def add_activity(message, act_type="info"):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('INSERT INTO activity_feed (message, type, created_at) VALUES (?, ?, ?)', 
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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM activity_feed ORDER BY created_at DESC LIMIT 50')
    feed = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(feed)

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
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('INSERT INTO teams (id, team_name, college, dept, theme, idea, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)', 
                  (reg_id, team_name, college, dept, theme, idea, created_at))
        
        leader_email = None
        for idx, m in enumerate(members):
            is_leader = 1 if idx == 0 else 0
            if is_leader:
                leader_email = m.get('email')
            c.execute('INSERT INTO members (team_id, name, year, phone, email, is_leader, avatar_url) VALUES (?, ?, ?, ?, ?, ?, ?)', 
                      (reg_id, m.get('name'), m.get('year'), m.get('phone'), m.get('email'), is_leader, m.get('avatar_url')))
            
        conn.commit()
        add_activity(f"Team {team_name} from {college} has joined REC 1.O!", "success")
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

    # Trigger email function in background thread to avoid portal lag
    if leader_email:
        threading.Thread(target=send_confirmation_email, args=(leader_email, reg_id, team_name)).start()

    return jsonify({'success': True, 'regId': reg_id})

@app.route('/api/team/login', methods=['POST'])
def team_login():
    data = request.get_json()
    team_id = data.get('teamId')
    
    if not team_id:
        return jsonify({'success': False, 'error': 'Team ID is required'}), 400

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM teams WHERE id = ?', (team_id,))
    team = c.fetchone()
    conn.close()

    if team:
        session['team_id'] = team_id
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Invalid Team ID'}), 401

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
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM teams WHERE id = ?', (team_id,))
    team = dict(c.fetchone() or {})
    
    if team:
        c.execute('SELECT * FROM members WHERE team_id = ?', (team_id,))
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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM teams ORDER BY created_at DESC')
    teams = [dict(row) for row in c.fetchall()]
    for t in teams:
        c.execute('SELECT * FROM members WHERE team_id = ?', (t['id'],))
        t['members'] = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(teams)

@app.route('/api/admin/teams/<team_id>', methods=['DELETE'])
@admin_required
def delete_team(team_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM teams WHERE id = ?', (team_id,))
    c.execute('DELETE FROM members WHERE team_id = ?', (team_id,))
    c.execute('DELETE FROM help_requests WHERE team_id = ?', (team_id,))
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
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Check if team exists
    c.execute('SELECT * FROM teams WHERE id = ?', (team_id,))
    team = c.fetchone()
    
    if not team:
        conn.close()
        return jsonify({'error': 'Invalid Team ID. Team not found.'}), 404
        
    column = 'checked_in'
    if checkin_type == 'lunch': column = 'lunch_checkin'
    if checkin_type == 'snack': column = 'snack_checkin'
        
    if team[column]:
        conn.close()
        return jsonify({'error': f'Team {team["team_name"]} ({team_id}) is already checked in for {checkin_type}.'}), 400

    # Mark as checked in
    c.execute(f'UPDATE teams SET {column} = 1 WHERE id = ?', (team_id,))
    conn.commit()
    conn.close()
    
    add_activity(f"Team {team['team_name']} checked in for {checkin_type}!", "info")
    return jsonify({'success': True, 'team_name': team['team_name']})

@app.route('/api/admin/reset_checkins', methods=['POST'])
@admin_required
def reset_checkins():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE teams SET checked_in = 0, lunch_checkin = 0, snack_checkin = 0')
    conn.commit()
    conn.close()
    add_activity("All team check-in statuses have been reset by administrator.", "warning")
    return jsonify({'success': True, 'message': 'All check-ins have been reset.'})

@app.route('/api/announcements', methods=['GET'])
def get_announcements():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM announcements WHERE active = 1 ORDER BY created_at DESC')
    announcements = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(announcements)

@app.route('/api/admin/announcements', methods=['GET', 'POST'])
@admin_required
def admin_announcements():
    if request.method == 'GET':
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT * FROM announcements ORDER BY created_at DESC')
        announcements = [dict(row) for row in c.fetchall()]
        conn.close()
        return jsonify(announcements)
    elif request.method == 'POST':
        data = request.json
        message = data.get('message')
        if not message:
            return jsonify({'error': 'Message required'}), 400
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('INSERT INTO announcements (message, created_at, active) VALUES (?, ?, 1)', 
                  (message, datetime.datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return jsonify({'success': True})

@app.route('/api/admin/announcements/<int:id>', methods=['DELETE'])
@admin_required
def delete_announcement(id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM announcements WHERE id = ?', (id,))
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
        
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('SELECT id FROM teams WHERE id = ?', (team_id,))
        if not c.fetchone():
            return jsonify({'error': 'Invalid Team ID'}), 404
            
        c.execute('INSERT INTO help_requests (team_id, location, topic, status, created_at) VALUES (?, ?, ?, ?, ?)',
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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('''
        SELECT h.*, t.team_name 
        FROM help_requests h 
        LEFT JOIN teams t ON h.team_id = t.id 
        ORDER BY 
            CASE status WHEN 'Pending' THEN 1 WHEN 'Claimed' THEN 2 ELSE 3 END,
            h.created_at DESC
    ''')
    requests = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(requests)

@app.route('/api/admin/help/<int:id>', methods=['PATCH'])
@admin_required
def update_help_status(id):
    data = request.json
    status = data.get('status')
    if status not in ['Pending', 'Claimed', 'Resolved']:
        return jsonify({'error': 'Invalid status'}), 400
        
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE help_requests SET status = ? WHERE id = ?', (status, id))
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

    if not smtp_user or not smtp_pass:
        return jsonify({'success': False, 'error': 'SMTP not configured'}), 500

    try:
        msg = MIMEMultipart()
        msg['From']    = smtp_user
        msg['To']      = to_email
        msg['Subject'] = subject

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
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        return jsonify({'success': True})
    except Exception as e:
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

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE teams SET github_link=?, demo_link=?, tech_stack=?, project_title=?, project_desc=? WHERE id=?', (github, demo, tech, title, desc, team_id))
    conn.commit()
    conn.close()
    
    add_activity(f"Team {team_id} just submitted their project: {title}!", "success")
    return jsonify({'success': True})

@app.route('/api/projects', methods=['GET'])
def get_projects():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM teams WHERE project_title IS NOT NULL ORDER BY upvotes DESC')
    projects = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(projects)

@app.route('/api/projects/<team_id>/upvote', methods=['POST'])
def upvote_project(team_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE teams SET upvotes = upvotes + 1 WHERE id=?', (team_id,))
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
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE teams SET innovation_score=?, ui_score=?, tech_score=? WHERE id=?', (inn, ui, tech, team_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/team/members/<int:member_id>', methods=['PATCH'])
def update_member(member_id):
    if not session.get('team_id'): return jsonify({'error': 'Unauthorized'}), 401
    team_id = session.get('team_id')
    data = request.json
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT team_id FROM members WHERE id=?', (member_id,))
    res = c.fetchone()
    if not res or res[0] != team_id:
        conn.close()
        return jsonify({'error': 'Unauthorized'}), 401

    if 'avatar_url' in data: c.execute('UPDATE members SET avatar_url=? WHERE id=?', (data['avatar_url'], member_id))
    if 'linkedin' in data: c.execute('UPDATE members SET linkedin=? WHERE id=?', (data['linkedin'], member_id))
    if 'github' in data: c.execute('UPDATE members SET github=? WHERE id=?', (data['github'], member_id))
    
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/team/help', methods=['GET'])
def team_help_requests():
    if not session.get('team_id'): return jsonify({'error': 'Unauthorized'}), 401
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('''
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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM chat_messages ORDER BY created_at ASC LIMIT 200')
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
    
    is_admin = 1 if session.get('is_admin') else 0
    team_id = session.get('team_id')
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    sender_name = "Admin"
    avatar_url = "logo.jpg"
    
    if not is_admin and team_id:
        c.execute('SELECT team_name FROM teams WHERE id = ?', (team_id,))
        team = c.fetchone()
        sender_name = team[0] if team else "Unknown Team"
        c.execute('SELECT avatar_url FROM members WHERE team_id = ? AND is_leader = 1', (team_id,))
        lead = c.fetchone()
        if lead and lead[0] and lead[0] != 'null': avatar_url = lead[0]
        else: avatar_url = ""
    
    c.execute('INSERT INTO chat_messages (team_id, sender_name, avatar_url, is_admin, message, created_at) VALUES (?, ?, ?, ?, ?, ?)',
              (team_id if team_id else "ADMIN", sender_name, avatar_url, is_admin, message, datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"Server starting on port {port}...")
    app.run(debug=True, host='0.0.0.0', port=port)
