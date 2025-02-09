"""
market_analysis_command.py

Implements async Command pattern for market analysis operations.
Handles validation and analysis of betting markets according to strategy criteria.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import logging

from ..repositories.bet_repository import BetRepository
from ..repositories.account_repository import AccountRepository
from ..betfair_client import BetfairClient

@dataclass
class MarketAnalysisRequest:
    """Data structure for market analysis request"""
    market_id: str
    min_odds: float = 3.0
    max_odds: float = 4.0
    liquidity_factor: float = 1.1
    dry_run: bool = True
    loop_count: int = 0
    fifth_market_id: str = None  # ID of the 5th market in the list

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

    def _find_draw_selection(self, runners: List[Dict]) -> Optional[Dict]:
        """Find the Draw selection in the runners list"""
        for runner in runners:
            if runner.get('runnerName', '').lower() == 'the draw':
                return runner
        return None

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

        # Special handling for dry run fallback - only on 5th market after 2 loops
        is_fifth_market = request.market_id == request.fifth_market_id
        if request.dry_run and request.loop_count >= 2 and is_fifth_market:
            self.logger.info("Dry run fallback: Selecting The Draw (ID: 58805) on 5th market")
            # Find runner with selection ID 58805 (The Draw)
            for runner in market_data.get('runners', []):
                if runner.get('selectionId') == 58805:
                    ex = runner.get('ex', {})
                    available_to_back = ex.get('availableToBack', [])
                    
                    if available_to_back:
                        return {
                            "market_id": market_data.get('marketId'),
                            "selection_id": 58805,
                            "runner_name": "The Draw",
                            "odds": available_to_back[0].get('price'),
                            "stake": current_balance,
                            "available_volume": available_to_back[0].get('size'),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "dry_run_fallback": True
                        }
            self.logger.warning("Could not find The Draw selection in fifth market")
            
            if draw_selection:
                ex = draw_selection.get('ex', {})
                available_to_back = ex.get('availableToBack', [])
                
                if available_to_back:
                    return {
                        "market_id": market_data.get('marketId'),
                        "selection_id": draw_selection.get('selectionId'),
                        "runner_name": draw_selection.get('runnerName', 'The Draw'),
                        "odds": available_to_back[0].get('price'),
                        "stake": current_balance,
                        "available_volume": available_to_back[0].get('size'),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "dry_run_fallback": True
                    }
            
        # Normal market analysis
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
                self.logger.info(f"Found opportunity for runner: {runner.get('runnerName', 'Unknown')}")
                
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
            # Get market book data with runner information
            market_books = await self.betfair_client.list_market_book(
                [request.market_id],
                # Pass empty dict to ensure runner names are mapped
                market_runners={}
            )
            
            if not market_books:
                self.logger.error("Failed to retrieve market data")
                return None
                
            market_book = market_books[0]
            
            # Analyze market
            return await self.analyze_market(market_book, request)
            
        except Exception as e:
            self.logger.error(f"Error during market analysis: {str(e)}")
            return None