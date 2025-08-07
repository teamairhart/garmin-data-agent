import os
import pandas as pd
from typing import Dict, Any, List, Optional
import numpy as np

class RideDataAgent:
    """Agent for analyzing Garmin ride data using GPT OSS model"""
    
    def __init__(self, model_name: str = "openai/gpt-oss-20b"):
        self.model_name = model_name
        self.ride_data = None
        self.session_data = None
        self._setup_model()
    
    def _setup_model(self):
        """Initialize the GPT OSS model - placeholder for now"""
        # TODO: Implement GPT OSS integration when ready for production
        self.llm = None
    
    def load_ride_data(self, df: pd.DataFrame, session_data: Dict):
        """Load ride data for analysis"""
        self.ride_data = df
        self.session_data = session_data
    
    def calculate_gradient_analysis(self) -> Dict[str, Any]:
        """Calculate gradient-based metrics"""
        # Check for altitude data - Garmin uses 'enhanced_altitude'
        altitude_col = None
        if 'enhanced_altitude' in self.ride_data.columns:
            altitude_col = 'enhanced_altitude'
        elif 'altitude' in self.ride_data.columns:
            altitude_col = 'altitude'
        else:
            return {"error": "No altitude data available"}
        
        # Calculate gradient
        if 'distance' in self.ride_data.columns:
            altitude_diff = self.ride_data[altitude_col].diff()
            distance_diff = self.ride_data['distance'].diff()
            # Avoid division by zero and infinite values
            gradient = np.where(distance_diff != 0, (altitude_diff / distance_diff) * 100, 0)
            gradient = np.where(np.isfinite(gradient), gradient, 0)  # Replace inf/nan with 0
            self.ride_data['gradient'] = gradient
        
        # Find steep climbs (gradient > 2.5%)
        steep_climbs = self.ride_data[self.ride_data['gradient'] > 2.5]
        
        if len(steep_climbs) == 0:
            return {"message": "No climbs steeper than 2.5% found in this ride"}
        
        # Use Garmin's enhanced_speed if available
        speed_col = 'enhanced_speed' if 'enhanced_speed' in steep_climbs.columns else 'speed'
        
        climb_metrics = {
            "avg_speed_on_climbs": steep_climbs[speed_col].mean() * 3.6 if speed_col in steep_climbs.columns else 0,
            "avg_heart_rate_on_climbs": steep_climbs['heart_rate'].mean() if 'heart_rate' in steep_climbs.columns else 0,
            "avg_power_on_climbs": steep_climbs['power'].mean() if 'power' in steep_climbs.columns else 0,
            "steepest_gradient": steep_climbs['gradient'].max(),
            "total_climb_distance": len(steep_climbs) * 0.01,  # Approximate
            "climb_segments": len(steep_climbs)
        }
        
        return climb_metrics
    
    def analyze_power_zones(self) -> Dict[str, Any]:
        """Analyze power distribution across different zones"""
        if self.ride_data is None or 'power' not in self.ride_data.columns:
            return {"error": "No power data available"}
        
        power_data = self.ride_data['power'].dropna()
        if len(power_data) == 0:
            return {"error": "No valid power data"}
        
        # Define power zones (assuming FTP of 250W for example)
        ftp = power_data.quantile(0.9)  # Rough estimate
        zones = {
            "Zone 1 (Recovery)": (0, 0.55 * ftp),
            "Zone 2 (Endurance)": (0.55 * ftp, 0.75 * ftp),
            "Zone 3 (Tempo)": (0.75 * ftp, 0.9 * ftp),
            "Zone 4 (Threshold)": (0.9 * ftp, 1.05 * ftp),
            "Zone 5 (VO2 Max)": (1.05 * ftp, 1.2 * ftp),
            "Zone 6 (Neuromuscular)": (1.2 * ftp, float('inf'))
        }
        
        zone_analysis = {}
        for zone_name, (min_power, max_power) in zones.items():
            zone_data = power_data[(power_data >= min_power) & (power_data < max_power)]
            zone_analysis[zone_name] = {
                "time_percentage": (len(zone_data) / len(power_data)) * 100,
                "avg_power": zone_data.mean() if len(zone_data) > 0 else 0
            }
        
        return zone_analysis
    
    def process_natural_query(self, query: str) -> str:
        """Process natural language queries about ride data"""
        if self.ride_data is None:
            return """I can help you analyze your ride data! Try asking questions like:
            
- "What was my average speed and heart rate on climbs steeper than 2.5%?"
- "How was my power distributed across different zones?"
- "What was my average speed?"
- "What was my heart rate during the ride?"

Upload your ride data first, then I can provide detailed analysis!"""
        
        query_lower = query.lower()
        
        # Check for climb-related queries (power, speed, heart rate)
        if "climb" in query_lower:
            climb_data = self.calculate_gradient_analysis()
            if "error" in climb_data:
                return climb_data["error"]
            elif "message" in climb_data:
                return climb_data["message"]
            
            response = f"""Based on your ride analysis:

**Steep Climbs (>2.5% gradient):**
- Average speed on climbs: {climb_data['avg_speed_on_climbs']:.1f} km/h
- Average heart rate on climbs: {climb_data['avg_heart_rate_on_climbs']:.0f} bpm
- Average power on climbs: {climb_data['avg_power_on_climbs']:.0f} W
- Steepest gradient: {climb_data['steepest_gradient']:.1f}%
- Total climb segments: {climb_data['climb_segments']}
"""
            return response
        
        elif "power" in query_lower and "zone" in query_lower:
            power_zones = self.analyze_power_zones()
            if "error" in power_zones:
                return power_zones["error"]
            
            response = "**Power Zone Distribution:**\n\n"
            for zone, data in power_zones.items():
                response += f"**{zone}:** {data['time_percentage']:.1f}% of ride\n"
            
            return response
        
        elif "average" in query_lower and "speed" in query_lower:
            avg_speed = self.session_data.get('avg_speed', 0) * 3.6 if self.session_data else 0
            max_speed = self.session_data.get('max_speed', 0) * 3.6 if self.session_data else 0
            return f"Your average speed was {avg_speed:.1f} km/h with a maximum speed of {max_speed:.1f} km/h."
        
        elif "heart rate" in query_lower:
            avg_hr = self.session_data.get('avg_heart_rate', 0) if self.session_data else 0
            max_hr = self.session_data.get('max_heart_rate', 0) if self.session_data else 0
            return f"Your average heart rate was {avg_hr} bpm with a maximum of {max_hr} bpm."
        
        else:
            return """I can help you analyze your ride data! Try asking questions like:
            
- "What was my average speed and heart rate on climbs steeper than 2.5%?"
- "How was my power distributed across different zones?"
- "What was my average speed?"
- "What was my heart rate during the ride?"

Upload your ride data first, then I can provide detailed analysis!"""

# Global instance for the Flask app
ride_analyzer = RideDataAgent()