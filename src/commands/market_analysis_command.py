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

    def _sort_runners_by_type(self, runners: List[Dict]) -> Tuple[Dict, Dict, Dict]:
        """Sort runners into home team, away team, and draw"""
        home_team = None
        away_team = None
        draw = None
        
        for runner in runners:
            team_name = runner.get('teamName', '').lower()
            if team_name in self.DRAW_VARIANTS:
                draw = runner
            elif not home_team:
                home_team = runner
            else:
                away_team = runner
                
        return home_team, draw, away_team

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
            market_id = market_book.get('marketId', 'Unknown Market ID')
            
            # Skip if market is in-play or has active bets
            if market_book.get('inplay') or await self.bet_repository.has_active_bets():
                return None
                
            # Get current balance for stake calculation
            account_status = await self.account_repository.get_account_status()
            current_balance = account_status.current_balance

            # Get start time
            market_start_time = market.get('marketStartTime', '')
            if market_start_time:
                start_time = datetime.fromisoformat(market_start_time.replace('Z', '+00:00'))
                formatted_time = start_time.strftime('%Y-%m-%d %H:%M:%S')
                self.logger.info(f"\n{formatted_time}")

            # Process runners
            runners = market_book.get('runners', [])
            home_team, draw, away_team = self._sort_runners_by_type(runners)
            
            if home_team and draw and away_team:
                # Get odds and sizes
                home_odds = home_team.get('ex', {}).get('availableToBack', [{}])[0].get('price', 'N/A')
                home_size = home_team.get('ex', {}).get('availableToBack', [{}])[0].get('size', 'N/A')
                home_id = home_team.get('selectionId', 'N/A')
                
                draw_odds = draw.get('ex', {}).get('availableToBack', [{}])[0].get('price', 'N/A')
                draw_size = draw.get('ex', {}).get('availableToBack', [{}])[0].get('size', 'N/A')
                draw_id = draw.get('selectionId', 'N/A')
                
                away_odds = away_team.get('ex', {}).get('availableToBack', [{}])[0].get('price', 'N/A')
                away_size = away_team.get('ex', {}).get('availableToBack', [{}])[0].get('size', 'N/A')
                away_id = away_team.get('selectionId', 'N/A')
                
                self.logger.info(
                    f"MarketID: {market_id} || "
                    f"{home_team['teamName']} (Win: {home_odds} / Available: £{home_size} / selectionID: {home_id}) || "
                    f"Draw (Win: {draw_odds} / Available: £{draw_size} / selectionID: {draw_id}) || "
                    f"{away_team['teamName']} (Win: {away_odds} / Available: £{away_size} / selectionID: {away_id})\n"
                )

            # Check betting criteria for each runner
            for runner in runners:
                ex = runner.get('ex', {})
                available_to_back = ex.get('availableToBack', [{}])[0]
                
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
                            "team_name": runner.get('teamName', 'Unknown Team'),
                            "event_name": event_name,
                            "odds": available_to_back.get('price'),
                            "stake": current_balance,
                            "available_volume": available_to_back.get('size'),
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }

            # Special handling for dry run fallback
            is_fifth_market = request.market_id == request.fifth_market_id
            if request.dry_run and request.loop_count >= 2 and is_fifth_market and draw:
                ex = draw.get('ex', {})
                available_to_back = ex.get('availableToBack', [{}])[0]
                
                if available_to_back:
                    return {
                        "market_id": market_book.get('marketId'),
                        "selection_id": draw['selectionId'],
                        "team_name": draw.get('teamName', 'The Draw'),
                        "event_name": event_name,
                        "odds": available_to_back.get('price'),
                        "stake": current_balance,
                        "available_volume": available_to_back.get('size'),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "dry_run_fallback": True
                    }
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error during market analysis: {str(e)}")
            return None