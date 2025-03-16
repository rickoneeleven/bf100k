"""
market_analysis_command.py

Command pattern implementation for market analysis operations, refactored to work with event-sourced approach.
Handles validation and analysis of betting markets according to strategy criteria.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import logging
import asyncio

from ..repositories.bet_repository import BetRepository
from ..repositories.account_repository import AccountRepository
from ..betfair_client import BetfairClient
from ..selection_mapper import SelectionMapper
from ..config_manager import ConfigManager
from ..betting_ledger import BettingLedger

@dataclass
class MarketAnalysisRequest:
    """Data structure for market analysis request"""
    liquidity_factor: float = 1.1
    max_markets: int = 10
    dry_run: bool = True
    polling_count: int = 0
    max_polling_attempts: int = 60

class MarketAnalysisCommand:
    def __init__(
        self,
        betfair_client: BetfairClient,
        bet_repository: BetRepository,
        account_repository: AccountRepository,
        config_manager: ConfigManager,
        betting_ledger: BettingLedger = None
    ):
        self.betfair_client = betfair_client
        self.bet_repository = bet_repository
        self.account_repository = account_repository
        self.selection_mapper = SelectionMapper()
        self.config_manager = config_manager
        
        # Use provided betting ledger or create a new one if none was provided
        self.betting_ledger = betting_ledger if betting_ledger else BettingLedger()
        
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
            # Check liquidity requirement
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
                sort_priority = runner.get('sortPriority', 'N/A')
                
                # Get odds and sizes
                back_price = runner.get('ex', {}).get('availableToBack', [{}])[0].get('price', 'N/A')
                back_size = runner.get('ex', {}).get('availableToBack', [{}])[0].get('size', 'N/A')
                
                # Add to runner details
                runner_details.append(
                    f"{team_name} (ID: {selection_id}, Priority: {sort_priority}, "
                    f"Win: {back_price} / Available: £{back_size})"
                )
            
            # Log the full market details
            self.logger.info(
                f"MarketID: {market_id} Event: {event_name} || " + 
                " || ".join(runner_details) + "\n"
            )
            
        except Exception as e:
            self.logger.error(f"Error logging market details: {str(e)}")

    async def _analyze_individual_market(
        self,
        market_id: str,
        event_name: str,
        request: MarketAnalysisRequest
    ) -> Optional[Dict]:
        """
        Analyze a single market directly with fresh data
        
        Args:
            market_id: Market ID to analyze
            event_name: Event name for logging
            request: Analysis request parameters
            
        Returns:
            Betting opportunity if found, None otherwise
        """
        try:
            self.logger.info(f"Analyzing market {market_id} - {event_name} with fresh data")
            
            # Get fresh market data directly with consistent approach
            market_data = await self.betfair_client.get_fresh_market_data(market_id, price_depth=3)
            
            if not market_data:
                self.logger.error(f"Failed to get market data for {market_id}")
                return None
                
            # We're no longer skipping in-play markets
                
            # Get event details
            event = market_data.get('event', {})
            event_id = event.get('id', 'Unknown')
            
            # Process runners with consistent naming
            runners = market_data.get('runners', [])
            
            # Ensure runners are sorted by sortPriority for consistent processing
            runners = sorted(runners, key=lambda r: r.get('sortPriority', 999))
            
            # Use the selection mapper to derive accurate team mappings
            runners = await self.selection_mapper.derive_teams_from_event(
                event_id=event_id,
                event_name=event_name,
                runners=runners
            )
            
            # Log detailed market information
            await self._log_market_details(market_id, event_name, runners)
            
            # Get the correct stake amount from the event-sourced betting ledger
            stake_amount = await self.betting_ledger.get_next_stake()
            
            self.logger.info(f"Using stake amount: £{stake_amount} for next bet (compound strategy)")
            
            # Find the Draw selection and team runners
            draw_runner = None
            team_runners = []
            
            for runner in runners:
                selection_id = str(runner.get('selectionId', ''))
                team_name = runner.get('teamName', 'Unknown')
                
                # Match the logic from selection_mapper.py's derive_teams_from_event method
                if selection_id == self.selection_mapper.KNOWN_DRAW_SELECTION_ID or team_name.lower() in self.selection_mapper.DRAW_VARIANTS:
                    draw_runner = runner
                else:
                    team_runners.append(runner)
            
            # If no Draw selection found, skip market
            if not draw_runner:
                self.logger.info(f"No Draw selection found in market {market_id}")
                return None
                
            if len(team_runners) < 2:
                self.logger.info(f"Not enough team runners found in market {market_id}")
                return None
                
            # Get Draw odds
            draw_ex = draw_runner.get('ex', {})
            draw_available_to_back = draw_ex.get('availableToBack', [{}])[0]
            
            if not draw_available_to_back:
                self.logger.info("No back prices available for Draw")
                return None
                
            draw_odds = draw_available_to_back.get('price', 0)
            draw_available_size = draw_available_to_back.get('size', 0)
            
            # Get odds for both teams
            team_odds = []
            for team_runner in team_runners:
                team_ex = team_runner.get('ex', {})
                team_available_to_back = team_ex.get('availableToBack', [{}])[0]
                
                if team_available_to_back:
                    team_odds.append(team_available_to_back.get('price', 0))
            
            # Check if Draw odds are higher than both team odds
            is_draw_odds_highest = len(team_odds) >= 2 and all(draw_odds > team_odd for team_odd in team_odds)
            
            if not is_draw_odds_highest:
                self.logger.info(
                    f"Draw odds ({draw_odds}) not higher than both teams odds: {team_odds}"
                )
                return None
            
            # Check liquidity criteria for the Draw
            meets_criteria, reason = self.validate_market_criteria(
                draw_odds,
                draw_available_size,
                stake_amount,
                request
            )
            
            if meets_criteria:
                self.logger.info(
                    f"Found betting opportunity on Draw: {event_name}, "
                    f"Odds: {draw_odds}, "
                    f"Selection ID: {draw_runner.get('selectionId')}, "
                    f"Stake: £{stake_amount}"
                )
                
                return await self._create_betting_opportunity(
                    market_id=market_id,
                    event_id=event_id,
                    market=market_data,
                    runner=draw_runner,
                    odds=draw_odds,
                    stake=stake_amount,
                    available_volume=draw_available_size
                )
            else:
                self.logger.debug(
                    f"Draw doesn't meet criteria: {reason}"
                )
            
            # No suitable selections found in this market
            return None
            
        except Exception as e:
            self.logger.error(f"Error analyzing individual market: {str(e)}")
            self.logger.exception(e)
            return None

    async def _create_betting_opportunity(
        self,
        market_id: str,
        event_id: str,
        market: Dict,
        runner: Dict,
        odds: float,
        stake: float,
        available_volume: float
    ) -> Dict:
        """
        Create a standardized betting opportunity dictionary with enhanced mapping data
        
        Args:
            market_id: Betfair market ID
            event_id: Betfair event ID
            market: Market data dictionary
            runner: Runner (selection) data dictionary
            odds: Current odds
            stake: Stake amount
            available_volume: Available liquidity
            
        Returns:
            Dictionary containing betting opportunity details
        """
        try:
            # Get event and runner details
            event_name = market.get('event', {}).get('name', 'Unknown Event')
            selection_id = runner.get('selectionId')
            team_name = runner.get('teamName', 'Unknown Team')
            sort_priority = runner.get('sortPriority', 999)
            
            # Get market start time
            market_start_time = market.get('marketStartTime')
            
            # Ensure team name mapping is stored
            await self.selection_mapper.add_mapping(
                event_id=event_id,
                event_name=event_name,
                selection_id=str(selection_id),
                team_name=team_name
            )
            
            # Get current cycle information from event-sourced ledger
            cycle_info = await self.betting_ledger.get_current_cycle_info()
            
            opportunity = {
                "market_id": market_id,
                "event_id": event_id,
                "selection_id": selection_id,
                "team_name": team_name,
                "event_name": event_name,
                "sort_priority": sort_priority,  
                "competition": market.get('competition', {}).get('name', 'Unknown Competition'),
                "odds": odds,
                "stake": stake,
                "available_volume": available_volume,
                "market_start_time": market_start_time,
                # Add cycle info from event-sourced state
                "cycle_number": cycle_info["current_cycle"],
                "bet_in_cycle": cycle_info["current_bet_in_cycle"] + 1,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            # Log the final opportunity data
            self.logger.info(
                f"Created betting opportunity: Market: {market_id}, Event: {event_name}, "
                f"Selection: {team_name} (ID: {selection_id}, Priority: {sort_priority}), "
                f"Odds: {odds}, Stake: £{stake}, "
                f"Cycle: {cycle_info['current_cycle']}, Bet: {cycle_info['current_bet_in_cycle'] + 1}"
            )
            
            return opportunity
        except Exception as e:
            self.logger.error(f"Error creating betting opportunity: {str(e)}")
            self.logger.exception(e)
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

    async def analyze_markets(self, request: MarketAnalysisRequest) -> Optional[Dict]:
        """
        Analyze available markets for betting opportunities
        
        Args:
            request: Market analysis request parameters
            
        Returns:
            Betting opportunity if found, None otherwise
        """
        try:
            self.logger.info(
                f"Analyzing markets (attempt {request.polling_count + 1}/{request.max_polling_attempts})"
            )
            
            # Get football markets data for initial list only
            markets, _ = await self.betfair_client.get_markets_with_odds(request.max_markets)
            
            if not markets:
                self.logger.error("Failed to get market data")
                return None
            
            self.logger.info(f"Analyzing {len(markets)} football markets")
            
            # Process each market individually with fresh data
            for market in markets:
                market_id = market.get('marketId')
                event = market.get('event', {})
                event_name = event.get('name', 'Unknown')
                
                # Check market start time
                market_start_time = market.get('marketStartTime')
                if market_start_time:
                    formatted_time = self._format_market_time(market_start_time)
                    self.logger.info(f"Analyzing market: {event_name} (Start: {formatted_time})")
                
                # Analyze individual market with fresh data
                opportunity = await self._analyze_individual_market(
                    market_id,
                    event_name,
                    request
                )
                
                if opportunity:
                    return opportunity
            
            # No suitable markets found in this polling attempt
            self.logger.info("No suitable markets found in this polling attempt")
            return None
            
        except Exception as e:
            self.logger.error(f"Error during market analysis: {str(e)}")
            self.logger.exception(e)
            return None

    async def execute(self) -> Optional[Dict]:
        """
        Execute market analysis with polling strategy
        Returns betting opportunity if found, None otherwise
        """
        try:
            # Skip if there are active bets
            if await self.bet_repository.has_active_bets():
                self.logger.info("Active bets exist - skipping market analysis")
                return None
            
            # Load configuration for market analysis
            config = self.config_manager.get_config()
            betting_config = config.get('betting', {})
            market_config = config.get('market_selection', {})
            
            # Create request with configuration (removed min/max odds)
            request = MarketAnalysisRequest(
                liquidity_factor=betting_config.get('liquidity_factor', 1.1),
                max_markets=market_config.get('max_markets', 10),
                dry_run=config.get('system', {}).get('dry_run', True),
                polling_count=0,
                max_polling_attempts=market_config.get('max_polling_attempts', 60)
            )
            
            # Perform initial market analysis
            opportunity = await self.analyze_markets(request)
            
            # If opportunity found, return it immediately
            if opportunity:
                return opportunity
            
            # Otherwise, return None - the polling will be handled by the main system
            # The system will recall this command periodically
            return None
            
        except Exception as e:
            self.logger.error(f"Error executing market analysis: {str(e)}")
            self.logger.exception(e)
            return None

    async def execute_with_polling(self) -> Optional[Dict]:
        """
        Execute market analysis with continuous polling
        This version performs polling internally rather than relying on the main system
        
        Returns:
            Betting opportunity if found, None after all polling attempts
        """
        try:
            # Skip if there are active bets
            if await self.bet_repository.has_active_bets():
                self.logger.info("Active bets exist - skipping market analysis")
                return None
            
            # Load configuration for market analysis
            config = self.config_manager.get_config()
            betting_config = config.get('betting', {})
            market_config = config.get('market_selection', {})
            
            # Create request with configuration (removed min/max odds)
            request = MarketAnalysisRequest(
                liquidity_factor=betting_config.get('liquidity_factor', 1.1),
                max_markets=market_config.get('max_markets', 10),
                dry_run=config.get('system', {}).get('dry_run', True),
                polling_count=0,
                max_polling_attempts=market_config.get('max_polling_attempts', 60)
            )
            
            polling_interval = market_config.get('polling_interval_seconds', 60)
            
            # Start polling for opportunities
            for attempt in range(request.max_polling_attempts):
                # Update polling count
                request.polling_count = attempt
                
                # Check for active bets before each attempt
                if await self.bet_repository.has_active_bets():
                    self.logger.info("Active bets exist - stopping market polling")
                    return None
                
                # Analyze markets
                opportunity = await self.analyze_markets(request)
                
                # If opportunity found, return it immediately
                if opportunity:
                    return opportunity
                
                # Otherwise, wait for the polling interval before next attempt
                if attempt < request.max_polling_attempts - 1:
                    self.logger.info(f"Waiting {polling_interval} seconds until next market check")
                    await asyncio.sleep(polling_interval)
            
            # No opportunities found after all attempts
            self.logger.info("No betting opportunities found after all polling attempts")
            return None
            
        except Exception as e:
            self.logger.error(f"Error executing market analysis with polling: {str(e)}")
            self.logger.exception(e)
            return None