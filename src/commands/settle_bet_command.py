"""
settle_bet_command.py

Implements async Command pattern for bet settlement operations.
Handles validation, execution, and recording of bet settlements.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple
import logging

from ..repositories.bet_repository import BetRepository
from ..repositories.account_repository import AccountRepository
from ..betfair_client import BetfairClient

@dataclass
class BetSettlementRequest:
    """Data structure for bet settlement request"""
    market_id: str
    won: bool
    profit: float

class BetSettlementCommand:
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
        self.logger = logging.getLogger('BetSettlementCommand')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('web/logs/commands.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    async def validate(self, request: BetSettlementRequest) -> Tuple[bool, str]:
        """
        Validate bet settlement request asynchronously
        Returns: (is_valid: bool, error_message: str)
        """
        self.logger.info(f"Validating bet settlement request for market {request.market_id}")
        
        # Get the bet details
        bet = await self.bet_repository.get_bet_by_market_id(request.market_id)
        if not bet:
            return False, f"No bet found for market {request.market_id}"
            
        # Check if bet is already settled
        if "settlement_time" in bet:
            return False, f"Bet for market {request.market_id} is already settled"
            
        # Validate profit calculation for winning bets
        if request.won:
            expected_profit = bet["stake"] * (bet["odds"] - 1)
            if abs(request.profit - expected_profit) > 0.01:  # Allow for small rounding differences
                return False, f"Invalid profit amount. Expected: £{expected_profit}, Got: £{request.profit}"
                
        return True, ""

    async def execute(self, request: BetSettlementRequest) -> Optional[Dict]:
        """
        Execute bet settlement asynchronously
        Returns updated bet details if successful, None if failed
        """
        self.logger.info(f"Executing bet settlement for market {request.market_id}")
        
        try:
            # Validate request
            is_valid, error = await self.validate(request)
            if not is_valid:
                self.logger.error(f"Validation failed: {error}")
                return None
                
            # Get original bet details
            bet_details = await self.bet_repository.get_bet_by_market_id(request.market_id)
            
            # Start atomic settlement process
            try:
                # Record settlement
                await self.bet_repository.record_bet_settlement(
                    bet_details=bet_details,
                    won=request.won,
                    profit=request.profit
                )
                
                # Update account balance and stats
                if request.won:
                    # For wins, add back stake plus profit
                    await self.account_repository.update_balance(bet_details["stake"] + request.profit)
                
                await self.account_repository.update_bet_stats(request.won)
                
                self.logger.info(
                    f"Successfully settled bet: Market ID {request.market_id}, "
                    f"Won: {request.won}, Profit: £{request.profit}"
                )
                
                # Get and return updated bet details
                return await self.bet_repository.get_bet_by_market_id(request.market_id)
                
            except Exception as settlement_error:
                # If any part of the settlement process fails, we should attempt to
                # roll back any changes that were made
                self.logger.error(f"Settlement process failed: {str(settlement_error)}")
                try:
                    # Note: In a full implementation, we would:
                    # 1. Track which operations completed successfully
                    # 2. Roll back completed operations in reverse order
                    # 3. Maintain a settlement audit log
                    # 4. Possibly implement a proper saga pattern
                    pass
                except Exception as rollback_error:
                    self.logger.error(f"Failed to rollback settlement: {str(rollback_error)}")
                return None
                
        except Exception as e:
            self.logger.error(f"Failed to settle bet: {str(e)}")
            return None