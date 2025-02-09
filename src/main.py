# File: src/main.py

"""
main.py

Entry point for the betting system. Handles initialization and main operation loop.
"""

import os
import asyncio
import logging
from dotenv import load_dotenv

from src.betting_system import BettingSystem
from src.betfair_client import BetfairClient
from src.repositories.bet_repository import BetRepository
from src.repositories.account_repository import AccountRepository

async def main():
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
    logger = logging.getLogger('main')
    
    try:
        # Initialize components
        betfair_client = BetfairClient(
            app_key=os.getenv('BETFAIR_APP_KEY'),
            cert_file=os.getenv('BETFAIR_CERT_FILE'),
            key_file=os.getenv('BETFAIR_KEY_FILE')
        )
        
        bet_repository = BetRepository()
        account_repository = AccountRepository()
        
        # Initialize system
        betting_system = BettingSystem(
            betfair_client=betfair_client,
            bet_repository=bet_repository,
            account_repository=account_repository
        )
        
        # Login to Betfair
        if not betfair_client.login():
            logger.error("Failed to login to Betfair")
            return
            
        logger.info("Starting betting system")
        
        while True:
            try:
                # Scan for opportunities
                opportunity = await betting_system.scan_markets()
                
                if opportunity:
                    # Place bet
                    bet = await betting_system.place_bet(opportunity)
                    if bet:
                        logger.info(
                            f"Placed bet: Market {bet['market_id']}, "
                            f"Stake: £{bet['stake']}, Odds: {bet['odds']}"
                        )
                
                # Wait before next scan
                await asyncio.sleep(60)  # Adjust timing as needed
                
            except Exception as e:
                logger.error(f"Error in main loop: {str(e)}")
                await asyncio.sleep(60)  # Wait before retry
                
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        
if __name__ == "__main__":
    asyncio.run(main())