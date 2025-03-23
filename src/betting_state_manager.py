"""
betting_state_manager.py

Centralized state manager for betting operations.
Maintains all betting state in a simple, consistent manner.
Enhanced to properly handle bet cancellations.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import time

from .simple_file_storage import SimpleFileStorage

@dataclass
class BettingState:
    """Data structure representing the entire betting system state."""
    # Account state
    current_balance: float
    starting_stake: float
    target_amount: float
    
    # Cycle tracking
    current_cycle: int
    current_bet_in_cycle: int
    total_cycles: int
    
    # Statistics
    total_bets_placed: int
    total_wins: int
    total_losses: int
    total_money_lost: float
    highest_balance: float
    total_commission_paid: float
    
    # Active bet tracking
    last_winning_profit: float
    active_bet: Optional[Dict] = None
    
    # Tracking
    highest_cycle_reached: int = 1
    last_updated: str = ""

class BettingStateManager:
    """
    Centralized state manager for all betting operations.
    Replaces event store, repositories, and betting ledger.
    """
    
    def __init__(self, data_dir: str = 'web/data/betting'):
        """
        Initialize the state manager.
        
        Args:
            data_dir: Directory for data storage
        """
        # Initialize storage
        self.storage = SimpleFileStorage(data_dir)
        
        # Setup logging
        self.logger = logging.getLogger('BettingStateManager')
        
        # Initialize state
        self._load_state()
    
    def _load_state(self) -> None:
        """Load betting state from storage."""
        state_data = self.storage.read_json('betting_state.json')
        
        if not state_data:
            # Initialize with default state
            self.state = BettingState(
                current_balance=1.0,
                starting_stake=1.0,
                target_amount=50000.0,
                current_cycle=1,
                current_bet_in_cycle=0,
                total_cycles=0,
                total_bets_placed=0,
                total_wins=0,
                total_losses=0,
                total_money_lost=0.0,
                highest_balance=1.0,
                total_commission_paid=0.0,
                last_winning_profit=0.0,
                last_updated=datetime.now(timezone.utc).isoformat()
            )
            self._save_state()
        else:
            # Convert dictionary to BettingState object
            self.state = BettingState(**state_data)
    
    def _save_state(self) -> None:
        """Save betting state to storage."""
        # Update timestamp
        self.state.last_updated = datetime.now(timezone.utc).isoformat()
        
        # Convert to dictionary and save
        state_dict = {k: v for k, v in self.state.__dict__.items()}
        self.storage.write_json('betting_state.json', state_dict)
    
    def get_current_state(self) -> BettingState:
        """Get the current betting state."""
        return self.state
    
    def reset_state(self, initial_stake: float = 1.0) -> None:
        """
        Reset the betting state to initial values.
        
        Args:
            initial_stake: Starting stake amount
        """
        self.logger.info(f"Resetting betting state with initial stake: Â£{initial_stake}")
        
        self.state = BettingState(
            current_balance=initial_stake,
            starting_stake=initial_stake,
            target_amount=50000.0,
            current_cycle=1,
            current_bet_in_cycle=0,
            total_cycles=0,
            total_bets_placed=0,
            total_wins=0,
            total_losses=0,
            total_money_lost=0.0,
            highest_balance=initial_stake,
            total_commission_paid=0.0,
            last_winning_profit=0.0,
            last_updated=datetime.now(timezone.utc).isoformat()
        )
        self._save_state()
        
        # Also reset bet history
        self.storage.write_json('active_bet.json', {
            "is_canceled": True,
            "canceled_at": datetime.now(timezone.utc).isoformat(),
            "canceled_market_id": None,
            "status": "RESET",
            "reason": "System reset"
        })
        self.storage.write_json('bet_history.json', {"bets": []})
    
    def get_next_stake(self) -> float:
        """
        Calculate the stake for the next bet based on the compound strategy.
        Use the full account balance (last winning profit + starting stake)
        
        Returns:
            Next stake amount
        """
        # Compound strategy: use last winning profit + starting stake if available 
        if self.state.last_winning_profit > 0:
            total_stake = self.state.last_winning_profit + self.state.starting_stake
            return total_stake
        
        # Otherwise, use starting stake
        return self.state.starting_stake
    
    def record_bet_placed(self, bet_details: Dict) -> None:
        """
        Record a bet placement and update state.
        
        Args:
            bet_details: Dictionary containing bet details
        """
        self.logger.info(f"Recording bet placement - Market: {bet_details.get('market_id')}")
        
        # Update state
        self.state.total_bets_placed += 1
        self.state.current_bet_in_cycle += 1
        
        # Update current balance
        stake = bet_details.get('stake', 0.0)
        self.state.current_balance -= stake
        
        # Update bet details with cycle information
        bet_details['cycle_number'] = self.state.current_cycle
        bet_details['bet_in_cycle'] = self.state.current_bet_in_cycle
        bet_details['timestamp'] = datetime.now(timezone.utc).isoformat()
        
        # Store as active bet
        self.state.active_bet = bet_details
        self.storage.write_json('active_bet.json', bet_details)
        
        # Save updated state
        self._save_state()
        
        self.logger.info(
            f"Bet placed - Cycle: {self.state.current_cycle}, "
            f"Bet in cycle: {self.state.current_bet_in_cycle}, "
            f"Stake: Â£{stake}"
        )
    
    def record_bet_result(self, bet_details: Dict, won: bool, profit: float, commission: float = 0.0) -> None:
        """
        Record a bet result and update state.
        
        Args:
            bet_details: Dictionary containing bet details
            won: Whether the bet was successful
            profit: Net profit amount (after commission)
            commission: Commission amount
        """
        # Calculate gross profit
        stake = bet_details.get('stake', 0.0)
        gross_profit = profit + commission if won else 0.0
        
        if won:
            self.logger.info(
                f"Recording bet win - Selection: {bet_details.get('team_name')}, "
                f"Profit: Â£{profit}, Commission: Â£{commission}"
            )
            # Update state for win
            self.state.total_wins += 1
            self.state.last_winning_profit = profit
            self.state.current_balance += stake + profit
            self.state.total_commission_paid += commission
            
            # Update highest balance if needed
            if self.state.current_balance > self.state.highest_balance:
                self.state.highest_balance = self.state.current_balance
        else:
            self.logger.info(
                f"Recording bet loss - Selection: {bet_details.get('team_name')}, "
                f"Loss: Â£{stake}"
            )
            # Update state for loss
            self.state.total_losses += 1
            self.state.total_money_lost += stake
            self.state.last_winning_profit = 0.0
            
            # Increment cycle after a loss
            self.state.total_cycles += 1
            self.state.current_cycle += 1
            self.state.current_bet_in_cycle = 0
            
            # Update highest cycle if needed
            if self.state.current_cycle > self.state.highest_cycle_reached:
                self.state.highest_cycle_reached = self.state.current_cycle
        
        # Add settlement details to bet
        settlement_details = {
            **bet_details,
            'settlement_time': datetime.now(timezone.utc).isoformat(),
            'won': won,
            'gross_profit': gross_profit,
            'commission': commission,
            'profit': profit
        }
        
        # Clear active bet
        self.state.active_bet = None
        self.storage.write_json('active_bet.json', {
            "is_canceled": False,
            "is_settled": True,
            "settlement_time": datetime.now(timezone.utc).isoformat(),
            "won": won
        })
        
        # Add to bet history
        history = self.storage.read_json('bet_history.json', {"bets": []})
        history["bets"].append(settlement_details)
        self.storage.write_json('bet_history.json', history)
        
        # Save updated state
        self._save_state()
    
    def check_target_reached(self) -> bool:
        """
        Check if the target amount has been reached.
        
        Returns:
            True if target reached, False otherwise
        """
        if self.state.current_balance >= self.state.target_amount:
            self.logger.info(
                f"Target reached! Balance: Â£{self.state.current_balance}, "
                f"Target: Â£{self.state.target_amount}"
            )
            
            # Reset cycle when target reached
            self.state.total_cycles += 1
            self.state.current_cycle += 1
            self.state.current_bet_in_cycle = 0
            self.state.last_winning_profit = 0.0
            
            # Save state
            self._save_state()
            return True
        
        return False
    
    def has_active_bet(self) -> bool:
        """
        Check if there is an active bet.
        
        Returns:
            True if active bet exists, False otherwise
        """
        return self.state.active_bet is not None
    
    def get_active_bet(self) -> Optional[Dict]:
        """
        Get the current active bet.
        
        Returns:
            Active bet details or None if no active bet
        """
        return self.state.active_bet
    
    def get_bet_history(self, limit: int = 10) -> List[Dict]:
        """
        Get bet history.
        
        Args:
            limit: Maximum number of bets to return
            
        Returns:
            List of settled bets
        """
        history = self.storage.read_json('bet_history.json', {"bets": []})
        
        # Sort by settlement time (newest first)
        bets = sorted(
            history["bets"],
            key=lambda b: b.get('settlement_time', ''),
            reverse=True
        )
        
        # Return limited number
        return bets[:limit]
    
    def get_win_rate(self) -> float:
        """
        Calculate win rate percentage.
        
        Returns:
            Win rate as percentage
        """
        if self.state.total_bets_placed == 0:
            return 0.0
        return (self.state.total_wins / self.state.total_bets_placed) * 100.0
    
    def update_balance(self, amount: float, reason: str) -> None:
        """
        Update account balance.
        
        Args:
            amount: Amount to add/subtract
            reason: Reason for balance update
        """
        self.logger.info(f"Updating balance by {amount} - {reason}")
        
        # Update balance
        previous_balance = self.state.current_balance
        self.state.current_balance += amount
        
        # Update highest balance if increased
        if self.state.current_balance > self.state.highest_balance:
            self.state.highest_balance = self.state.current_balance
        
        # Save state
        self._save_state()
        
        self.logger.info(f"Balance updated: Â£{previous_balance} -> Â£{self.state.current_balance}")
        
    def reset_active_bet(self) -> None:
        """
        Reset the active bet state without settlement.
        Only used for cancellations in dry run mode.
        """
        self.logger.info("Resetting active bet without settlement (for cancellation)")
        
        # Backup original bet details for logging
        original_bet = self.state.active_bet
        
        # Clear active bet
        self.state.active_bet = None
        
        # Instead of writing an empty object, write a special flag object
        # that explicitly marks this as a canceled bet
        self.storage.write_json('active_bet.json', {
            "is_canceled": True,
            "canceled_at": datetime.now(timezone.utc).isoformat(),
            "canceled_market_id": original_bet.get('market_id') if original_bet else None,
            "status": "CANCELED"
        })
        
        # Decrement bet counters
        self.state.total_bets_placed -= 1
        if self.state.current_bet_in_cycle > 0:
            self.state.current_bet_in_cycle -= 1
        
        # Save state
        self._save_state()
        
        self.logger.info("Active bet reset complete")
    
    def get_stats_summary(self) -> Dict:
        """
        Get summary statistics for the dashboard.
        
        Returns:
            Dictionary of statistics
        """
        return {
            "current_balance": self.state.current_balance,
            "target_amount": self.state.target_amount,
            "current_cycle": self.state.current_cycle,
            "current_bet_in_cycle": self.state.current_bet_in_cycle,
            "total_cycles": self.state.total_cycles,
            "total_bets_placed": self.state.total_bets_placed,
            "win_rate": self.get_win_rate(),
            "total_wins": self.state.total_wins,
            "total_losses": self.state.total_losses,
            "total_money_lost": self.state.total_money_lost,
            "total_commission_paid": self.state.total_commission_paid,
            "highest_balance": self.state.highest_balance,
            "next_stake": self.get_next_stake(),
            "last_winning_profit": self.state.last_winning_profit,
            "last_updated": self.state.last_updated
        }