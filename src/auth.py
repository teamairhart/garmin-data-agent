from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os

auth_bp = Blueprint('auth', __name__)

DATABASE = os.environ.get('DATABASE_PATH', 'users.db')


def normalize_email(email):
    """Normalize email addresses before storage and lookup."""
    return (email or '').strip().lower()


def get_db_connection():
    database_path = os.path.abspath(DATABASE)
    database_dir = os.path.dirname(database_path)
    if database_dir:
        os.makedirs(database_dir, exist_ok=True)
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the user database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Rides table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            distance REAL,
            duration REAL,
            avg_speed REAL,
            avg_heart_rate INTEGER,
            avg_power INTEGER,
            total_ascent INTEGER,
            training_stress_score REAL,
            ride_data TEXT,  -- JSON of ride metrics
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    conn.close()

def create_user(email, password, name):
    """Create a new user"""
    email = normalize_email(email)
    name = (name or '').strip() or email
    password_hash = generate_password_hash(password)
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM users WHERE lower(email) = ?', (email,))
        if cursor.fetchone():
            conn.close()
            return None
        cursor.execute(
            'INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)',
            (email, password_hash, name)
        )
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return user_id
    except sqlite3.IntegrityError:
        if conn:
            conn.close()
        return None  # Email already exists

def verify_user(email, password):
    """Verify user credentials"""
    email = normalize_email(email)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, email, password_hash, name FROM users WHERE lower(email) = ?', (email,))
    user = cursor.fetchone()
    conn.close()
    
    if user and check_password_hash(user['password_hash'], password):
        return {'id': user['id'], 'email': user['email'], 'name': user['name']}
    return None

def _safe_next(target):
    """Only allow same-site relative redirect targets (e.g. /plan)."""
    if target and target.startswith('/') and not target.startswith('//'):
        return target
    return None


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        nxt = _safe_next(request.args.get('next'))
        if nxt:
            session['login_next'] = nxt
        else:
            session.pop('login_next', None)
    if request.method == 'POST':
        email = normalize_email(request.form.get('email'))
        password = request.form['password']

        user = verify_user(email, password)
        if user:
            session['user_id'] = user['id']
            session['user_email'] = user['email']
            session['user_name'] = user['name']
            flash(f'Welcome back, {user["name"]}!', 'success')
            return redirect(session.pop('login_next', None) or '/board')
        else:
            flash('Invalid email or password', 'error')

    return render_template('auth/login.html')

@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'GET':
        nxt = _safe_next(request.args.get('next'))
        if nxt:
            session['login_next'] = nxt
        else:
            session.pop('login_next', None)
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = normalize_email(request.form.get('email'))
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('Passwords do not match', 'error')
        elif len(password) < 6:
            flash('Password must be at least 6 characters', 'error')
        else:
            user_id = create_user(email, password, name)
            if user_id:
                session['user_id'] = user_id
                session['user_email'] = email
                session['user_name'] = name
                flash(f'Welcome to Garmin Data Agent, {name}!', 'success')
                return redirect(session.pop('login_next', None) or '/board')
            else:
                flash('Email already registered', 'error')

    return render_template('auth/signup.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('index'))
