"""
betting_ledger.py

Refactored to use event-sourced approach for bet cycle management.
Replaces direct state management with state derived from immutable events.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional
import asyncio

from .event_store import BettingEventStore

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
        
        # Initialize event store
        self.event_store = BettingEventStore(data_dir)
        
        # Transaction lock to prevent race conditions
        self._transaction_lock = asyncio.Lock()

    async def get_ledger(self) -> Dict[str, Any]:
        """Get current ledger data derived from event history"""
        stats = await self.event_store.get_betting_stats()
        
        # Add timestamp
        stats["last_updated"] = datetime.now(timezone.utc).isoformat()
        
        return stats

    async def record_bet_placed(self, bet_details: Dict) -> Dict:
        """
        Record a new bet placement as an event
        
        Args:
            bet_details: Details of the placed bet
            
        Returns:
            Updated ledger data
        """
        try:
            # Use transaction lock to prevent race conditions
            async with self._transaction_lock:
                # Create event data from bet details
                event_data = {
                    "market_id": bet_details.get("market_id"),
                    "event_id": bet_details.get("event_id"),
                    "event_name": bet_details.get("event_name"),
                    "selection_id": bet_details.get("selection_id"),
                    "team_name": bet_details.get("team_name", "Unknown"),
                    "odds": bet_details.get("odds", 0.0),
                    "stake": bet_details.get("stake", 0.0),
                    "timestamp": bet_details.get("timestamp", datetime.now(timezone.utc).isoformat())
                }
                
                # Add bet placement event
                await self.event_store.add_event("BET_PLACED", event_data)
                
                # Get current cycle info
                current_cycle = await self.event_store.get_current_cycle()
                current_bet_in_cycle = await self.event_store.get_current_bet_in_cycle()
                
                self.logger.info(
                    f"Recorded bet placement - Cycle: {current_cycle}, "
                    f"Bet #{current_bet_in_cycle} in cycle, "
                    f"Stake: £{bet_details['stake']}, Odds: {bet_details['odds']}"
                )
                
                # Return updated ledger data
                return await self.get_ledger()
                
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
        Record a bet result as an event
        
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
            # Use transaction lock to prevent race conditions
            async with self._transaction_lock:
                # Get bet details for logging
                market_id = bet_details.get("market_id", "Unknown")
                selection_id = bet_details.get("selection_id", "Unknown")
                team_name = bet_details.get("team_name", "Unknown")
                stake = bet_details.get("stake", 0.0)
                odds = bet_details.get("odds", 0.0)
                gross_profit = bet_details.get("gross_profit", profit + commission)
                
                # Prepare event data
                event_data = {
                    "market_id": market_id,
                    "selection_id": selection_id,
                    "team_name": team_name,
                    "stake": stake,
                    "odds": odds,
                    "new_balance": new_balance
                }
                
                if won:
                    # Add win-specific data
                    event_data.update({
                        "gross_profit": gross_profit,
                        "commission": commission,
                        "net_profit": profit
                    })
                    
                    # Add bet won event
                    await self.event_store.add_event("BET_WON", event_data)
                    
                    self.logger.info(
                        f"Bet WON - Selection: {team_name}, Stake: £{stake}, "
                        f"Odds: {odds}, Gross Profit: £{gross_profit}, "
                        f"Commission: £{commission}, Net Profit: £{profit}"
                    )
                else:
                    # Add bet lost event
                    await self.event_store.add_event("BET_LOST", event_data)
                    
                    self.logger.info(
                        f"Bet LOST - Selection: {team_name}, Lost stake: £{stake}"
                    )
                
                # Get updated cycle information
                current_cycle = await self.event_store.get_current_cycle()
                current_bet_in_cycle = await self.event_store.get_current_bet_in_cycle()
                
                self.logger.info(
                    f"Current cycle: {current_cycle}, "
                    f"Bet in cycle: {current_bet_in_cycle}"
                )
                
                # Return updated ledger data
                return await self.get_ledger()
                
        except Exception as e:
            self.logger.error(f"Error recording bet result: {str(e)}")
            raise

    async def check_target_reached(self, balance: float, target: float) -> bool:
        """
        Check if target amount has been reached and record target reached event if so
        
        Args:
            balance: Current account balance
            target: Target amount
            
        Returns:
            True if target reached, False otherwise
        """
        try:
            if balance >= target:
                # Target reached - record event
                async with self._transaction_lock:
                    event_data = {
                        "balance": balance,
                        "target": target,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    
                    await self.event_store.add_event("TARGET_REACHED", event_data)
                    
                    # Get updated cycle information
                    current_cycle = await self.event_store.get_current_cycle()
                    
                    self.logger.info(
                        f"TARGET REACHED! Final balance: £{balance}, "
                        f"Starting new cycle: {current_cycle}"
                    )
                    
                    return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking target: {str(e)}")
            return False

    async def get_current_cycle_info(self) -> Dict:
        """Get information about the current cycle"""
        try:
            stats = await self.event_store.get_betting_stats()
            
            # Log cycle info for debugging
            self.logger.debug(
                f"Current cycle info - Cycle: {stats['current_cycle']}, "
                f"Bet in cycle: {stats['current_bet_in_cycle']}"
            )
            
            return {
                "current_cycle": stats["current_cycle"],
                "current_bet_in_cycle": stats["current_bet_in_cycle"],
                "total_cycles": stats["total_cycles"],
                "total_bets": stats["total_bets"],
                "total_wins": stats["total_wins"],
                "total_losses": stats["total_losses"],
                "total_money_lost": stats["total_money_lost"],
                "highest_cycle_reached": stats["highest_cycle_reached"],
                "highest_balance": stats["highest_balance"],
                "total_commission_paid": stats["total_commission_paid"]
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
            # Get current ledger information
            ledger = await self.get_ledger()
            
            # Check if we have a previous winning profit to use
            last_winning_profit = await self.event_store.get_last_winning_profit()
            
            if last_winning_profit > 0:
                # We have a previous winning profit, use it regardless of bet cycle
                self.logger.info(f"Next stake calculated as £{last_winning_profit:.2f} based on compound strategy (last_winning_profit)")
                return last_winning_profit
                    
            # Otherwise, use the initial stake
            initial_stake = ledger.get("starting_stake", 1.0)
            self.logger.info(f"Using initial stake: £{initial_stake:.2f} (no previous winning profit)")
            return initial_stake
        
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
            
            async with self._transaction_lock:
                # Reset the event store
                await self.event_store.reset_events(starting_stake)
                
                self.logger.info("Betting ledger reset successfully")
                
                # Return updated ledger data
                return await self.get_ledger()
            
        except Exception as e:
            self.logger.error(f"Error resetting ledger: {str(e)}")
            raise