# File: test_settlement_manual.py

"""
test_settlement_manual.py

Manual test script for settling bets. This script allows for interactive
testing of the bet settlement functionality.
"""

import os
from datetime import datetime
from dotenv import load_dotenv
from src.betfair_client import BetfairClient
from src.commands.settle_bet_command import BetSettlementCommand, BetSettlementRequest
from src.repositories.bet_repository import BetRepository
from src.repositories.account_repository import AccountRepository

def display_active_bets(bet_repository: BetRepository):
    """Display all active bets"""
    active_bets = bet_repository.get_active_bets()
    
    if not active_bets:
        print("\nNo active bets found.")
        return
    
    print("\nActive Bets:")
    print("-" * 80)
    for bet in active_bets:
        print(f"Market ID: {bet['market_id']}")
        print(f"Selection ID: {bet['selection_id']}")
        print(f"Stake: £{bet['stake']}")
        print(f"Odds: {bet['odds']}")
        print(f"Potential Profit: £{bet['stake'] * (bet['odds'] - 1):.2f}")
        print(f"Time Placed: {bet['timestamp']}")
        print("-" * 80)

def display_account_status(account_repository: AccountRepository):
    """Display current account status"""
    status = account_repository.get_account_status()
    print("\nAccount Status:")
    print("-" * 40)
    print(f"Current Balance: £{status.current_balance:.2f}")
    print(f"Total Bets Placed: {status.total_bets_placed}")
    print(f"Successful Bets: {status.successful_bets}")
    print(f"Win Rate: {account_repository.get_win_rate():.1f}%")
    print("-" * 40)

def settle_bet_manually():
    """Interactive function to settle a bet manually"""
    # Load environment variables
    load_dotenv('env')
    
    # Initialize components
    print("\n=== Manual Bet Settlement Tool ===\n")
    
    betfair_client = BetfairClient(
        app_key=os.getenv('BETFAIR_APP_KEY'),
        cert_file=os.getenv('BETFAIR_CERT_FILE'),
        key_file=os.getenv('BETFAIR_KEY_FILE')
    )
    bet_repository = BetRepository()
    account_repository = AccountRepository()
    
    # Initialize settlement command
    settlement_command = BetSettlementCommand(
        betfair_client=betfair_client,
        bet_repository=bet_repository,
        account_repository=account_repository
    )
    
    # Show current status
    display_account_status(account_repository)
    display_active_bets(bet_repository)
    
    # Get bet to settle
    market_id = input("\nEnter Market ID to settle (or 'q' to quit): ")
    if market_id.lower() == 'q':
        return
    
    # Get settlement details
    while True:
        result = input("Did the bet win? (y/n): ").lower()
        if result in ['y', 'n']:
            won = result == 'y'
            break
        print("Please enter 'y' for yes or 'n' for no")
    
    # Get original bet to calculate profit
    bet = bet_repository.get_bet_by_market_id(market_id)
    if not bet:
        print(f"Error: No bet found for market ID {market_id}")
        return
    
    # Calculate profit for winning bets
    profit = 0.0
    if won:
        profit = bet["stake"] * (bet["odds"] - 1)
        print(f"Calculated profit: £{profit:.2f}")
    
    # Create settlement request
    request = BetSettlementRequest(
        market_id=market_id,
        won=won,
        profit=profit
    )
    
    # Execute settlement
    print("\nSettling bet...")
    result = settlement_command.execute(request)
    
    if result:
        print("\n✓ Bet settled successfully!")
        display_account_status(account_repository)
    else:
        print("\n✗ Failed to settle bet")

if __name__ == "__main__":
    while True:
        settle_bet_manually()
        
        choice = input("\nSettle another bet? (y/n): ")
        if choice.lower() != 'y':
            break
    
    print("\nBet settlement complete.")