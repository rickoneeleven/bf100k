"""
market_analysis_command.py

Improved Command pattern implementation for market analysis operations.
Handles validation and analysis of betting markets according to strategy criteria.
Includes double-checking of market data to ensure consistent odds mapping.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Set
import logging
import asyncio

from ..repositories.bet_repository import BetRepository
from ..repositories.account_repository import AccountRepository
from ..betfair_client import BetfairClient
from ..selection_mapper import SelectionMapper
from ..config_manager import ConfigManager

@dataclass
class MarketAnalysisRequest:
    """Data structure for market analysis request"""
    min_odds: float = 3.0
    max_odds: float = 4.0
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
        config_manager: ConfigManager
    ):
        self.betfair_client = betfair_client
        self.bet_repository = bet_repository
        self.account_repository = account_repository
        self.selection_mapper = SelectionMapper()
        self.config_manager = config_manager
        
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

    async def _confirm_opportunity(
        self, 
        market_id: str, 
        selection_id: int, 
        initial_odds: float,
        current_balance: float,
        request: MarketAnalysisRequest
    ) -> Tuple[bool, float]:
        """
        Double-check a betting opportunity with fresh market data
        
        Args:
            market_id: Market ID to check
            selection_id: Selection ID to check
            initial_odds: Initial odds discovered
            current_balance: Current account balance for liquidity check
            request: Original analysis request parameters
            
        Returns:
            Tuple of (confirmed: bool, fresh_odds: float)
        """
        try:
            # Get fresh market data
            fresh_market = await self.betfair_client.check_market_status(market_id)
            
            if not fresh_market:
                self.logger.warning(f"Could not retrieve fresh market data for {market_id}")
                return False, initial_odds
            
            # Check if market is now in-play
            if fresh_market.get('inplay'):
                self.logger.warning(f"Market {market_id} is now in-play, skipping opportunity")
                return False, initial_odds
            
            # Find the specific selection
            for runner in fresh_market.get('runners', []):
                if runner.get('selectionId') == selection_id:
                    # Get fresh odds
                    ex = runner.get('ex', {})
                    available_to_back = ex.get('availableToBack', [{}])[0]
                    
                    if not available_to_back:
                        self.logger.warning(f"No available back price for selection {selection_id}")
                        return False, initial_odds
                    
                    fresh_odds = available_to_back.get('price', 0)
                    available_size = available_to_back.get('size', 0)
                    
                    # Check if odds have changed significantly
                    odds_delta = abs(fresh_odds - initial_odds)
                    odds_percent_change = (odds_delta / initial_odds) * 100
                    
                    self.logger.info(
                        f"Odds check - Initial: {initial_odds}, Fresh: {fresh_odds}, "
                        f"Delta: {odds_delta:.4f}, Percent Change: {odds_percent_change:.2f}%"
                    )
                    
                    # If odds have changed by more than 2%, re-validate criteria
                    if odds_percent_change > 2.0:
                        self.logger.warning(
                            f"Significant odds change for selection {selection_id}: "
                            f"{initial_odds} -> {fresh_odds} ({odds_percent_change:.2f}%)"
                        )
                        
                        # Re-validate criteria with fresh odds
                        meets_criteria, reason = self.validate_market_criteria(
                            fresh_odds,
                            available_size,
                            current_balance,
                            request
                        )
                        
                        return meets_criteria, fresh_odds
                    
                    # Check if liquidity is still sufficient
                    if available_size < current_balance * request.liquidity_factor:
                        self.logger.warning(
                            f"Insufficient liquidity for selection {selection_id}: "
                            f"{available_size} < {current_balance * request.liquidity_factor}"
                        )
                        return False, fresh_odds
                    
                    # If odds haven't changed significantly and liquidity is still good, confirm opportunity
                    return True, fresh_odds
            
            # Selection not found in fresh market data
            self.logger.warning(f"Selection {selection_id} not found in fresh market data")
            return False, initial_odds
        
        except Exception as e:
            self.logger.error(f"Error confirming opportunity: {str(e)}")
            self.logger.exception(e)
            return False, initial_odds

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
            odds: Current odds (double-checked)
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
            
            opportunity = {
                "market_id": market_id,
                "event_id": event_id,
                "selection_id": selection_id,
                "team_name": team_name,
                "event_name": event_name,
                "sort_priority": sort_priority,  # Include sort priority for consistent ordering
                "competition": market.get('competition', {}).get('name', 'Unknown Competition'),
                "odds": odds,
                "stake": stake,
                "available_volume": available_volume,
                "market_start_time": market_start_time,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            # Log the final opportunity data
            self.logger.info(
                f"Created betting opportunity: Market: {market_id}, Event: {event_name}, "
                f"Selection: {team_name} (ID: {selection_id}, Priority: {sort_priority}), "
                f"Odds: {odds}, Stake: £{stake}"
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
        Analyze available markets for betting opportunities with enhanced selection mapping
        
        Args:
            request: Market analysis request parameters
            
        Returns:
            Betting opportunity if found, None otherwise
        """
        try:
            # Get current balance for stake calculation
            account_status = await self.account_repository.get_account_status()
            current_balance = account_status.current_balance
            
            self.logger.info(
                f"Analyzing markets (attempt {request.polling_count + 1}/{request.max_polling_attempts})"
            )
            
            # Get football markets data
            markets, market_books = await self.betfair_client.get_markets_with_odds(request.max_markets)
            
            if not markets or not market_books:
                self.logger.error("Failed to get market data")
                return None
            
            self.logger.info(f"Analyzing {len(markets)} football markets")
            
            # Process each market
            for market, market_book in zip(markets, market_books):
                market_id = market.get('marketId')
                event = market.get('event', {})
                event_id = event.get('id', 'Unknown')
                event_name = event.get('name', 'Unknown')
                
                # Skip if market is in-play
                if market_book.get('inplay'):
                    self.logger.debug(f"Skipping in-play market: {event_name}")
                    continue
                
                # Check market start time
                market_start_time = market.get('marketStartTime')
                if market_start_time:
                    formatted_time = self._format_market_time(market_start_time)
                    self.logger.info(f"Analyzing market: {event_name} (Start: {formatted_time})")
                
                # Process runners with consistent naming
                runners = market_book.get('runners', [])
                
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
                
                # Check betting criteria for each runner
                for runner in runners:
                    # Skip "Draw" selections - we're only interested in team selections
                    if runner.get('teamName', '').lower() == 'draw':
                        continue
                    
                    selection_id = runner.get('selectionId')
                    team_name = runner.get('teamName', 'Unknown')
                    
                    # Get available prices
                    ex = runner.get('ex', {})
                    available_to_back = ex.get('availableToBack', [{}])[0]
                    
                    if not available_to_back:
                        continue
                    
                    # Get best back price and size
                    odds = available_to_back.get('price', 0)
                    available_size = available_to_back.get('size', 0)
                    
                    # Check market criteria
                    meets_criteria, reason = self.validate_market_criteria(
                        odds,
                        available_size,
                        current_balance,
                        request
                    )
                    
                    if meets_criteria:
                        self.logger.info(
                            f"Found potential betting opportunity: {event_name}, "
                            f"Selection: {team_name}, Odds: {odds}"
                        )
                        
                        # Double-check with fresh market data before finalizing
                        opportunity_confirmed, fresh_odds = await self._confirm_opportunity(
                            market_id, 
                            selection_id, 
                            odds,
                            current_balance,
                            request
                        )
                        
                        if opportunity_confirmed:
                            self.logger.info(
                                f"Confirmed betting opportunity: {event_name}, "
                                f"Selection: {team_name}, Initial Odds: {odds}, Final Odds: {fresh_odds}"
                            )
                            
                            return await self._create_betting_opportunity(
                                market_id=market_id,
                                event_id=event_id,
                                market=market,
                                runner=runner,
                                odds=fresh_odds,  # Use the fresh odds
                                stake=current_balance,
                                available_volume=available_size
                            )
                        else:
                            self.logger.warning(
                                f"Opportunity not confirmed for {team_name} in {event_name}. "
                                f"Initial odds: {odds}, Fresh odds: {fresh_odds}"
                            )
                    else:
                        self.logger.debug(
                            f"Selection {team_name} doesn't meet criteria: {reason}"
                        )
            
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
            
            # Create request with configuration
            request = MarketAnalysisRequest(
                min_odds=betting_config.get('min_odds', 3.0),
                max_odds=betting_config.get('max_odds', 4.0),
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
            
            # Create request with configuration
            request = MarketAnalysisRequest(
                min_odds=betting_config.get('min_odds', 3.0),
                max_odds=betting_config.get('max_odds', 4.0),
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