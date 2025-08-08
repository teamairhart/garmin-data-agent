from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
import os
from werkzeug.utils import secure_filename
import zipfile
import pandas as pd
from fitparse import FitFile
import tempfile
from src.agents.data_analyzer import ride_analyzer
from src.agents.update_monitor import update_monitor
from src.auth import auth_bp, init_db
from demo_data import generate_demo_ride_data

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

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def parse_fit_file(fit_file_path):
    """Parse FIT file and extract ride data"""
    try:
        fitfile = FitFile(fit_file_path)
        
        records = []
        for record in fitfile.get_messages('record'):
            data = {}
            for record_data in record:
                data[record_data.name] = record_data.value
            records.append(data)
        
        df = pd.DataFrame(records)
        
        # Extract session summary
        session_data = {}
        for record in fitfile.get_messages('session'):
            for record_data in record:
                session_data[record_data.name] = record_data.value
        
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
        fitfile = FitFile('/Users/jonathan_airhart/Downloads/19975720234_ACTIVITY.fit')
        
        records = []
        for record in fitfile.get_messages('record'):
            data = {}
            for record_data in record:
                data[record_data.name] = record_data.value
            records.append(data)
        
        df = pd.DataFrame(records)
        
        # Extract session summary
        session_data = {}
        for record in fitfile.get_messages('session'):
            for record_data in record:
                session_data[record_data.name] = record_data.value
            break
        
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

if __name__ == '__main__':
    app.run(debug=True)