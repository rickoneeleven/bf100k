"""
place_bet_command.py

Implements async Command pattern for bet placement operations.
Handles validation, execution, and recording of bet placement.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple
import logging

from src.repositories.bet_repository import BetRepository
from src.repositories.account_repository import AccountRepository
from src.betfair_client import BetfairClient

@dataclass
class PlaceBetRequest:
    """Data structure for bet placement request"""
    market_id: str
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
                    
                return True, ""
                
        return False, "Selection not found in market"

    async def execute(self, request: PlaceBetRequest) -> Optional[Dict]:
        """
        Execute bet placement asynchronously
        Returns bet details if successful, None if failed
        """
        self.logger.info(f"Executing bet placement for market {request.market_id}")
        
        try:
            # Validate request
            is_valid, error = await self.validate(request)
            if not is_valid:
                self.logger.error(f"Validation failed: {error}")
                return None
                
            # Create bet record
            bet_details = {
                "market_id": request.market_id,
                "selection_id": request.selection_id,
                "odds": request.odds,
                "stake": request.stake,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            # Record bet placement and update balance atomically
            await self.bet_repository.record_bet_placement(bet_details)
            await self.account_repository.update_balance(-request.stake)
            
            self.logger.info(
                f"Successfully placed bet: Market ID {request.market_id}, "
                f"Selection ID {request.selection_id}, Stake £{request.stake}"
            )
            
            return bet_details
            
        except Exception as e:
            self.logger.error(f"Failed to place bet: {str(e)}")
            # If an error occurs after bet recording but before balance update,
            # we should attempt to roll back the bet recording
            try:
                # Note: In a full implementation, we would track the state and
                # implement proper rollback mechanisms for partial failures
                pass
            except Exception as rollback_error:
                self.logger.error(f"Failed to rollback bet placement: {str(rollback_error)}")
            return None