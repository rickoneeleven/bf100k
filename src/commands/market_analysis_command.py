"""
market_analysis_command.py

Implements async Command pattern for market analysis operations.
Handles validation and analysis of betting markets according to strategy criteria.
Uses context-aware team mapping for consistent selection identification.
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
        try:
            if odds < request.min_odds or odds > request.max_odds:
                return False, f"odds {odds} outside range {request.min_odds}-{request.max_odds}"
                
            if available_volume < required_stake * request.liquidity_factor:
                return False, f"liquidity {available_volume:.2f} < required {required_stake * request.liquidity_factor:.2f}"
                
            return True, "meets criteria"
        except Exception as e:
            self.logger.error(f"Error validating market criteria: {str(e)}")
            return False, f"validation error: {str(e)}"

    def _format_market_time(self, market_start_time: str) -> Optional[str]:
        """Format market start time for logging"""
        try:
            if market_start_time:
                start_time = datetime.fromisoformat(market_start_time.replace('Z', '+00:00'))
                return start_time.strftime('%Y-%m-%d %H:%M:%S')
            return None
        except Exception as e:
            self.logger.error(f"Error formatting market time: {str(e)}")
            return None

    async def _log_market_details(
        self,
        market_id: str,
        event_name: str,
        runners: List[Dict]
    ) -> None:
        """Log details of all runners in the market with current odds and liquidity"""
        try:
            # Build the log message
            runner_details = []
            
            for runner in runners:
                # Get basic runner info
                selection_id = runner.get('selectionId', 'N/A')
                team_name = runner.get('teamName', 'Unknown')
                
                # Get odds and sizes
                back_price = runner.get('ex', {}).get('availableToBack', [{}])[0].get('price', 'N/A')
                back_size = runner.get('ex', {}).get('availableToBack', [{}])[0].get('size', 'N/A')
                
                # Add to runner details
                runner_details.append(
                    f"{team_name} (Win: {back_price} / Available: £{back_size} / selectionID: {selection_id})"
                )
            
            # Log the full market details
            self.logger.info(
                f"MarketID: {market_id} Event: {event_name} || " + 
                " || ".join(runner_details) + "\n"
            )
            
        except Exception as e:
            self.logger.error(f"Error logging market details: {str(e)}")

    async def _create_betting_opportunity(
        self,
        market_id: str,
        event_id: str,
        market: Dict,
        runner: Dict,
        odds: float,
        stake: float,
        available_volume: float,
        is_dry_run_fallback: bool = False
    ) -> Dict:
        """Create a standardized betting opportunity dictionary"""
        try:
            # Get event and runner details
            event_name = market.get('event', {}).get('name', 'Unknown Event')
            selection_id = str(runner.get('selectionId'))
            team_name = runner.get('teamName', 'Unknown Team')
            
            # Ensure team name mapping is stored
            await self.selection_mapper.add_mapping(
                event_id=event_id,
                event_name=event_name,
                selection_id=selection_id,
                team_name=team_name
            )
            
            opportunity = {
                "market_id": market_id,
                "event_id": event_id,
                "selection_id": runner.get('selectionId'),
                "team_name": team_name,
                "event_name": event_name,
                "competition": market.get('competition', {}).get('name', 'Unknown Competition'),
                "odds": odds,
                "stake": stake,
                "available_volume": available_volume,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            if is_dry_run_fallback:
                opportunity["dry_run_fallback"] = True
                
            return opportunity
        except Exception as e:
            self.logger.error(f"Error creating betting opportunity: {str(e)}")
            # Return a minimal opportunity to avoid failure
            return {
                "market_id": market_id,
                "selection_id": runner.get('selectionId', 0),
                "team_name": "Error - Unknown Team",
                "event_name": "Error - Unknown Event",
                "odds": odds,
                "stake": stake,
                "available_volume": available_volume,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(e)
            }

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
            event = market.get('event', {})
            event_id = event.get('id', 'Unknown Event ID')
            event_name = event.get('name', 'Unknown Event')
            
            # Skip if market is in-play or has active bets
            if market_book.get('inplay'):
                self.logger.info(f"Market {market_id} - {event_name} is in-play, skipping")
                return None
                
            if await self.bet_repository.has_active_bets():
                self.logger.info(f"Active bet exists, skipping market {market_id} - {event_name}")
                return None
                
            # Get current balance for stake calculation
            account_status = await self.account_repository.get_account_status()
            current_balance = account_status.current_balance

            # Log market start time
            market_start_time = market.get('marketStartTime', '')
            if formatted_time := self._format_market_time(market_start_time):
                self.logger.info(f"\n                                                                  Kick off: {formatted_time}")

            # Process runners with consistent naming based on event context
            runners = market_book.get('runners', [])
            
            # Use the selection mapper to derive accurate team mappings
            runners = await self.selection_mapper.derive_teams_from_event(
                event_id=event_id,
                event_name=event_name,
                runners=runners
            )
            
            # Log market details with mapped team names
            await self._log_market_details(market_id, event_name, runners)

            # Check betting criteria for each runner
            for runner in runners:
                # Skip checking Draw for regular betting criteria (unless it's a dry run fallback)
                if runner.get('teamName', '').lower() == 'draw' and not (
                    request.dry_run and 
                    request.loop_count >= 2 and 
                    request.market_id == request.fifth_market_id
                ):
                    continue
                    
                ex = runner.get('ex', {})
                available_to_back = ex.get('availableToBack', [{}])[0]
                
                if available_to_back:
                    odds = available_to_back.get('price', 0)
                    size = available_to_back.get('size', 0)
                    
                    meets_criteria, reason = self.validate_market_criteria(
                        odds,
                        size,
                        current_balance,
                        request
                    )
                    
                    if meets_criteria:
                        self.logger.info(
                            f"Found betting opportunity: {event_name}, "
                            f"Selection: {runner.get('teamName')}, Odds: {odds}"
                        )
                        return await self._create_betting_opportunity(
                            market_id=market_id,
                            event_id=event_id,
                            market=market,
                            runner=runner,
                            odds=odds,
                            stake=current_balance,
                            available_volume=size
                        )
                    else:
                        self.logger.debug(
                            f"Selection {runner.get('teamName')} in {event_name} "
                            f"doesn't meet criteria: {reason}"
                        )

            # Special handling for dry run fallback
            if request.dry_run and request.loop_count >= 2 and request.market_id == request.fifth_market_id:
                # Find the Draw runner for the fallback
                draw_runner = next(
                    (r for r in runners if r.get('teamName', '').lower() == 'draw'), 
                    None
                )
                
                if draw_runner:
                    ex = draw_runner.get('ex', {})
                    available_to_back = ex.get('availableToBack', [{}])[0]
                    
                    if available_to_back:
                        self.logger.info(
                            f"Using dry run fallback for {event_name}, "
                            f"Selection: Draw, Odds: {available_to_back.get('price')}"
                        )
                        return await self._create_betting_opportunity(
                            market_id=market_id,
                            event_id=event_id,
                            market=market,
                            runner=draw_runner,
                            odds=available_to_back.get('price'),
                            stake=current_balance,
                            available_volume=available_to_back.get('size'),
                            is_dry_run_fallback=True
                        )
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error during market analysis: {str(e)}")
            self.logger.exception(e)
            return None