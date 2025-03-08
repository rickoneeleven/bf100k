"""
settle_bet_command.py

Improved Command pattern implementation for bet settlement operations.
Uses real Betfair API results instead of simulation.
Handles validation, execution, and recording of bet settlements.
Enhanced with consistent selection ID handling and unified market data retrieval.
"""

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Tuple, List
import logging
import asyncio

from ..repositories.bet_repository import BetRepository
from ..repositories.account_repository import AccountRepository
from ..betfair_client import BetfairClient
from ..selection_mapper import SelectionMapper
from ..config_manager import ConfigManager

@dataclass
class BetSettlementRequest:
    """Data structure for bet settlement request"""
    market_id: str
    forced_settlement: bool = False  # Force settlement with simulated result
    force_won: bool = False  # Only used if forced_settlement is True
    force_profit: float = 0.0  # Only used if forced_settlement is True

class BetSettlementCommand:
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
        
        # Setup logging
        self.logger = logging.getLogger('BetSettlementCommand')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('web/logs/commands.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    async def validate_request(self, request: BetSettlementRequest) -> Tuple[bool, str]:
        """
        Validate bet settlement request
        
        Args:
            request: Settlement request
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            self.logger.info(f"Validating bet settlement request for market {request.market_id}")
            
            # Get bet details
            bet = await self.bet_repository.get_bet_by_market_id(request.market_id)
            if not bet:
                return False, f"No bet found for market {request.market_id}"
                
            # Check if already settled
            if "settlement_time" in bet:
                return False, f"Bet for market {request.market_id} is already settled"
                
            return True, ""
            
        except Exception as e:
            self.logger.error(f"Error validating settlement request: {str(e)}")
            return False, f"Validation error: {str(e)}"

    async def check_bet_result(self, bet_details: Dict) -> Tuple[bool, float, str]:
        """
        Check the result of a bet using Betfair API with enhanced selection handling
        
        Args:
            bet_details: Bet details including market_id and selection_id
            
        Returns:
            Tuple of (won: bool, profit: float, status_message: str)
        """
        try:
            market_id = bet_details["market_id"]
            selection_id = bet_details["selection_id"]
            stake = bet_details["stake"]
            odds = bet_details["odds"]
            team_name = bet_details.get("team_name", "Unknown")
            
            self.logger.info(
                f"Checking result for bet: Market {market_id}, "
                f"Selection {selection_id} ({team_name}), "
                f"Stake: Â£{stake}, Odds: {odds}"
            )
            
            # Get result from Betfair using consistent method
            won, status_message = await self.betfair_client.get_market_result(
                market_id, selection_id
            )
            
            # Calculate profit if won
            profit = 0.0
            if won:
                profit = stake * (odds - 1)
                
            return won, profit, status_message
            
        except Exception as e:
            self.logger.error(f"Error checking bet result: {str(e)}")
            return False, 0.0, f"Error: {str(e)}"

    async def execute(self, request: BetSettlementRequest) -> Optional[Dict]:
        """
        Execute bet settlement operation
        
        Args:
            request: Settlement request
            
        Returns:
            Updated bet details if successful, None otherwise
        """
        try:
            self.logger.info(f"Executing bet settlement for market {request.market_id}")
            
            # Validate request
            is_valid, error = await self.validate_request(request)
            if not is_valid:
                self.logger.error(f"Invalid settlement request: {error}")
                return None
                
            # Get bet details
            bet_details = await self.bet_repository.get_bet_by_market_id(request.market_id)
            selection_id = bet_details.get("selection_id")
            team_name = bet_details.get("team_name", "Unknown")
            
            # Get result (either forced or from Betfair)
            if request.forced_settlement:
                # Use forced result (for dry run or testing)
                won = request.force_won
                profit = request.force_profit
                status = "Forced settlement"
                self.logger.info(
                    f"Using forced settlement result: Won: {won}, Profit: Â£{profit} "
                    f"for selection {selection_id} ({team_name})"
                )
            else:
                # Get actual result from Betfair
                won, profit, status = await self.check_bet_result(bet_details)
                self.logger.info(
                    f"Got result from Betfair: Won: {won}, Profit: Â£{profit}, Status: {status} "
                    f"for selection {selection_id} ({team_name})"
                )
            
            # Record settlement
            try:
                # Start atomic update
                await self.bet_repository.record_bet_settlement(
                    bet_details=bet_details,
                    won=won,
                    profit=profit
                )
                
                # Update account balance and stats
                if won:
                    # Add stake plus profit for winning bets
                    await self.account_repository.update_balance(bet_details["stake"] + profit)
                
                # Update bet statistics
                await self.account_repository.update_bet_stats(won)
                
                self.logger.info(
                    f"Successfully settled bet: Market ID {request.market_id}, "
                    f"Selection: {selection_id} ({team_name}), "
                    f"Won: {won}, Profit: Â£{profit}"
                )
                
                # Get updated bet details
                updated_bet = await self.bet_repository.get_bet_by_market_id(request.market_id)
                return updated_bet
                
            except Exception as settlement_error:
                self.logger.error(f"Error during settlement: {str(settlement_error)}")
                self.logger.exception(settlement_error)
                return None
                
        except Exception as e:
            self.logger.error(f"Error executing bet settlement: {str(e)}")
            self.logger.exception(e)
            return None

    async def check_active_bets(self) -> List[Dict]:
        """
        Check all active bets for possible settlement
        
        Returns:
            List of settled bet details
        """
        try:
            # Get active bets
            active_bets = await self.bet_repository.get_active_bets()
            
            if not active_bets:
                self.logger.debug("No active bets to check")
                return []
                
            self.logger.info(f"Checking {len(active_bets)} active bets for results")
            
            settled_bets = []
            
            # Check each bet
            for bet in active_bets:
                market_id = bet["market_id"]
                selection_id = bet["selection_id"]
                team_name = bet["team_name"]
                
                self.logger.info(
                    f"Checking settlement status for market {market_id}, "
                    f"Selection {selection_id} ({team_name})"
                )
                
                # Check if market is settled using consistent method
                market_status = await self.betfair_client.get_fresh_market_data(market_id)
                
                if market_status and market_status.get('status') in ['CLOSED', 'SETTLED']:
                    self.logger.info(
                        f"Market {market_id} is settled with status {market_status.get('status')}"
                    )
                    
                    # Create settlement request
                    request = BetSettlementRequest(market_id=market_id)
                    
                    # Execute settlement
                    settled_bet = await self.execute(request)
                    
                    if settled_bet:
                        settled_bets.append(settled_bet)
                else:
                    status_msg = market_status.get('status') if market_status else 'Unknown'
                    self.logger.info(
                        f"Market {market_id} is not yet settled. "
                        f"Current status: {status_msg}"
                    )
            
            return settled_bets
            
        except Exception as e:
            self.logger.error(f"Error checking active bets: {str(e)}")
            self.logger.exception(e)
            return []

    async def execute_settlement_poller(self) -> None:
        """
        Execute continuous polling for bet settlements
        Used to periodically check and settle bets
        """
        try:
            # Load configuration
            config = self.config_manager.get_config()
            result_config = config.get('result_checking', {})
            
            check_interval_minutes = result_config.get('check_interval_minutes', 5)
            max_check_attempts = result_config.get('max_check_attempts', 24)
            event_timeout_hours = result_config.get('event_timeout_hours', 12)
            
            self.logger.info(
                f"Starting settlement poller (interval: {check_interval_minutes} minutes, "
                f"max attempts: {max_check_attempts})"
            )
            
            polling_count = 0
            
            while polling_count < max_check_attempts:
                # Check for active bets
                active_bets = await self.bet_repository.get_active_bets()
                
                if active_bets:
                    self.logger.info(
                        f"Checking active bets (attempt {polling_count + 1}/{max_check_attempts})"
                    )
                    
                    # Check for bet results
                    settled_bets = await self.check_active_bets()
                    
                    if settled_bets:
                        self.logger.info(f"Settled {len(settled_bets)} bets")
                        
                    # Check for timed out bets
                    await self._check_for_timed_out_bets(event_timeout_hours)
                else:
                    self.logger.info("No active bets to check - pausing settlement poller")
                    break
                
                # Increment count
                polling_count += 1
                
                # Sleep until next check
                if polling_count < max_check_attempts:
                    self.logger.info(
                        f"Waiting {check_interval_minutes} minutes until next result check"
                    )
                    await asyncio.sleep(check_interval_minutes * 60)
            
            if polling_count >= max_check_attempts:
                self.logger.warning(
                    f"Settlement poller reached maximum attempts ({max_check_attempts})"
                )
                
        except Exception as e:
            self.logger.error(f"Error in settlement poller: {str(e)}")
            self.logger.exception(e)

    async def _check_for_timed_out_bets(self, timeout_hours: int) -> None:
        """
        Check for bets that have timed out (event should have ended)
        
        Args:
            timeout_hours: Number of hours after which to consider an event timed out
        """
        try:
            # Get active bets
            active_bets = await self.bet_repository.get_active_bets()
            
            if not active_bets:
                return
                
            now = datetime.now(timezone.utc)
            timeout_threshold = now - timedelta(hours=timeout_hours)
            
            for bet in active_bets:
                # Check bet timestamp
                bet_time = datetime.fromisoformat(bet["timestamp"])
                
                if bet_time < timeout_threshold:
                    # Bet has been active for too long, likely an issue
                    self.logger.warning(
                        f"Bet on market {bet['market_id']} has timed out. "
                        f"Selection: {bet['selection_id']} ({bet.get('team_name', 'Unknown')}), "
                        f"Placed at {bet_time.isoformat()}, which is over {timeout_hours} hours ago"
                    )
                    
                    # Force settlement as a loss in dry run mode
                    request = BetSettlementRequest(
                        market_id=bet["market_id"],
                        forced_settlement=True,
                        force_won=False,
                        force_profit=0.0
                    )
                    
                    # Execute forced settlement
                    await self.execute(request)
                    
                    self.logger.info(
                        f"Forced settlement of timed out bet on market {bet['market_id']}"
                    )
                    
        except Exception as e:
            self.logger.error(f"Error checking for timed out bets: {str(e)}")
            self.logger.exception(e)