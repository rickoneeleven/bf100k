# File: src/betting_system.py

"""
betting_system.py

Main system orchestrator that coordinates betting operations using the command pattern.
Replaces legacy BetTracker functionality with a more modular, maintainable design.
"""

import logging
from typing import Optional, Dict, List
from datetime import datetime, timezone

from src.betfair_client import BetfairClient
from src.commands.market_analysis_command import MarketAnalysisCommand, MarketAnalysisRequest
from src.commands.place_bet_command import PlaceBetCommand, PlaceBetRequest
from src.commands.settle_bet_command import BetSettlementCommand, BetSettlementRequest
from src.repositories.bet_repository import BetRepository
from src.repositories.account_repository import AccountRepository

class BettingSystem:
    def __init__(
        self,
        betfair_client: BetfairClient,
        bet_repository: BetRepository,
        account_repository: AccountRepository
    ):
        self.betfair_client = betfair_client
        self.bet_repository = bet_repository
        self.account_repository = account_repository
        
        # Initialize commands
        self.market_analysis = MarketAnalysisCommand(
            betfair_client,
            bet_repository,
            account_repository
        )
        self.place_bet = PlaceBetCommand(
            betfair_client,
            bet_repository,
            account_repository
        )
        self.settle_bet = BetSettlementCommand(
            betfair_client,
            bet_repository,
            account_repository
        )
        
        # Setup logging
        self.logger = logging.getLogger('BettingSystem')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('web/logs/betting_system.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    async def scan_markets(self) -> Optional[Dict]:
        """
        Scan available markets for betting opportunities
        Returns potential bet if found, None otherwise
        """
        self.logger.info("Scanning markets for betting opportunities")
        
        try:
            # Check for active bets first
            if self.bet_repository.has_active_bets():
                self.logger.info("Active bet exists - skipping market scan")
                return None
            
            # Get available markets
            markets, market_books = self.betfair_client.get_markets_with_odds()
            if not markets or not market_books:
                self.logger.error("Failed to retrieve market data")
                return None
            
            # Analyze each market
            for market, market_book in zip(markets, market_books):
                market_id = market['marketId']
                
                # Create analysis request
                request = MarketAnalysisRequest(
                    market_id=market_id,
                    min_odds=3.0,
                    max_odds=4.0,
                    liquidity_factor=1.1
                )
                
                # Execute market analysis
                betting_opportunity = self.market_analysis.execute(request)
                if betting_opportunity:
                    self.logger.info(f"Found betting opportunity in market {market_id}")
                    return betting_opportunity
            
            self.logger.info("No suitable betting opportunities found")
            return None
            
        except Exception as e:
            self.logger.error(f"Error during market scan: {str(e)}")
            return None

    async def place_bet(self, betting_opportunity: Dict) -> Optional[Dict]:
        """
        Place a bet based on identified opportunity
        Returns bet details if successful, None otherwise
        """
        self.logger.info(f"Attempting to place bet for market {betting_opportunity['market_id']}")
        
        try:
            # Create bet placement request
            request = PlaceBetRequest(
                market_id=betting_opportunity['market_id'],
                selection_id=betting_opportunity['selection_id'],
                odds=betting_opportunity['odds'],
                stake=betting_opportunity['stake']
            )
            
            # Execute bet placement
            bet_details = self.place_bet.execute(request)
            
            if bet_details:
                self.logger.info(f"Successfully placed bet in market {request.market_id}")
                return bet_details
            else:
                self.logger.error("Bet placement failed")
                return None
                
        except Exception as e:
            self.logger.error(f"Error during bet placement: {str(e)}")
            return None

    async def settle_bet(self, market_id: str, won: bool, profit: float) -> Optional[Dict]:
        """
        Settle an existing bet
        Returns updated bet details if successful, None otherwise
        """
        self.logger.info(f"Attempting to settle bet for market {market_id}")
        
        try:
            # Create settlement request
            request = BetSettlementRequest(
                market_id=market_id,
                won=won,
                profit=profit
            )
            
            # Execute bet settlement
            settled_bet = self.settle_bet.execute(request)
            
            if settled_bet:
                self.logger.info(
                    f"Successfully settled bet: Market {market_id}, "
                    f"Won: {won}, Profit: £{profit}"
                )
                return settled_bet
            else:
                self.logger.error("Bet settlement failed")
                return None
                
        except Exception as e:
            self.logger.error(f"Error during bet settlement: {str(e)}")
            return None

    def get_active_bets(self) -> List[Dict]:
        """Get all currently active bets"""
        return self.bet_repository.get_active_bets()

    def get_settled_bets(self) -> List[Dict]:
        """Get all settled bets"""
        return self.bet_repository.get_settled_bets()

    def get_account_status(self) -> Dict:
        """Get current account status"""
        status = self.account_repository.get_account_status()
        return {
            "current_balance": status.current_balance,
            "target_amount": status.target_amount,
            "total_bets_placed": status.total_bets_placed,
            "successful_bets": status.successful_bets,
            "win_rate": self.account_repository.get_win_rate(),
            "profit_loss": self.account_repository.get_profit_loss()
        }