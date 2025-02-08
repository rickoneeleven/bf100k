"""
test_market_analysis.py

Test script for football market analysis functionality and data structure validation.
"""

import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List
from dotenv import load_dotenv
from src.betfair_client import BetfairClient

def setup_data_directories():
    """Create necessary data directories if they don't exist"""
    base_path = Path('web/data/market_analysis')
    today = datetime.now(timezone.utc)
    year_month_path = base_path / str(today.year) / f"{today.month:02d}"
    year_month_path.mkdir(parents=True, exist_ok=True)
    return year_month_path

def transform_market_data(markets: List[Dict]) -> Dict:
    """Transform raw API market data into our storage format"""
    now = datetime.now(timezone.utc)
    
    return {
        "analysis_date": now.strftime("%Y-%m-%d"),
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "top_markets": [
            {
                "market_id": market.get('marketId'),
                "event_name": market.get('event', {}).get('name'),
                "market_name": market.get('marketName'),
                "start_time": market.get('marketStartTime'),
                "matched_volume": market.get('totalMatched', 0),
                "market_status": "OPEN"
            }
            for market in markets
        ],
        "analysis_metadata": {
            "total_markets_analyzed": len(markets),
            "analysis_duration_ms": 0,  # Will be set later
            "api_status": "SUCCESS"
        }
    }

def main():
    start_time = datetime.now(timezone.utc)
    
    # Load environment variables from 'env' file
    load_dotenv('env')
    
    # Initialize client
    client = BetfairClient(
        app_key=os.getenv('BETFAIR_APP_KEY'),
        cert_file=os.getenv('BETFAIR_CERT_FILE'),
        key_file=os.getenv('BETFAIR_KEY_FILE')
    )
    
    # Login
    if not client.login():
        print("Failed to login")
        return
    
    # Get today's top 5 football Match Odds markets
    markets = client.get_football_markets_for_today()
    if not markets:
        print("Failed to get markets")
        return
    
    print(f"\nRetrieved {len(markets)} top markets")
    
    # Transform data with timing
    end_time = datetime.now(timezone.utc)
    duration_ms = int((end_time - start_time).total_seconds() * 1000)
    analysis_data = transform_market_data(markets)
    analysis_data['analysis_metadata']['analysis_duration_ms'] = duration_ms
    
    # Setup directories and save data
    data_dir = setup_data_directories()
    today = datetime.now(timezone.utc)
    filename = today.strftime("%Y-%m-%d.json")
    filepath = data_dir / filename
    
    # Save the data
    with open(filepath, 'w') as f:
        json.dump(analysis_data, f, indent=2)
    
    # Print validation info
    print("\nValidation:")
    print(f"Markets in order of matched volume:")
    for market in markets:
        print(f"- {market.get('event', {}).get('name')}: {market.get('totalMatched', 0)}")
    print(f"\nData saved to: {filepath}")

if __name__ == "__main__":
    main()