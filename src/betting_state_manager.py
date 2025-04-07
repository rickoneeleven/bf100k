"""
betting_state_manager.py

Centralized state manager for betting operations, acting as the single source of truth.
Manages all betting state (balance, cycle, active bet, history, stats)
and persists it using SimpleFileStorage.
Consolidates logic previously handled by BettingLedger, EventStore, AccountRepository, BetRepository.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
import time # Keep for potential future use, but not currently used

from .simple_file_storage import SimpleFileStorage

@dataclass
class BettingState:
    """Data structure representing the entire betting system state."""
    # Core Betting Config/State
    current_balance: float = 1.0
    starting_stake: float = 1.0 # The initial stake for cycle 1, bet 1
    target_amount: float = 50000.0
    last_winning_profit: float = 0.0 # Net profit of the last won bet in the current cycle

    # Cycle Tracking
    current_cycle: int = 1
    current_bet_in_cycle: int = 0 # 0 means no bet placed yet in this cycle

    # Statistics
    total_cycles: int = 0 # Completed cycles (due to loss or target reached)
    total_bets_placed: int = 0 # Overall total bets ever placed
    total_wins: int = 0
    total_losses: int = 0
    total_money_lost: float = 0.0 # Sum of stakes from lost bets
    total_commission_paid: float = 0.0
    highest_balance: float = 1.0
    highest_cycle_reached: int = 1

    # Active Bet Tracking (volatile, stored separately but mirrored here for logic)
    active_bet: Optional[Dict] = None # Holds details ONLY when a bet is active

    # Metadata
    last_updated: str = ""

class BettingStateManager:
    """
    Centralized state manager using SimpleFileStorage.
    Consolidates state logic.
    """
    STATE_FILENAME = 'betting_state.json'
    ACTIVE_BET_FILENAME = 'active_bet.json'
    HISTORY_FILENAME = 'bet_history.json'

    def __init__(self, data_dir: str = 'web/data/betting', config: Optional[Dict] = None):
        """
        Initialize the state manager.

        Args:
            data_dir: Directory for data storage.
            config: Optional initial configuration dictionary.
        """
        self.storage = SimpleFileStorage(data_dir)
        self.logger = logging.getLogger('BettingStateManager')
        self.state: BettingState = BettingState() # Initialize with defaults

        # Load initial configuration if provided
        if config:
            self._apply_initial_config(config)

        # Load persistent state or initialize if first run
        self._load_state()
        # Ensure active_bet state matches persisted file at startup
        self._sync_active_bet_on_load()


    def _apply_initial_config(self, config: Dict) -> None:
        """Apply relevant settings from config during initialization."""
        try:
            betting_config = config.get('betting', {})
            system_config = config.get('system', {})

            self.state.starting_stake = float(betting_config.get('initial_stake', self.state.starting_stake))
            self.state.target_amount = float(betting_config.get('target_amount', self.state.target_amount))

            # Ensure starting balance reflects starting stake if initializing
            if not (self.storage.data_dir / self.STATE_FILENAME).exists():
                 self.state.current_balance = self.state.starting_stake
                 self.state.highest_balance = self.state.starting_stake

            self.logger.info(f"Applied initial config: StartStake={self.state.starting_stake}, Target={self.state.target_amount}")

        except (ValueError, TypeError) as e:
            self.logger.error(f"Invalid configuration value during init: {e}. Using defaults.", exc_info=True)


    def _load_state(self) -> None:
        """Load betting state from storage or initialize."""
        state_data = self.storage.read_json(self.STATE_FILENAME)

        if not state_data:
            # If file doesn't exist or is empty, initialize with current defaults
            self.logger.info(f"No existing state file found or file empty. Initializing '{self.STATE_FILENAME}'.")
            # Ensure starting balance and highest balance match initial stake
            self.state.current_balance = self.state.starting_stake
            self.state.highest_balance = self.state.starting_stake
            self._save_state() # Save the initial state
        else:
            # Load state from file, applying defaults for missing fields
            try:
                # Get default values from a default instance
                default_state_dict = asdict(BettingState())
                # Update default dict with loaded data
                merged_data = {**default_state_dict, **state_data}
                # Create state object from merged data
                self.state = BettingState(**merged_data)
                self.logger.info(f"Loaded state from '{self.STATE_FILENAME}'.")
            except TypeError as e:
                 self.logger.error(f"Error creating BettingState from loaded data: {e}. Data: {state_data}. Re-initializing state.", exc_info=True)
                 # Re-initialize state if loading fails badly
                 self.state = BettingState()
                 self.state.current_balance = self.state.starting_stake
                 self.state.highest_balance = self.state.starting_stake
                 self._save_state()

    def _sync_active_bet_on_load(self) -> None:
        """Ensure in-memory active_bet matches the persisted file at startup."""
        active_bet_from_file = self.storage.read_json(self.ACTIVE_BET_FILENAME)
        if active_bet_from_file and isinstance(active_bet_from_file, dict) and \
           'market_id' in active_bet_from_file and \
           not active_bet_from_file.get('is_canceled') and \
           not active_bet_from_file.get('is_settled'):
            self.state.active_bet = active_bet_from_file
            self.logger.info(f"Synced active bet from file on load: Market {active_bet_from_file.get('market_id')}")
        else:
            # If file indicates no active bet, ensure memory matches
            if self.state.active_bet is not None:
                 self.logger.warning("In-memory state had an active bet, but file did not. Clearing in-memory active bet.")
                 self.state.active_bet = None
            # Ensure the file contains an empty object if no bet is active
            if not active_bet_from_file or active_bet_from_file.get('is_canceled') or active_bet_from_file.get('is_settled'):
                 self.storage.write_json(self.ACTIVE_BET_FILENAME, {})


    def _save_state(self) -> None:
        """Save the current betting state to storage."""
        self.state.last_updated = datetime.now(timezone.utc).isoformat()
        # Use asdict for robust conversion of dataclass to dictionary
        state_dict = asdict(self.state)
        if not self.storage.write_json(self.STATE_FILENAME, state_dict):
             self.logger.error(f"CRITICAL: Failed to save state to '{self.STATE_FILENAME}'!")
             # Consider additional error handling here - retry? alert?

    def get_current_state(self) -> BettingState:
        """Get the current betting state."""
        # Maybe add a read from disk here if consistency is paramount and writes might fail?
        # For now, return the in-memory state assuming writes are successful or errors logged.
        return self.state

    def reset_state(self, initial_stake: Optional[float] = None) -> None:
        """
        Reset the betting state to initial values.

        Args:
            initial_stake: Optional new starting stake amount. If None, uses existing starting_stake.
        """
        stake_to_use = initial_stake if initial_stake is not None and initial_stake > 0 else self.state.starting_stake
        if stake_to_use <= 0: stake_to_use = 1.0 # Ensure positive stake

        self.logger.info(f"Resetting betting state with initial stake: £{stake_to_use:.2f}")

        # Create a new default state instance
        self.state = BettingState(
             starting_stake=stake_to_use,
             target_amount=self.state.target_amount, # Keep existing target
             current_balance=stake_to_use,
             highest_balance=stake_to_use
        )
        self._save_state()

        # Reset active bet file (write empty object)
        self.storage.write_json(self.ACTIVE_BET_FILENAME, {})
        # Reset bet history file
        self.storage.write_json(self.HISTORY_FILENAME, {"bets": []})
        self.logger.info("Betting state, active bet, and history reset.")


    def get_next_stake(self) -> float:
        """
        Calculate the stake for the next bet based on the compound strategy.
        Uses last winning profit + starting stake, or just starting stake.

        Returns:
            Next stake amount, ensuring it's at least the starting stake.
        """
        # If a cycle just ended (loss or target), last_winning_profit should be 0
        if self.state.last_winning_profit > 0:
            # Compound: Use last net profit + the initial stake defined for the session
            total_stake = self.state.last_winning_profit + self.state.starting_stake
            self.logger.debug(f"Calculating next stake: LastWinProfit={self.state.last_winning_profit:.2f} + StartingStake={self.state.starting_stake:.2f} = {total_stake:.2f}")
            return max(total_stake, self.state.starting_stake) # Ensure stake doesn't drop below starting stake
        else:
            # Start of cycle or after loss: Use the starting stake
            self.logger.debug(f"Calculating next stake: Using StartingStake={self.state.starting_stake:.2f}")
            return self.state.starting_stake

    def record_bet_placed(self, bet_details: Dict) -> None:
        """
        Record a bet placement, update state, and persist.

        Args:
            bet_details: Dictionary containing bet details from BettingService.
        """
        if self.state.active_bet:
            self.logger.error(f"Cannot place bet on market {bet_details.get('market_id')}: Active bet already exists for market {self.state.active_bet.get('market_id')}")
            # Optionally raise an error here? Or just log and return?
            # raise RuntimeError("Cannot place bet when another is active.")
            return # Prevent placing multiple bets

        try:
            stake = float(bet_details.get('stake', 0.0))
            market_id = bet_details.get('market_id')
            if stake <= 0 or not market_id:
                 raise ValueError(f"Invalid stake ({stake}) or market_id ({market_id}) for bet placement.")

            if stake > self.state.current_balance:
                 raise ValueError(f"Insufficient funds: Stake £{stake:.2f} > Balance £{self.state.current_balance:.2f}")

            self.logger.info(f"Recording bet placement - Market: {market_id}, Stake: £{stake:.2f}")

            # --- Update State ---
            self.state.total_bets_placed += 1
            self.state.current_bet_in_cycle += 1
            self.state.current_balance -= stake # Deduct stake

            # Add cycle info to bet details before storing
            bet_details['cycle_number'] = self.state.current_cycle
            bet_details['bet_in_cycle'] = self.state.current_bet_in_cycle
            # Ensure timestamp exists
            if 'timestamp' not in bet_details:
                 bet_details['timestamp'] = datetime.now(timezone.utc).isoformat()

            # Store as active bet in memory AND persist to file
            self.state.active_bet = bet_details
            if not self.storage.write_json(self.ACTIVE_BET_FILENAME, bet_details):
                 self.logger.error(f"CRITICAL: Failed to write active bet file for market {market_id}!")
                 # Attempt to rollback state? Complex. For now, log critical error.
                 # self.state.current_balance += stake # Rollback balance deduction
                 # self.state.current_bet_in_cycle -= 1
                 # self.state.total_bets_placed -= 1
                 # self.state.active_bet = None
                 # # Don't save state here as the file write failed.
                 return # Abort further processing

            # Save updated main state
            self._save_state()

            self.logger.info(
                f"Bet placed recorded - Cycle: {self.state.current_cycle}, "
                f"Bet#: {self.state.current_bet_in_cycle}, Stake: £{stake:.2f}, New Bal: £{self.state.current_balance:.2f}"
            )

        except (ValueError, TypeError) as e:
             self.logger.error(f"Error recording bet placement: {e}", exc_info=True)
             # Ensure state is not left inconsistent if possible
             # If error occurred before state changes, nothing to rollback.
             # If after, rollback might be needed but is complex. Logging is key.


    def record_bet_result(self, bet_details: Dict, won: bool, profit: float, commission: float) -> None:
        """
        Record a bet result, update state (balance, stats, cycle), persist history,
        and clear active bet.

        Args:
            bet_details: Original dictionary of the active bet being settled.
            won: Boolean indicating if the bet was successful.
            profit: Net profit amount (after commission if won).
            commission: Commission amount deducted (only if won).
        """
        try:
            market_id = bet_details.get('market_id')
            stake = float(bet_details.get('stake', 0.0))
            team_name = bet_details.get('team_name', 'Unknown')

            if stake <= 0 or not market_id:
                 self.logger.error(f"Cannot record result for invalid bet details: {bet_details}")
                 return

            # Prevent processing if no active bet or mismatch
            if not self.state.active_bet or self.state.active_bet.get('market_id') != market_id:
                 self.logger.warning(f"Attempted to record result for market {market_id}, but it's not the active bet (Current: {self.state.active_bet.get('market_id') if self.state.active_bet else 'None'}). Skipping.")
                 return

            self.logger.info(f"Recording bet result for Market: {market_id} - Won: {won}, Net Profit: £{profit:.2f}, Comm: £{commission:.2f}")

            # --- Update State ---
            if won:
                self.state.total_wins += 1
                self.state.last_winning_profit = profit # Store net profit
                # Add stake back + net profit
                self.state.current_balance += stake + profit
                self.state.total_commission_paid += commission
                if self.state.current_balance > self.state.highest_balance:
                    self.state.highest_balance = self.state.current_balance
            else: # Lost Bet
                self.state.total_losses += 1
                self.state.total_money_lost += stake
                self.state.last_winning_profit = 0.0 # Reset profit on loss

                # --- Cycle Reset Logic ---
                self.state.total_cycles += 1 # Increment completed cycles
                self.state.current_cycle += 1 # Move to the next cycle number
                self.state.current_bet_in_cycle = 0 # Reset bet count for new cycle
                if self.state.current_cycle > self.state.highest_cycle_reached:
                    self.state.highest_cycle_reached = self.state.current_cycle
                self.logger.info(f"Bet LOST. Resetting cycle. Starting Cycle #{self.state.current_cycle}")


            # --- Persistence ---
            # 1. Add settlement details to the bet record for history
            settlement_details = {
                **bet_details,
                'settlement_time': datetime.now(timezone.utc).isoformat(),
                'won': won,
                # Calculate gross profit for history record
                'gross_profit': profit + commission if won else 0.0,
                'commission': commission,
                'profit': profit # Net profit
            }

            # 2. Add to bet history file
            history = self.storage.read_json(self.HISTORY_FILENAME, {"bets": []})
            # Ensure 'bets' key exists and is a list
            if not isinstance(history.get("bets"), list):
                 history["bets"] = []
            history["bets"].append(settlement_details)
            if not self.storage.write_json(self.HISTORY_FILENAME, history):
                 self.logger.error(f"CRITICAL: Failed to write bet history for market {market_id}!")
                 # Consider potential inconsistency

            # 3. Clear active bet state in memory first
            self.state.active_bet = None

            # 4. Update active_bet.json to show settlement
            settled_marker = {
                "is_settled": True,
                "settlement_time": settlement_details['settlement_time'],
                "won": won,
                "settled_market_id": market_id # Add market ID for confirmation
            }
            if not self.storage.write_json(self.ACTIVE_BET_FILENAME, settled_marker):
                 self.logger.error(f"CRITICAL: Failed to write settled status to active_bet.json for market {market_id}!")
                 # Potential issue: state thinks no active bet, but file might still show one

            # 5. Save the main state last (contains updated balance, cycle, stats)
            self._save_state()

            self.logger.info(f"Bet result recorded for {market_id}. New Bal: £{self.state.current_balance:.2f}")

        except (ValueError, TypeError) as e:
             self.logger.error(f"Error recording bet result: {e}", exc_info=True)
             # State might be inconsistent if error occurred mid-update.


    def check_target_reached(self) -> bool:
        """
        Check if the target amount has been reached and reset cycle if so.

        Returns:
            True if target was reached and cycle reset, False otherwise.
        """
        if self.state.current_balance >= self.state.target_amount:
            self.logger.info(
                f"TARGET REACHED! Balance: £{self.state.current_balance:.2f} >= Target: £{self.state.target_amount:.2f}"
            )

            # --- Cycle Reset Logic (Target Reached) ---
            self.state.total_cycles += 1
            self.state.current_cycle += 1
            self.state.current_bet_in_cycle = 0
            self.state.last_winning_profit = 0.0 # Reset profit for new cycle
            if self.state.current_cycle > self.state.highest_cycle_reached:
                 self.state.highest_cycle_reached = self.state.current_cycle
            self.logger.info(f"Target reached. Resetting cycle. Starting Cycle #{self.state.current_cycle}")

            # Save state with updated cycle info
            self._save_state()
            return True

        return False

    def has_active_bet(self) -> bool:
        """Check if there is an active bet in memory."""
        return self.state.active_bet is not None

    def get_active_bet(self) -> Optional[Dict]:
        """Get the current active bet details from memory."""
        # Consider adding a check against the active_bet.json file for belt-and-suspenders consistency?
        # file_bet = self.storage.read_json(self.ACTIVE_BET_FILENAME)
        # if not file_bet or file_bet.get('is_settled') or file_bet.get('is_canceled'):
        #     if self.state.active_bet is not None:
        #          self.logger.warning("Mismatch: State has active bet, but file doesn't. Clearing state.")
        #          self.state.active_bet = None
        # return self.state.active_bet
        # --- For now, trust the in-memory state which should be synced on load/update ---
        return self.state.active_bet

    def get_bet_history(self, limit: int = 10) -> List[Dict]:
        """Get bet history from storage."""
        history = self.storage.read_json(self.HISTORY_FILENAME, {"bets": []})
        bets = history.get("bets", [])
        if not isinstance(bets, list): return [] # Ensure it's a list

        # Sort by settlement time (newest first)
        try:
            sorted_bets = sorted(
                bets,
                # Handle missing or invalid settlement_time robustly
                key=lambda b: b.get('settlement_time', '0000-01-01T00:00:00Z'),
                reverse=True
            )
        except (TypeError, ValueError):
             self.logger.error("Error sorting bet history, returning unsorted.")
             sorted_bets = bets # Return unsorted if keys are bad

        # Return limited number
        return sorted_bets[:limit]

    def get_win_rate(self) -> float:
        """Calculate win rate percentage."""
        if self.state.total_bets_placed == 0:
            return 0.0
        try:
            return (self.state.total_wins / self.state.total_bets_placed) * 100.0
        except ZeroDivisionError:
            return 0.0

    def update_balance(self, amount: float, reason: str) -> None:
        """
        Manually update account balance (e.g., for deposits/withdrawals or corrections).
        NOTE: Standard bet operations update balance via record_bet_placed/record_bet_result.

        Args:
            amount: Amount to add (positive) or subtract (negative).
            reason: Reason for the update (logged).
        """
        self.logger.info(f"Manual balance update requested: {amount:+.2f} - Reason: {reason}")
        previous_balance = self.state.current_balance
        new_balance = previous_balance + amount

        if new_balance < 0:
            self.logger.error(f"Manual balance update failed: Would result in negative balance (£{new_balance:.2f}).")
            return # Prevent negative balance

        # Update state
        self.state.current_balance = new_balance
        if new_balance > self.state.highest_balance:
            self.state.highest_balance = new_balance

        # Save state
        self._save_state()
        self.logger.info(f"Balance manually updated: £{previous_balance:.2f} -> £{new_balance:.2f}. Reason: {reason}")
        # Note: Does not add to bet_history.json, consider a separate transaction log if needed.


    def reset_active_bet(self) -> None:
        """
        Reset the active bet state, typically used for cancellation in dry run mode.
        Decrements counters and marks active_bet.json as canceled.
        """
        self.logger.info("Resetting active bet state (manual cancellation or error recovery)")

        original_bet = self.state.active_bet
        if not original_bet:
            self.logger.warning("No active bet to reset.")
            return

        market_id = original_bet.get('market_id', 'Unknown')

        # --- Update State ---
        # Decrement counters (reverse the increments from record_bet_placed)
        if self.state.total_bets_placed > 0:
            self.state.total_bets_placed -= 1
        if self.state.current_bet_in_cycle > 0:
            self.state.current_bet_in_cycle -= 1
        # Note: Balance was already restored by caller (CommandHandler.cmd_cancel_bet) via update_balance

        # Clear active bet in memory
        self.state.active_bet = None

        # --- Persistence ---
        # 1. Mark active_bet.json as canceled
        cancel_marker = {
            "is_canceled": True,
            "canceled_at": datetime.now(timezone.utc).isoformat(),
            "canceled_market_id": market_id,
            "status": "CANCELED"
        }
        if not self.storage.write_json(self.ACTIVE_BET_FILENAME, cancel_marker):
             self.logger.error(f"CRITICAL: Failed to write canceled status to active_bet.json for market {market_id}!")

        # 2. Save the main state (updated counters)
        self._save_state()

        self.logger.info(f"Active bet state reset for market {market_id}.")


    def get_stats_summary(self) -> Dict:
        """Get summary statistics for the dashboard."""
        # Use asdict to ensure all fields from the state are included
        summary = asdict(self.state)
        # Add calculated fields
        summary["win_rate"] = self.get_win_rate()
        summary["next_stake"] = self.get_next_stake()
        # Remove active_bet object itself from summary if present
        summary.pop("active_bet", None)
        return summary