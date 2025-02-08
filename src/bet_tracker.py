"""
bet_tracker.py

Handles bet tracking and market analysis for the compound betting system.
Manages active bets, settled bets, and account status while implementing
the core betting strategy logic.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

class BetTracker:
    def __init__(self, data_dir: str = 'web/data/betting'):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup logging
        self.logger = logging.getLogger('BetTracker')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('web/logs/bet_tracker.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        
        # Initialize or load betting data
        self.active_bets_file = self.data_dir / 'active_bets.json'
        self.settled_bets_file = self.data_dir / 'settled_bets.json'
        self.account_status_file = self.data_dir / 'account_status.json'
        
        self._initialize_data_files()

    def _initialize_data_files(self):
        """Initialize betting data files if they don't exist"""
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
        
        # Account status structure
        if not self.account_status_file.exists():
            self._save_json(self.account_status_file, {
                "current_balance": 0.0,
                "target_amount": 50000.0,
                "total_bets_placed": 0,
                "successful_bets": 0,
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

    def check_market_criteria(self, odds: float, available_volume: float, required_stake: float) -> Tuple[bool, str]:
        """
        Check if market meets betting criteria
        Returns: (meets_criteria: bool, reason: str)
        """
        if odds < 3.0 or odds > 4.0:
            return False, f"Odds {odds} outside target range (3.0-4.0)"
            
        if available_volume < required_stake * 1.1:
            return False, f"Insufficient liquidity: {available_volume} < {required_stake * 1.1}"
            
        return True, "Market meets criteria"

    def analyze_market_for_betting(self, market_data: Dict, current_balance: float) -> Optional[Dict]:
        """
        Analyze market for potential betting opportunities
        Returns bet details if criteria met, None otherwise
        """
        self.logger.info(f"Analyzing market {market_data.get('marketId')} for betting opportunity")
        
        # Skip if market is in-play
        if market_data.get('inplay'):
            self.logger.info("Market is in-play - skipping")
            return None
            
        # Check for active bets
        if self.has_active_bets():
            self.logger.info("Active bet exists - skipping market analysis")
            return None
            
        # Analyze each runner (selection) in the market
        for runner in market_data.get('runners', []):
            ex = runner.get('ex', {})
            available_to_back = ex.get('availableToBack', [])
            
            if not available_to_back:
                continue
                
            # Get best back price and size
            best_price = available_to_back[0].get('price')
            available_size = available_to_back[0].get('size')
            
            # Check market criteria
            meets_criteria, reason = self.check_market_criteria(
                best_price, 
                available_size,
                current_balance
            )
            
            if meets_criteria:
                return {
                    "market_id": market_data.get('marketId'),
                    "selection_id": runner.get('selectionId'),
                    "odds": best_price,
                    "stake": current_balance,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            else:
                self.logger.info(f"Market criteria not met: {reason}")
                
        return None

    def record_bet_placement(self, bet_details: Dict) -> None:
        """Record a new bet placement"""
        # Update active bets
        active_bets = self._load_json(self.active_bets_file)
        active_bets["bets"].append(bet_details)
        active_bets["last_updated"] = datetime.now(timezone.utc).isoformat()
        self._save_json(self.active_bets_file, active_bets)
        
        # Update account status
        account_status = self._load_json(self.account_status_file)
        account_status["current_balance"] -= bet_details["stake"]
        account_status["total_bets_placed"] += 1
        account_status["last_updated"] = datetime.now(timezone.utc).isoformat()
        self._save_json(self.account_status_file, account_status)
        
        self.logger.info(f"Recorded bet placement: Market ID {bet_details['market_id']}")

    def record_bet_settlement(self, bet_details: Dict, won: bool, profit: float) -> None:
        """Record settlement of a bet"""
        # Move bet from active to settled
        active_bets = self._load_json(self.active_bets_file)
        settled_bets = self._load_json(self.settled_bets_file)
        
        # Find and remove bet from active bets
        active_bets["bets"] = [b for b in active_bets["bets"] 
                              if b["market_id"] != bet_details["market_id"]]
        active_bets["last_updated"] = datetime.now(timezone.utc).isoformat()
        
        # Add settlement details and move to settled bets
        bet_details["settlement_time"] = datetime.now(timezone.utc).isoformat()
        bet_details["won"] = won
        bet_details["profit"] = profit
        settled_bets["bets"].append(bet_details)
        settled_bets["last_updated"] = datetime.now(timezone.utc).isoformat()
        
        # Update account status
        account_status = self._load_json(self.account_status_file)
        if won:
            account_status["successful_bets"] += 1
            account_status["current_balance"] += bet_details["stake"] + profit
        account_status["last_updated"] = datetime.now(timezone.utc).isoformat()
        
        # Save all updates
        self._save_json(self.active_bets_file, active_bets)
        self._save_json(self.settled_bets_file, settled_bets)
        self._save_json(self.account_status_file, account_status)
        
        self.logger.info(
            f"Recorded bet settlement: Market ID {bet_details['market_id']}, "
            f"Won: {won}, Profit: {profit}"
        )