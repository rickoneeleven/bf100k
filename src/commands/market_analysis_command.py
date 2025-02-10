"""
market_analysis_command.py

Implements async Command pattern for market analysis operations.
Handles validation and analysis of betting markets according to strategy criteria.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Set
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
    fifth_market_id: str = None

class MarketAnalysisCommand:
    # Set of valid draw selection names (case insensitive)
    DRAW_VARIANTS: Set[str] = {'the draw', 'draw', 'empate', 'x'}

    def __init__(
        self,
        betfair_client: BetfairClient,
        bet_repository: BetRepository,
        account_repository: AccountRepository
    ):
        self.betfair_client = betfair_client
        self.bet_repository = bet_repository
        self.account_repository = account_repository
        
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
            return False, f"odds {odds} outside range {request.min_odds}-{request.max_odds}"
            
        if available_volume < required_stake * request.liquidity_factor:
            return False, f"liquidity {available_volume:.2f} < required {required_stake * request.liquidity_factor:.2f}"
            
        return True, "meets criteria"

    def _find_draw_selection(self, runners: List[Dict]) -> Optional[Dict]:
        """Find the Draw selection in the runners list"""
        for runner in runners:
            team_name = runner.get('teamName', '').lower()
            if team_name in self.DRAW_VARIANTS:
                return runner
        return None

    async def execute(
        self, 
        request: MarketAnalysisRequest, 
        market: Dict,
        market_book: Dict
    ) -> Optional[Dict]:
        """
        Execute market analysis command
        Returns betting opportunity if found, None otherwise
        """
        try:
            event_name = market.get('event', {}).get('name', 'Unknown Event')
            
            # Skip if market is in-play or has active bets
            if market_book.get('inplay') or await self.bet_repository.has_active_bets():
                return None
                
            # Get current balance for stake calculation
            account_status = await self.account_repository.get_account_status()
            current_balance = account_status.current_balance

            # Get start time
            market_start_time = market_book.get('marketStartTime', 'Unknown')
            if market_start_time != 'Unknown':
                start_time = datetime.fromisoformat(market_start_time.replace('Z', '+00:00'))
                formatted_time = start_time.strftime('%Y-%m-%d %H:%M:%S')
            else:
                formatted_time = 'Unknown'

            # Display market odds in cleaner format
            runners = market_book.get('runners', [])
            runner_data = []
            
            # Process and store runner data
            for runner in runners:
                ex = runner.get('ex', {})
                available_to_back = ex.get('availableToBack', [{}])[0]
                odds = available_to_back.get('price', 'N/A')
                size = available_to_back.get('size', 'N/A')
                
                runner_data.append((
                    runner.get('teamName', 'Unknown'),
                    odds,
                    size
                ))
                
                # Check betting criteria
                if available_to_back:
                    meets_criteria, _ = self.validate_market_criteria(
                        available_to_back.get('price', 0),
                        available_to_back.get('size', 0),
                        current_balance,
                        request
                    )
                    
                    if meets_criteria:
                        return {
                            "market_id": market_book.get('marketId'),
                            "selection_id": runner.get('selectionId'),
                            "team_name": runner.get('teamName', 'Unknown'),
                            "event_name": event_name,
                            "odds": available_to_back.get('price'),
                            "stake": current_balance,
                            "available_volume": available_to_back.get('size'),
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }
            
            # Log market data if we have all three runners
            if len(runner_data) == 3:  # home, draw, away
                home, draw, away = runner_data
                self.logger.info(
                    f"{formatted_time}\n"
                    f"{home[0]} (Win: {home[1]} / Available: £{home[2]}) || "
                    f"Draw: {draw[1]} / Available: £{draw[2]} || "
                    f"{away[0]} (Win: {away[1]} / Available: £{away[2]})\n"
                )

            # Special handling for dry run fallback
            is_fifth_market = request.market_id == request.fifth_market_id
            if request.dry_run and request.loop_count >= 2 and is_fifth_market:
                draw_selection = self._find_draw_selection(runners)
                if draw_selection:
                    ex = draw_selection.get('ex', {})
                    available_to_back = ex.get('availableToBack', [])
                    
                    if available_to_back:
                        return {
                            "market_id": market_book.get('marketId'),
                            "selection_id": draw_selection['selectionId'],
                            "team_name": draw_selection.get('teamName', 'The Draw'),
                            "event_name": event_name,
                            "odds": available_to_back[0].get('price'),
                            "stake": current_balance,
                            "available_volume": available_to_back[0].get('size'),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "dry_run_fallback": True
                        }
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error during market analysis: {str(e)}")
            return None