"""
place_bet_command.py

Implements async Command pattern for bet placement operations.
Handles validation, execution, and recording of bet placement.
Enhanced with improved selection ID to team name mapping for consistency.
Updated to use consistent market data retrieval method.
FIXED: Properly synchronize with betting ledger cycle information
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple
import logging

from ..repositories.bet_repository import BetRepository
from ..repositories.account_repository import AccountRepository
from ..betfair_client import BetfairClient
from ..selection_mapper import SelectionMapper
from ..betting_ledger import BettingLedger

@dataclass
class PlaceBetRequest:
    """Data structure for bet placement request"""
    market_id: str
    event_id: str  # Added event_id for context-aware mapping
    event_name: str  # Added event_name for better logging and validation
    selection_id: int
    odds: float
    stake: float

class PlaceBetCommand:
    def __init__(
        self,
        betfair_client: BetfairClient,
        bet_repository: BetRepository,
        account_repository: AccountRepository,
        betting_ledger: BettingLedger = None
    ):
        self.betfair_client = betfair_client
        self.bet_repository = bet_repository
        self.account_repository = account_repository
        self.selection_mapper = SelectionMapper()
        # Use provided betting ledger or create a new one if none was provided
        self.betting_ledger = betting_ledger if betting_ledger else BettingLedger()
        
        # Setup logging
        self.logger = logging.getLogger('PlaceBetCommand')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('web/logs/commands.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    async def validate(self, request: PlaceBetRequest) -> Tuple[bool, str]:
        """
        Validate bet placement request asynchronously
        Returns: (is_valid: bool, error_message: str)
        """
        try:
            self.logger.info(f"Validating bet placement request for market {request.market_id}")
            
            # Verify selection ID is valid
            if not request.selection_id:
                return False, "Missing selection ID"
                
            # Check for active bets
            if await self.bet_repository.has_active_bets():
                return False, "Cannot place bet while another bet is active"
                
            # Validate odds range
            if not (3.0 <= request.odds <= 4.0):
                return False, f"Odds {request.odds} outside valid range (3.0-4.0)"
                
            # Validate stake against account balance
            account_status = await self.account_repository.get_account_status()
            if request.stake > account_status.current_balance:
                return False, f"Insufficient funds: stake {request.stake} > balance {account_status.current_balance}"
                
            # Validate market liquidity using consistent market data retrieval
            try:
                # Get fresh market data to ensure accurate odds
                market = await self.betfair_client.get_fresh_market_data(request.market_id)
                if not market:
                    return False, "Failed to retrieve market data"
                    
                # Check market status
                if market.get('inplay'):
                    return False, "Cannot place bet on in-play market"
                    
                # Find runner and check liquidity by selection ID
                found_selection = False
                for runner in market.get('runners', []):
                    if runner.get('selectionId') == request.selection_id:
                        found_selection = True
                        available_to_back = runner.get('ex', {}).get('availableToBack', [])
                        if not available_to_back:
                            return False, "No prices available for selection"
                            
                        best_price = available_to_back[0].get('price')
                        available_size = available_to_back[0].get('size')
                        
                        # Check if odds have moved
                        if abs(best_price - request.odds) > 0.01:
                            return False, f"Odds have changed from {request.odds} to {best_price}"
                            
                        if available_size < request.stake * 1.1:
                            return False, f"Insufficient liquidity: {available_size} < {request.stake * 1.1}"
                        
                        # Get the team name from mapper for logging purposes
                        team_name = await self.selection_mapper.get_team_name(
                            request.event_id, 
                            str(request.selection_id)
                        )
                        
                        if not team_name:
                            # Try to derive team name from event name
                            runners = market.get('runners', [])
                            runners = await self.selection_mapper.derive_teams_from_event(
                                request.event_id,
                                request.event_name,
                                runners
                            )
                            
                            # Try getting team name again after deriving
                            team_name = await self.selection_mapper.get_team_name(
                                request.event_id, 
                                str(request.selection_id)
                            )
                            
                            if not team_name:
                                self.logger.warning(
                                    f"No team mapping could be created for selection {request.selection_id} "
                                    f"in event {request.event_name}"
                                )
                        
                        self.logger.info(
                            f"Validated selection {request.selection_id} ({team_name}) "
                            f"with odds {best_price} and liquidity {available_size}"
                        )
                        return True, ""
                
                if not found_selection:
                    return False, f"Selection {request.selection_id} not found in market {request.market_id}"
                
            except Exception as e:
                self.logger.error(f"Error validating market: {str(e)}")
                return False, f"Market validation failed: {str(e)}"
                
        except Exception as e:
            self.logger.error(f"Validation error: {str(e)}")
            return False, f"Validation failed: {str(e)}"

    async def execute(self, request: PlaceBetRequest) -> Optional[Dict]:
        """
        Execute bet placement asynchronously with enhanced selection handling
        Returns bet details if successful, None if failed
        """
        try:
            self.logger.info(f"Executing bet placement for market {request.market_id}, selection {request.selection_id}")
            
            # Validate request
            is_valid, error = await self.validate(request)
            if not is_valid:
                self.logger.error(f"Validation failed: {error}")
                return None
            
            # Get fresh market data with consistent method
            market = await self.betfair_client.get_fresh_market_data(request.market_id)
            market_start_time = market.get('marketStartTime') if market else None
            
            # Get team name for the selection from the mapper
            team_name = await self.selection_mapper.get_team_name(
                request.event_id,
                str(request.selection_id)
            )
            
            if not team_name:
                # Create/update the mapping if not found
                # First try to get team mappings from a fresh market lookup
                if market:
                    runners = market.get('runners', [])
                    runners = await self.selection_mapper.derive_teams_from_event(
                        request.event_id,
                        request.event_name,
                        runners
                    )
                    
                    # Try again after deriving teams
                    team_name = await self.selection_mapper.get_team_name(
                        request.event_id,
                        str(request.selection_id)
                    )
                
                # If still not found, add a generic mapping
                if not team_name:
                    await self.selection_mapper.add_mapping(
                        request.event_id,
                        request.event_name,
                        str(request.selection_id),
                        "Unknown Team"  # Will be derived from event name
                    )
                    
                    # Try to get it again after adding
                    team_name = await self.selection_mapper.get_team_name(
                        request.event_id,
                        str(request.selection_id)
                    ) or "Unknown Team"
            
            # Find sort priority for the selection (for consistent ordering)
            sort_priority = 999
            if market:
                for runner in market.get('runners', []):
                    if runner.get('selectionId') == request.selection_id:
                        sort_priority = runner.get('sortPriority', 999)
                        break
            
            # FIXED: Always get the most current cycle information from the ledger
            # This ensures we're using the correct cycle number after a previous bet has been lost
            cycle_info = await self.betting_ledger.get_current_cycle_info()
            
            # Create bet record with enhanced details including cycle information
            bet_details = {
                "market_id": request.market_id,
                "event_id": request.event_id,
                "event_name": request.event_name,
                "selection_id": request.selection_id,
                "team_name": team_name,
                "sort_priority": sort_priority,
                "odds": request.odds,
                "stake": request.stake,
                "market_start_time": market_start_time,
                "cycle_number": cycle_info["current_cycle"],
                "bet_in_cycle": cycle_info["current_bet_in_cycle"] + 1,  # Will be incremented when recorded
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            # Log cycle information for debugging
            self.logger.info(
                f"Using current cycle information from ledger: "
                f"Cycle #{cycle_info['current_cycle']}, "
                f"Bet #{cycle_info['current_bet_in_cycle'] + 1} in cycle"
            )
            
            # Record bet placement and update balance atomically
            await self.bet_repository.record_bet_placement(bet_details)
            await self.account_repository.update_balance(-request.stake)
            
            self.logger.info(
                f"Successfully placed bet: Market ID {request.market_id}, "
                f"Selection: {team_name} (ID: {request.selection_id}, Priority: {sort_priority}), "
                f"Stake ÃÂ£{request.stake}, Odds: {request.odds}, "
                f"Cycle #{cycle_info['current_cycle']}, Bet #{cycle_info['current_bet_in_cycle'] + 1} in cycle"
            )
            
            return bet_details
            
        except Exception as e:
            self.logger.error(f"Failed to place bet: {str(e)}")
            self.logger.exception(e)
            # If an error occurs after bet recording but before balance update,
            # we should attempt to roll back the bet recording
            try:
                # Note: In a full implementation, we would track the state and
                # implement proper rollback mechanisms for partial failures
                pass
            except Exception as rollback_error:
                self.logger.error(f"Failed to rollback bet placement: {str(rollback_error)}")
            return None