"""
settle_bet_command.py

Command pattern implementation for bet settlement operations.
Updated to work with the event-sourced ledger approach.
Modified to never automatically settle bets due to timeouts.
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
from ..betting_ledger import BettingLedger

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
        config_manager: ConfigManager,
        betting_ledger: BettingLedger = None
    ):
        self.betfair_client = betfair_client
        self.bet_repository = bet_repository
        self.account_repository = account_repository
        self.config_manager = config_manager
        self.selection_mapper = SelectionMapper()
        # Use provided betting ledger or create a new one if none was provided
        self.betting_ledger = betting_ledger if betting_ledger else BettingLedger()
        
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

    async def check_bet_result(self, bet_details: Dict) -> Tuple[bool, float, float, float, str]:
        """
        Check the result of a bet using Betfair API with enhanced selection handling
        
        Args:
            bet_details: Bet details including market_id and selection_id
            
        Returns:
            Tuple of (won: bool, gross_profit: float, commission: float, net_profit: float, status_message: str)
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
            gross_profit = 0.0
            commission = 0.0
            net_profit = 0.0
            
            if won:
                gross_profit = stake * (odds - 1)
                # Apply 5% Betfair commission on winnings
                commission = gross_profit * 0.05
                net_profit = gross_profit - commission
                
                self.logger.info(
                    f"Bet won: Gross profit: Â£{gross_profit:.2f}, "
                    f"Commission (5%): Â£{commission:.2f}, "
                    f"Net profit: Â£{net_profit:.2f}"
                )
                
            return won, gross_profit, commission, net_profit, status_message
            
        except Exception as e:
            self.logger.error(f"Error checking bet result: {str(e)}")
            return False, 0.0, 0.0, 0.0, f"Error: {str(e)}"

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
                gross_profit = request.force_profit
                commission = gross_profit * 0.05 if won else 0.0
                net_profit = gross_profit - commission if won else 0.0
                status = "Forced settlement"
                
                self.logger.info(
                    f"Using forced settlement result: Won: {won}, "
                    f"Gross profit: Â£{gross_profit:.2f}, "
                    f"Commission: Â£{commission:.2f}, "
                    f"Net profit: Â£{net_profit:.2f} "
                    f"for selection {selection_id} ({team_name})"
                )
            else:
                # Get actual result from Betfair
                won, gross_profit, commission, net_profit, status = await self.check_bet_result(bet_details)
                
                self.logger.info(
                    f"Got result from Betfair: Won: {won}, "
                    f"Gross profit: Â£{gross_profit:.2f}, "
                    f"Commission: Â£{commission:.2f}, "
                    f"Net profit: Â£{net_profit:.2f}, "
                    f"Status: {status} "
                    f"for selection {selection_id} ({team_name})"
                )
            
            # Calculate new balance
            account_status = await self.account_repository.get_account_status()
            current_balance = account_status.current_balance
            new_balance = current_balance
            
            if won:
                # Add stake plus net profit for winning bets
                new_balance = current_balance + bet_details["stake"] + net_profit
            
            # Record settlement in betting ledger FIRST - creates BET_WON or BET_LOST event
            await self.betting_ledger.record_bet_result(
                bet_details=bet_details,
                won=won,
                profit=net_profit,
                new_balance=new_balance,
                commission=commission
            )
            
            # Record settlement in bet repository
            try:
                # Update bet repository
                await self.bet_repository.record_bet_settlement(
                    bet_details=bet_details,
                    won=won,
                    gross_profit=gross_profit,
                    commission=commission,
                    net_profit=net_profit
                )
                
                # Update account balance and stats
                if won:
                    # Add stake plus net profit for winning bets (after commission)
                    await self.account_repository.update_balance(
                        bet_details["stake"] + net_profit, 
                        f"Bet settlement: {won}, Market: {request.market_id}"
                    )
                
                # Update bet statistics
                await self.account_repository.update_bet_stats(won)
                
                self.logger.info(
                    f"Successfully settled bet: Market ID {request.market_id}, "
                    f"Selection: {selection_id} ({team_name}), "
                    f"Won: {won}, Net Profit: Â£{net_profit}"
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
                        
                    # Check for bet issues that need attention but DON'T settle them
                    await self._check_for_bet_issues()
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

    async def _check_for_bet_issues(self) -> List[Dict]:
        """
        Check for bets that might have issues but DO NOT automatically settle them.
        Instead, provide detailed logging for manual troubleshooting.
        
        Returns:
            List of bets with potential issues
        """
        try:
            # Get active bets
            active_bets = await self.bet_repository.get_active_bets()
            
            if not active_bets:
                return []
                
            now = datetime.now(timezone.utc)
            problem_bets = []
            
            for bet in active_bets:
                market_id = bet["market_id"]
                selection_id = bet["selection_id"]
                team_name = bet.get("team_name", "Unknown")
                event_name = bet.get("event_name", "Unknown Event")
                
                # Get current market status for checking in-play and event start times
                market_status = await self.betfair_client.get_fresh_market_data(market_id)
                
                if not market_status:
                    self.logger.warning(
                        f"ATTENTION NEEDED: Could not retrieve market status for {market_id}, "
                        f"Event: {event_name}, Selection: {team_name}. "
                        f"Unable to check result. Manual verification required."
                    )
                    problem_bets.append({**bet, "issue": "Cannot retrieve market data"})
                    continue
                
                # Check if market is in-play
                is_inplay = market_status.get('inplay', False)
                current_status = market_status.get('status', 'Unknown')
                
                # Get market start time
                market_start_time = None
                try:
                    if 'marketStartTime' in market_status:
                        market_start_time = datetime.fromisoformat(
                            market_status['marketStartTime'].replace('Z', '+00:00')
                        )
                    elif 'market_start_time' in bet:
                        market_start_time = datetime.fromisoformat(
                            bet['market_start_time'].replace('Z', '+00:00')
                        )
                except (ValueError, TypeError) as e:
                    self.logger.warning(f"Could not parse market start time: {e}")
                
                # Get bet placement time
                bet_placement_time = datetime.fromisoformat(bet["timestamp"])
                
                # Identify potential issues without auto-settling
                issue_type = None
                issue_details = None
                
                # Check for stalled in-play markets
                if is_inplay and market_start_time:
                    inplay_duration = now - market_start_time
                    max_inplay_hours = 4  # Most sports events don't last more than 4 hours
                    
                    if inplay_duration.total_seconds() > max_inplay_hours * 3600:
                        issue_type = "Long in-play duration"
                        issue_details = (
                            f"Event has been in-play for {inplay_duration.total_seconds() / 3600:.1f} hours, "
                            f"which exceeds typical game duration of {max_inplay_hours} hours. "
                            f"Event started at {market_start_time.isoformat()}"
                        )
                
                # Check for events scheduled in the past but not started/settled
                elif market_start_time and market_start_time < now and current_status not in ['CLOSED', 'SETTLED']:
                    delay = now - market_start_time
                    max_delay_hours = 6  # Allow up to 6 hours delay for event to start
                    
                    if delay.total_seconds() > max_delay_hours * 3600:
                        issue_type = "Event scheduled in past but not settled"
                        issue_details = (
                            f"Event was scheduled to start {delay.total_seconds() / 3600:.1f} hours ago "
                            f"at {market_start_time.isoformat()} but status is {current_status}"
                        )
                
                # Check for very old bets regardless of market status
                bet_age = now - bet_placement_time
                max_bet_age_days = 3  # Very old bet (3 days) needs attention
                
                if bet_age.total_seconds() > max_bet_age_days * 24 * 3600:
                    issue_type = "Aged bet"
                    issue_details = (
                        f"Bet is {bet_age.total_seconds() / (24 * 3600):.1f} days old. "
                        f"Placed at {bet_placement_time.isoformat()}, "
                        f"Current market status: {current_status}"
                    )
                
                # Log detailed warning for any issues found
                if issue_type:
                    self.logger.warning(
                        f"ATTENTION NEEDED: Possible issue with bet on market {market_id}, "
                        f"Event: {event_name}, Selection: {team_name} (ID: {selection_id}). "
                        f"Issue type: {issue_type}. Details: {issue_details}. "
                        f"Current market status: {current_status}. "
                        f"Manual verification/resolution required."
                    )
                    
                    problem_bets.append({
                        **bet, 
                        "issue": issue_type,
                        "issue_details": issue_details,
                        "current_status": current_status
                    })
            
            # Summary log if issues found
            if problem_bets:
                self.logger.warning(
                    f"Found {len(problem_bets)} bet(s) that may need manual attention. "
                    f"NO automatic settlement performed."
                )
            
            return problem_bets
                    
        except Exception as e:
            self.logger.error(f"Error checking for bet issues: {str(e)}")
            self.logger.exception(e)
            return []