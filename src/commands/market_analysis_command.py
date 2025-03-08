"""
market_analysis_command_improved.py

Improved Command pattern implementation for market analysis operations.
Handles validation and analysis of betting markets according to strategy criteria.
Removes fallback to Draw selections and implements continuous market checking.
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
        available_volume: float
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

    async def analyze_markets(self, request: MarketAnalysisRequest) -> Optional[Dict]:
        """
        Analyze available markets for betting opportunities
        
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
                            available_volume=available_size
                        )
                    else:
                        self.logger.debug(
                            f"Selection {runner.get('teamName')} doesn't meet criteria: {reason}"
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