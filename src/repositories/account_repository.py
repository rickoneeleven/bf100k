"""
account_repository.py

Repository pattern implementation for account data management.
Handles storage and retrieval of account status and balance.
"""

import json
import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

@dataclass
class AccountStatus:
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
        
        self._initialize_storage()

    def _initialize_storage(self) -> None:
        """Initialize storage file if it doesn't exist"""
        if not self.account_status_file.exists():
            initial_status = {
                "current_balance": 0.0,
                "target_amount": 50000.0,
                "total_bets_placed": 0,
                "successful_bets": 0,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            self._save_json(self.account_status_file, initial_status)

    def _save_json(self, file_path: Path, data: Dict) -> None:
        """Save data to JSON file"""
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)

    def _load_json(self, file_path: Path) -> Dict:
        """Load data from JSON file"""
        with open(file_path, 'r') as f:
            return json.load(f)

    def get_account_status(self) -> AccountStatus:
        """Get current account status"""
        data = self._load_json(self.account_status_file)
        return AccountStatus(**data)

    def update_balance(self, amount_change: float) -> None:
        """
        Update account balance
        
        Args: