"""
main.py

Entry point for the betting system. Handles initialization, main operation loop,
and graceful shutdown of async components.
"""

import os
import asyncio
import signal
import logging
from dotenv import load_dotenv
from typing import Optional

from .betting_system import BettingSystem
from .betfair_client import BetfairClient
from .repositories.bet_repository import BetRepository
from .repositories.account_repository import AccountRepository

# Global variable for graceful shutdown
shutdown_event: Optional[asyncio.Event] = None

async def run_betting_cycle(betting_system: BettingSystem):
    """Execute a single betting cycle"""
    try:
        # Scan for opportunities
        opportunity = await betting_system.scan_markets()
        
        if opportunity:
            if betting_system.dry_run:
                logging.info(
                    f"[DRY RUN] Found betting opportunity:\n"
                    f"Market ID: {opportunity['market_id']}\n"
                    f"Selection ID: {opportunity['selection_id']}\n"
                    f"Odds: {opportunity['odds']}\n"
                    f"Stake: £{opportunity['stake']}\n"
                    f"Available Volume: £{opportunity.get('available_volume', 'Unknown')}"
                )
            else:
                # Place real bet
                bet = await betting_system.place_bet(opportunity)
                if bet:
                    logging.info(
                        f"Placed bet: Market {bet['market_id']}, "
                        f"Stake: £{bet['stake']}, Odds: {bet['odds']}"
                    )
    except Exception as e:
        logging.error(f"Error in betting cycle: {str(e)}")

async def monitor_active_bets(betting_system: BettingSystem):
    """Monitor and update status of active bets"""
    try:
        active_bets = await betting_system.get_active_bets()
        for bet in active_bets:
            # In a real implementation, we would:
            # 1. Check market status
            # 2. Verify if bet is settled
            # 3. Calculate profit/loss
            # 4. Call settle_bet with actual results
            pass
    except Exception as e:
        logging.error(f"Error monitoring active bets: {str(e)}")

async def main_loop(betting_system: BettingSystem):
    """Main operation loop with faster shutdown response"""
    global shutdown_event
    
    while not shutdown_event.is_set():
        try:
            # Execute betting cycle
            await run_betting_cycle(betting_system)
            
            # Monitor active bets
            await monitor_active_bets(betting_system)
            
            # Break the long sleep into shorter intervals to check shutdown_event more frequently
            for _ in range(60):  # 60 one-second intervals
                if shutdown_event.is_set():
                    break
                await asyncio.sleep(1)  # Check shutdown_event every second
                
        except Exception as e:
            logging.error(f"Error in main loop: {str(e)}")
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

async def cleanup(betting_system: BettingSystem):
    """Perform cleanup operations"""
    try:
        # Log final status
        status = await betting_system.get_account_status()
        logging.info(f"Final account status: {status}")
        
        # Close any open connections
        if hasattr(betting_system.betfair_client, 'close_session'):
            await betting_system.betfair_client.close_session()
        
        logging.info("Cleanup completed")
    except Exception as e:
        logging.error(f"Error during cleanup: {str(e)}")

async def main():
    """Entry point for the betting system"""
    global shutdown_event
    shutdown_event = asyncio.Event()
    
    # Load environment variables
    load_dotenv()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('web/logs/main.log'),
            logging.StreamHandler()
        ]
    )
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    
    try:
        # Initialize components
        betfair_client = BetfairClient(
            app_key=os.getenv('BETFAIR_APP_KEY'),
            cert_file=os.getenv('BETFAIR_CERT_FILE'),
            key_file=os.getenv('BETFAIR_KEY_FILE')
        )
        
        bet_repository = BetRepository()
        account_repository = AccountRepository()
        
        # Initialize system in dry run mode
        betting_system = BettingSystem(
            betfair_client=betfair_client,
            bet_repository=bet_repository,
            account_repository=account_repository,
            dry_run=True  # Enable dry run mode
        )
        
        # Login to Betfair
        async with betfair_client as client:
            if not await client.login():
                logging.error("Failed to login to Betfair")
                return
            
            logging.info("Starting betting system in DRY RUN mode")
            
            try:
                # Run main loop
                await main_loop(betting_system)
            except asyncio.CancelledError:
                logging.info("Main loop cancelled")
            finally:
                # Ensure cleanup runs
                await cleanup(betting_system)
            
    except Exception as e:
        logging.error(f"Fatal error: {str(e)}")
    finally:
        # Ensure all tasks are cancelled
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()
        
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Process interrupted by user")
    except Exception as e:
        logging.error(f"Process terminated due to error: {str(e)}")
    finally:
        logging.info("Process shutdown complete")