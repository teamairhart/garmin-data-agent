from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os

auth_bp = Blueprint('auth', __name__)

DATABASE = 'users.db'

def init_db():
    """Initialize the user database"""
    conn = sqlite3.connect(DATABASE)
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
    password_hash = generate_password_hash(password)
    
    try:
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)',
            (email, password_hash, name)
        )
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return user_id
    except sqlite3.IntegrityError:
        return None  # Email already exists

def verify_user(email, password):
    """Verify user credentials"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('SELECT id, password_hash, name FROM users WHERE email = ?', (email,))
    user = cursor.fetchone()
    conn.close()
    
    if user and check_password_hash(user[1], password):
        return {'id': user[0], 'email': email, 'name': user[2]}
    return None

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        user = verify_user(email, password)
        if user:
            session['user_id'] = user['id']
            session['user_email'] = user['email'] 
            session['user_name'] = user['name']
            flash(f'Welcome back, {user["name"]}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid email or password', 'error')
    
    return render_template('auth/login.html')

@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
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
                return redirect(url_for('index'))
            else:
                flash('Email already registered', 'error')
    
    return render_template('auth/signup.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('index'))