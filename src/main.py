"""
main.py

Entry point for the betting system with command-line interface.
Handles initialization, interactive command processing, and graceful shutdown.
UPDATED: Removed automatic ledger reset to support compound betting strategy.
UPDATED: Added log rotation and management to control log file size and retention.
"""

import os
import asyncio
import signal
import logging
import select
import sys
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
from .command_processor import CommandProcessor
from .log_manager import LogManager  # Import the new LogManager

# Global variables for shutdown control
shutdown_event: Optional[asyncio.Event] = None
shutdown_in_progress: bool = False

async def run_betting_cycle(betting_system: BettingSystem):
    """Execute a single betting cycle"""
    try:
        # Only run if no active bets
        if await betting_system.bet_repository.has_active_bets():
            logging.info("Active bet exists - skipping market scan")
            return
            
        # Get current cycle info and next stake amount using compound strategy
        cycle_info = await betting_system.betting_ledger.get_current_cycle_info()
        next_stake = await betting_system.betting_ledger.get_next_stake()
        
        logging.info(
            f"Running betting cycle - Cycle: {cycle_info['current_cycle']}, "
            f"Bet in cycle: {cycle_info['current_bet_in_cycle'] + 1}, "
            f"Next stake: £{next_stake:.2f} (compound strategy)"
        )
            
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
                    f"Balance: £{account_status['current_balance']:.2f}, "
                    f"Stake: £{bet['stake']:.2f}"
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
            ledger = await betting_system.get_ledger_info()
            
            logging.info(
                f"Updated status - Cycle: {status['current_cycle']}, "
                f"Balance: £{status['current_balance']:.2f}, "
                f"Total cycles: {status['total_cycles']}, "
                f"Total money lost: £{status['total_money_lost']:.2f}, "
                f"Total commission paid: £{ledger.get('total_commission_paid', 0.0):.2f}"
            )
    except Exception as e:
        logging.error(f"Error checking results: {str(e)}")
        logging.exception(e)

async def display_status(betting_system: BettingSystem):
    """Display current system status"""
    try:
        # Get account status and ledger info
        status = await betting_system.get_account_status()
        ledger = await betting_system.get_ledger_info()
        
        # Get next stake using compound strategy
        next_stake = await betting_system.betting_ledger.get_next_stake()
        
        # Display summary
        print("\n" + "="*60)
        print("BETTING SYSTEM STATUS SUMMARY")
        print("="*60)
        print(f"Current Cycle: #{status['current_cycle']}")
        print(f"Current Bet in Cycle: #{status['current_bet_in_cycle']}")
        print(f"Current Balance: £{status['current_balance']:.2f}")
        print(f"Next Bet Stake: £{next_stake:.2f}")
        print(f"Target Amount: £{status['target_amount']:.2f}")
        print(f"Total Cycles Completed: {status['total_cycles']}")
        print(f"Total Bets Placed: {status['total_bets_placed']}")
        print(f"Successful Bets: {status['successful_bets']}")
        print(f"Win Rate: {status['win_rate']:.1f}%")
        print(f"Total Money Lost: £{status['total_money_lost']:.2f}")
        print(f"Total Commission Paid: £{ledger.get('total_commission_paid', 0.0):.2f}")
        print(f"Highest Balance Reached: £{ledger['highest_balance']:.2f}")
        print("="*60 + "\n")
        
        logging.info("\n" + "="*60)
        logging.info("BETTING SYSTEM STATUS SUMMARY")
        logging.info("="*60)
        logging.info(f"Current Cycle: #{status['current_cycle']}")
        logging.info(f"Current Bet in Cycle: #{status['current_bet_in_cycle']}")
        logging.info(f"Current Balance: £{status['current_balance']:.2f}")
        logging.info(f"Next Bet Stake: £{next_stake:.2f}")
        logging.info(f"Target Amount: £{status['target_amount']:.2f}")
        logging.info(f"Total Cycles Completed: {status['total_cycles']}")
        logging.info(f"Total Bets Placed: {status['total_bets_placed']}")
        logging.info(f"Successful Bets: {status['successful_bets']}")
        logging.info(f"Win Rate: {status['win_rate']:.1f}%")
        logging.info(f"Total Money Lost: £{status['total_money_lost']:.2f}")
        logging.info(f"Total Commission Paid: £{ledger.get('total_commission_paid', 0.0):.2f}")
        logging.info(f"Highest Balance Reached: £{ledger['highest_balance']:.2f}")
        logging.info("="*60 + "\n")
    except Exception as e:
        logging.error(f"Error displaying status: {str(e)}")

async def main_loop_with_commands(betting_system: BettingSystem):
    """Main operation loop with command processing and countdown timer"""
    global shutdown_event, shutdown_in_progress
    
    # Initialize command processor
    cmd_processor = CommandProcessor(betting_system)
    
    # Start the result poller in the background
    result_poller_task = await betting_system.start_result_poller()
    
    # Show available commands
    await cmd_processor.cmd_help()
    
    try:
        while not shutdown_event.is_set() and not cmd_processor.should_exit:
            try:
                # First check for results of active bets
                await check_results(betting_system)
                
                # Check if there are active bets
                has_active_bets = await betting_system.bet_repository.has_active_bets()
                
                # Automatically display bet details if there are active bets
                if has_active_bets:
                    await cmd_processor.cmd_bet_details()
                
                # Then scan for betting opportunities if no active bets
                if not has_active_bets:
                    await run_betting_cycle(betting_system)
                
                # Wait with countdown and command processing
                wait_seconds = 60  # Default wait time
                
                print(f"\nWaiting {wait_seconds} seconds before next cycle...")
                print("Enter commands during this time. Type 'help' for available commands.")
                
                # Process commands during wait period
                for remaining in range(wait_seconds, 0, -1):
                    if shutdown_event.is_set() or cmd_processor.should_exit:
                        break
                        
                    # Display countdown
                    cmd_processor.print_countdown(remaining)
                    
                    # Check for input with timeout (non-blocking)
                    ready_to_read, _, _ = select.select([sys.stdin], [], [], 0.1)
                    
                    if ready_to_read:
                        command = sys.stdin.readline().strip()
                        print()  # New line after input
                        
                        if command:
                            await cmd_processor.process_command(command)
                        else:
                            # Empty input (just Enter) shows status
                            await cmd_processor.cmd_status()
                    
                    # Sleep briefly to prevent CPU spinning
                    await asyncio.sleep(0.9)
                    
            except asyncio.CancelledError:
                # Handle task cancellation
                logging.info("Main loop task cancelled")
                break
            except Exception as e:
                logging.error(f"Error in main loop: {str(e)}")
                logging.exception(e)
                # Shorter error retry interval
                await asyncio.sleep(5)
    finally:
        # Ensure cleanup runs
        if cmd_processor.should_exit:
            logging.info("Command exit requested")
        
        # Cancel the result poller task if it's still running
        if not result_poller_task.done():
            result_poller_task.cancel()
            try:
                await result_poller_task
            except asyncio.CancelledError:
                pass
        
        await cleanup(betting_system)

def handle_shutdown(signum, frame):
    """Handle shutdown signals with improved handling for repeated signals"""
    global shutdown_event, shutdown_in_progress
    
    # If shutdown is already in progress, force exit on repeated signals
    if shutdown_in_progress:
        print("\nForced exit due to repeated shutdown signals")
        logging.warning("Forced exit due to repeated shutdown signals")
        os._exit(1)  # Force immediate exit
    
    # Set flags for graceful shutdown
    print("\nShutdown signal received. Press Ctrl+C again to force exit.")
    logging.info("Shutdown signal received")
    shutdown_in_progress = True
    
    if shutdown_event:
        shutdown_event.set()

async def cleanup(betting_system: BettingSystem):
    """Perform cleanup operations with timeout"""
    try:
        print("\nShutting down. Please wait...")
        
        # Display final status
        await display_status(betting_system)
        
        # Set a timeout for graceful shutdown
        try:
            # Use wait_for to set a timeout for the shutdown
            await asyncio.wait_for(betting_system.shutdown(), timeout=10.0)
        except asyncio.TimeoutError:
            print("Shutdown timed out. Some operations may not have completed.")
            logging.warning("Shutdown timed out. Some operations may not have completed.")
        
        logging.info("Cleanup completed")
        print("System shutdown complete. Goodbye!")
    except Exception as e:
        logging.error(f"Error during cleanup: {str(e)}")
        logging.exception(e)

async def main():
    """Entry point for the betting system"""
    global shutdown_event, shutdown_in_progress
    print("Setting up shutdown event...")
    shutdown_event = asyncio.Event()
    shutdown_in_progress = False
    
    # Load environment variables
    print("Loading environment variables...")
    load_dotenv()
    
    # Initialize log management before setting up other logging
    print("Initializing log management...")
    LogManager.initialize_system_logging(retention_days=3)
    
    # Check and truncate existing large log files
    LogManager.truncate_old_logs('web/logs', retention_days=3)
    
    # Setup logging with rotation
    print("Setting up logging with rotation...")
    # Ensure log directory exists
    log_dir = Path('web/logs')
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Set up main logger using LogManager
    main_logger = LogManager.setup_logger(
        'main',
        'web/logs/main.log',
        level=logging.INFO,
        retention_days=3
    )
    
    # Set root logger to use main logger's handlers
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    for handler in main_logger.handlers:
        root_logger.addHandler(handler)
    
    logging.info("Logging initialized with 3-day retention")
    
    print("Setting up signal handlers...")
    # Setup signal handlers
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    
    # Create a reference to the main task so we can cancel it
    main_task = None
    
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
        
        # Reset account balance but not the ledger (preserves compound betting data)
        print("Resetting account to starting stake...")
        initial_stake = config.get('betting', {}).get('initial_stake', 1.0)
        await account_repository.reset_to_starting_stake(initial_stake)
        
        # Get current ledger info to check if we should use compound strategy
        ledger_info = await betting_ledger.get_ledger()
        has_previous_profit = ledger_info.get('last_winning_profit', 0.0) > 0
        
        if has_previous_profit:
            print(f"Found previous winning profit: £{ledger_info['last_winning_profit']:.2f}")
            print("Using compound betting strategy with previous profit as next stake")
        else:
            print(f"No previous profit found, using initial stake: £{initial_stake}")
        
        # After initialization
        account_status = await account_repository.get_account_status()
        print(f"DEBUG - Account balance: £{account_status.current_balance}")
        print(f"DEBUG - Ledger starting stake: £{ledger_info['starting_stake']}")
        print(f"DEBUG - Ledger highest balance: £{ledger_info['highest_balance']}")
        print(f"DEBUG - Current cycle: {ledger_info['current_cycle']}")
        print(f"DEBUG - Current bet in cycle: {ledger_info['current_bet_in_cycle']}")
        if has_previous_profit:
            print(f"DEBUG - Last winning profit: £{ledger_info['last_winning_profit']}")
        
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
                # Create the main loop task
                main_task = asyncio.create_task(main_loop_with_commands(betting_system))
                
                # Wait for shutdown event or task completion
                await shutdown_event.wait()
                
                # Cancel the main task if it's still running
                if main_task and not main_task.done():
                    main_task.cancel()
                    try:
                        await main_task
                    except asyncio.CancelledError:
                        pass
                
            except asyncio.CancelledError:
                print("Main task cancelled")
                logging.info("Main task cancelled")
            finally:
                # Ensure cleanup runs
                if not shutdown_in_progress:
                    # This can happen if the main task exits without setting shutdown_event
                    print("Running cleanup...")
                    await cleanup(betting_system)
            
    except Exception as e:
        print(f"Fatal error: {str(e)}")
        logging.error(f"Fatal error: {str(e)}")
        logging.exception(e)
    finally:
        # Cancel the main task if it exists and is still running
        if main_task and not main_task.done():
            main_task.cancel()
        
        # Ensure all tasks are cancelled
        print("Cancelling remaining tasks...")
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()
        print("Main function completed.")
        
if __name__ == "__main__":
    print("Starting Betfair Compound Betting System with Command Interface...")
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