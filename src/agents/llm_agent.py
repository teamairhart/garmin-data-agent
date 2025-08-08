import os
import requests
import json
from typing import Dict, Any, Optional
import pandas as pd

class HuggingFaceLLMAgent:
    """LLM integration via Hugging Face Inference API"""
    
    def __init__(self, model_name: str = "mistralai/Mistral-7B-Instruct-v0.3"):
        # Try multiple models in order of preference
        self.models_to_try = [
            "mistralai/Mistral-7B-Instruct-v0.3",  # Reliable, fast
            "microsoft/DialoGPT-large",            # Backup option
            "openai/gpt-oss-20b"                   # Original goal (when available)
        ]
        self.current_model = model_name
        self.api_url = f"https://api-inference.huggingface.co/models/{model_name}"
        self.headers = {
            "Authorization": f"Bearer {os.getenv('HUGGING_FACE_API_TOKEN', '').strip()}"
        }
        self.max_tokens = 500
        
    def query_llm(self, prompt: str, max_retries: int = 3) -> Optional[str]:
        """Query the Hugging Face Inference API"""
        token = os.getenv('HUGGING_FACE_API_TOKEN', '').strip()
        if not token:
            print("DEBUG: No Hugging Face API token found")
            return None
        
        print(f"DEBUG: Found API token, first 10 chars: {token[:10]}...")
        print(f"DEBUG: Token length: {len(token)}")
        print(f"DEBUG: Querying model: {self.current_model}")
        print(f"DEBUG: Prompt length: {len(prompt)} characters")
            
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
        
        # Use fresh headers with cleaned token
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    self.api_url, 
                    headers=headers, 
                    json=payload,
                    timeout=30
                )
                
                print(f"DEBUG: API Response Status: {response.status_code}")
                
                if response.status_code == 200:
                    result = response.json()
                    print(f"DEBUG: API Response: {result}")
                    if isinstance(result, list) and len(result) > 0:
                        generated_text = result[0].get('generated_text', '').strip()
                        print(f"DEBUG: Generated text length: {len(generated_text)}")
                        return generated_text
                    elif isinstance(result, dict):
                        generated_text = result.get('generated_text', '').strip()
                        print(f"DEBUG: Generated text length: {len(generated_text)}")
                        return generated_text
                
                elif response.status_code == 503:  # Model loading
                    print("DEBUG: Model is loading, waiting...")
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(10)  # Wait for model to load
                        continue
                
                else:
                    print(f"DEBUG: HF API Error {response.status_code}: {response.text}")
                    
            except Exception as e:
                print(f"LLM Query error (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2)
        
        return None
    
    def create_cycling_prompt(self, query: str, ride_summary: Dict, sample_data: Dict) -> str:
        """Create a specialized prompt for cycling analysis"""
        
        prompt = f"""[INST] You are an expert cycling coach. Analyze this ride data and answer the question with specific insights.

RIDE: {ride_summary.get('total_distance', 0) * 0.000621371:.1f} miles, {ride_summary.get('total_time', 0):.1f} hours
PERFORMANCE: {ride_summary.get('avg_speed', 0):.1f} mph avg, {ride_summary.get('avg_power', 0)}W avg, {ride_summary.get('avg_heart_rate', 0)} bpm avg
ELEVATION: {ride_summary.get('total_ascent', 0)} feet gained

QUESTION: {query}

Provide cycling coach insights in 2-3 sentences with actionable advice. [/INST]"""
        
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