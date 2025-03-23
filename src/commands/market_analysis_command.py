"""
market_analysis_command.py

Command pattern implementation for market analysis operations, refactored to work with event-sourced approach.
Handles validation and analysis of betting markets according to updated strategy criteria.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import logging
import asyncio
import sys

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
        
        # Set up console logging for debugging
        self.logger = logging.getLogger('MarketAnalysisCommand')
        self.logger.setLevel(logging.DEBUG)  # Set to DEBUG level
        
        # File handler
        file_handler = logging.FileHandler('web/logs/commands.log')
        file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(logging.DEBUG)
        self.logger.addHandler(file_handler)
        
        # Console handler for immediate visibility
        console_handler = logging.StreamHandler(sys.stdout)
        console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(logging.DEBUG)
        self.logger.addHandler(console_handler)
        
        # Log initialization to confirm
        self.logger.debug("Market Analysis Command initialized with DEBUG logging")

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
                "inplay": market.get('inplay', False),
                "market_status": market.get('status', 'UNKNOWN'),
                "cycle_number": cycle_info["current_cycle"],
                "bet_in_cycle": cycle_info["current_bet_in_cycle"] + 1,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            # Log the final opportunity data
            self.logger.info(
                f"Created betting opportunity: Market: {market_id}, Event: {event_name}, "
                f"Selection: {team_name} (ID: {selection_id}, Priority: {sort_priority}), "
                f"Odds: {odds}, Stake: £{stake}, "
                f"Cycle: {cycle_info['current_cycle']}, Bet: {cycle_info['current_bet_in_cycle'] + 1}, "
                f"In-Play: {market.get('inplay', False)}"
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
        Analyze available markets for betting opportunities with focus on high-liquidity markets.
        
        Args:
            request: Market analysis request parameters
            
        Returns:
            Betting opportunity if found, None otherwise
        """
        try:
            self.logger.info(
                f"Analyzing markets (attempt {request.polling_count + 1}/{request.max_polling_attempts})"
            )
            
            # Get configuration
            config = self.config_manager.get_config()
            market_config = config.get('market_selection', {})
            hours_ahead = market_config.get('hours_ahead', 4)
            top_markets = market_config.get('top_markets', 10)
            
            # Get football markets for the next 4 hours AND active in-play markets
            markets = await self.betfair_client.get_football_markets(request.max_markets, hours_ahead)
            
            if not markets:
                self.logger.error("Failed to get market data")
                return None
            
            # Markets should already be sorted by MAXIMUM_TRADED from the API call
            # Take only the top N markets with the highest traded volume
            top_markets_list = markets[:top_markets]
            
            self.logger.info(
                f"Analyzing {len(top_markets_list)} top markets by traded volume out of {len(markets)} total markets "
                f"for the next {hours_ahead} hours, including in-play markets"
            )
            
            # As we now rely on BettingService.scan_markets for the actual selection logic,
            # we're primarily using this class for exploration and debugging purposes
            self.logger.info("Selection logic is now handled by BettingService.scan_markets")
            
            # No suitable markets found in this polling attempt
            self.logger.info("Analysis complete")
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
        Execute market analysis with continuous polling.
        This version performs polling internally rather than relying on the main system.
        
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
                liquidity_factor=betting_config.get('liquidity_factor', 1.1),
                max_markets=market_config.get('max_markets', 1000),
                dry_run=config.get('system', {}).get('dry_run', True),
                polling_count=0,
                max_polling_attempts=market_config.get('max_polling_attempts', 60)
            )
            
            polling_interval = market_config.get('polling_interval_seconds', 60)
            
            # Log the market selection settings
            self.logger.info(
                f"Market selection settings: "
                f"max_markets={request.max_markets}, "
                f"top_markets={market_config.get('top_markets', 10)}, "
                f"hours_ahead={market_config.get('hours_ahead', 4)}"
            )
            
            # Notify that actual selection logic is now in BettingService
            self.logger.info("Selection logic is now directly handled by BettingService.scan_markets")
            
            # Return None to indicate no opportunity found
            return None
            
        except Exception as e:
            self.logger.error(f"Error executing market analysis with polling: {str(e)}")
            self.logger.exception(e)
            return None