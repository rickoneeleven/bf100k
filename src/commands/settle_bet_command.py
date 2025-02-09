# File: src/commands/settle_bet_command.py

"""
settle_bet_command.py

Implements the Command pattern for bet settlement operations.
Handles validation, execution, and recording of bet settlements.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple
import logging

from src.repositories.bet_repository import BetRepository
from src.repositories.account_repository import AccountRepository
from src.betfair_client import BetfairClient

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

    def validate(self, request: BetSettlementRequest) -> Tuple[bool, str]:
        """
        Validate bet settlement request
        Returns: (is_valid: bool, error_message: str)
        """
        self.logger.info(f"Validating bet settlement request for market {request.market_id}")
        
        # Get the bet details
        bet = self.bet_repository.get_bet_by_market_id(request.market_id)
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

    def execute(self, request: BetSettlementRequest) -> Optional[Dict]:
        """
        Execute bet settlement
        Returns updated bet details if successful, None if failed
        """
        self.logger.info(f"Executing bet settlement for market {request.market_id}")
        
        # Validate request
        is_valid, error = self.validate(request)
        if not is_valid:
            self.logger.error(f"Validation failed: {error}")
            return None
            
        try:
            # Get original bet details
            bet_details = self.bet_repository.get_bet_by_market_id(request.market_id)
            
            # Record settlement
            self.bet_repository.record_bet_settlement(
                bet_details=bet_details,
                won=request.won,
                profit=request.profit
            )
            
            # Update account balance and stats
            if request.won:
                # For wins, add back stake plus profit
                self.account_repository.update_balance(bet_details["stake"] + request.profit)
            
            self.account_repository.update_bet_stats(request.won)
            
            self.logger.info(
                f"Successfully settled bet: Market ID {request.market_id}, "
                f"Won: {request.won}, Profit: £{request.profit}"
            )
            
            # Get and return updated bet details
            return self.bet_repository.get_bet_by_market_id(request.market_id)
            
        except Exception as e:
            self.logger.error(f"Failed to settle bet: {str(e)}")
            return None