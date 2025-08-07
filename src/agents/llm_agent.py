import os
import requests
import json
from typing import Dict, Any, Optional
import pandas as pd

class HuggingFaceLLMAgent:
    """GPT OSS integration via Hugging Face Inference API"""
    
    def __init__(self, model_name: str = "openai/gpt-oss-20b"):
        self.model_name = model_name
        self.api_url = f"https://api-inference.huggingface.co/models/{model_name}"
        self.headers = {
            "Authorization": f"Bearer {os.getenv('HUGGING_FACE_API_TOKEN', '')}"
        }
        self.max_tokens = 500
        
    def query_llm(self, prompt: str, max_retries: int = 3) -> Optional[str]:
        """Query the Hugging Face Inference API"""
        if not os.getenv('HUGGING_FACE_API_TOKEN'):
            return None
            
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": self.max_tokens,
                "temperature": 0.7,
                "top_p": 0.9,
                "do_sample": True,
                "return_full_text": False
            }
        }
        
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    self.api_url, 
                    headers=self.headers, 
                    json=payload,
                    timeout=30
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if isinstance(result, list) and len(result) > 0:
                        return result[0].get('generated_text', '').strip()
                    elif isinstance(result, dict):
                        return result.get('generated_text', '').strip()
                
                elif response.status_code == 503:  # Model loading
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(10)  # Wait for model to load
                        continue
                
                else:
                    print(f"HF API Error {response.status_code}: {response.text}")
                    
            except Exception as e:
                print(f"LLM Query error (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2)
        
        return None
    
    def create_cycling_prompt(self, query: str, ride_summary: Dict, sample_data: Dict) -> str:
        """Create a specialized prompt for cycling analysis"""
        
        prompt = f"""You are an expert cycling coach analyzing ride data. Provide detailed, actionable insights.

RIDE SUMMARY:
- Distance: {ride_summary.get('total_distance', 0) * 0.000621371:.1f} miles
- Duration: {ride_summary.get('total_time', 0):.1f} hours
- Avg Speed: {ride_summary.get('avg_speed', 0):.1f} mph
- Avg Power: {ride_summary.get('avg_power', 0)} watts
- Avg Heart Rate: {ride_summary.get('avg_heart_rate', 0)} bpm
- Elevation Gain: {ride_summary.get('total_ascent', 0)} feet

SAMPLE DATA POINTS:
{json.dumps(sample_data, indent=2)}

USER QUESTION: {query}

Provide a cycling coach's analysis with specific insights about performance, pacing, and training recommendations. Keep response under 200 words and focus on actionable advice.

CYCLING COACH RESPONSE:"""
        
        return prompt
    
    def analyze_with_llm(self, query: str, ride_data: pd.DataFrame, session_data: Dict) -> Optional[str]:
        """Analyze ride data using GPT OSS"""
        
        # Create ride summary for LLM context
        ride_summary = {
            'total_distance': session_data.get('total_distance', 0),
            'total_time': session_data.get('total_timer_time', 0) / 3600 if session_data.get('total_timer_time') else 0,
            'avg_speed': session_data.get('enhanced_avg_speed', 0) * 2.23694,
            'avg_power': session_data.get('avg_power', 0),
            'avg_heart_rate': session_data.get('avg_heart_rate', 0),
            'total_ascent': session_data.get('total_ascent', 0) * 3.28084
        }
        
        # Sample some data points for context (first, middle, last 5 points)
        if len(ride_data) > 15:
            sample_indices = list(range(5)) + list(range(len(ride_data)//2 - 2, len(ride_data)//2 + 3)) + list(range(-5, 0))
            sample_data = ride_data.iloc[sample_indices][['distance', 'enhanced_speed', 'heart_rate', 'power', 'enhanced_altitude']].to_dict('records')[:10]
        else:
            sample_data = ride_data[['distance', 'enhanced_speed', 'heart_rate', 'power', 'enhanced_altitude']].to_dict('records')[:10]
        
        # Convert to Imperial and clean up
        for point in sample_data:
            if 'distance' in point and point['distance']:
                point['distance_miles'] = point['distance'] * 0.000621371
            if 'enhanced_speed' in point and point['enhanced_speed']:
                point['speed_mph'] = point['enhanced_speed'] * 2.23694
            if 'enhanced_altitude' in point and point['enhanced_altitude']:
                point['altitude_feet'] = point['enhanced_altitude'] * 3.28084
        
        prompt = self.create_cycling_prompt(query, ride_summary, sample_data)
        
        return self.query_llm(prompt)


# Global instance
llm_agent = HuggingFaceLLMAgent()