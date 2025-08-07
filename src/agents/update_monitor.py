import requests
import json
from typing import Dict, List, Any
from datetime import datetime, timedelta
import subprocess
import os

class UpdateMonitorAgent:
    """Agent that monitors and reports on dependency updates"""
    
    def __init__(self):
        self.dependencies = {
            # Core web framework
            'flask': {'type': 'pypi', 'critical': True},
            'flask-sqlalchemy': {'type': 'pypi', 'critical': True},
            'flask-login': {'type': 'pypi', 'critical': True},
            
            # Data processing
            'pandas': {'type': 'pypi', 'critical': True},
            'numpy': {'type': 'pypi', 'critical': True},
            'fitparse': {'type': 'pypi', 'critical': True},
            
            # AI/ML Stack
            'transformers': {'type': 'pypi', 'critical': True},
            'huggingface-hub': {'type': 'pypi', 'critical': True},
            'langchain': {'type': 'pypi', 'critical': True},
            'langgraph': {'type': 'pypi', 'critical': True},
            
            # Garmin-specific
            'garmin-connect-python': {'type': 'pypi', 'critical': False}
        }
        
        # Model tracking
        self.models_to_track = [
            'openai/gpt-oss-20b',
            'openai/gpt-oss-120b'
        ]
        
    def check_pypi_updates(self) -> Dict[str, Any]:
        """Check for PyPI package updates"""
        updates = {}
        
        for package, info in self.dependencies.items():
            if info['type'] != 'pypi':
                continue
                
            try:
                # Get current installed version
                result = subprocess.run(['pip', 'show', package], 
                                      capture_output=True, text=True)
                current_version = None
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if line.startswith('Version:'):
                            current_version = line.split(': ')[1]
                            break
                
                # Get latest version from PyPI
                response = requests.get(f'https://pypi.org/pypi/{package}/json', timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    latest_version = data['info']['version']
                    
                    updates[package] = {
                        'current': current_version,
                        'latest': latest_version,
                        'needs_update': current_version != latest_version if current_version else True,
                        'critical': info['critical'],
                        'release_date': data['releases'][latest_version][0]['upload_time'] if data['releases'][latest_version] else None
                    }
                    
            except Exception as e:
                updates[package] = {
                    'error': str(e),
                    'critical': info['critical']
                }
        
        return updates
    
    def check_huggingface_model_updates(self) -> Dict[str, Any]:
        """Check for Hugging Face model updates"""
        model_updates = {}
        
        for model_name in self.models_to_track:
            try:
                response = requests.get(
                    f'https://huggingface.co/api/models/{model_name}',
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    model_updates[model_name] = {
                        'last_modified': data.get('lastModified'),
                        'downloads': data.get('downloads', 0),
                        'tags': data.get('tags', []),
                        'status': 'available'
                    }
                else:
                    model_updates[model_name] = {
                        'status': 'unavailable',
                        'error': f'HTTP {response.status_code}'
                    }
                    
            except Exception as e:
                model_updates[model_name] = {
                    'status': 'error',
                    'error': str(e)
                }
        
        return model_updates
    
    def check_garmin_api_changes(self) -> Dict[str, Any]:
        """Monitor Garmin Connect API or related tools"""
        garmin_status = {}
        
        try:
            # Check if fitparse is still working with recent files
            # This is a basic health check
            import fitparse
            garmin_status['fitparse'] = {
                'status': 'working',
                'version': fitparse.__version__ if hasattr(fitparse, '__version__') else 'unknown'
            }
            
        except Exception as e:
            garmin_status['fitparse'] = {
                'status': 'error',
                'error': str(e)
            }
        
        return garmin_status
    
    def generate_update_report(self) -> str:
        """Generate a comprehensive update report"""
        print("🔍 Checking for updates...")
        
        pypi_updates = self.check_pypi_updates()
        model_updates = self.check_huggingface_model_updates()
        garmin_status = self.check_garmin_api_changes()
        
        report = f"""
# 🔄 Dependency Update Report
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 📦 PyPI Packages

"""
        
        critical_updates = []
        regular_updates = []
        
        for package, info in pypi_updates.items():
            if 'error' in info:
                report += f"❌ **{package}**: Error - {info['error']}\n"
            elif info['needs_update']:
                update_line = f"🔄 **{package}**: {info['current']} → {info['latest']}"
                if info['critical']:
                    critical_updates.append(package)
                    update_line += " ⚠️ CRITICAL"
                else:
                    regular_updates.append(package)
                report += update_line + "\n"
            else:
                report += f"✅ **{package}**: {info['current']} (latest)\n"
        
        report += f"""
## 🤖 AI Models Status

"""
        for model, info in model_updates.items():
            if info['status'] == 'available':
                report += f"✅ **{model}**: Available (Downloads: {info['downloads']:,})\n"
            else:
                report += f"❌ **{model}**: {info['status']} - {info.get('error', 'Unknown error')}\n"
        
        report += f"""
## 🚴‍♂️ Garmin Integration Status

"""
        for component, info in garmin_status.items():
            if info['status'] == 'working':
                report += f"✅ **{component}**: Working (v{info.get('version', 'unknown')})\n"
            else:
                report += f"❌ **{component}**: {info['error']}\n"
        
        # Summary
        if critical_updates or regular_updates:
            report += f"""
## 🎯 Action Items

"""
            if critical_updates:
                report += f"🚨 **Critical Updates Needed:** {', '.join(critical_updates)}\n"
            if regular_updates:
                report += f"📈 **Optional Updates Available:** {', '.join(regular_updates)}\n"
            
            report += f"""
**Update Command:**
```bash
pip install --upgrade {' '.join(critical_updates + regular_updates)}
```
"""
        else:
            report += "\n🎉 **All dependencies are up to date!**\n"
        
        return report
    
    def auto_update_safe_packages(self, dry_run=True) -> Dict[str, str]:
        """Automatically update non-critical packages"""
        results = {}
        pypi_updates = self.check_pypi_updates()
        
        safe_to_update = []
        for package, info in pypi_updates.items():
            if (info.get('needs_update', False) and 
                not info.get('critical', True) and 
                'error' not in info):
                safe_to_update.append(package)
        
        if dry_run:
            results['dry_run'] = True
            results['would_update'] = safe_to_update
        else:
            # Actually update packages
            for package in safe_to_update:
                try:
                    result = subprocess.run(['pip', 'install', '--upgrade', package], 
                                          capture_output=True, text=True)
                    results[package] = 'success' if result.returncode == 0 else 'failed'
                except Exception as e:
                    results[package] = f'error: {e}'
        
        return results

# Global instance
update_monitor = UpdateMonitorAgent()

if __name__ == "__main__":
    print(update_monitor.generate_update_report())