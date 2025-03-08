"""
betting_ledger.py

Handles tracking of betting cycles and performance metrics for the compound betting strategy.
Maintains a history of bets, cycles, and performance over time.
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
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            with open(self.ledger_file, 'w') as f:
                json.dump(initial_data, f, indent=2)

    async def _save_json(self, data: Dict) -> None:
        """Save data to JSON file asynchronously"""
        try:
            async with aiofiles.open(self.ledger_file, 'w') as f:
                await f.write(json.dumps(data, indent=2))
        except Exception as e:
            self.logger.error(f"Error saving ledger: {str(e)}")
            raise

    async def _load_json(self) -> Dict:
        """Load data from JSON file asynchronously"""
        try:
            async with aiofiles.open(self.ledger_file, 'r') as f:
                content = await f.read()
                return json.loads(content)
        except Exception as e:
            self.logger.error(f"Error loading ledger: {str(e)}")
            # Return default structure if file can't be loaded
            return {
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
                "last_updated": datetime.now(timezone.utc).isoformat()
            }

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

    async def record_bet_result(self, 
                               bet_details: Dict, 
                               won: bool, 
                               profit: float, 
                               new_balance: float) -> Dict:
        """
        Record a bet result and update the ledger
        
        Args:
            bet_details: Details of the bet
            won: Whether the bet was successful
            profit: Amount of profit (if won)
            new_balance: New account balance after bet settlement
            
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
            
            if won:
                ledger["total_wins"] += 1
                
                # Update highest balance if needed
                if new_balance > ledger["highest_balance"]:
                    ledger["highest_balance"] = new_balance
                    
                self.logger.info(
                    f"Bet WON - Cycle: {ledger['current_cycle']}, "
                    f"Bet #{ledger['current_bet_in_cycle']} in cycle, "
                    f"Selection: {selection}, Stake: £{stake}, "
                    f"Odds: {odds}, Profit: £{profit}, New Balance: £{new_balance}"
                )
            else:
                ledger["total_losses"] += 1
                ledger["total_money_lost"] += stake
                
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
                "highest_balance": ledger["highest_balance"]
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
                "highest_balance": 1.0
            }