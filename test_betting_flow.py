"""
test_betting_flow.py

Tests the full betting flow using the new Command pattern implementation.
This script runs a real interaction with the Betfair API and our betting system.
"""

import os
from datetime import datetime
from dotenv import load_dotenv
from src.betfair_client import BetfairClient
from src.commands.place_bet_command import PlaceBetCommand, PlaceBetRequest
from src.repositories.bet_repository import BetRepository
from src.repositories.account_repository import AccountRepository
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_betting_flow():
    """Test the entire betting flow with real data"""
    # Load environment variables
    load_dotenv('env')
    
    print("\n=== Testing Betting Flow with New Architecture ===\n")
    
    # Initialize components
    print("Initializing components...")
    betfair_client = BetfairClient(
        app_key=os.getenv('BETFAIR_APP_KEY'),
        cert_file=os.getenv('BETFAIR_CERT_FILE'),
        key_file=os.getenv('BETFAIR_KEY_FILE')
    )
    bet_repository = BetRepository()
    account_repository = AccountRepository()
    
    # Set initial test balance
    print("\nSetting up test account...")
    account_repository.reset_account_stats(initial_balance=1000.0)
    print(f"Initial balance: £{account_repository.get_account_status().current_balance}")
    
    # Login to Betfair
    print("\nLogging in to Betfair...")
    if not betfair_client.login():
        print("❌ Failed to login to Betfair")
        return
    print("✅ Successfully logged in")
    
    # Initialize command
    place_bet_command = PlaceBetCommand(
        betfair_client=betfair_client,
        bet_repository=bet_repository,
        account_repository=account_repository
    )
    
    # Get available markets
    print("\nFetching available markets...")
    markets, market_books = betfair_client.get_markets_with_odds()
    if not markets or not market_books:
        print("❌ Failed to retrieve markets")
        return
    
    print(f"\nAnalyzing {len(markets)} markets for betting opportunities...")
    
    # Try to find and place a bet
    for market, market_book in zip(markets, market_books):
        print(f"\nAnalyzing market: {market.get('event', {}).get('name')}")
        
        # Skip in-play markets
        if market_book.get('inplay'):
            print("Skipping in-play market")
            continue
        
        # Check each runner
        for runner in market_book.get('runners', []):
            ex = runner.get('ex', {})
            available_to_back = ex.get('availableToBack', [])
            
            if not available_to_back:
                continue
            
            odds = available_to_back[0].get('price')
            available_size = available_to_back[0].get('size')
            
            print(f"Selection: {runner.get('runnerName', 'Unknown')}")
            print(f"Odds: {odds}")
            print(f"Available size: £{available_size}")
            
            # Check if odds are in our target range (3.0-4.0)
            if 3.0 <= odds <= 4.0:
                print("\n🎯 Found potential betting opportunity!")
                
                # Create bet request
                request = PlaceBetRequest(
                    market_id=market.get('marketId'),
                    selection_id=runner.get('selectionId'),
                    odds=odds,
                    stake=100.0  # Test with £100 stake
                )
                
                # Try to place bet
                print("\nAttempting to place bet...")
                result = place_bet_command.execute(request)
                
                if result:
                    print("\n✅ Successfully placed bet:")
                    print(f"Market: {market.get('event', {}).get('name')}")
                    print(f"Selection: {runner.get('runnerName')}")
                    print(f"Odds: {result['odds']}")
                    print(f"Stake: £{result['stake']}")
                    
                    # Show updated account status
                    status = account_repository.get_account_status()
                    print(f"\nUpdated balance: £{status.current_balance}")
                    print(f"Total bets placed: {status.total_bets_placed}")
                    
                    return  # Exit after placing one bet
                else:
                    print("❌ Failed to place bet - continuing search...")
    
    print("\nNo valid betting opportunities found")
    
    # Show final status
    status = account_repository.get_account_status()
    print("\nFinal account status:")
    print(f"Balance: £{status.current_balance}")
    print(f"Total bets placed: {status.total_bets_placed}")
    print(f"Successful bets: {status.successful_bets}")
    print(f"Win rate: {account_repository.get_win_rate():.1f}%")

if __name__ == "__main__":
    test_betting_flow()