"""
betting_ledger.py

Handles tracking of betting cycles and performance metrics for the compound betting strategy.
Maintains a history of bets, cycles, and performance over time.
Enhanced to record commission amounts and properly track previous bet profits for stake calculation.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import aiofiles

class BettingLedger:
    def __init__(self, data_dir: str = 'web/data/betting'):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup logging
        self.logger = logging.getLogger('BettingLedger')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('web/logs/betting_ledger.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        
        # Initialize file paths
        self.ledger_file = self.data_dir / 'betting_ledger.json'
        
        # In-memory cache of ledger data
        self._ledger_cache = None
        
        # Ensure storage is initialized
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        """Initialize storage file if it doesn't exist (sync operation during init)"""
        if not self.ledger_file.exists():
            initial_data = {
                "starting_stake": 1.0,        # £1 starting stake
                "current_cycle": 1,           # Cycle number
                "current_bet_in_cycle": 0,    # Bet number in current cycle
                "total_cycles": 0,            # Total cycles completed
                "total_bets": 0,              # Total bets placed
                "total_wins": 0,              # Total winning bets
                "total_losses": 0,            # Total losing bets
                "total_money_lost": 0.0,      # Total money lost (sum of lost stakes)
                "highest_cycle_reached": 1,   # Highest cycle number reached
                "highest_balance": 1.0,       # Highest balance reached
                "cycle_history": [],          # History of completed cycles
                "total_commission_paid": 0.0, # Total Betfair commission paid
                "last_winning_profit": 0.0,   # Profit from last winning bet for compound strategy
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            with open(self.ledger_file, 'w') as f:
                json.dump(initial_data, f, indent=2)
            
            # Initialize cache
            self._ledger_cache = initial_data.copy()
        else:
            # Load existing data into cache during initialization
            try:
                with open(self.ledger_file, 'r') as f:
                    self._ledger_cache = json.load(f)
                    self.logger.info(f"Initialized cache from existing ledger file")
            except Exception as e:
                self.logger.error(f"Failed to load existing ledger during init: {str(e)}")
                self._ledger_cache = None

    async def _save_json(self, data: Dict) -> None:
        """Save data to JSON file asynchronously and update cache"""
        try:
            # Update the cache first
            self._ledger_cache = data.copy()
            
            # Then save to disk
            async with aiofiles.open(self.ledger_file, 'w') as f:
                await f.write(json.dumps(data, indent=2))
                
            self.logger.debug(f"Saved ledger data to file and updated cache")
        except Exception as e:
            self.logger.error(f"Error saving ledger: {str(e)}")
            raise

    async def _load_json(self) -> Dict:
        """Load data from JSON file asynchronously with cache support"""
        try:
            # Use cache if available to reduce disk I/O
            if self._ledger_cache is not None:
                return self._ledger_cache.copy()
            
            # Read from file if cache isn't initialized
            async with aiofiles.open(self.ledger_file, 'r') as f:
                content = await f.read()
                data = json.loads(content)
                
                # Update cache
                self._ledger_cache = data.copy()
                
                return data
        except Exception as e:
            self.logger.error(f"Error loading ledger: {str(e)}")
            # Return default structure if file can't be loaded
            default_data = {
                "starting_stake": 1.0,
                "current_cycle": 1,
                "current_bet_in_cycle": 0,
                "total_cycles": 0,
                "total_bets": 0,
                "total_wins": 0,
                "total_losses": 0,
                "total_money_lost": 0.0,
                "highest_cycle_reached": 1,
                "highest_balance": 1.0,
                "cycle_history": [],
                "total_commission_paid": 0.0,
                "last_winning_profit": 0.0,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            
            # Set cache to default data
            self._ledger_cache = default_data.copy()
            
            return default_data

    async def get_ledger(self) -> Dict:
        """Get current ledger data"""
        return await self._load_json()

    async def record_bet_placed(self, bet_details: Dict) -> Dict:
        """
        Record a new bet placement in the ledger
        
        Args:
            bet_details: Details of the placed bet
            
        Returns:
            Updated ledger data
        """
        try:
            ledger = await self._load_json()
            
            # Increment bet counters
            ledger["current_bet_in_cycle"] += 1
            ledger["total_bets"] += 1
            
            # Add timestamp for cycle start if this is the first bet in cycle
            if ledger["current_bet_in_cycle"] == 1:
                ledger["cycle_start_time"] = bet_details.get("timestamp", datetime.now(timezone.utc).isoformat())
            
            # Add cycle information to bet details for tracking
            bet_details["cycle_number"] = ledger["current_cycle"]
            bet_details["bet_in_cycle"] = ledger["current_bet_in_cycle"]
            
            ledger["last_updated"] = datetime.now(timezone.utc).isoformat()
            await self._save_json(ledger)
            
            self.logger.info(
                f"Recorded bet placement - Cycle: {ledger['current_cycle']}, "
                f"Bet #{ledger['current_bet_in_cycle']} in cycle, "
                f"Stake: £{bet_details['stake']}, Odds: {bet_details['odds']}"
            )
            
            return ledger
        except Exception as e:
            self.logger.error(f"Error recording bet placement: {str(e)}")
            raise

    async def record_bet_result(
        self, 
        bet_details: Dict, 
        won: bool, 
        profit: float, 
        new_balance: float,
        commission: float = 0.0
    ) -> Dict:
        """
        Record a bet result and update the ledger
        
        Args:
            bet_details: Details of the bet
            won: Whether the bet was successful
            profit: Amount of profit (net profit after commission if won)
            new_balance: New account balance after bet settlement
            commission: Commission amount (if won)
            
        Returns:
            Updated ledger data
        """
        try:
            ledger = await self._load_json()
            
            # Get bet details for logging
            market_id = bet_details.get("market_id", "Unknown")
            selection = bet_details.get("team_name", "Unknown")
            stake = bet_details.get("stake", 0.0)
            odds = bet_details.get("odds", 0.0)
            gross_profit = bet_details.get("gross_profit", profit + commission)
            
            if won:
                ledger["total_wins"] += 1
                ledger["total_commission_paid"] = ledger.get("total_commission_paid", 0.0) + commission
                
                # Update highest balance if needed
                if new_balance > ledger["highest_balance"]:
                    ledger["highest_balance"] = new_balance
                
                # Set the profit for the next bet's stake (compound strategy)
                # Make sure we're using the NET profit (after commission)
                ledger["last_winning_profit"] = profit
                
                self.logger.info(
                    f"Bet WON - Cycle: {ledger['current_cycle']}, "
                    f"Bet #{ledger['current_bet_in_cycle']} in cycle, "
                    f"Selection: {selection}, Stake: £{stake}, "
                    f"Odds: {odds}, Gross Profit: £{gross_profit}, "
                    f"Commission: £{commission}, Net Profit: £{profit}, "
                    f"New Balance: £{new_balance}, "
                    f"Next Stake Set: £{profit}"
                )
            else:
                ledger["total_losses"] += 1
                ledger["total_money_lost"] += stake
                
                # Reset the last winning profit
                ledger["last_winning_profit"] = 0.0
                
                # Record completed cycle
                cycle_record = {
                    "cycle_number": ledger["current_cycle"],
                    "bets_in_cycle": ledger["current_bet_in_cycle"],
                    "start_time": ledger.get("cycle_start_time", "Unknown"),
                    "end_time": datetime.now(timezone.utc).isoformat(),
                    "final_stake": stake,
                    "result": "Lost"
                }
                ledger["cycle_history"].append(cycle_record)
                
                # Start new cycle
                ledger["current_cycle"] += 1
                ledger["total_cycles"] += 1
                ledger["current_bet_in_cycle"] = 0
                
                # Update highest cycle if needed
                if ledger["current_cycle"] > ledger["highest_cycle_reached"]:
                    ledger["highest_cycle_reached"] = ledger["current_cycle"]
                    
                self.logger.info(
                    f"Bet LOST - Cycle {ledger['current_cycle']-1} ended, "
                    f"Selection: {selection}, Lost stake: £{stake}, "
                    f"Starting new cycle #{ledger['current_cycle']}"
                )
            
            ledger["last_updated"] = datetime.now(timezone.utc).isoformat()
            await self._save_json(ledger)
            
            return ledger
        except Exception as e:
            self.logger.error(f"Error recording bet result: {str(e)}")
            raise

    async def check_target_reached(self, balance: float, target: float) -> bool:
        """
        Check if target amount has been reached and handle cycle completion
        
        Args:
            balance: Current account balance
            target: Target amount
            
        Returns:
            True if target reached, False otherwise
        """
        try:
            if balance >= target:
                # Target reached - record successful cycle
                ledger = await self._load_json()
                
                cycle_record = {
                    "cycle_number": ledger["current_cycle"],
                    "bets_in_cycle": ledger["current_bet_in_cycle"],
                    "start_time": ledger.get("cycle_start_time", "Unknown"),
                    "end_time": datetime.now(timezone.utc).isoformat(),
                    "final_balance": balance,
                    "result": "Target Reached"
                }
                ledger["cycle_history"].append(cycle_record)
                ledger["total_cycles"] += 1
                
                # Reset for new cycle
                ledger["current_cycle"] += 1
                ledger["current_bet_in_cycle"] = 0
                ledger["last_winning_profit"] = 0.0  # Reset winning profit for new cycle
                
                # Update highest cycle if needed
                if ledger["current_cycle"] > ledger["highest_cycle_reached"]:
                    ledger["highest_cycle_reached"] = ledger["current_cycle"]
                    
                await self._save_json(ledger)
                
                self.logger.info(
                    f"TARGET REACHED! Final balance: £{balance}, "
                    f"Starting new cycle: {ledger['current_cycle']}"
                )
                
                return True
            
            return False
        except Exception as e:
            self.logger.error(f"Error checking target: {str(e)}")
            return False

    async def get_current_cycle_info(self) -> Dict:
        """Get information about the current cycle"""
        try:
            ledger = await self._load_json()
            
            return {
                "current_cycle": ledger["current_cycle"],
                "current_bet_in_cycle": ledger["current_bet_in_cycle"],
                "total_cycles": ledger["total_cycles"],
                "total_bets": ledger["total_bets"],
                "total_wins": ledger["total_wins"],
                "total_losses": ledger["total_losses"],
                "total_money_lost": ledger["total_money_lost"],
                "highest_cycle_reached": ledger["highest_cycle_reached"],
                "highest_balance": ledger["highest_balance"],
                "total_commission_paid": ledger.get("total_commission_paid", 0.0)
            }
        except Exception as e:
            self.logger.error(f"Error getting cycle info: {str(e)}")
            # Return default info if error occurs
            return {
                "current_cycle": 1,
                "current_bet_in_cycle": 0,
                "total_cycles": 0,
                "total_bets": 0,
                "total_wins": 0,
                "total_losses": 0,
                "total_money_lost": 0.0,
                "highest_cycle_reached": 1,
                "highest_balance": 1.0,
                "total_commission_paid": 0.0
            }
    
    async def get_next_stake(self) -> float:
        """
        Get the stake amount for the next bet based on the compound strategy
        using only the previous bet's profit
        
        Returns:
            Stake amount for the next bet
        """
        try:
            ledger = await self._load_json()
            
            # If this is the first bet in a cycle, use the initial stake
            if ledger["current_bet_in_cycle"] == 0:
                self.logger.info(f"First bet in cycle - using initial stake: £{ledger['starting_stake']}")
                return ledger["starting_stake"]
                
            # Otherwise, use the profit from the last winning bet
            # If there's no recorded profit (e.g., after a reset), use initial stake
            next_stake = ledger.get("last_winning_profit", 0.0)
            if next_stake <= 0:
                next_stake = ledger["starting_stake"]
                
            self.logger.info(f"Next stake calculated as £{next_stake} based on compound strategy (last_winning_profit)")
            
            return next_stake
        
        except Exception as e:
            self.logger.error(f"Error getting next stake: {str(e)}")
            # Return default stake amount if error occurs
            return 1.0
            
    async def reset_ledger(self, starting_stake: float = 1.0) -> Dict:
        """
        Reset the ledger to initial state
        
        Args:
            starting_stake: Initial stake amount for the new cycle
            
        Returns:
            Updated ledger data
        """
        try:
            self.logger.info(f"Resetting betting ledger to initial state with stake: £{starting_stake}")
            
            initial_data = {
                "starting_stake": starting_stake,
                "current_cycle": 1,
                "current_bet_in_cycle": 0,
                "total_cycles": 0,
                "total_bets": 0,
                "total_wins": 0,
                "total_losses": 0,
                "total_money_lost": 0.0,
                "highest_cycle_reached": 1,
                "highest_balance": starting_stake,
                "cycle_history": [],
                "total_commission_paid": 0.0,
                "last_winning_profit": 0.0,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            
            # Reset the cache
            self._ledger_cache = initial_data.copy()
            
            await self._save_json(initial_data)
            self.logger.info("Betting ledger reset successfully")
            
            return initial_data
            
        except Exception as e:
            self.logger.error(f"Error resetting ledger: {str(e)}")
            raise