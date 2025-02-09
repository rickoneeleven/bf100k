"""
betting_system.py

Main system orchestrator that coordinates betting operations using the command pattern.
Handles async coordination between client, repositories, and commands.
"""

import logging
from typing import Optional, Dict, List
from datetime import datetime, timezone

from .betfair_client import BetfairClient
from .commands.market_analysis_command import MarketAnalysisCommand, MarketAnalysisRequest
from .commands.place_bet_command import PlaceBetCommand, PlaceBetRequest
from .commands.settle_bet_command import BetSettlementCommand, BetSettlementRequest
from .repositories.bet_repository import BetRepository
from .repositories.account_repository import AccountRepository

class BettingSystem:
    def __init__(
        self,
        betfair_client: BetfairClient,
        bet_repository: BetRepository,
        account_repository: AccountRepository,
        dry_run: bool = True  # Default to dry run for safety
    ):
        self.betfair_client = betfair_client
        self.bet_repository = bet_repository
        self.account_repository = account_repository
        self.dry_run = dry_run
        
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
        
        # Setup logging with dry run indicator
        self.logger = logging.getLogger('BettingSystem')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('web/logs/betting_system.log')
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - [DRY RUN] %(levelname)s - %(message)s' 
            if dry_run else
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    async def scan_markets(self) -> Optional[Dict]:
        """Scan available markets for betting opportunities"""
        self.logger.info(
            "Scanning markets for betting opportunities (DRY RUN)" 
            if self.dry_run else
            "Scanning markets for betting opportunities"
        )
        
        try:
            # Original scanning logic remains the same
            if await self.bet_repository.has_active_bets():
                self.logger.info("Active bet exists - skipping market scan")
                return None
            
            async with self.betfair_client as client:
                markets, market_books = await client.get_markets_with_odds()
                
            if not markets or not market_books:
                self.logger.error("Failed to retrieve market data")
                return None
            
            # Analyze each market
            for market, market_book in zip(markets, market_books):
                market_id = market['marketId']
                request = MarketAnalysisRequest(
                    market_id=market_id,
                    min_odds=3.0,
                    max_odds=4.0,
                    liquidity_factor=1.1
                )
                
                betting_opportunity = await self.market_analysis.execute(request)
                if betting_opportunity:
                    if self.dry_run:
                        self.logger.info(
                            f"[DRY RUN] Would place bet: Market {betting_opportunity['market_id']}, "
                            f"Selection {betting_opportunity['selection_id']}, "
                            f"Odds {betting_opportunity['odds']}, "
                            f"Stake £{betting_opportunity['stake']}"
                        )
                    return betting_opportunity
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error during market scan: {str(e)}")
            return None

    async def place_bet(self, betting_opportunity: Dict) -> Optional[Dict]:
        """Place a bet based on identified opportunity"""
        if self.dry_run:
            self.logger.info(
                f"[DRY RUN] Would place bet: Market {betting_opportunity['market_id']}, "
                f"Selection {betting_opportunity['selection_id']}, "
                f"Odds {betting_opportunity['odds']}, "
                f"Stake £{betting_opportunity['stake']}"
            )
            return betting_opportunity
            
        # Original bet placement logic for non-dry run
        try:
            request = PlaceBetRequest(
                market_id=betting_opportunity['market_id'],
                selection_id=betting_opportunity['selection_id'],
                odds=betting_opportunity['odds'],
                stake=betting_opportunity['stake']
            )
            
            bet_details = await self.place_bet.execute(request)
            if bet_details:
                self.logger.info(
                    f"Successfully placed bet: Market {request.market_id}, "
                    f"stake: £{request.stake}, odds: {request.odds}"
                )
            return bet_details
                
        except Exception as e:
            self.logger.error(f"Error during bet placement: {str(e)}")
            return None


    async def settle_bet(self, market_id: str, won: bool, profit: float) -> Optional[Dict]:
        """
        Settle an existing bet asynchronously
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
            settled_bet = await self.settle_bet.execute(request)
            
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

    async def get_active_bets(self) -> List[Dict]:
        """Get all currently active bets asynchronously"""
        return await self.bet_repository.get_active_bets()

    async def get_settled_bets(self) -> List[Dict]:
        """Get all settled bets asynchronously"""
        return await self.bet_repository.get_settled_bets()

    async def get_account_status(self) -> Dict:
        """Get current account status asynchronously"""
        status = await self.account_repository.get_account_status()
        win_rate = await self.account_repository.get_win_rate()
        profit_loss = await self.account_repository.get_profit_loss()
        
        return {
            "current_balance": status.current_balance,
            "target_amount": status.target_amount,
            "total_bets_placed": status.total_bets_placed,
            "successful_bets": status.successful_bets,
            "win_rate": win_rate,
            "profit_loss": profit_loss
        }