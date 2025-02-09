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
        event_name = market_data.get('eventName', 'Unknown Event')
        self.logger.info(f"Analyzing match: {event_name} (Market: {market_data.get('marketId')})")
        
        # Skip if market is in-play
        if market_data.get('inplay'):
            self.logger.info(f"Match {event_name} is in-play - skipping")
            return None
            
        # Check for active bets
        if await self.bet_repository.has_active_bets():
            self.logger.info("Active bet exists - skipping match analysis")
            return None
            
        # Get current balance for stake calculation
        account_status = await self.account_repository.get_account_status()
        current_balance = account_status.current_balance

        # Special handling for dry run fallback
        is_fifth_market = request.market_id == request.fifth_market_id
        if request.dry_run and request.loop_count >= 2 and is_fifth_market:
            self.logger.info(f"Dry run fallback: Looking for Draw in match: {event_name}")
            
            draw_selection = self._find_draw_selection(market_data.get('runners', []))
            if draw_selection:
                ex = draw_selection.get('ex', {})
                available_to_back = ex.get('availableToBack', [])
                
                if available_to_back:
                    return {
                        "market_id": market_data.get('marketId'),
                        "selection_id": draw_selection['selectionId'],
                        "team_name": "The Draw",
                        "event_name": event_name,
                        "odds": available_to_back[0].get('price'),
                        "stake": current_balance,
                        "available_volume": available_to_back[0].get('size'),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "dry_run_fallback": True
                    }
            
            self.logger.warning(f"Could not find Draw selection in match: {event_name}")
            return None
            
        # Normal market analysis
        for runner in market_data.get('runners', []):
            ex = runner.get('ex', {})
            available_to_back = ex.get('availableToBack', [])
            
            if not available_to_back:
                continue
                
            team_name = runner.get('teamName', 'Unknown Team')
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
                self.logger.info(f"Found opportunity for {team_name} in {event_name}")
                
                return {
                    "market_id": market_data.get('marketId'),
                    "selection_id": runner.get('selectionId'),
                    "team_name": team_name,
                    "event_name": event_name,
                    "odds": best_price,
                    "stake": current_balance,
                    "available_volume": available_size,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            else:
                self.logger.info(f"Market criteria not met for {team_name} in {event_name}: {reason}")
                
        return None

    async def execute(self, request: MarketAnalysisRequest) -> Optional[Dict]:
        """
        Execute market analysis asynchronously
        Returns betting opportunity if found, None otherwise
        """
        self.logger.info(f"Executing market analysis for match with market ID: {request.market_id}")
        
        try:
            # First get the market catalog to get team names
            async with self.betfair_client as client:
                markets = await client.get_football_markets_for_today()
                
            if not markets:
                self.logger.error("Failed to retrieve market catalog")
                return None

            # Find the relevant market data
            market_data = next((m for m in markets if m['marketId'] == request.market_id), None)
            if not market_data:
                self.logger.error(f"Could not find market {request.market_id} in catalog")
                return None

            # Now get market book with runner information
            market_books = await self.betfair_client.list_market_book(
                [request.market_id],
                {request.market_id: market_data.get('runners', [])}  # Pass the actual runners data
            )
            
            if not market_books:
                self.logger.error("Failed to retrieve match data")
                return None
                
            market_book = market_books[0]
            # Add event name from catalog data
            market_book['eventName'] = market_data.get('event', {}).get('name', 'Unknown Event')
            
            # Analyze market
            return await self.analyze_market(market_book, request)
            
        except Exception as e:
            self.logger.error(f"Error during match analysis: {str(e)}")
            return None