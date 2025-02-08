"""
test_market_analysis.py

Test script for football market analysis functionality and data structure validation.
"""

import os
import json
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from src.betfair_client import BetfairClient

def setup_data_directories():
    """Create necessary data directories if they don't exist"""
    base_path = Path('web/data/market_analysis')
    today = datetime.now(timezone.utc)
    year_month_path = base_path / str(today.year) / f"{today.month:02d}"
    year_month_path.mkdir(parents=True, exist_ok=True)
    return year_month_path

def transform_market_data(markets, volume_map):
    """Transform raw API market data into our storage format"""
    now = datetime.now(timezone.utc)
    
    # Sort markets by volume and take top 5
    sorted_markets = sorted(
        markets,
        key=lambda x: volume_map.get(x.get('marketId'), 0),
        reverse=True
    )[:5]
    
    return {
        "analysis_date": now.strftime("%Y-%m-%d"),
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "top_markets": [
            {
                "market_id": market.get('marketId'),
                "event_name": market.get('event', {}).get('name'),
                "market_name": market.get('marketName'),
                "start_time": market.get('marketStartTime'),
                "matched_volume": volume_map.get(market.get('marketId'), 0),
                "market_status": "OPEN"
            }
            for market in markets
        ],
        "analysis_metadata": {
            "total_markets_analyzed": len(markets),
            "analysis_duration_ms": 0,  # We'll calculate this in the full implementation
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
    
    # Get today's football markets
    markets = client.get_football_markets_for_today()
    if not markets:
        print("Failed to get markets")
        return
    
    # Filter for Match Odds markets only
    match_odds_markets = [m for m in markets if m.get('marketName') == 'Match Odds']
    print(f"\nFiltered to {len(match_odds_markets)} Match Odds markets")
    
    # Get volumes for these markets
    market_ids = [m['marketId'] for m in match_odds_markets]
    volumes = client.get_market_volumes(market_ids)
    
    if not volumes:
        print("Failed to get market volumes")
        return
        
    # Create market_id to volume mapping
    volume_map = {
        book['marketId']: book.get('totalMatched', 0) 
        for book in volumes
    }
    
    # Transform data with volumes and timing
    end_time = datetime.now(timezone.utc)
    duration_ms = int((end_time - start_time).total_seconds() * 1000)
    analysis_data = transform_market_data(match_odds_markets, volume_map)
    analysis_data['analysis_metadata']['analysis_duration_ms'] = duration_ms
    
    # Setup directories and save data
    data_dir = setup_data_directories()
    today = datetime.now(timezone.utc)
    filename = today.strftime("%Y-%m-%d.json")
    filepath = data_dir / filename
    
    # Save the data
    with open(filepath, 'w') as f:
        json.dump(analysis_data, f, indent=2)
    
    # Print first few markets for inspection
    print("\nFirst 3 markets from API:")
    for market in markets[:3]:
        print(json.dumps(market, indent=2))
        
    print("\nTransformed data structure:")
    print(json.dumps(analysis_data, indent=2))
    
    # Basic validation
    print("\nValidation:")
    print(f"Total markets found: {len(markets)}")
    print(f"Data saved to: {filepath}")

if __name__ == "__main__":
    main()