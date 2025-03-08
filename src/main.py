"""
main.py

Entry point for the betting system. Handles initialization, main operation loop,
and graceful shutdown of async components.
Updated to implement compound betting strategy with bet simulation.
"""

import os
import asyncio
import signal
import logging
import random
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone
from typing import Optional, Dict

from .betting_system import BettingSystem
from .betfair_client import BetfairClient
from .repositories.bet_repository import BetRepository
from .repositories.account_repository import AccountRepository
from .betting_ledger import BettingLedger

# Global variable for graceful shutdown
shutdown_event: Optional[asyncio.Event] = None

async def simulate_bet_result(bet_details: Dict) -> tuple[bool, float]:
    """
    Simulate a bet result based on odds
    
    Args:
        bet_details: Bet details including odds
        
    Returns:
        Tuple of (won: bool, profit: float)
    """
    odds = bet_details.get('odds', 0.0)
    stake = bet_details.get('stake', 0.0)
    
    # Calculate win probability based on odds (roughly inverse of odds)
    # Example: odds of 3.0 = ~33% chance of winning
    win_probability = min(1.0 / odds, 0.35)  # Cap at 35% for realism
    
    # Add some randomness to avoid always winning or losing
    random_factor = random.random()
    
    # Force some early wins in cycle 1 to demonstrate compounding
    # but make later bets more likely to lose to demonstrate cycle reset
    cycle_number = 1  # Default if not provided
    bet_in_cycle = 1  # Default if not provided
    
    if 'cycle_number' in bet_details:
        cycle_number = bet_details.get('cycle_number', 1)
    if 'bet_in_cycle' in bet_details:
        bet_in_cycle = bet_details.get('bet_in_cycle', 1)
    
    # For demonstration, make first few bets more likely to win
    if cycle_number == 1 and bet_in_cycle <= 3:
        win_probability += 0.2  # Boost win chance for first 3 bets
    elif bet_in_cycle > 5:
        win_probability -= 0.1  # Reduce win chance for later bets
    
    # Simulate result
    won = random_factor < win_probability
    
    # Calculate profit
    profit = 0.0
    if won:
        profit = stake * (odds - 1)
        
    return won, profit

async def run_betting_cycle(betting_system: BettingSystem):
    """Execute a single betting cycle"""
    try:
        # Only run if no active bets
        if await betting_system.bet_repository.has_active_bets():
            logging.info("Active bet exists - skipping market scan")
            return
            
        # Scan for opportunities
        opportunity = await betting_system.scan_markets()
        
        if opportunity:
            # Place bet (real or simulated)
            bet = await betting_system.place_bet_order(opportunity)
            if bet:
                account_status = await betting_system.get_account_status()
                logging.info(
                    f"Bet placed - Cycle #{account_status['current_cycle']}, "
                    f"Bet #{account_status['current_bet_in_cycle']} in cycle, "
                    f"Balance: £{account_status['current_balance']:.2f}"
                )
    except Exception as e:
        logging.error(f"Error in betting cycle: {str(e)}")
        logging.exception(e)

async def monitor_active_bets(betting_system: BettingSystem):
    """Monitor and update status of active bets"""
    try:
        # Get active bets
        active_bets = await betting_system.get_active_bets()
        
        if not active_bets:
            logging.debug("No active bets to monitor")
            return
            
        logging.info(f"Monitoring {len(active_bets)} active bet(s)")
            
        for bet in active_bets:
            # In a real implementation, we would check the actual market results
            # For dry run mode, simulate the result
            if betting_system.dry_run:
                # Get details for simulation
                market_id = bet.get('market_id')
                selection_id = bet.get('selection_id')
                team_name = bet.get('team_name', 'Unknown Team')
                odds = bet.get('odds')
                stake = bet.get('stake')
                
                # Simulate result
                won, profit = await simulate_bet_result(bet)
                
                # Log the simulated result
                result_str = "WON" if won else "LOST"
                logging.info(
                    f"[DRY RUN] Simulated bet result: {result_str}\n"
                    f"Market ID: {market_id}\n"
                    f"Selection: {team_name}\n"
                    f"Odds: {odds}\n"
                    f"Stake: £{stake}\n"
                    f"Profit: £{profit:.2f}"
                )
                
                # Settle the bet with the simulated result
                await betting_system.settle_bet_order(market_id, won, profit)
                
                # Log updated status
                status = await betting_system.get_account_status()
                logging.info(
                    f"Updated status - Cycle: {status['current_cycle']}, "
                    f"Balance: £{status['current_balance']:.2f}, "
                    f"Total cycles: {status['total_cycles']}, "
                    f"Total money lost: £{status['total_money_lost']:.2f}"
                )
                
                # Break after settling one bet to prevent settling multiple bets at once
                break
    except Exception as e:
        logging.error(f"Error monitoring active bets: {str(e)}")
        logging.exception(e)

async def main_loop(betting_system: BettingSystem):
    """Main operation loop with faster shutdown response"""
    global shutdown_event
    
    while not shutdown_event.is_set():
        try:
            # First monitor any active bets to check for results
            await monitor_active_bets(betting_system)
            
            # Then scan for betting opportunities if no active bets
            if not await betting_system.bet_repository.has_active_bets():
                await run_betting_cycle(betting_system)
            
            # Break the long sleep into shorter intervals to check shutdown_event more frequently
            for _ in range(3):  # 3 one-second intervals (check every 3 seconds)
                if shutdown_event.is_set():
                    break
                await asyncio.sleep(1)
                
        except Exception as e:
            logging.error(f"Error in main loop: {str(e)}")
            logging.exception(e)
            # Shorter error retry interval
            for _ in range(5):  # 5 one-second intervals
                if shutdown_event.is_set():
                    break
                await asyncio.sleep(1)

def handle_shutdown(signum, frame):
    """Handle shutdown signals"""
    logging.info("Shutdown signal received")
    if shutdown_event:
        shutdown_event.set()

async def display_status(betting_system: BettingSystem):
    """Display current system status"""
    try:
        # Get account status and ledger info
        status = await betting_system.get_account_status()
        ledger = await betting_system.get_ledger_info()
        
        # Display summary
        logging.info("\n" + "="*60)
        logging.info("BETTING SYSTEM STATUS SUMMARY")
        logging.info("="*60)
        logging.info(f"Current Cycle: #{status['current_cycle']}")
        logging.info(f"Current Bet in Cycle: #{status['current_bet_in_cycle']}")
        logging.info(f"Current Balance: £{status['current_balance']:.2f}")
        logging.info(f"Target Amount: £{status['target_amount']:.2f}")
        logging.info(f"Total Cycles Completed: {status['total_cycles']}")
        logging.info(f"Total Bets Placed: {status['total_bets_placed']}")
        logging.info(f"Successful Bets: {status['successful_bets']}")
        logging.info(f"Win Rate: {status['win_rate']:.1f}%")
        logging.info(f"Total Money Lost: £{status['total_money_lost']:.2f}")
        logging.info(f"Highest Balance Reached: £{ledger['highest_balance']:.2f}")
        logging.info("="*60 + "\n")
    except Exception as e:
        logging.error(f"Error displaying status: {str(e)}")

async def cleanup(betting_system: BettingSystem):
    """Perform cleanup operations"""
    try:
        # Display final status
        await display_status(betting_system)
        
        # Close any open connections
        if hasattr(betting_system.betfair_client, 'close_session'):
            await betting_system.betfair_client.close_session()
        
        logging.info("Cleanup completed")
    except Exception as e:
        logging.error(f"Error during cleanup: {str(e)}")
        logging.exception(e)

async def main():
    """Entry point for the betting system"""
    global shutdown_event
    print("Setting up shutdown event...")
    shutdown_event = asyncio.Event()
    
    # Load environment variables
    print("Loading environment variables...")
    load_dotenv()
    
    # Setup logging
    print("Setting up logging...")
    # Ensure log directory exists
    log_dir = Path('web/logs')
    log_dir.mkdir(parents=True, exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('web/logs/main.log'),
            logging.StreamHandler()
        ]
    )
    
    print("Setting up signal handlers...")
    # Setup signal handlers
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    
    try:
        # Initialize components
        print("Initializing Betfair client...")
        betfair_client = BetfairClient(
            app_key=os.getenv('BETFAIR_APP_KEY'),
            cert_file=os.getenv('BETFAIR_CERT_FILE'),
            key_file=os.getenv('BETFAIR_KEY_FILE')
        )
        
        print("Initializing repositories...")
        bet_repository = BetRepository()
        account_repository = AccountRepository()
        
        # Initialize BettingLedger to ensure it exists
        print("Initializing betting ledger...")
        betting_ledger = BettingLedger()
        
        # Reset account to starting stake (£1) to ensure proper initialization
        print("Resetting account to starting stake...")
        await account_repository.reset_to_starting_stake()
        
        # Initialize system in dry run mode
        print("Initializing betting system...")
        betting_system = BettingSystem(
            betfair_client=betfair_client,
            bet_repository=bet_repository,
            account_repository=account_repository,
            dry_run=True  # Enable dry run mode
        )
        
        # Login to Betfair
        print("Logging into Betfair API...")
        async with betfair_client as client:
            login_result = await client.login()
            print(f"Login result: {login_result}")
            
            if not login_result:
                print("Failed to login to Betfair")
                logging.error("Failed to login to Betfair")
                return
            
            print("Starting betting system in DRY RUN mode with compound strategy")
            logging.info("Starting betting system in DRY RUN mode with compound strategy")
            logging.info("Initial balance: £1.00, Target: £50,000.00")
            
            # Display initial status
            print("Displaying initial status...")
            await display_status(betting_system)
            
            try:
                # Run main loop
                print("Starting main loop...")
                await main_loop(betting_system)
            except asyncio.CancelledError:
                print("Main loop cancelled")
                logging.info("Main loop cancelled")
            finally:
                # Ensure cleanup runs
                print("Running cleanup...")
                await cleanup(betting_system)
            
    except Exception as e:
        print(f"Fatal error: {str(e)}")
        logging.error(f"Fatal error: {str(e)}")
        logging.exception(e)
    finally:
        # Ensure all tasks are cancelled
        print("Cancelling remaining tasks...")
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()
        print("Main function completed.")
        
if __name__ == "__main__":
    print("Starting Betfair Compound Betting System...")
    try:
        print("Initializing asyncio event loop...")
        asyncio.run(main())
        print("Main event loop completed.")
    except KeyboardInterrupt:
        print("Process interrupted by user")
        logging.info("Process interrupted by user")
    except Exception as e:
        print(f"ERROR: Process terminated due to error: {str(e)}")
        print(f"Exception details: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        logging.error(f"Process terminated due to error: {str(e)}")
    finally:
        print("Process shutdown complete")
        logging.info("Process shutdown complete")