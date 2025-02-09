"""
market_analysis_command.py

Implements async Command pattern for market analysis operations.
Handles validation and analysis of betting markets according to strategy criteria.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import logging

from src.repositories.bet_repository import BetRepository
from src.repositories.account_repository import AccountRepository
from src.betfair_client import BetfairClient

@dataclass
class MarketAnalysisRequest:
    """Data structure for market analysis request"""
    market_id: str
    min_odds: float = 3.0
    max_odds: float = 4.0
    liquidity_factor: float = 1.1

class MarketAnalysisCommand:
    def __init__(
        self,
        betfair_client: BetfairClient,
        bet_repository: BetRepository,
        account_repository: AccountRepository
    ):
        self.betfair_client = betfair_client
        self.bet_repository = bet_repository
        self.account_repository = account_repository
        
        # Setup logging
        self.logger = logging.getLogger('MarketAnalysisCommand')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('web/logs/commands.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    def validate_market_criteria(
        self,
        odds: float,
        available_volume: float,
        required_stake: float,
        request: MarketAnalysisRequest
    ) -> Tuple[bool, str]:
        """
        Validate if market meets betting criteria
        Returns: (meets_criteria: bool, reason: str)
        """
        if odds < request.min_odds or odds > request.max_odds:
            return False, f"Odds {odds} outside target range ({request.min_odds}-{request.max_odds})"
            
        if available_volume < required_stake * request.liquidity_factor:
            return False, f"Insufficient liquidity: {available_volume} < {required_stake * request.liquidity_factor}"
            
        return True, "Market meets criteria"

    async def analyze_market(self, market_data: Dict, request: MarketAnalysisRequest) -> Optional[Dict]:
        """
        Analyze market for potential betting opportunities asynchronously
        Returns bet details if criteria met, None otherwise
        """
        self.logger.info(f"Analyzing market {market_data.get('marketId')} for betting opportunity")
        
        # Skip if market is in-play
        if market_data.get('inplay'):
            self.logger.info("Market is in-play - skipping")
            return None
            
        # Check for active bets
        if await self.bet_repository.has_active_bets():
            self.logger.info("Active bet exists - skipping market analysis")
            return None
            
        # Get current balance for stake calculation
        account_status = await self.account_repository.get_account_status()
        current_balance = account_status.current_balance
        
        # Analyze each runner (selection) in the market
        for runner in market_data.get('runners', []):
            ex = runner.get('ex', {})
            available_to_back = ex.get('availableToBack', [])
            
            if not available_to_back:
                continue
                
            # Get best back price and size
            best_price = available_to_back[0].get('price')
            available_size = available_to_back[0].get('size')
            
            # Check market criteria
            meets_criteria, reason = self.validate_market_criteria(
                best_price,
                available_size,
                current_balance,
                request
            )
            
            if meets_criteria:
                return {
                    "market_id": market_data.get('marketId'),
                    "selection_id": runner.get('selectionId'),
                    "runner_name": runner.get('runnerName', 'Unknown'),
                    "odds": best_price,
                    "stake": current_balance,
                    "available_volume": available_size,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            else:
                self.logger.info(f"Market criteria not met: {reason}")
                
        return None

    async def execute(self, request: MarketAnalysisRequest) -> Optional[Dict]:
        """
        Execute market analysis asynchronously
        Returns betting opportunity if found, None otherwise
        """
        self.logger.info(f"Executing market analysis for market {request.market_id}")
        
        try:
            # Get market book data
            market_books = await self.betfair_client.list_market_book([request.market_id])
            if not market_books:
                self.logger.error("Failed to retrieve market data")
                return None
                
            market_book = market_books[0]
            
            # Analyze market
            return await self.analyze_market(market_book, request)
            
        except Exception as e:
            self.logger.error(f"Error during market analysis: {str(e)}")
            return None