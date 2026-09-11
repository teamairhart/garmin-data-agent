from datetime import date
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
import os
from werkzeug.utils import secure_filename
import zipfile
import tempfile
from src.agents.data_analyzer import ride_analyzer
from src.agents.update_monitor import update_monitor
from src.auth import auth_bp, init_db
from src.dashboard_data import build_dashboard_context
from src.training_log import (create_gym_session, get_workout_logs, init_training_tables, list_recent_gym_sessions,
                              upsert_workout_log, init_strength_columns, upsert_gym_session, list_gym_sessions,
                              strength_summary)
from src.strength_log import parse_workout_log, coerce_session, load_exercise_library
from src.strength_plan import (load_strength_plan, current_phase, phase_progress, days_to_race, ladder_status,
                               week_view, week_label)
from src.plan_tracker import (init_plan_tables, load_plan, get_completions, set_completion,
                              progress_summary, plan_prescriptions, plan_week_rows)
from src.board import (init_board_tables, get_calendar, set_calendar_day, list_reports,
                       upsert_report, record_upload, list_uploads, get_upload, upload_dir,
                       init_trends_table, get_trends, set_trends)
from demo_data import generate_demo_ride_data
from src.fit_parser import load_single_fit_activity

app = Flask(__name__)

# Production-ready configuration - Imperial units enabled
if os.environ.get('FLASK_ENV') == 'production':
    app.secret_key = os.environ.get('SECRET_KEY', 'fallback-secret-key')
    app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB for production
else:
    app.secret_key = 'dev-secret-key-change-in-production'

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'fit', 'zip'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Register authentication blueprint
app.register_blueprint(auth_bp, url_prefix='/auth')

# Initialize database
init_db()
init_training_tables()
init_strength_columns()
init_plan_tables()
init_board_tables()
init_trends_table()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def parse_fit_file(fit_file_path):
    """Parse FIT file and extract ride data"""
    try:
        df, session_data = load_single_fit_activity(fit_file_path)
        return df, session_data
    except Exception as e:
        return None, str(e)

def extract_ride_metrics(df, session_data):
    """Extract key metrics from ride data - converted to Imperial units"""
    if df is None or df.empty:
        return {}
    
    # Conversion constants
    METERS_TO_MILES = 0.000621371
    METERS_TO_FEET = 3.28084
    MPS_TO_MPH = 2.23694
    
    # Handle Garmin's enhanced fields
    metrics = {
        'total_distance': session_data.get('total_distance', 0) * METERS_TO_MILES,  # Convert to miles
        'total_time': session_data.get('total_timer_time', 0) / 3600 if 'total_timer_time' in session_data else 0,  # Convert to hours
        'avg_speed': session_data.get('enhanced_avg_speed', session_data.get('avg_speed', 0)) * MPS_TO_MPH,  # Convert to mph
        'max_speed': session_data.get('enhanced_max_speed', session_data.get('max_speed', 0)) * MPS_TO_MPH,  # Convert to mph
        'avg_heart_rate': session_data.get('avg_heart_rate', 0),
        'max_heart_rate': session_data.get('max_heart_rate', 0),
        'avg_power': session_data.get('avg_power', 0),
        'max_power': session_data.get('max_power', session_data.get('normalized_power', 0)),
        'total_ascent': session_data.get('total_ascent', 0) * METERS_TO_FEET,  # Convert to feet
        'total_descent': session_data.get('total_descent', 0) * METERS_TO_FEET,  # Convert to feet
        'normalized_power': session_data.get('normalized_power', 0),
        'training_stress_score': session_data.get('training_stress_score', 0)
    }
    
    return metrics

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/dashboard')
def dashboard():
    context = build_dashboard_context(today=date.today())
    workout_logs = {}
    recent_gym_sessions = []
    if session.get('user_id'):
        workout_logs = get_workout_logs(int(session['user_id']))
        recent_gym_sessions = list_recent_gym_sessions(int(session['user_id']))
    return render_template(
        'dashboard.html',
        workout_logs=workout_logs,
        recent_gym_sessions=recent_gym_sessions,
        **context,
    )

@app.route('/plan')
@app.route('/plan/<athlete>')
def plan(athlete='jonathan'):
    """Interactive day-by-day race plan with check-offs (per athlete)."""
    if athlete not in ('jonathan', 'robert'):
        return redirect(url_for('plan'))
    plan_data = load_plan(athlete)
    completions = {}
    if session.get('user_id'):
        completions = get_completions(int(session['user_id']))
    summary = progress_summary(plan_data, completions)
    return render_template(
        'plan.html',
        plan=plan_data,
        completions=completions,
        summary=summary,
        today=date.today().isoformat(),
        logged_in=bool(session.get('user_id')),
    )


@app.route('/plan/toggle', methods=['POST'])
def plan_toggle():
    """Persist a single check-off (requires login)."""
    if not session.get('user_id'):
        return jsonify({'ok': False, 'error': 'login_required'}), 401
    payload = request.get_json(silent=True) or {}
    item_id = payload.get('item_id')
    completed = bool(payload.get('completed'))
    if not item_id:
        return jsonify({'ok': False, 'error': 'missing item_id'}), 400
    set_completion(int(session['user_id']), item_id, completed, payload.get('notes'))
    plan_data = load_plan()
    summary = progress_summary(plan_data, get_completions(int(session['user_id'])))
    return jsonify({'ok': True, 'summary': summary})


# ---------------- P2P accountability board ----------------

from datetime import datetime as _dt, timezone


def _board_login_required_json():
    if not session.get('user_id'):
        return jsonify({'ok': False, 'error': 'login_required'}), 401
    return None


@app.route('/board')
def board():
    """Shared Airhart × Raff accountability board."""
    if not session.get('user_id'):
        return redirect(url_for('auth.login', next='/board'))
    reports = list_reports()
    for r in reports:
        r['label'] = _dt.strptime(r['day'], '%Y-%m-%d').strftime('%a %b %d').replace(' 0', ' ')
    uploads = list_uploads()[:6]
    for u in uploads:
        u['when'] = (u['uploaded_at'] or '')[:16].replace('T', ' ')
        u['stale'] = False
        if u['status'] == 'received' and u.get('uploaded_at'):
            try:
                age_s = (_dt.now(timezone.utc) - _dt.fromisoformat(u['uploaded_at'])).total_seconds()
                u['stale'] = age_s > 30 * 60
            except ValueError:
                pass
    plan_days = {'JA': plan_prescriptions('jonathan'), 'RR': plan_prescriptions('robert')}
    report_idx = {'JA': {}, 'RR': {}}
    for r in reports:
        if r['athlete'] in report_idx:
            report_idx[r['athlete']][r['day']] = r.get('subline') or r['title']
    return render_template('board.html', reports=reports, cal_state=get_calendar(), uploads=uploads,
                           plan_days=plan_days, report_idx=report_idx, plan_weeks=plan_week_rows(),
                           trends=get_trends())


@app.route('/board/trends', methods=['GET', 'POST'])
def board_trends():
    """Fitness-trends payload for the board (pushed by scripts/push_trends.py)."""
    err = _board_login_required_json()
    if err:
        return err
    if request.method == 'GET':
        return jsonify({'ok': True, 'trends': get_trends()})
    payload = request.get_json(silent=True) or {}
    try:
        set_trends(payload)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    return jsonify({'ok': True})


@app.route('/board/calendar', methods=['GET', 'POST'])
def board_calendar():
    err = _board_login_required_json()
    if err:
        return err
    if request.method == 'GET':
        return jsonify({'ok': True, 'calendar': get_calendar()})
    payload = request.get_json(silent=True) or {}
    try:
        result = set_calendar_day(
            payload.get('athlete', ''), payload.get('day', ''),
            loc=payload.get('loc'), ex=payload.get('ex'),
            user_id=int(session['user_id']),
        )
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    return jsonify({'ok': True, 'day': result})


@app.route('/board/upload', methods=['POST'])
def board_upload():
    err = _board_login_required_json()
    if err:
        return err
    f = request.files.get('file')
    if f is None or not f.filename:
        return jsonify({'ok': False, 'error': 'no file'}), 400
    if not allowed_file(f.filename):
        return jsonify({'ok': False, 'error': f.filename + ': .zip or .fit only'}), 400
    safe = secure_filename(f.filename)
    dest = upload_dir() / ('%s_%s' % (_dt.now().strftime('%Y%m%d%H%M%S'), safe))
    f.save(str(dest))
    uid = record_upload(safe, str(dest), dest.stat().st_size, int(session['user_id']))
    return jsonify({'ok': True, 'id': uid, 'filename': safe, 'size': dest.stat().st_size})


@app.route('/board/uploads')
def board_uploads():
    err = _board_login_required_json()
    if err:
        return err
    return jsonify({'ok': True, 'uploads': list_uploads()})


@app.route('/board/uploads/<int:uid>/status', methods=['POST'])
def board_upload_status(uid):
    """Mark an upload's pipeline status (used by the Mac-side import pass)."""
    err = _board_login_required_json()
    if err:
        return err
    status = (request.get_json(silent=True) or {}).get('status', '')
    if status not in ('received', 'analyzed', 'error'):
        return jsonify({'ok': False, 'error': 'bad status'}), 400
    from src.board import set_upload_status
    set_upload_status(uid, status)
    return jsonify({'ok': True})


@app.route('/board/uploads/<int:uid>/download')
def board_upload_download(uid):
    err = _board_login_required_json()
    if err:
        return err
    rec = get_upload(uid)
    if not rec or not os.path.exists(rec['stored_path']):
        return jsonify({'ok': False, 'error': 'not found'}), 404
    from flask import send_file
    return send_file(rec['stored_path'], as_attachment=True, download_name=rec['filename'])


@app.route('/board/reports', methods=['POST'])
def board_reports_post():
    """Publish/update a coached ride report (used by the Mac-side pipeline)."""
    err = _board_login_required_json()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    try:
        upsert_report(payload.get('athlete', ''), payload.get('day', ''),
                      payload.get('title', ''), payload.get('subline', ''),
                      payload.get('body_html', ''))
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    return jsonify({'ok': True})


@app.route('/demo')
def demo():
    """Demo route with sample data"""
    # Generate demo data
    df, session_data = generate_demo_ride_data()
    
    # Load data into the analyzer
    ride_analyzer.load_ride_data(df, session_data)
    
    # Store in session for query processing
    session['ride_loaded'] = True
    
    metrics = extract_ride_metrics(df, session_data)
    
    return render_template('results.html', metrics=metrics, data_available=True, demo_mode=True)

@app.route('/test-real-data')
def test_real_data():
    """Test with your actual Garmin file"""
    try:
        df, session_data = load_single_fit_activity('/Users/jonathan_airhart/Downloads/19975720234_ACTIVITY.fit')
        
        # Load data into the analyzer
        ride_analyzer.load_ride_data(df, session_data)
        
        # Store in session for query processing
        session['ride_loaded'] = True
        
        metrics = extract_ride_metrics(df, session_data)
        
        return render_template('results.html', metrics=metrics, data_available=True, demo_mode=False)
    
    except Exception as e:
        flash(f'Error loading real data: {str(e)}')
        return redirect(url_for('index'))

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        flash('No file selected')
        return redirect(request.url)
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected')
        return redirect(request.url)
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        fit_file_path = filepath
        
        # Handle zip files
        if filename.lower().endswith('.zip'):
            with tempfile.TemporaryDirectory() as temp_dir:
                with zipfile.ZipFile(filepath, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                    
                    # Find .fit file in extracted contents
                    for extracted_file in os.listdir(temp_dir):
                        if extracted_file.lower().endswith('.fit'):
                            fit_file_path = os.path.join(temp_dir, extracted_file)
                            break
                    else:
                        flash('No .fit file found in zip archive')
                        return redirect(url_for('index'))
                
                # Parse the fit file
                df, session_data = parse_fit_file(fit_file_path)
        else:
            # Direct .fit file
            df, session_data = parse_fit_file(fit_file_path)
        
        # Clean up uploaded file
        os.remove(filepath)
        
        if df is None:
            flash(f'Error parsing file: {session_data}')
            return redirect(url_for('index'))
        
        metrics = extract_ride_metrics(df, session_data)
        
        # Load data into the analyzer
        ride_analyzer.load_ride_data(df, session_data)
        
        # Store in session for query processing
        session['ride_loaded'] = True
        
        return render_template('results.html', metrics=metrics, data_available=True)
    
    flash('Invalid file type. Please upload .fit or .zip files only.')
    return redirect(url_for('index'))

@app.route('/query', methods=['POST'])
def query_data():
    print(f"DEBUG: Session ride_loaded: {session.get('ride_loaded')}")
    print(f"DEBUG: Ride analyzer has data: {ride_analyzer.ride_data is not None}")
    print(f"DEBUG: Ride analyzer data length: {len(ride_analyzer.ride_data) if ride_analyzer.ride_data is not None else 'None'}")
    
    if not session.get('ride_loaded'):
        return jsonify({'response': 'Please upload a ride file first!'})
    
    query_text = request.json.get('query', '')
    print(f"DEBUG: Query text: '{query_text}'")
    
    if not query_text:
        return jsonify({'response': 'Please enter a question!'})
    
    try:
        # Use the data analyzer to process the query
        response = ride_analyzer.process_natural_query(query_text)
        print(f"DEBUG: Response length: {len(response)}")
        return jsonify({'response': response})
    except Exception as e:
        print(f"DEBUG: Exception in query processing: {e}")
        return jsonify({'response': f'Error processing query: {str(e)}'})

@app.route('/system/updates')
def system_updates():
    """System update monitoring page"""
    report = update_monitor.generate_update_report()
    return f"<pre>{report}</pre>"

@app.route('/system/debug-llm')
def debug_llm():
    """Debug LLM API connection"""
    from src.agents.llm_agent import llm_agent
    import os
    
    debug_info = {
        "has_token": bool(os.getenv('HUGGING_FACE_API_TOKEN')),
        "token_preview": os.getenv('HUGGING_FACE_API_TOKEN', '')[:10] + '...' if os.getenv('HUGGING_FACE_API_TOKEN') else 'None',
        "current_model": llm_agent.current_model,
        "api_url": llm_agent.api_url,
        "available_models": llm_agent.models_to_try
    }
    
    # Test with simple query
    if debug_info["has_token"]:
        test_result = llm_agent.query_llm("Hello, test message.")
        debug_info["test_result"] = test_result if test_result else "No response"
        debug_info["test_result_length"] = len(test_result) if test_result else 0
    else:
        debug_info["test_result"] = "No token - cannot test"
    
    return f"<pre>{debug_info}</pre>"



# ---------------- Strength & Conditioning (Workout log grammar) ----------------

import re as _re


def _trends_ftp_w(trends, athlete='JA'):
    """Pull 'Est. FTP' (watts) out of the Fitness Trends payload pushed by push_trends.py."""
    try:
        for t in (trends or {}).get('athletes', {}).get(athlete, {}).get('kpis', []):
            if str(t.get('label', '')).lower().startswith('est. ftp'):
                m = _re.search(r'(\d+(?:\.\d+)?)', str(t.get('value', '')))
                if m:
                    return float(m.group(1))
    except Exception:
        return None
    return None


def _ingest_sessions(user_id, parsed, source):
    results = []
    for sess in parsed:
        results.append(upsert_gym_session(user_id, sess, source=source))
    return results


@app.route('/strength')
def strength():
    """Strength & Conditioning page: plan, this week, log, history, ladder."""
    if not session.get('user_id'):
        return redirect(url_for('auth.login', next='/strength'))
    user_id = int(session['user_id'])
    today = date.today()
    plan_data = load_strength_plan()
    phase = current_phase(plan_data, today)
    sessions = list_gym_sessions(user_id)
    summary = strength_summary(user_id, today, sessions=sessions)
    ladder, next_rung = ladder_status(plan_data, summary['bench']['best_e1rm'] if summary['bench'] else None, today)
    week = week_view(plan_data, phase, summary['week']['sessions'])
    wkg = None
    ftp_w = _trends_ftp_w(get_trends())
    if ftp_w:
        bw = summary['latest_bodyweight']['value'] if summary['latest_bodyweight'] else None
        assumed = bw is None
        if bw is None:
            bw = next((g.get('start') for g in plan_data.get('goals', []) if g.get('key') == 'bodyweight'), None)
        if bw:
            wkg = {'ftp_w': int(ftp_w), 'lb': bw, 'wkg': round(ftp_w / (bw * 0.45359237), 2), 'assumed': assumed}
    return render_template(
        'strength.html',
        plan=plan_data, phase=phase, phase_prog=phase_progress(phase, today),
        days_to_race=days_to_race(plan_data, today), ladder=ladder, next_rung=next_rung,
        week=week, week_label=week_label(today), sessions=sessions, summary=summary, wkg=wkg,
        today=today.isoformat(),
    )


@app.route('/strength/log', methods=['POST'])
def strength_log_form():
    """Textarea on the page: same grammar as the Obsidian note."""
    if not session.get('user_id'):
        flash('Please log in to save sessions.', 'error')
        return redirect(url_for('auth.login', next='/strength'))
    text = request.form.get('text', '')
    parsed = parse_workout_log(text)
    if not parsed:
        flash('Nothing parsed — the first line must be a header like "## 2026-09-10 · Upper A".', 'error')
        return redirect(url_for('strength'))
    results = _ingest_sessions(int(session['user_id']), parsed, source='page')
    n_new = sum(1 for r in results if r['created'])
    warn = [w for r in results for w in r['warnings']]
    flash(f"Saved {len(results)} session(s) ({n_new} new, {len(results) - n_new} replaced)." +
          (f" {len(warn)} warning(s): " + '; '.join(warn[:4]) if warn else ''), 'success' if not warn else 'error')
    return redirect(url_for('strength'))


@app.route('/strength/sessions', methods=['GET', 'POST'])
def strength_sessions_api():
    """JSON API used by scripts/push_workouts.py. POST {"text": "..."} or {"sessions": [...]}; GET lists."""
    err = _board_login_required_json()
    if err:
        return err
    user_id = int(session['user_id'])
    if request.method == 'GET':
        return jsonify({'ok': True, 'sessions': list_gym_sessions(user_id, limit=int(request.args.get('limit', 50)))})
    payload = request.get_json(silent=True) or {}
    parsed = []
    try:
        if payload.get('text'):
            parsed = parse_workout_log(str(payload['text']))
        else:
            lib = load_exercise_library()
            parsed = [coerce_session(d, lib) for d in (payload.get('sessions') or [])]
    except (ValueError, TypeError) as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    if not parsed:
        return jsonify({'ok': False, 'error': 'no sessions in payload'}), 400
    results = _ingest_sessions(user_id, parsed, source='push')
    return jsonify({'ok': True, 'results': results})


@app.route('/dashboard/log-workout', methods=['POST'])
def log_workout():
    if not session.get('user_id'):
        flash('Please log in to save workout logs.', 'error')
        return redirect(url_for('auth.login'))

    planned_date = request.form.get('planned_date', '').strip()
    workout_name = request.form.get('workout_name', '').strip()
    workout_type = request.form.get('workout_type', '').strip() or None
    location = request.form.get('location', '').strip() or None
    status = request.form.get('status', 'completed').strip() or 'completed'
    duration_minutes_raw = request.form.get('duration_minutes', '').strip()
    rpe_raw = request.form.get('rpe', '').strip()
    notes = request.form.get('notes', '').strip() or None

    if not planned_date or not workout_name:
        flash('Workout log is missing required fields.', 'error')
        return redirect(url_for('dashboard'))

    duration_minutes = int(duration_minutes_raw) if duration_minutes_raw else None
    rpe = int(rpe_raw) if rpe_raw else None
    upsert_workout_log(
        user_id=int(session['user_id']),
        planned_date=planned_date,
        workout_name=workout_name,
        workout_type=workout_type,
        location=location,
        status=status,
        duration_minutes=duration_minutes,
        rpe=rpe,
        notes=notes,
    )
    flash(f'Saved workout log for {workout_name}.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/dashboard/log-gym', methods=['POST'])
def log_gym():
    if not session.get('user_id'):
        flash('Please log in to save gym sessions.', 'error')
        return redirect(url_for('auth.login'))

    session_date = request.form.get('session_date', '').strip() or date.today().isoformat()
    title = request.form.get('title', '').strip() or None
    notes = request.form.get('notes', '').strip() or None

    exercise_names = request.form.getlist('exercise_name[]')
    set_numbers = request.form.getlist('set_number[]')
    reps = request.form.getlist('reps[]')
    weights = request.form.getlist('weight[]')
    set_notes = request.form.getlist('set_notes[]')

    gym_sets = []
    for index, exercise_name in enumerate(exercise_names):
        gym_sets.append(
            {
                'exercise_name': exercise_name,
                'set_number': int(set_numbers[index]) if index < len(set_numbers) and set_numbers[index] else None,
                'reps': int(reps[index]) if index < len(reps) and reps[index] else None,
                'weight': float(weights[index]) if index < len(weights) and weights[index] else None,
                'notes': set_notes[index].strip() if index < len(set_notes) and set_notes[index].strip() else None,
            }
        )

    create_gym_session(
        user_id=int(session['user_id']),
        session_date=session_date,
        title=title,
        notes=notes,
        sets=gym_sets,
    )
    flash('Gym session saved.', 'success')
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True)
