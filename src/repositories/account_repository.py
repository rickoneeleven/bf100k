"""
account_repository.py

Async repository pattern implementation for account data management.
Handles storage and retrieval of account status and balance.
"""

import json
import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Dict
import aiofiles

@dataclass
class AccountStatus:
    """Data structure for account status"""
    current_balance: float
    target_amount: float
    total_bets_placed: int
    successful_bets: int
    last_updated: str

class AccountRepository:
    def __init__(self, data_dir: str = 'web/data/betting'):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup logging
        self.logger = logging.getLogger('AccountRepository')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('web/logs/repositories.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        
        # Initialize file path
        self.account_status_file = self.data_dir / 'account_status.json'
        
        # Ensure storage is initialized
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        """Initialize storage file if it doesn't exist (sync operation during init)"""
        if not self.account_status_file.exists():
            initial_status = {
                "current_balance": 1.0,  # Changed to £1 starting stake
                "target_amount": 50000.0,
                "total_bets_placed": 0,
                "successful_bets": 0,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            with open(self.account_status_file, 'w') as f:
                json.dump(initial_status, f, indent=2)

    async def _save_json(self, file_path: Path, data: Dict) -> None:
        """Save data to JSON file asynchronously"""
        try:
            async with aiofiles.open(file_path, 'w') as f:
                await f.write(json.dumps(data, indent=2))
        except Exception as e:
            self.logger.error(f"Error saving JSON: {str(e)}")
            raise

    async def _load_json(self, file_path: Path) -> Dict:
        """Load data from JSON file asynchronously"""
        try:
            async with aiofiles.open(file_path, 'r') as f:
                content = await f.read()
                return json.loads(content)
        except Exception as e:
            self.logger.error(f"Error loading JSON: {str(e)}")
            # Return default structure if file can't be loaded
            return {
                "current_balance": 1.0,
                "target_amount": 50000.0,
                "total_bets_placed": 0,
                "successful_bets": 0,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }

    async def get_account_status(self) -> AccountStatus:
        """
        Get current account status asynchronously
        
        Returns:
            AccountStatus object containing current account information
        """
        try:
            data = await self._load_json(self.account_status_file)
            return AccountStatus(**data)
        except Exception as e:
            self.logger.error(f"Error getting account status: {str(e)}")
            # Return default status if error occurs
            return AccountStatus(
                current_balance=1.0,
                target_amount=50000.0,
                total_bets_placed=0,
                successful_bets=0,
                last_updated=datetime.now(timezone.utc).isoformat()
            )

    async def update_balance(self, amount_change: float) -> None:
        """
        Update account balance asynchronously
        
        Args:
            amount_change: Amount to add/subtract from balance (negative for deductions)
            
        Raises:
            ValueError: If resulting balance would be negative
        """
        try:
            self.logger.info(f"Updating balance by {amount_change}")
            
            data = await self._load_json(self.account_status_file)
            new_balance = data["current_balance"] + amount_change
            
            if new_balance < 0:
                raise ValueError(f"Insufficient funds: {data['current_balance']} + {amount_change} = {new_balance}")
            
            data["current_balance"] = new_balance
            data["last_updated"] = datetime.now(timezone.utc).isoformat()
            
            await self._save_json(self.account_status_file, data)
            self.logger.info(f"New balance: £{new_balance}")
        except Exception as e:
            self.logger.error(f"Error updating balance: {str(e)}")
            raise

    async def reset_to_starting_stake(self) -> None:
        """Reset account balance to the starting stake (£1)"""
        try:
            self.logger.info("Resetting account balance to starting stake (£1)")
            
            data = await self._load_json(self.account_status_file)
            data["current_balance"] = 1.0  # £1 starting stake
            data["last_updated"] = datetime.now(timezone.utc).isoformat()
            
            await self._save_json(self.account_status_file, data)
            self.logger.info("Account balance reset to £1")
        except Exception as e:
            self.logger.error(f"Error resetting to starting stake: {str(e)}")
            raise

    async def update_bet_stats(self, bet_won: bool) -> None:
        """
        Update betting statistics asynchronously
        
        Args:
            bet_won: Whether the bet was successful
        """
        try:
            self.logger.info(f"Updating bet statistics - Won: {bet_won}")
            
            data = await self._load_json(self.account_status_file)
            data["total_bets_placed"] += 1
            if bet_won:
                data["successful_bets"] += 1
            data["last_updated"] = datetime.now(timezone.utc).isoformat()
            
            await self._save_json(self.account_status_file, data)
            
            self.logger.info(
                f"Updated stats: Total bets: {data['total_bets_placed']}, "
                f"Successful: {data['successful_bets']}"
            )
        except Exception as e:
            self.logger.error(f"Error updating bet stats: {str(e)}")
            raise

    async def check_target_reached(self) -> bool:
        """
        Check if target amount has been reached asynchronously
        
        Returns:
            bool: True if current balance >= target amount, False otherwise
        """
        try:
            status = await self.get_account_status()
            return status.current_balance >= status.target_amount
        except Exception as e:
            self.logger.error(f"Error checking target: {str(e)}")
            return False

    async def reset_account_stats(self, initial_balance: float = 1.0) -> None:
        """
        Reset account statistics to initial state asynchronously
        
        Args:
            initial_balance: Starting balance for new session
            
        Raises:
            ValueError: If initial_balance is negative
        """
        try:
            if initial_balance < 0:
                raise ValueError(f"Initial balance cannot be negative: {initial_balance}")
                
            self.logger.info(f"Resetting account statistics with initial balance: £{initial_balance}")
            
            initial_status = {
                "current_balance": initial_balance,
                "target_amount": 50000.0,
                "total_bets_placed": 0,
                "successful_bets": 0,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            
            await self._save_json(self.account_status_file, initial_status)
            self.logger.info("Account statistics reset successfully")
        except Exception as e:
            self.logger.error(f"Error resetting account stats: {str(e)}")
            raise

    async def update_target_amount(self, new_target: float) -> None:
        """
        Update the target amount asynchronously
        
        Args:
            new_target: New target amount to set
            
        Raises:
            ValueError: If new_target is not positive
        """
        try:
            if new_target <= 0:
                raise ValueError(f"Target amount must be positive: {new_target}")
                
            self.logger.info(f"Updating target amount to: £{new_target}")
            
            data = await self._load_json(self.account_status_file)
            data["target_amount"] = new_target
            data["last_updated"] = datetime.now(timezone.utc).isoformat()
            
            await self._save_json(self.account_status_file, data)
            self.logger.info("Target amount updated successfully")
        except Exception as e:
            self.logger.error(f"Error updating target amount: {str(e)}")
            raise

    async def get_profit_loss(self) -> float:
        """
        Calculate total profit/loss from initial balance asynchronously
        
        Returns:
            float: Current balance minus initial balance
        """
        try:
            status = await self.get_account_status()
            return status.current_balance - 1.0  # Assuming initial balance was £1
        except Exception as e:
            self.logger.error(f"Error getting profit/loss: {str(e)}")
            return 0.0

    async def get_win_rate(self) -> float:
        """
        Calculate win rate as percentage asynchronously
        
        Returns:
            float: Win rate percentage (0-100)
        """
        try:
            status = await self.get_account_status()
            if status.total_bets_placed == 0:
                return 0.0
            return (status.successful_bets / status.total_bets_placed) * 100.0
        except Exception as e:
            self.logger.error(f"Error calculating win rate: {str(e)}")
            return 0.0