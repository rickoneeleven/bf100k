"""
test_bet_tracker.py

Test script for bet tracking and market analysis functionality.
Tests the core betting logic and data storage functionality with real market data.
"""

import os
import json
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from src.betfair_client import BetfairClient
from src.bet_tracker import BetTracker

def test_bet_tracker_initialization():
    """Test initial setup of bet tracker and data files"""
    print("\nTesting bet tracker initialization...")
    
    # Initialize bet tracker
    tracker = BetTracker()
    
    # Check if data files were created
    data_files = [
        'web/data/betting/active_bets.json',
        'web/data/betting/settled_bets.json',
        'web/data/betting/account_status.json'
    ]
    
    for file_path in data_files:
        if Path(file_path).exists():
            print(f"✓ {file_path} created successfully")
            # Verify file structure
            with open(file_path, 'r') as f:
                data = json.load(f)
                print(f"  Structure: {list(data.keys())}")
        else:
            print(f"✗ Failed to create {file_path}")

def test_market_analysis():
    """Test market analysis functionality with real market data"""
    print("\nTesting market analysis with live data...")
    
    # Load environment variables
    load_dotenv('env')
    
    # Initialize Betfair client
    client = BetfairClient(
        app_key=os.getenv('BETFAIR_APP_KEY'),
        cert_file=os.getenv('BETFAIR_CERT_FILE'),
        key_file=os.getenv('BETFAIR_KEY_FILE')
    )
    
    # Initialize bet tracker
    tracker = BetTracker()
    
    # Login to Betfair
    if not client.login():
        print("✗ Failed to login to Betfair")
        return
    
    print("✓ Successfully logged in to Betfair")
    
    # Get football markets
    markets = client.get_football_markets_for_today()
    if not markets:
        print("✗ Failed to retrieve markets")
        return
    
    print(f"✓ Retrieved {len(markets)} markets for analysis")
    
    # Get detailed market data including odds
    market_books = client.list_market_book([market['marketId'] for market in markets])
    if not market_books:
        print("✗ Failed to retrieve market odds")
        return
        
    # Analyze each market
    found_opportunity = False
    for market, market_book in zip(markets, market_books):
        print(f"\nAnalyzing market: {market.get('event', {}).get('name')}")
        
        # Map runners to their names for better output
        runner_map = {runner['selectionId']: runner['runnerName'] for runner in market.get('runners', [])}
        
        # Print available odds for each selection
        print("Available odds:")
        for runner in market_book.get('runners', []):
            selection_id = runner.get('selectionId')
            back_prices = runner.get('ex', {}).get('availableToBack', [])
            if back_prices:
                best_price = back_prices[0].get('price')
                best_size = back_prices[0].get('size')
                print(f"  {runner_map.get(selection_id, 'Unknown')}: {best_price} (£{best_size} available)")
        
        # Test market analysis
        bet_opportunity = tracker.analyze_market_for_betting(market_book, 100.0)
        
        if bet_opportunity and not found_opportunity:
            found_opportunity = True
            print(f"\n✓ Found valid betting opportunity:")
            print(f"  - Market: {market.get('event', {}).get('name')}")
            print(f"  - Selection: {runner_map.get(bet_opportunity['selection_id'], 'Unknown')}")
            print(f"  - Odds: {bet_opportunity['odds']}")
            print(f"  - Stake: £{bet_opportunity['stake']}")
            break
        
    if not found_opportunity:
        print("\n✗ No valid betting opportunities found in any market")

def test_bet_recording():
    """Test bet placement and settlement recording"""
    print("\nTesting bet recording functionality...")
    
    tracker = BetTracker()
    
    # Test bet placement
    sample_bet = {
        "market_id": "1.123456789",
        "selection_id": 123456,
        "odds": 3.5,
        "stake": 100.0,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    print("Recording sample bet placement...")
    tracker.record_bet_placement(sample_bet)
    
    # Verify active bet was recorded
    with open('web/data/betting/active_bets.json', 'r') as f:
        active_bets = json.load(f)
        if any(b['market_id'] == sample_bet['market_id'] for b in active_bets['bets']):
            print("✓ Bet successfully recorded in active_bets.json")
        else:
            print("✗ Failed to record bet in active_bets.json")
    
    # Test bet settlement
    print("\nRecording sample bet settlement...")
    tracker.record_bet_settlement(sample_bet, won=True, profit=250.0)
    
    # Verify bet was moved to settled bets
    with open('web/data/betting/settled_bets.json', 'r') as f:
        settled_bets = json.load(f)
        if any(b['market_id'] == sample_bet['market_id'] for b in settled_bets['bets']):
            print("✓ Bet successfully moved to settled_bets.json")
        else:
            print("✗ Failed to move bet to settled_bets.json")
    
    # Verify bet was removed from active bets
    with open('web/data/betting/active_bets.json', 'r') as f:
        active_bets = json.load(f)
        if not any(b['market_id'] == sample_bet['market_id'] for b in active_bets['bets']):
            print("✓ Bet successfully removed from active_bets.json")
        else:
            print("✗ Failed to remove bet from active_bets.json")

if __name__ == "__main__":
    # Run all tests
    test_bet_tracker_initialization()
    test_market_analysis()
    test_bet_recording()