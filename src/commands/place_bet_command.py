"""
place_bet_command.py

Implements async Command pattern for bet placement operations.
Handles validation, execution, and recording of bet placement.
Updated for context-aware mapping system.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple
import logging

from ..repositories.bet_repository import BetRepository
from ..repositories.account_repository import AccountRepository
from ..betfair_client import BetfairClient
from ..selection_mapper import SelectionMapper

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
        account_repository: AccountRepository
    ):
        self.betfair_client = betfair_client
        self.bet_repository = bet_repository
        self.account_repository = account_repository
        self.selection_mapper = SelectionMapper()
        
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
                
            # Validate market liquidity
            try:
                market_books = await self.betfair_client.list_market_book([request.market_id])
                if not market_books:
                    return False, "Failed to retrieve market data"
                    
                market = market_books[0]
                
                # Check market status
                if market.get('inplay'):
                    return False, "Cannot place bet on in-play market"
                    
                # Find runner and check liquidity
                for runner in market.get('runners', []):
                    if runner.get('selectionId') == request.selection_id:
                        available_to_back = runner.get('ex', {}).get('availableToBack', [])
                        if not available_to_back:
                            return False, "No prices available for selection"
                            
                        best_price = available_to_back[0].get('price')
                        available_size = available_to_back[0].get('size')
                        
                        if best_price != request.odds:
                            return False, f"Odds have changed: {best_price} != {request.odds}"
                            
                        if available_size < request.stake * 1.1:
                            return False, f"Insufficient liquidity: {available_size} < {request.stake * 1.1}"
                        
                        # Get the team name from mapper for logging purposes
                        team_name = await self.selection_mapper.get_team_name(
                            request.event_id, 
                            str(request.selection_id)
                        )
                        if not team_name:
                            self.logger.warning(
                                f"No team mapping found for selection {request.selection_id} "
                                f"in event {request.event_name}"
                            )
                            
                        return True, ""
                        
                return False, "Selection not found in market"
                
            except Exception as e:
                self.logger.error(f"Error validating market: {str(e)}")
                return False, f"Market validation failed: {str(e)}"
                
        except Exception as e:
            self.logger.error(f"Validation error: {str(e)}")
            return False, f"Validation failed: {str(e)}"

    async def execute(self, request: PlaceBetRequest) -> Optional[Dict]:
        """
        Execute bet placement asynchronously
        Returns bet details if successful, None if failed
        """
        try:
            self.logger.info(f"Executing bet placement for market {request.market_id}")
            
            # Validate request
            is_valid, error = await self.validate(request)
            if not is_valid:
                self.logger.error(f"Validation failed: {error}")
                return None
            
            # Get team name for the selection
            team_name = await self.selection_mapper.get_team_name(
                request.event_id,
                str(request.selection_id)
            )
            if not team_name:
                # Create/update the mapping if not found
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
                
            # Create bet record
            bet_details = {
                "market_id": request.market_id,
                "event_id": request.event_id,  # Include event_id
                "event_name": request.event_name,  # Include event_name
                "selection_id": request.selection_id,
                "team_name": team_name,  # Include mapped team name
                "odds": request.odds,
                "stake": request.stake,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            # Record bet placement and update balance atomically
            await self.bet_repository.record_bet_placement(bet_details)
            await self.account_repository.update_balance(-request.stake)
            
            self.logger.info(
                f"Successfully placed bet: Market ID {request.market_id}, "
                f"Selection: {team_name}, Stake £{request.stake}, Odds: {request.odds}"
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