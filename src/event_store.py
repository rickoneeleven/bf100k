"""
event_store.py

Implements an event-sourced approach to betting system state management.
Stores events as immutable records and provides state derivation functions.
"""

import json
import logging
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
import aiofiles

class BettingEventStore:
    """
    Event store for betting events with derived state calculations.
    """
    
    def __init__(self, data_dir: str = 'web/data/betting'):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Event store file
        self.events_file = self.data_dir / 'betting_events.json'
        
        # Lock for concurrent access
        self._lock = asyncio.Lock()
        
        # Setup logging
        self.logger = logging.getLogger('BettingEventStore')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('web/logs/event_store.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        
        # Initialize storage
        self._ensure_store_exists()
    
    def _ensure_store_exists(self) -> None:
        """Initialize event store file if it doesn't exist"""
        if not self.events_file.exists():
            initial_data = {
                "events": [],
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            with open(self.events_file, 'w') as f:
                json.dump(initial_data, f, indent=2)
            self.logger.info(f"Created new event store at {self.events_file}")
    
    async def _load_events(self) -> List[Dict[str, Any]]:
        """Load all events from the event store"""
        try:
            async with aiofiles.open(self.events_file, 'r') as f:
                content = await f.read()
                data = json.loads(content)
                return data.get("events", [])
        except Exception as e:
            self.logger.error(f"Error loading events: {str(e)}")
            return []
    
    async def _save_events(self, events: List[Dict[str, Any]]) -> None:
        """Save events to the event store"""
        try:
            data = {
                "events": events,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            async with aiofiles.open(self.events_file, 'w') as f:
                await f.write(json.dumps(data, indent=2))
        except Exception as e:
            self.logger.error(f"Error saving events: {str(e)}")
            raise
    
    async def add_event(self, event_type: str, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add a new event to the event store
        
        Args:
            event_type: Type of event (e.g., 'BET_PLACED', 'BET_WON', 'BET_LOST')
            event_data: Event data payload
            
        Returns:
            The complete event record
        """
        async with self._lock:
            # Create event record
            event = {
                "id": str(len(await self._load_events()) + 1),  # Simple incrementing ID
                "type": event_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": event_data
            }
            
            # Load existing events
            events = await self._load_events()
            
            # Append new event
            events.append(event)
            
            # Save updated events
            await self._save_events(events)
            
            self.logger.info(f"Added event: {event_type} - {event['id']}")
            
            return event
    
    async def get_current_cycle(self) -> int:
        """
        Calculate the current cycle number based on event history.
        Each cycle ends with a BET_LOST event or a TARGET_REACHED event.
        
        Returns:
            Current cycle number (starting from 1)
        """
        events = await self._load_events()
        
        # If no events, we're in cycle 1
        if not events:
            return 1
        
        # Count completed cycles (each loss or target reached ends a cycle)
        completed_cycles = 0
        for event in events:
            if event["type"] in ["BET_LOST", "TARGET_REACHED"]:
                completed_cycles += 1
        
        # Current cycle is the number of completed cycles plus 1
        return completed_cycles + 1
    
    async def get_current_bet_in_cycle(self) -> int:
        """
        Calculate the current bet number in the current cycle.
        This resets to 0 after each BET_LOST or TARGET_REACHED event.
        
        Returns:
            Current bet number in cycle (starting from 0)
        """
        events = await self._load_events()
        
        if not events:
            return 0
        
        # Start from the end and find the last cycle reset
        current_bet = 0
        
        # Iterate in reverse to find the most recent cycle reset
        for event in reversed(events):
            if event["type"] in ["BET_LOST", "TARGET_REACHED"]:
                break
            elif event["type"] == "BET_PLACED":
                current_bet += 1
        
        return current_bet
    
    async def get_last_winning_profit(self) -> float:
        """
        Get the profit from the last winning bet for compound betting strategy.
        Resets after a loss or target reached event.
        
        Returns:
            Last winning profit amount or 0 if none
        """
        events = await self._load_events()
        
        if not events:
            return 0.0
        
        # Start from the end and find the last win before any cycle reset
        for event in reversed(events):
            if event["type"] in ["BET_LOST", "TARGET_REACHED"]:
                # If we hit a cycle reset, there's no previous winning profit
                return 0.0
            elif event["type"] == "BET_WON":
                # Return the net profit from the last win (after commission)
                return event["data"].get("net_profit", 0.0)
        
        return 0.0
    
    async def get_betting_stats(self) -> Dict[str, Any]:
        """
        Calculate comprehensive betting statistics from event history
        
        Returns:
            Dictionary containing various betting statistics
        """
        events = await self._load_events()
        
        # Initialize stats
        stats = {
            "current_cycle": 1,
            "current_bet_in_cycle": 0,
            "total_cycles": 0,
            "total_bets": 0,
            "total_wins": 0,
            "total_losses": 0,
            "total_money_lost": 0.0,
            "highest_cycle_reached": 1,
            "highest_balance": 1.0,
            "total_commission_paid": 0.0,
            "last_winning_profit": 0.0,
            "starting_stake": 1.0,
            "cycle_history": [],
        }
        
        if not events:
            return stats
        
        # Calculate stats from events
        current_cycle = 1
        current_bet_in_cycle = 0
        cycle_start_time = events[0]["timestamp"]
        current_balance = 1.0
        cycle_bets = []
        
        for event in events:
            event_type = event["type"]
            event_data = event["data"]
            
            if event_type == "SYSTEM_RESET":
                # Reset stats on system reset
                stats["starting_stake"] = event_data.get("initial_stake", 1.0)
                current_balance = stats["starting_stake"]
                stats["highest_balance"] = current_balance
                current_cycle = 1
                current_bet_in_cycle = 0
                stats["total_cycles"] = 0
                stats["total_bets"] = 0
                stats["total_wins"] = 0
                stats["total_losses"] = 0
                stats["total_money_lost"] = 0.0
                stats["highest_cycle_reached"] = 1
                stats["total_commission_paid"] = 0.0
                stats["last_winning_profit"] = 0.0
                stats["cycle_history"] = []
                cycle_start_time = event["timestamp"]
                cycle_bets = []
            
            elif event_type == "BET_PLACED":
                stats["total_bets"] += 1
                current_bet_in_cycle += 1
                cycle_bets.append(event)
            
            elif event_type == "BET_WON":
                stats["total_wins"] += 1
                stats["last_winning_profit"] = event_data.get("net_profit", 0.0)
                stats["total_commission_paid"] += event_data.get("commission", 0.0)
                
                # Update balance
                if "stake" in event_data and "net_profit" in event_data:
                    current_balance += event_data["net_profit"]
                elif "new_balance" in event_data:
                    current_balance = event_data["new_balance"]
                
                # Update highest balance if needed
                if current_balance > stats["highest_balance"]:
                    stats["highest_balance"] = current_balance
            
            elif event_type == "BET_LOST":
                stats["total_losses"] += 1
                stats["total_money_lost"] += event_data.get("stake", 0.0)
                
                # Record completed cycle
                cycle_record = {
                    "cycle_number": current_cycle,
                    "bets_in_cycle": current_bet_in_cycle,
                    "start_time": cycle_start_time,
                    "end_time": event["timestamp"],
                    "final_stake": event_data.get("stake", 0.0),
                    "result": "Lost"
                }
                stats["cycle_history"].append(cycle_record)
                
                # Increment cycle counter
                stats["total_cycles"] += 1
                current_cycle += 1
                current_bet_in_cycle = 0
                cycle_start_time = event["timestamp"]
                cycle_bets = []
                
                # Update highest cycle if needed
                if current_cycle > stats["highest_cycle_reached"]:
                    stats["highest_cycle_reached"] = current_cycle
                
                # Reset last winning profit
                stats["last_winning_profit"] = 0.0
            
            elif event_type == "TARGET_REACHED":
                # Record completed cycle
                cycle_record = {
                    "cycle_number": current_cycle,
                    "bets_in_cycle": current_bet_in_cycle,
                    "start_time": cycle_start_time,
                    "end_time": event["timestamp"],
                    "final_balance": event_data.get("balance", 0.0),
                    "result": "Target Reached"
                }
                stats["cycle_history"].append(cycle_record)
                
                # Increment cycle counter
                stats["total_cycles"] += 1
                current_cycle += 1
                current_bet_in_cycle = 0
                cycle_start_time = event["timestamp"]
                cycle_bets = []
                
                # Update highest cycle if needed
                if current_cycle > stats["highest_cycle_reached"]:
                    stats["highest_cycle_reached"] = current_cycle
                
                # Reset last winning profit
                stats["last_winning_profit"] = 0.0
        
        # Set current cycle state
        stats["current_cycle"] = current_cycle
        stats["current_bet_in_cycle"] = current_bet_in_cycle
        
        return stats
    
    async def reset_events(self, initial_stake: float = 1.0) -> None:
        """
        Reset the event store to initial state
        
        Args:
            initial_stake: Initial stake amount for new betting session
        """
        async with self._lock:
            reset_event = {
                "id": "1",
                "type": "SYSTEM_RESET",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": {
                    "initial_stake": initial_stake,
                    "reason": "Manual reset"
                }
            }
            
            # Reset with just the reset event
            await self._save_events([reset_event])
            
            self.logger.info(f"Event store reset with initial stake: £{initial_stake}")