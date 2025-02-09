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
        self.loop_count = 0
        
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
            f"Scanning matches for betting opportunities (DRY RUN) - Loop {self.loop_count}" 
            if self.dry_run else
            "Scanning matches for betting opportunities"
        )
        
        try:
            if await self.bet_repository.has_active_bets():
                self.logger.info("Active bet exists - skipping match scan")
                return None
            
            async with self.betfair_client as client:
                markets, market_books = await client.get_markets_with_odds()
                
            if not markets or not market_books:
                self.logger.error("Failed to retrieve match data")
                return None
            
            # Get the fifth market ID if available
            fifth_market_id = markets[4]['marketId'] if len(markets) >= 5 else None
            
            # Analyze each market
            for market, market_book in zip(markets, market_books):
                market_id = market['marketId']
                request = MarketAnalysisRequest(
                    market_id=market_id,
                    min_odds=3.0,
                    max_odds=4.0,
                    liquidity_factor=1.1,
                    dry_run=self.dry_run,
                    loop_count=self.loop_count,
                    fifth_market_id=fifth_market_id
                )
                
                betting_opportunity = await self.market_analysis.execute(request)
                if betting_opportunity:
                    if self.dry_run:
                        self.logger.info(
                            f"[DRY RUN] Would place bet:\n"
                            f"Match: {betting_opportunity['event_name']}\n"
                            f"Selection: {betting_opportunity['team_name']}\n"
                            f"Odds: {betting_opportunity['odds']}\n"
                            f"Stake: £{betting_opportunity['stake']}\n"
                            f"Available Volume: £{betting_opportunity['available_volume']}"
                        )
                    return betting_opportunity

            # Increment loop count if no opportunity found
            self.loop_count += 1
            return None
            
        except Exception as e:
            self.logger.error(f"Error during market scan: {str(e)}")
            return None

    async def place_bet(self, betting_opportunity: Dict) -> Optional[Dict]:
        """Place a bet based on identified opportunity"""
        if self.dry_run:
            dry_run_msg = "[DRY RUN FALLBACK]" if betting_opportunity.get('dry_run_fallback') else "[DRY RUN]"
            self.logger.info(
                f"{dry_run_msg} Would place bet:\n"
                f"Match: {betting_opportunity['event_name']}\n"
                f"Selection: {betting_opportunity['team_name']}\n"
                f"Odds: {betting_opportunity['odds']}\n"
                f"Stake: £{betting_opportunity['stake']}\n"
                f"Available Volume: £{betting_opportunity['available_volume']}"
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
                    f"Successfully placed bet:\n"
                    f"Match: {betting_opportunity['event_name']}\n"
                    f"Selection: {betting_opportunity['team_name']}\n"
                    f"Stake: £{request.stake}\n"
                    f"Odds: {request.odds}"
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
                    f"Successfully settled bet:\n"
                    f"Match: {settled_bet.get('event_name', 'Unknown Event')}\n"
                    f"Selection: {settled_bet.get('team_name', 'Unknown Team')}\n"
                    f"Won: {won}\n"
                    f"Profit: £{profit}"
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