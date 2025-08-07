# 🚴‍♂️ Garmin Data Agent

An AI-powered web application for analyzing Garmin ride data with natural language queries. Built with Flask, LangGraph agents, and the new GPT OSS models.

## 🌟 Features

- **Upload Garmin .fit/.zip files** - Direct from Garmin Connect
- **AI-Powered Analysis** - Ask natural language questions about your rides
- **Detailed Metrics** - Speed, power, heart rate, elevation, TSS, and more
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