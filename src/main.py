"""
main_improved.py

Entry point for the improved betting system. 
Handles initialization, main operation loop, and graceful shutdown of async components.
Updates include:
- Real result integration instead of simulation
- Improved selection diversity with continuous market checking
- Configurable parameters
- More robust error handling and logging
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
from .config_manager import ConfigManager

# Global variable for graceful shutdown
shutdown_event: Optional[asyncio.Event] = None

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

async def check_results(betting_system: BettingSystem):
    """Check results of active bets"""
    try:
        # Check for settled bets
        settled_bets = await betting_system.check_for_results()
        
        if settled_bets:
            logging.info(f"Found {len(settled_bets)} settled bets")
            
            # Get updated status
            status = await betting_system.get_account_status()
            logging.info(
                f"Updated status - Cycle: {status['current_cycle']}, "
                f"Balance: £{status['current_balance']:.2f}, "
                f"Total cycles: {status['total_cycles']}, "
                f"Total money lost: £{status['total_money_lost']:.2f}"
            )
    except Exception as e:
        logging.error(f"Error checking results: {str(e)}")
        logging.exception(e)

async def main_loop(betting_system: BettingSystem):
    """Main operation loop with faster shutdown response"""
    global shutdown_event
    
    # Start the result poller in the background
    await betting_system.start_result_poller()
    
    while not shutdown_event.is_set():
        try:
            # First check for results of active bets
            await check_results(betting_system)
            
            # Then scan for betting opportunities if no active bets
            if not await betting_system.bet_repository.has_active_bets():
                await run_betting_cycle(betting_system)
            
            # Wait with periodic checks for shutdown event
            for _ in range(60):  # 60 one-second intervals
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
        
        # Gracefully shutdown the betting system
        await betting_system.shutdown()
        
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
        # Initialize configuration manager
        print("Initializing configuration manager...")
        config_manager = ConfigManager()
        config = config_manager.load_config()
        
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
        
        # Reset account to configured starting stake
        print("Resetting account to starting stake...")
        initial_stake = config.get('betting', {}).get('initial_stake', 1.0)
        await account_repository.reset_to_starting_stake(initial_stake)
        
        # Initialize system with configuration
        print("Initializing betting system...")
        betting_system = BettingSystem(
            betfair_client=betfair_client,
            bet_repository=bet_repository,
            account_repository=account_repository,
            config_manager=config_manager
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
            
            # Get dry run status from config
            is_dry_run = config.get('system', {}).get('dry_run', True)
            mode_str = "DRY RUN" if is_dry_run else "LIVE"
            
            print(f"Starting betting system in {mode_str} mode with compound strategy")
            logging.info(f"Starting betting system in {mode_str} mode with compound strategy")
            logging.info(f"Initial balance: £{initial_stake}, Target: £{config.get('betting', {}).get('target_amount', 50000.0)}")
            
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