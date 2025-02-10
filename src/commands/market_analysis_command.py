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
from ..selection_mapper import SelectionMapper

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
        self.selection_mapper = SelectionMapper()
        
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

    async def _get_or_create_team_mapping(self, selection_id: str, team_name: str) -> str:
        """Get team name from mapper or create new mapping"""
        try:
            # Try to get existing mapping
            mapped_name = await self.selection_mapper.get_team_name(str(selection_id))
            if mapped_name:
                return mapped_name
                
            # Create new mapping if none exists
            await self.selection_mapper.add_mapping(str(selection_id), team_name)
            return team_name
            
        except Exception as e:
            self.logger.error(f"Error managing team mapping: {str(e)}")
            return team_name  # Fall back to original name on error

    async def _sort_runners_by_type(self, runners: List[Dict]) -> Tuple[Dict, Dict, Dict]:
        """Sort runners into home team, away team, and draw with consistent naming"""
        home_team = None
        away_team = None
        draw = None
        
        for runner in runners:
            # Get selection ID and original team name
            selection_id = str(runner.get('selectionId', ''))
            original_name = runner.get('teamName', '').lower()
            
            # Get or create mapping
            mapped_name = await self._get_or_create_team_mapping(selection_id, original_name)
            runner['teamName'] = mapped_name  # Update with mapped name
            
            if mapped_name.lower() in self.DRAW_VARIANTS:
                draw = runner
            elif not home_team:
                home_team = runner
            else:
                away_team = runner
                
        return home_team, draw, away_team

    def _format_market_time(self, market_start_time: str) -> Optional[str]:
        """Format market start time for logging"""
        if market_start_time:
            start_time = datetime.fromisoformat(market_start_time.replace('Z', '+00:00'))
            return start_time.strftime('%Y-%m-%d %H:%M:%S')
        return None

    async def _log_runner_details(
        self,
        market_id: str,
        event_name: str,
        home_team: Dict,
        draw: Dict,
        away_team: Dict
    ) -> None:
        """Log details of all runners in the market"""
        # Get odds and sizes for home team
        home_odds = home_team.get('ex', {}).get('availableToBack', [{}])[0].get('price', 'N/A')
        home_size = home_team.get('ex', {}).get('availableToBack', [{}])[0].get('size', 'N/A')
        home_id = home_team.get('selectionId', 'N/A')
        home_name = await self._get_or_create_team_mapping(str(home_id), home_team.get('teamName', 'Unknown'))
        
        # Get odds and sizes for draw
        draw_odds = draw.get('ex', {}).get('availableToBack', [{}])[0].get('price', 'N/A')
        draw_size = draw.get('ex', {}).get('availableToBack', [{}])[0].get('size', 'N/A')
        draw_id = draw.get('selectionId', 'N/A')
        
        # Get odds and sizes for away team
        away_odds = away_team.get('ex', {}).get('availableToBack', [{}])[0].get('price', 'N/A')
        away_size = away_team.get('ex', {}).get('availableToBack', [{}])[0].get('size', 'N/A')
        away_id = away_team.get('selectionId', 'N/A')
        away_name = await self._get_or_create_team_mapping(str(away_id), away_team.get('teamName', 'Unknown'))
        
        self.logger.info(
            f"MarketID: {market_id} Event: {event_name} || "
            f"{home_name} (Win: {home_odds} / Available: £{home_size} / selectionID: {home_id}) || "
            f"Draw (Win: {draw_odds} / Available: £{draw_size} / selectionID: {draw_id}) || "
            f"{away_name} (Win: {away_odds} / Available: £{away_size} / selectionID: {away_id})\n"
        )

    async def _create_betting_opportunity(
        self,
        market_id: str,
        market: Dict,
        runner: Dict,
        odds: float,
        stake: float,
        available_volume: float,
        is_dry_run_fallback: bool = False
    ) -> Dict:
        """Create a standardized betting opportunity dictionary"""
        # Get mapped team name
        selection_id = str(runner.get('selectionId'))
        team_name = await self._get_or_create_team_mapping(
            selection_id,
            runner.get('teamName', 'Unknown Team')
        )
        
        opportunity = {
            "market_id": market_id,
            "selection_id": runner.get('selectionId'),
            "team_name": team_name,
            "event_name": market.get('event', {}).get('name', 'Unknown Event'),
            "competition": market.get('competition', {}).get('name', 'Unknown Competition'),
            "odds": odds,
            "stake": stake,
            "available_volume": available_volume,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        if is_dry_run_fallback:
            opportunity["dry_run_fallback"] = True
            
        return opportunity

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
            # Extract market details
            market_id = market_book.get('marketId', 'Unknown Market ID')
            
            # Skip if market is in-play or has active bets
            if market_book.get('inplay') or await self.bet_repository.has_active_bets():
                return None
                
            # Get current balance for stake calculation
            account_status = await self.account_repository.get_account_status()
            current_balance = account_status.current_balance

            # Log market start time
            market_start_time = market.get('marketStartTime', '')
            if formatted_time := self._format_market_time(market_start_time):
                self.logger.info(f"\n                                                                  Kick off: {formatted_time}")

            # Process runners with consistent naming
            runners = market_book.get('runners', [])
            home_team, draw, away_team = await self._sort_runners_by_type(runners)
            
            # Log runner details if all parts are present
            if home_team and draw and away_team:
                event_name = market.get('event', {}).get('name', 'Unknown Event')
                await self._log_runner_details(market_id, event_name, home_team, draw, away_team)

            # Check betting criteria for each runner
            for runner in runners:
                ex = runner.get('ex', {})
                available_to_back = ex.get('availableToBack', [{}])[0]
                
                if available_to_back:
                    odds = available_to_back.get('price', 0)
                    size = available_to_back.get('size', 0)
                    
                    meets_criteria, _ = self.validate_market_criteria(
                        odds,
                        size,
                        current_balance,
                        request
                    )
                    
                    if meets_criteria:
                        return await self._create_betting_opportunity(
                            market_id=market_id,
                            market=market,
                            runner=runner,
                            odds=odds,
                            stake=current_balance,
                            available_volume=size
                        )

            # Special handling for dry run fallback
            is_fifth_market = request.market_id == request.fifth_market_id
            if request.dry_run and request.loop_count >= 2 and is_fifth_market and draw:
                ex = draw.get('ex', {})
                available_to_back = ex.get('availableToBack', [{}])[0]
                
                if available_to_back:
                    return await self._create_betting_opportunity(
                        market_id=market_id,
                        market=market,
                        runner=draw,
                        odds=available_to_back.get('price'),
                        stake=current_balance,
                        available_volume=available_to_back.get('size'),
                        is_dry_run_fallback=True
                    )
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error during market analysis: {str(e)}")
            return None