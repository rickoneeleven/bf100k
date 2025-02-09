# File: src/repositories/bet_repository.py

"""
bet_repository.py

Repository pattern implementation for bet data management.
Handles storage and retrieval of bet records.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

class BetRepository:
    def __init__(self, data_dir: str = 'web/data/betting'):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup logging
        self.logger = logging.getLogger('BetRepository')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('web/logs/repositories.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        
        # Initialize file paths
        self.active_bets_file = self.data_dir / 'active_bets.json'
        self.settled_bets_file = self.data_dir / 'settled_bets.json'
        
        self._initialize_storage()

    def _initialize_storage(self) -> None:
        """Initialize storage files if they don't exist"""
        # Active bets structure
        if not self.active_bets_file.exists():
            self._save_json(self.active_bets_file, {
                "bets": [],
                "last_updated": datetime.now(timezone.utc).isoformat()
            })
        
        # Settled bets structure
        if not self.settled_bets_file.exists():
            self._save_json(self.settled_bets_file, {
                "bets": [],
                "last_updated": datetime.now(timezone.utc).isoformat()
            })

    def _save_json(self, file_path: Path, data: Dict) -> None:
        """Save data to JSON file"""
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)

    def _load_json(self, file_path: Path) -> Dict:
        """Load data from JSON file"""
        with open(file_path, 'r') as f:
            return json.load(f)

    def has_active_bets(self) -> bool:
        """Check if there are any active bets"""
        active_bets = self._load_json(self.active_bets_file)
        return len(active_bets["bets"]) > 0

    def get_active_bets(self) -> List[Dict]:
        """Retrieve all active bets"""
        active_bets = self._load_json(self.active_bets_file)
        return active_bets["bets"]

    def get_settled_bets(self) -> List[Dict]:
        """Retrieve all settled bets"""
        settled_bets = self._load_json(self.settled_bets_file)
        return settled_bets["bets"]

    def get_bet_by_market_id(self, market_id: str) -> Optional[Dict]:
        """Retrieve specific bet by market ID"""
        # Check active bets first
        active_bets = self._load_json(self.active_bets_file)
        for bet in active_bets["bets"]:
            if bet["market_id"] == market_id:
                return bet
        
        # Check settled bets if not found in active
        settled_bets = self._load_json(self.settled_bets_file)
        for bet in settled_bets["bets"]:
            if bet["market_id"] == market_id:
                return bet
        
        return None

    def record_bet_placement(self, bet_details: Dict) -> None:
        """Record a new bet placement"""
        self.logger.info(f"Recording bet placement for market {bet_details['market_id']}")
        
        active_bets = self._load_json(self.active_bets_file)
        
        # Verify no duplicate market IDs
        if any(bet["market_id"] == bet_details["market_id"] for bet in active_bets["bets"]):
            raise ValueError(f"Bet already exists for market {bet_details['market_id']}")
        
        # Add new bet
        active_bets["bets"].append(bet_details)
        active_bets["last_updated"] = datetime.now(timezone.utc).isoformat()
        
        self._save_json(self.active_bets_file, active_bets)
        self.logger.info(f"Successfully recorded bet placement")

    def record_bet_settlement(self, bet_details: Dict, won: bool, profit: float) -> None:
        """Record settlement of a bet"""
        self.logger.info(f"Recording bet settlement for market {bet_details['market_id']}")
        
        # Load both files
        active_bets = self._load_json(self.active_bets_file)
        settled_bets = self._load_json(self.settled_bets_file)
        
        # Remove bet from active bets
        active_bets["bets"] = [
            bet for bet in active_bets["bets"]
            if bet["market_id"] != bet_details["market_id"]
        ]
        active_bets["last_updated"] = datetime.now(timezone.utc).isoformat()
        
        # Add settlement details
        bet_details["settlement_time"] = datetime.now(timezone.utc).isoformat()
        bet_details["won"] = won
        bet_details["profit"] = profit
        
        # Add to settled bets
        settled_bets["bets"].append(bet_details)
        settled_bets["last_updated"] = datetime.now(timezone.utc).isoformat()
        
        # Save both files
        self._save_json(self.active_bets_file, active_bets)
        self._save_json(self.settled_bets_file, settled_bets)
        
        self.logger.info(
            f"Successfully recorded bet settlement: "
            f"Won: {won}, Profit: £{profit}"
        )