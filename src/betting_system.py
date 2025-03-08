"""
betting_system_improved.py

Improved betting system that coordinates betting operations using the command pattern.
Handles async coordination between client, repositories, and commands.
Updates include:
- Real result integration instead of simulation
- Improved selection diversity with continuous market checking
- Configurable parameters
- More robust error handling and logging
"""

import logging
import asyncio
from typing import Optional, Dict, List
from datetime import datetime, timezone

from .betfair_client import BetfairClient
from .commands.market_analysis_command import MarketAnalysisCommand
from .commands.place_bet_command import PlaceBetCommand, PlaceBetRequest
from .commands.settle_bet_command import BetSettlementCommand, BetSettlementRequest
from .repositories.bet_repository import BetRepository
from .repositories.account_repository import AccountRepository
from .betting_ledger import BettingLedger
from .config_manager import ConfigManager

class BettingSystem:
    def __init__(
        self,
        betfair_client: BetfairClient,
        bet_repository: BetRepository,
        account_repository: AccountRepository,
        config_manager: ConfigManager
    ):
        self.betfair_client = betfair_client
        self.bet_repository = bet_repository
        self.account_repository = account_repository
        self.betting_ledger = BettingLedger()
        self.config_manager = config_manager
        
        # Load system configuration
        config = self.config_manager.get_config()
        self.dry_run = config.get('system', {}).get('dry_run', True)
        
        # Initialize commands with improved versions
        self.market_analysis = MarketAnalysisCommand(
            betfair_client,
            bet_repository,
            account_repository,
            config_manager
        )
        
        self.place_bet = PlaceBetCommand(
            betfair_client,
            bet_repository,
            account_repository
        )
        
        self.settle_bet = BetSettlementCommand(
            betfair_client,
            bet_repository,
            account_repository,
            config_manager
        )
        
        # Setup logging
        self.logger = logging.getLogger('BettingSystem')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('web/logs/betting_system.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        
        # Track running tasks
        self.tasks = {}
        self._shutdown_event = asyncio.Event()

    async def scan_markets(self) -> Optional[Dict]:
        """
        Scan available markets for betting opportunities
        
        Returns:
            Dict containing betting opportunity if found, None otherwise
        """
        try:
            if await self.bet_repository.has_active_bets():
                self.logger.info("Active bet exists - skipping market scan")
                return None
            
            # Get current account information
            account_status = await self.account_repository.get_account_status()
            
            # Get current cycle info for logging
            cycle_info = await self.betting_ledger.get_current_cycle_info()
            self.logger.info(
                f"Scanning markets - Cycle #{cycle_info['current_cycle']}, "
                f"Bet #{cycle_info['current_bet_in_cycle'] + 1} in cycle, "
                f"Balance: £{account_status.current_balance:.2f}"
            )
            
            # Execute market analysis with polling
            betting_opportunity = await self.market_analysis.execute_with_polling()
            
            if betting_opportunity:
                if self.dry_run:
                    self.logger.info(
                        f"[DRY RUN] Would place bet:\n"
                        f"Market ID: {betting_opportunity['market_id']}\n"
                        f"Selection: {betting_opportunity['team_name']}\n"
                        f"Selection ID: {betting_opportunity['selection_id']}\n"
                        f"Odds: {betting_opportunity['odds']}\n"
                        f"Stake: £{betting_opportunity['stake']}\n"
                        f"Available Volume: £{betting_opportunity['available_volume']}"
                    )
                return betting_opportunity
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error scanning markets: {str(e)}")
            self.logger.exception(e)
            return None

    async def place_bet_order(self, betting_opportunity: Dict) -> Optional[Dict]:
        """
        Place a bet based on identified opportunity
        
        Args:
            betting_opportunity: Dict containing betting opportunity details
            
        Returns:
            Dict containing bet details if successful, None otherwise
        """
        try:
            # Ensure we have all required fields
            if 'event_id' not in betting_opportunity:
                self.logger.warning("Missing event_id in betting opportunity. Using market_id as fallback.")
                betting_opportunity['event_id'] = betting_opportunity['market_id']
                
            if 'event_name' not in betting_opportunity:
                self.logger.warning("Missing event_name in betting opportunity. Using placeholder.")
                betting_opportunity['event_name'] = "Unknown Event"
                
            # Record in ledger before placing bet
            await self.betting_ledger.record_bet_placed(betting_opportunity)
            
            if self.dry_run:
                self.logger.info(
                    f"[DRY RUN] Simulated bet placement: "
                    f"Match: {betting_opportunity['event_name']}, "
                    f"Selection: {betting_opportunity['team_name']}, "
                    f"Stake: £{betting_opportunity['stake']}, "
                    f"Odds: {betting_opportunity['odds']}"
                )
                
                # For dry run, explicitly record bet in repository to mark it as active
                await self.bet_repository.record_bet_placement(betting_opportunity)
                self.logger.info(f"[DRY RUN] Bet recorded as active in repository")
                
                return betting_opportunity
                
            # Place real bet
            request = PlaceBetRequest(
                market_id=betting_opportunity['market_id'],
                event_id=betting_opportunity['event_id'],
                event_name=betting_opportunity['event_name'],
                selection_id=betting_opportunity['selection_id'],
                odds=betting_opportunity['odds'],
                stake=betting_opportunity['stake']
            )
            
            bet_details = await self.place_bet.execute(request)
            if bet_details:
                self.logger.info(
                    f"Successfully placed bet:\n"
                    f"Match: {betting_opportunity['event_name']}\n"
                    f"Selection: {betting_opportunity['team_name']}\n"
                    f"Stake: £{request.stake}\n"
                    f"Odds: {request.odds}"
                )
            return bet_details
                
        except Exception as e:
            self.logger.error(f"Error during bet placement: {str(e)}")
            self.logger.exception(e)
            return None

    async def settle_bet_order(self, market_id: str, forced_settlement: bool = False, force_won: bool = False, force_profit: float = 0.0) -> Optional[Dict]:
        """
        Settle an existing bet asynchronously
        
        Args:
            market_id: Betfair market ID
            forced_settlement: Whether to force a settlement (for dry run or testing)
            force_won: Whether the forced settlement should be a win
            force_profit: Profit amount for forced winning settlement
            
        Returns:
            Dict containing updated bet details if successful, None otherwise
        """
        try:
            request = BetSettlementRequest(
                market_id=market_id,
                forced_settlement=forced_settlement,
                force_won=force_won,
                force_profit=force_profit
            )
            
            settled_bet = await self.settle_bet.execute(request)
            if not settled_bet:
                self.logger.error(f"Failed to settle bet for market {market_id}")
                return None
                
            # Get updated account balance after settlement
            account_status = await self.account_repository.get_account_status()
            
            # Record result in ledger
            await self.betting_ledger.record_bet_result(
                settled_bet, 
                settled_bet.get('won', False), 
                settled_bet.get('profit', 0.0), 
                account_status.current_balance
            )
            
            # Check if target reached
            if settled_bet.get('won', False) and await self.betting_ledger.check_target_reached(
                account_status.current_balance, account_status.target_amount
            ):
                # Reset to starting stake for new cycle if target reached
                initial_stake = await self.config_manager.get_initial_stake()
                await self.account_repository.reset_to_starting_stake(initial_stake)
                self.logger.info(f"Target reached! Reset to starting stake (£{initial_stake}) for new cycle.")
            elif not settled_bet.get('won', False):
                # Reset to starting stake after a loss
                initial_stake = await self.config_manager.get_initial_stake()
                await self.account_repository.reset_to_starting_stake(initial_stake)
                self.logger.info(f"Bet lost. Reset to starting stake (£{initial_stake}) for new cycle.")
            
            self.logger.info(
                f"Successfully settled bet:\n"
                f"Match: {settled_bet.get('event_name', 'Unknown Event')}\n"
                f"Selection: {settled_bet.get('team_name', 'Unknown Team')}\n"
                f"Won: {settled_bet.get('won', False)}\n"
                f"Profit: £{settled_bet.get('profit', 0.0)}\n"
                f"New Balance: £{account_status.current_balance}"
            )
            
            return settled_bet
                
        except Exception as e:
            self.logger.error(f"Error during bet settlement: {str(e)}")
            self.logger.exception(e)
            return None

    async def check_for_results(self) -> List[Dict]:
        """
        Check for results of active bets
        
        Returns:
            List of settled bets
        """
        try:
            # Run the settlement checker
            settled_bets = await self.settle_bet.check_active_bets()
            
            if settled_bets:
                self.logger.info(f"Settled {len(settled_bets)} bets")
                
            return settled_bets
            
        except Exception as e:
            self.logger.error(f"Error checking for results: {str(e)}")
            self.logger.exception(e)
            return []

    async def start_result_poller(self) -> asyncio.Task:
        """
        Start a background task to continuously poll for bet results
        
        Returns:
            asyncio.Task for the result poller
        """
        if 'result_poller' in self.tasks and not self.tasks['result_poller'].done():
            self.logger.info("Result poller already running")
            return self.tasks['result_poller']
        
        self.logger.info("Starting result poller task")
        
        async def poller_task():
            while not self._shutdown_event.is_set():
                try:
                    # Only run if there are active bets
                    if await self.bet_repository.has_active_bets():
                        # Run the settlement poller
                        await self.settle_bet.execute_settlement_poller()
                    
                    # Check if we should continue or exit
                    if self._shutdown_event.is_set():
                        break
                    
                    # Wait a bit before checking again
                    await asyncio.sleep(60)  # Check every minute if there are new active bets
                    
                except asyncio.CancelledError:
                    self.logger.info("Result poller task cancelled")
                    break
                except Exception as e:
                    self.logger.error(f"Error in result poller: {str(e)}")
                    self.logger.exception(e)
                    await asyncio.sleep(60)  # Wait before retrying
        
        task = asyncio.create_task(poller_task())
        self.tasks['result_poller'] = task
        return task

    async def shutdown(self) -> None:
        """Shutdown the betting system gracefully"""
        self.logger.info("Shutting down betting system")
        
        # Signal shutdown to all tasks
        self._shutdown_event.set()
        
        # Cancel all running tasks
        for name, task in self.tasks.items():
            if not task.done():
                self.logger.info(f"Cancelling {name} task")
                task.cancel()
                
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Close the Betfair client
        await self.betfair_client.close_session()
        
        self.logger.info("Betting system shutdown complete")

    async def get_active_bets(self) -> List[Dict]:
        """Get all currently active bets asynchronously"""
        return await self.bet_repository.get_active_bets()

    async def get_settled_bets(self) -> List[Dict]:
        """Get all settled bets asynchronously"""
        return await self.bet_repository.get_settled_bets()

    async def get_account_status(self) -> Dict:
        """Get current account status asynchronously"""
        status = await self.account_repository.get_account_status()
        win_rate = await self.account_repository.get_win_rate()
        profit_loss = await self.account_repository.get_profit_loss()
        
        # Get cycle information from ledger
        cycle_info = await self.betting_ledger.get_current_cycle_info()
        
        return {
            "current_balance": status.current_balance,
            "target_amount": status.target_amount,
            "total_bets_placed": status.total_bets_placed,
            "successful_bets": status.successful_bets,
            "win_rate": win_rate,
            "profit_loss": profit_loss,
            "current_cycle": cycle_info["current_cycle"],
            "current_bet_in_cycle": cycle_info["current_bet_in_cycle"],
            "total_cycles": cycle_info["total_cycles"],
            "total_money_lost": cycle_info["total_money_lost"]
        }

    async def get_ledger_info(self) -> Dict:
        """Get comprehensive ledger information"""
        return await self.betting_ledger.get_ledger()