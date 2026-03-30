# 🚴‍♂️ Garmin Data Agent

An AI-powered web application for analyzing Garmin ride data with natural language queries. Built with Flask, LangGraph agents, and the new GPT OSS models.

## 🌟 Features

- **Upload Garmin .fit/.zip files** - Direct from Garmin Connect
- **AI-Powered Analysis** - Ask natural language questions about your rides
- **Detailed Metrics** - Speed, power, heart rate, elevation, TSS, and more
- **Full FIT Export** - Batch-export every discovered FIT message type and field to CSV
- **Climb Analysis** - Analyze performance on steep gradients
- **Power Zone Distribution** - Training zone breakdowns
- **Auto-Update Monitoring** - Stay current with dependencies
- **Demo Mode** - Try without uploading data

## 🚀 Quick Start

### Local Development

```bash
# Clone and setup
git clone <your-repo>
cd garmin-data-agent

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py

# Visit http://127.0.0.1:5000
```

### Batch Export Every FIT Field

If you want to inspect everything your Edge recorded across a folder of FIT files, use the exporter:

```bash
python scripts/export_fit_folder.py "/Users/jonathan_airhart/DevProjects/Fitness Data/Garmin_Data" \
  --output-dir exports/edge840
```

This writes:

- `exports/edge840/file_summary.csv` - one row per FIT file with ride-level summaries
- `exports/edge840/message_catalog.csv` - every discovered FIT message type and its CSV file
- `exports/edge840/manifest.json` - schema manifest with field names, units, and definition numbers
- `exports/edge840/messages/*.csv` - one CSV per FIT message type (`record`, `session`, `lap`, `event`, `device_info`, unknown vendor messages, and more)

This is intentionally better than a single giant sparse CSV because FIT data is multi-table by design. Keeping message types separate preserves session summaries, lap structure, device metadata, gear-change events, and developer definitions without throwing away fields that do not live on `record` messages.

### Export Apple Health Data

Export your Apple Health archive from the Health app, then point the XML exporter at `export.xml`:

```bash
python scripts/export_apple_health.py "/path/to/apple-health/export.xml" \
  --cutoff-date 2025-07-01 \
  --output-dir exports/apple_health
```

This writes:

- `exports/apple_health/record_catalog.csv` - one row per Apple Health record type
- `exports/apple_health/record_types/*.csv` - one CSV per Apple Health record type
- `exports/apple_health/workout.csv` - Apple Watch workouts
- `exports/apple_health/activity_summary.csv` - Move/Exercise/Stand summaries
- `exports/apple_health/daily_metrics.csv` - daily recovery metrics such as sleep, HRV, resting HR, workouts, and activity summaries

### Build A Cross-Source Training Dataset

Once you have Garmin `file_summary.csv` and Apple Health `daily_metrics.csv`, merge them into a single day-level dataset:

```bash
python scripts/build_training_dataset.py \
  --garmin-file-summary exports/edge840/file_summary.csv \
  --apple-daily-metrics exports/apple_health/daily_metrics.csv \
  --output-path exports/training_dataset/training_daily.csv
```

The merged dataset includes ride load, TSS, work, sleep, HRV, resting HR, rolling 7-day baselines, and previous-day training columns so you can ask questions like “what kind of sessions reduce next-day HRV?” or “how does sleep change after high-TSS road workouts?”

If you want to physically shrink the raw Apple export before analysis, create a trimmed export first:

```bash
python scripts/trim_apple_health_export.py \
  "/Users/jonathan_airhart/DevProjects/Fitness Data/Apple_Health/raw/apple_health_export" \
  "/Users/jonathan_airhart/DevProjects/Fitness Data/Apple_Health/raw/apple_health_export_2025-07-01_plus" \
  --cutoff-date 2025-07-01
```

### Deploy to Render.com

1. **Connect GitHub repo** to Render
2. **Create Web Service** with these settings:
   - **Environment**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn --bind 0.0.0.0:$PORT app:app`
3. **Set Environment Variables**:
   - `FLASK_ENV=production`
   - `SECRET_KEY=<random-secret-key>`
4. **Deploy!**

## 📊 Usage Examples

### Upload & Analyze
1. Upload your .fit file from Garmin Connect
2. View comprehensive metrics dashboard
3. Ask questions like:
   - "What was my average speed and heart rate on climbs steeper than 2.5%?"
   - "How was my power distributed across different zones?"
   - "What was my maximum power output?"

### System Monitoring
- Visit `/system/updates` to check dependency status
- Automatic monitoring of:
  - PyPI packages (Flask, pandas, transformers, etc.)
  - Hugging Face models (GPT OSS)
  - Garmin integration health

## 🏗️ Architecture

```
├── app.py              # Main Flask application
├── src/
│   └── agents/
│       ├── data_analyzer.py    # AI ride analysis agent
│       └── update_monitor.py   # Dependency monitoring agent
├── templates/          # HTML templates
├── demo_data.py       # Sample data generator
└── requirements.txt   # Dependencies
```

## 🔧 Tech Stack

- **Backend**: Flask, SQLAlchemy
- **AI/ML**: LangChain, LangGraph, Transformers, GPT OSS
- **Data**: pandas, numpy, fitparse
- **Deployment**: Render.com, Gunicorn
- **Frontend**: Bootstrap 5, JavaScript

## 🧠 AI Agents

### Data Analyzer Agent
- Parses Garmin .fit files
- Calculates gradients and zones
- Processes natural language queries
- Provides detailed ride insights

### FIT Export Pipeline
- Scans every `.fit` file in a folder
- Preserves all discovered FIT message types, including unknown/vendor-specific ones
- Writes schema metadata so AI workflows can see what fields exist before deep analysis

### Apple Health Export Pipeline
- Streams the standard Apple Health XML export
- Preserves all record types, workouts, and activity summaries
- Builds daily recovery metrics for cross-source readiness analysis

### Update Monitor Agent  
- Monitors PyPI package versions
- Tracks Hugging Face model updates
- Checks Garmin integration health
- Generates update reports

## 🔄 Staying Up-to-Date

The Update Monitor Agent automatically checks:
- **Critical dependencies** (Flask, pandas, transformers)
- **AI models** (GPT OSS 20B/120B)  
- **Garmin tools** (fitparse)

Visit `/system/updates` for status reports.

## 🗄️ Future Enhancements

- [ ] User authentication & profiles
- [ ] PostgreSQL database for ride history
- [ ] Training trend analysis over time
- [ ] Comparison between multiple rides
- [ ] Advanced visualizations
- [ ] Mobile-responsive design

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License.

## 🙏 Acknowledgments

- **Garmin** for the .fit file format and fitparse library
- **OpenAI** for the GPT OSS models
- **Hugging Face** for model hosting and transformers
- **LangChain/LangGraph** for agent framework
