import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def generate_demo_ride_data():
    """Generate sample ride data for testing"""
    
    # Generate 1 hour ride with 1-second intervals
    duration = 3600  # 1 hour in seconds
    timestamps = pd.date_range(
        start=datetime.now() - timedelta(hours=1),
        periods=duration,
        freq='1S'
    )
    
    # Generate realistic cycling data
    np.random.seed(42)  # For reproducible results
    
    # Base speed around 25 km/h with variations
    base_speed = 25 / 3.6  # Convert to m/s
    speed_variation = np.random.normal(0, 2, duration) / 3.6
    speed = np.maximum(base_speed + speed_variation, 0)  # Ensure non-negative
    
    # Distance (cumulative)
    distance = np.cumsum(speed)
    
    # Altitude with some climbs
    altitude_base = 100
    # Create some hills
    hill_factor = np.sin(np.linspace(0, 4*np.pi, duration)) * 50
    climb_factor = np.linspace(0, 200, duration//3)  # Gradual climb for first third
    altitude = altitude_base + hill_factor + np.concatenate([
        climb_factor,
        np.full(duration//3, 200),  # Maintain elevation
        200 - np.linspace(0, 200, duration - 2*(duration//3))  # Descend
    ])
    
    # Heart rate (correlated with effort/altitude changes)
    base_hr = 150
    hr_variation = (altitude - altitude_base) * 0.3 + np.random.normal(0, 5, duration)
    heart_rate = np.clip(base_hr + hr_variation, 100, 200)
    
    # Power (correlated with speed and gradient)
    gradient = np.gradient(altitude, distance)
    base_power = 200
    power_variation = speed * 50 + gradient * 1000 + np.random.normal(0, 20, duration)
    power = np.maximum(base_power + power_variation, 0)
    
    # Temperature
    temperature = np.full(duration, 22) + np.random.normal(0, 2, duration)
    
    # Create DataFrame
    df = pd.DataFrame({
        'timestamp': timestamps,
        'distance': distance,
        'speed': speed,
        'altitude': altitude,
        'heart_rate': heart_rate.astype(int),
        'power': power.astype(int),
        'temperature': temperature
    })
    
    # Create session summary
    session_data = {
        'total_distance': distance[-1],
        'total_timer_time': duration,
        'avg_speed': speed.mean(),
        'max_speed': speed.max(),
        'avg_heart_rate': int(heart_rate.mean()),
        'max_heart_rate': int(heart_rate.max()),
        'avg_power': int(power.mean()),
        'normalized_power': int(np.mean(power**4)**(1/4)),
        'total_ascent': int(np.sum(np.maximum(np.diff(altitude), 0))),
        'total_descent': int(np.sum(np.maximum(-np.diff(altitude), 0)))
    }
    
    return df, session_data

if __name__ == "__main__":
    # Test the demo data generator
    df, session = generate_demo_ride_data()
    print("Sample ride data generated:")
    print(f"Duration: {len(df)} seconds")
    print(f"Distance: {df['distance'].iloc[-1]/1000:.2f} km")
    print(f"Avg Speed: {session['avg_speed']*3.6:.1f} km/h")
    print(f"Max Heart Rate: {session['max_heart_rate']} bpm")
    print("\nFirst 5 rows:")
    print(df.head())