"""
account_repository_improved.py

Improved async repository pattern implementation for account data management.
Handles storage and retrieval of account status and balance.
Updates include:
- Support for configurable initial stake
- More robust error handling
- Consistent logging
- Transaction history tracking
- Better concurrency handling
- Enhanced analytics
"""

import json
import logging
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
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
        
        # Initialize file paths
        self.account_status_file = self.data_dir / 'account_status.json'
        self.transactions_file = self.data_dir / 'account_transactions.json'
        self.analytics_file = self.data_dir / 'account_analytics.json'
        
        # Locks for concurrent access
        self._update_lock = asyncio.Lock()
        
        # Ensure storage is initialized
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        """Initialize storage files if they don't exist (sync operation during init)"""
        # Account status file
        if not self.account_status_file.exists():
            initial_status = {
                "current_balance": 1.0,  # Default £1 starting stake
                "target_amount": 50000.0,
                "total_bets_placed": 0,
                "successful_bets": 0,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            with open(self.account_status_file, 'w') as f:
                json.dump(initial_status, f, indent=2)
        
        # Transactions file
        if not self.transactions_file.exists():
            initial_transactions = {
                "transactions": [],
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            with open(self.transactions_file, 'w') as f:
                json.dump(initial_transactions, f, indent=2)
                
        # Analytics file
        if not self.analytics_file.exists():
            initial_analytics = {
                "daily_balances": {},  # Format: {"YYYY-MM-DD": balance}
                "weekly_performance": {},  # Format: {"YYYY-WW": {"bets": n, "wins": m, "profit": x}}
                "monthly_performance": {},  # Format: {"YYYY-MM": {"bets": n, "wins": m, "profit": x}}
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            with open(self.analytics_file, 'w') as f:
                json.dump(initial_analytics, f, indent=2)

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

    async def update_balance(self, amount_change: float, description: str = "Balance update") -> None:
        """
        Update account balance asynchronously
        
        Args:
            amount_change: Amount to add/subtract from balance (negative for deductions)
            description: Description of the balance change (for transaction history)
            
        Raises:
            ValueError: If resulting balance would be negative
        """
        try:
            # Use lock to prevent race conditions
            async with self._update_lock:
                self.logger.info(f"Updating balance by {amount_change} - {description}")
                
                # Get current data
                data = await self._load_json(self.account_status_file)
                current_balance = data["current_balance"]
                new_balance = current_balance + amount_change
                
                # Validate
                if new_balance < 0:
                    raise ValueError(f"Insufficient funds: {current_balance} + {amount_change} = {new_balance}")
                
                # Update balance
                data["current_balance"] = new_balance
                data["last_updated"] = datetime.now(timezone.utc).isoformat()
                
                # Save updated account status
                await self._save_json(self.account_status_file, data)
                
                # Record transaction
                transaction_id = str(uuid.uuid4())
                transaction = {
                    "id": transaction_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "type": "credit" if amount_change > 0 else "debit",
                    "amount": abs(amount_change),
                    "previous_balance": current_balance,
                    "new_balance": new_balance,
                    "description": description
                }
                
                # Add to transaction history
                transactions = await self._load_json(self.transactions_file)
                transactions["transactions"].append(transaction)
                transactions["last_updated"] = datetime.now(timezone.utc).isoformat()
                await self._save_json(self.transactions_file, transactions)
                
                # Update analytics
                await self._update_analytics(current_balance, new_balance, amount_change > 0)
                
                self.logger.info(f"New balance: £{new_balance} (Transaction ID: {transaction_id})")
                
        except Exception as e:
            self.logger.error(f"Error updating balance: {str(e)}")
            raise

    async def reset_to_starting_stake(self, initial_stake: float = 1.0) -> None:
        """
        Reset account balance to the starting stake
        
        Args:
            initial_stake: Starting stake amount (default: £1)
        """
        try:
            if initial_stake <= 0:
                self.logger.warning(f"Invalid initial stake: {initial_stake}, using 1.0 instead")
                initial_stake = 1.0
                
            self.logger.info(f"Resetting account balance to starting stake (£{initial_stake})")
            
            # Get current balance first
            data = await self._load_json(self.account_status_file)
            current_balance = data["current_balance"]
            
            # Only track this as a transaction if it's different from current balance
            if current_balance != initial_stake:
                # Use the update_balance method to ensure transaction tracking
                # First reset to zero, then add the initial stake
                await self.update_balance(
                    -current_balance, 
                    "Reset account balance to zero"
                )
                await self.update_balance(
                    initial_stake, 
                    "Set initial stake for new cycle"
                )
            else:
                self.logger.info(f"Balance already at initial stake (£{initial_stake})")
        except Exception as e:
            self.logger.error(f"Error resetting to starting stake: {str(e)}")
            raise

    async def update_target_amount(self, target_amount: float) -> None:
        """
        Update the target amount
        
        Args:
            target_amount: New target amount
        """
        try:
            if target_amount <= 0:
                self.logger.warning(f"Invalid target amount: {target_amount}, using 50000.0 instead")
                target_amount = 50000.0
                
            self.logger.info(f"Updating target amount to £{target_amount}")
            
            data = await self._load_json(self.account_status_file)
            data["target_amount"] = target_amount
            data["last_updated"] = datetime.now(timezone.utc).isoformat()
            
            await self._save_json(self.account_status_file, data)
            self.logger.info(f"Target amount updated to £{target_amount}")
        except Exception as e:
            self.logger.error(f"Error updating target amount: {str(e)}")
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
            
    async def _update_analytics(self, previous_balance: float, new_balance: float, is_win: bool = False) -> None:
        """
        Update analytics data
        
        Args:
            previous_balance: Previous account balance
            new_balance: New account balance
            is_win: Whether this was a winning transaction
        """
        try:
            # Get current date components
            now = datetime.now(timezone.utc)
            date_str = now.strftime('%Y-%m-%d')
            week_str = f"{now.strftime('%Y')}-{now.strftime('%V')}"  # Year-WeekNumber
            month_str = now.strftime('%Y-%m')
            
            # Load analytics data
            analytics = await self._load_json(self.analytics_file)
            
            # Update daily balance
            analytics["daily_balances"][date_str] = new_balance
            
            # Update weekly performance
            if week_str not in analytics["weekly_performance"]:
                analytics["weekly_performance"][week_str] = {"bets": 0, "wins": 0, "profit": 0.0}
            
            if is_win:
                analytics["weekly_performance"][week_str]["wins"] += 1
                analytics["weekly_performance"][week_str]["profit"] += (new_balance - previous_balance)
            analytics["weekly_performance"][week_str]["bets"] += 1
            
            # Update monthly performance
            if month_str not in analytics["monthly_performance"]:
                analytics["monthly_performance"][month_str] = {"bets": 0, "wins": 0, "profit": 0.0}
            
            if is_win:
                analytics["monthly_performance"][month_str]["wins"] += 1
                analytics["monthly_performance"][month_str]["profit"] += (new_balance - previous_balance)
            analytics["monthly_performance"][month_str]["bets"] += 1
            
            # Update timestamp
            analytics["last_updated"] = now.isoformat()
            
            # Save updated analytics
            await self._save_json(self.analytics_file, analytics)
            
        except Exception as e:
            self.logger.error(f"Error updating analytics: {str(e)}")
            # Don't raise - analytics updates are non-critical
            
    async def get_transaction_history(self, days: int = 30) -> List[Dict]:
        """
        Get transaction history for the specified period
        
        Args:
            days: Number of days to retrieve (default: 30)
            
        Returns:
            List of transaction records
        """
        try:
            # Calculate cutoff date
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            cutoff_str = cutoff_date.isoformat()
            
            # Load transactions
            transactions = await self._load_json(self.transactions_file)
            
            # Filter by date
            recent_transactions = [
                t for t in transactions["transactions"]
                if t["timestamp"] > cutoff_str
            ]
            
            # Sort by timestamp (newest first)
            sorted_transactions = sorted(
                recent_transactions, 
                key=lambda x: x["timestamp"], 
                reverse=True
            )
            
            return sorted_transactions
            
        except Exception as e:
            self.logger.error(f"Error getting transaction history: {str(e)}")
            return []
            
    async def get_performance_metrics(self, period: str = 'monthly') -> Dict[str, Any]:
        """
        Get performance metrics for analysis
        
        Args:
            period: 'daily', 'weekly', or 'monthly'
            
        Returns:
            Dict containing performance metrics
        """
        try:
            analytics = await self._load_json(self.analytics_file)
            
            if period == 'daily':
                # Return daily balance data
                return {
                    "type": "daily_balance",
                    "data": analytics["daily_balances"]
                }
            elif period == 'weekly':
                # Return weekly performance data
                return {
                    "type": "weekly_performance",
                    "data": analytics["weekly_performance"]
                }
            else:  # Default to monthly
                # Return monthly performance data
                return {
                    "type": "monthly_performance",
                    "data": analytics["monthly_performance"]
                }
                
        except Exception as e:
            self.logger.error(f"Error getting performance metrics: {str(e)}")
            return {"type": "error", "data": {}}
            
    async def backup_data(self) -> bool:
        """
        Create a backup of all account data
        
        Returns:
            True if backup was successful, False otherwise
        """
        try:
            # Create backup directory
            backup_dir = self.data_dir / 'backups'
            backup_dir.mkdir(exist_ok=True)
            
            # Create timestamp for backup
            timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
            
            # Backup each file
            for file_name in ['account_status.json', 'account_transactions.json', 'account_analytics.json']:
                source_file = self.data_dir / file_name
                if source_file.exists():
                    # Read source
                    async with aiofiles.open(source_file, 'r') as f:
                        content = await f.read()
                    
                    # Write to backup
                    backup_file = backup_dir / f"{file_name}.{timestamp}"
                    async with aiofiles.open(backup_file, 'w') as f:
                        await f.write(content)
            
            self.logger.info(f"Account data backed up with timestamp {timestamp}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error backing up account data: {str(e)}")
            return False