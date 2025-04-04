"""
main.py

Entry point for the betting system with simplified flow and command-line interface.
Updated to use the new config file location and enhanced active bet information.
Enhanced to properly handle canceled bets in the updater task.
"""

import os
import asyncio
import signal
import logging
import select
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone
from typing import Dict, Any

from .betting_service import BettingService
from .betfair_client import BetfairClient
from .betting_state_manager import BettingStateManager
from .config_manager import ConfigManager
from .log_manager import LogManager

# Global variables for shutdown control
shutdown_event = None

class CommandHandler:
    """Handles command-line input and operations."""
    
    def __init__(self, betting_service: BettingService, state_manager: BettingStateManager, config_manager: ConfigManager, betting_system=None):
        self.betting_service = betting_service
        self.state_manager = state_manager
        self.config_manager = config_manager
        self.betting_system = betting_system  # Add betting_system reference
        self.should_exit = False
        self.logger = logging.getLogger('CommandHandler')
        
    async def handle_command(self, command: str) -> None:
        """Process a command from user input."""
        parts = command.strip().split()
        if not parts:
            await self.cmd_status()
            return
            
        cmd = parts[0].lower()
        args = parts[1:]
        
        if cmd in ['help', 'h', '?']:
            await self.cmd_help()
        elif cmd in ['status', 's']:
            await self.cmd_status()
        elif cmd in ['bet', 'b']:
            await self.cmd_bet_details()
        elif cmd in ['history', 'hist']:
            await self.cmd_history()
        elif cmd in ['odds', 'o']:
            await self.cmd_odds(*args)
        elif cmd in ['cancel', 'c']:  # Add the cancel command
            await self.cmd_cancel_bet()
        elif cmd in ['reset', 'r']:
            await self.cmd_reset(*args)
        elif cmd in ['quit', 'exit', 'q']:
            await self.cmd_quit()
        else:
            print(f"Unknown command: {cmd}")
            print("Type 'help' for a list of available commands.")
            
    async def cmd_cancel_bet(self) -> None:
        """Cancel the current active bet (dry run mode only)"""
        # Check if in dry run mode
        config = self.config_manager.get_config()
        dry_run = config.get('system', {}).get('dry_run', True)
        
        if not dry_run:
            print("\nERROR: Cancel bet command can only be used in dry run mode")
            return
            
        # Get active bet
        active_bet = self.state_manager.get_active_bet()
        
        if not active_bet:
            print("\nNo active bet to cancel")
            return
            
        print("\n" + "="*75)
        print("CANCELING ACTIVE BET")
        print("="*75)
        
        # Display bet details being canceled
        event_name = active_bet.get('event_name', 'Unknown Event')
        team_name = active_bet.get('team_name', 'Unknown')
        odds = active_bet.get('odds', 0.0)
        stake = active_bet.get('stake', 0.0)
        
        print(f"Event: {event_name}")
        print(f"Selection: {team_name} @ {odds}")
        print(f"Stake: Â£{stake:.2f}")
        
        # Ask for confirmation
        print("\nAre you sure you want to cancel this bet?")
        print("Type 'yes' to confirm or anything else to cancel.")
        
        confirm = input("> ").strip().lower()
        if confirm != 'yes':
            print("Bet cancellation aborted.")
            return
        
        # Perform the cancellation
        
        # 1. Restore the stake (add back to balance)
        self.state_manager.update_balance(stake, "Bet cancellation - stake refund")
        
        # 2. Clear the active bet
        self.state_manager.reset_active_bet()
        
        # 3. Save updated state
        print("\nBet successfully canceled. System is ready to find a new bet.")
        print(f"Â£{stake:.2f} has been returned to your balance.")
        print("="*75 + "\n")
    
    async def cmd_help(self) -> None:
        """Display help information."""
        print("\n=== Available Commands ===")
        print("help, h, ?      - Show this help message")
        print("status, s       - Show current betting system status")
        print("bet, b          - Show details of active bet")
        print("history, hist   - Show betting history")
        print("odds [min max]  - View or change target odds range")
        print("reset [stake]   - Reset the betting system with optional stake")
        print("quit, exit, q   - Exit the application")
        print("========================\n")
    
    async def cmd_status(self) -> None:
        """Display current system status."""
        stats = self.state_manager.get_stats_summary()
        
        print("\n" + "="*60)
        print("BETTING SYSTEM STATUS SUMMARY")
        print("="*60)
        print(f"Current Cycle: #{stats['current_cycle']}")
        print(f"Current Bet in Cycle: #{stats['current_bet_in_cycle']}")
        print(f"Current Balance: Â£{stats['current_balance']:.2f}")
        print(f"Next Bet Stake: Â£{stats['next_stake']:.2f}")
        print(f"Target Amount: Â£{stats['target_amount']:.2f}")
        print(f"Total Cycles Completed: {stats['total_cycles']}")
        print(f"Total Bets Placed: {stats['total_bets_placed']}")
        print(f"Successful Bets: {stats['total_wins']}")
        print(f"Win Rate: {stats['win_rate']:.1f}%")
        print(f"Total Money Lost: Â£{stats['total_money_lost']:.2f}")
        print(f"Total Commission Paid: Â£{stats['total_commission_paid']:.2f}")
        print(f"Highest Balance Reached: Â£{stats['highest_balance']:.2f}")
        
        # Show current configuration
        config = self.config_manager.get_config()
        betting_config = config.get('betting', {})
        min_odds = betting_config.get('min_odds', 3.0)
        max_odds = betting_config.get('max_odds', 4.0)
        
        print("\nCurrent Configuration:")
        print(f"Mode: {'DRY RUN' if config.get('system', {}).get('dry_run', True) else 'LIVE'}")
        print(f"Target Odds Range: {min_odds} - {max_odds}")
        print(f"Initial Stake: Â£{betting_config.get('initial_stake', 1.0):.2f}")
        print("="*60 + "\n")
    
    async def cmd_bet_details(self) -> None:
        """Display details of current active bet."""
        active_bet = self.state_manager.get_active_bet()
        
        if not active_bet:
            print("\nNo active bet currently placed.")
            return
            
        print("\n" + "="*75)
        print("ACTIVE BET DETAILS")
        print("="*75)
        
        # Get enhanced data if betting system is available
        enhanced_data = None
        if self.betting_system:
            enhanced_bets = await self.betting_system.get_active_bet_details()
            if enhanced_bets and len(enhanced_bets) > 0:
                enhanced_data = enhanced_bets[0]
        
        # Use enhanced data if available, otherwise fall back to basic data
        display_data = enhanced_data if enhanced_data else active_bet
        
        # Basic details
        print(f"Market ID: {display_data.get('market_id')}")
        print(f"Event: {display_data.get('event_name', 'Unknown Event')}")
        print(f"Cycle #{display_data.get('cycle_number', '?')}, Bet #{display_data.get('bet_in_cycle', '?')} in cycle")
        print(f"Selection: {display_data.get('team_name', 'Unknown')} @ {display_data.get('odds', 0.0)}")
        print(f"Selection ID: {display_data.get('selection_id')}")
        print(f"Stake: Â£{display_data.get('stake', 0.0):.2f}")
        
        # Market start time
        market_start_time = display_data.get('market_start_time')
        if market_start_time:
            try:
                start_dt = datetime.fromisoformat(market_start_time.replace('Z', '+00:00'))
                formatted_time = start_dt.strftime('%Y-%m-%d %H:%M:%S')
                print(f"Kick Off Time: {formatted_time}")
            except:
                print(f"Kick Off Time: {market_start_time}")
        
        # Enhanced market data if available
        if enhanced_data and 'current_market' in enhanced_data:
            market_info = enhanced_data['current_market']
            
            # In-play status
            is_inplay = market_info.get('inplay', False)
            market_status = market_info.get('status', 'Unknown')
            print(f"In Play Status: {market_status} {'(In Play)' if is_inplay else ''}")
            
            # Current odds
            runners = market_info.get('runners', [])
            if runners:
                # Sort runners by sortPriority
                sorted_runners = sorted(runners, key=lambda r: r.get('sortPriority', 999))
                
                print("\nCurrent Market Odds:")
                for runner in sorted_runners:
                    selection_id = runner.get('selectionId')
                    team_name = runner.get('teamName', runner.get('runnerName', 'Unknown'))
                    
                    # Get current best back price
                    back_prices = runner.get('ex', {}).get('availableToBack', [])
                    current_odds = back_prices[0].get('price', 0.0) if back_prices else 0.0
                    
                    # Mark our selection
                    is_our_selection = selection_id == display_data.get('selection_id')
                    selection_marker = " â OUR BET" if is_our_selection else ""
                    
                    print(f"  {team_name}: {current_odds}{selection_marker}")
        
        # Placement time
        placement_time = display_data.get('timestamp')
        if placement_time:
            try:
                dt = datetime.fromisoformat(placement_time)
                formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S')
                print(f"\nBet Placed: {formatted_time}")
            except:
                print(f"\nBet Placed: {placement_time}")
        
        print("="*75 + "\n")
    
    async def cmd_history(self, limit: int = 10) -> None:
        """Display betting history."""
        try:
            limit = int(limit)
        except:
            limit = 10
            
        bets = self.state_manager.get_bet_history(limit)
        
        if not bets:
            print("\nNo settled bets found.")
            return
            
        print("\n" + "="*75)
        print(f"SETTLED BET HISTORY (Last {len(bets)} bets)")
        print("="*75)
        
        total_won = 0
        total_lost = 0
        total_commission = 0.0
        
        for bet in bets:
            settlement_time = bet.get('settlement_time', 'Unknown')
            try:
                dt = datetime.fromisoformat(settlement_time)
                formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S')
            except:
                formatted_time = settlement_time
                
            won = bet.get('won', False)
            if won:
                total_won += 1
                result_marker = "â WON"
                stake = bet.get('stake', 0.0)
                gross_profit = bet.get('gross_profit', 0.0)
                commission = bet.get('commission', 0.0)
                profit = bet.get('profit', 0.0)
                total_commission += commission
                profit_display = f"+Â£{profit:.2f} (Commission: Â£{commission:.2f})"
            else:
                total_lost += 1
                result_marker = "â LOST"
                stake = bet.get('stake', 0.0)
                profit_display = f"-Â£{stake:.2f}"
            
            print(f"\n{formatted_time} - {result_marker} - {profit_display}")
            print(f"Event: {bet.get('event_name', 'Unknown Event')}")
            print(f"Selection: {bet.get('team_name', 'Unknown')} (ID: {bet.get('selection_id', 'Unknown')}) @ {bet.get('odds', 0.0)}")
            print(f"Stake: Â£{bet.get('stake', 0.0):.2f}")
            
            if won:
                print(f"Gross Profit: Â£{gross_profit:.2f}")
                print(f"Commission (5%): Â£{commission:.2f}")
                print(f"Net Profit: Â£{profit:.2f}")
        
        # Show summary
        win_rate = (total_won / len(bets)) * 100 if bets else 0
        print("\nSummary:")
        print(f"Won: {total_won}, Lost: {total_lost}")
        print(f"Win Rate: {win_rate:.1f}%")
        print(f"Total Commission Paid: Â£{total_commission:.2f}")
        print("="*75 + "\n")
    
    async def cmd_odds(self, *args) -> None:
        """View or change target odds range."""
        config = self.config_manager.get_config()
        betting_config = config.get('betting', {})
        
        current_min = betting_config.get('min_odds', 3.0)
        current_max = betting_config.get('max_odds', 4.0)
        
        if not args or len(args) < 2:
            print(f"\nCurrent target odds range: {current_min} - {current_max}")
            print("To change, use: odds <min> <max>")
            print("Example: odds 3.0 4.0")
            return
            
        try:
            new_min = float(args[0])
            new_max = float(args[1])
            
            if new_min <= 1.0:
                print("Minimum odds must be greater than 1.0")
                return
                
            if new_max <= new_min:
                print("Maximum odds must be greater than minimum odds")
                return
            
            # Update configuration
            self.config_manager.update_config_value('betting', 'min_odds', new_min)
            self.config_manager.update_config_value('betting', 'max_odds', new_max)
            
            print(f"\nTarget odds range updated: {new_min} - {new_max}")
        except ValueError:
            print("Invalid odds values. Please use numeric values.")
    
    async def cmd_reset(self, *args) -> None:
        """Reset the betting system."""
        config = self.config_manager.get_config()
        configured_stake = config.get('betting', {}).get('initial_stake', 1.0)
        
        initial_stake = configured_stake
        if args and len(args) > 0:
            try:
                initial_stake = float(args[0])
            except ValueError:
                print(f"Invalid stake amount: {args[0]}. Using configured default: Â£{configured_stake}")
        
        # Ask for confirmation
        print(f"\nAre you sure you want to reset the betting system with initial stake: Â£{initial_stake}?")
        print("This will clear all bet history and reset the account balance.")
        print("Type 'yes' to confirm or anything else to cancel.")
        
        confirm = input("> ").strip().lower()
        if confirm != 'yes':
            print("Reset cancelled.")
            return
        
        print(f"Resetting betting system with initial stake: Â£{initial_stake}...")
        
        # Update configuration if stake changed
        if initial_stake != configured_stake:
            self.config_manager.update_config_value('betting', 'initial_stake', initial_stake)
        
        # Reset state
        self.state_manager.reset_state(initial_stake)
        
        print("Reset complete! System is ready for new betting cycle.")
    
    async def cmd_quit(self) -> None:
        """Exit the application."""
        self.should_exit = True
        print("Shutting down betting system...")

def handle_shutdown_signal(signum, frame):
    """Handle shutdown signals."""
    global shutdown_event
    if shutdown_event:
        shutdown_event.set()
    print("\nShutdown signal received. Exiting...")

async def run_command_loop(cmd_handler: CommandHandler, betting_service: BettingService) -> None:
    """Run interactive command loop while the betting service runs."""
    try:
        while not cmd_handler.should_exit and not shutdown_event.is_set():
            # Display countdown with command prompt
            interval = 60  # Default interval
            
            print(f"Waiting {interval} seconds for next betting cycle...")
            print("Enter commands during this time. Type 'help' for available commands.")
            
            # Process commands during wait period
            for remaining in range(interval, 0, -1):
                if cmd_handler.should_exit or shutdown_event.is_set():
                    break
                    
                # Display countdown
                sys.stdout.write(f"\rNext cycle in {remaining} seconds. Enter command or press Enter for status: ")
                sys.stdout.flush()
                
                # Check for input with timeout (non-blocking)
                ready_to_read, _, _ = select.select([sys.stdin], [], [], 0.1)
                
                if ready_to_read:
                    command = sys.stdin.readline().strip()
                    print()  # New line after input
                    
                    await cmd_handler.handle_command(command)
                    
                # Sleep briefly
                await asyncio.sleep(0.9)
                
    except asyncio.CancelledError:
        print("Command loop cancelled")
    finally:
        await betting_service.stop()

async def update_enhanced_bet_data(betting_system, data_dir: str = 'web/data/betting', interval: int = 30) -> None:
    """
    Background task to periodically update active bet data with enhanced information
    
    Args:
        betting_system: Betting system instance
        data_dir: Directory for data files
        interval: Update interval in seconds
    """
    logger = logging.getLogger('EnhancedBetUpdater')
    logger.info("Starting enhanced bet data updater task")
    
    data_path = Path(data_dir)
    active_bet_file = data_path / 'active_bet.json'
    
    try:
        while not shutdown_event.is_set():
            try:
                # Only update if the file exists and there's an active bet
                if active_bet_file.exists():
                    # Read the active bet directly
                    try:
                        with open(active_bet_file, 'r') as f:
                            active_bet = json.load(f)
                        
                        # First check for explicit cancellation flag
                        if active_bet and isinstance(active_bet, dict) and active_bet.get('is_canceled', False):
                            logger.debug(f"Skipping enhancement for explicitly canceled bet (canceled at {active_bet.get('canceled_at')})")
                            await asyncio.sleep(interval)
                            continue
                        
                        # Then check if it's a valid active bet with all required fields
                        if (active_bet and isinstance(active_bet, dict) and 
                            'market_id' in active_bet and 
                            'selection_id' in active_bet and 
                            'stake' in active_bet):
                            
                            market_id = active_bet['market_id']
                            logger.info(f"Enhancing active bet with market ID: {market_id}")
                            
                            # Get fresh market data directly
                            market_info = await betting_system.betfair_client.get_fresh_market_data(market_id)
                            
                            if market_info:
                                # Add market info to active bet
                                active_bet['current_market'] = market_info
                                
                                # Write back enhanced data
                                with open(active_bet_file, 'w') as f:
                                    json.dump(active_bet, f, indent=2)
                                    logger.info("Updated active_bet.json with enhanced market data")
                            else:
                                logger.warning(f"Could not retrieve market data for {market_id}")
                        else:
                            logger.debug("No valid active bet found in active_bet.json")
                    except Exception as e:
                        logger.error(f"Error processing active_bet.json: {str(e)}")
                        logger.exception(e)
                else:
                    logger.debug("No active_bet.json file found")
                    
            except Exception as e:
                logger.error(f"Error updating enhanced bet data: {str(e)}")
                logger.exception(e)
                
            # Wait for next update
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("Enhanced bet data updater task cancelled")

async def main():
    """Entry point for the betting system."""
    global shutdown_event
    shutdown_event = asyncio.Event()
    
    # Load environment variables
    load_dotenv()
    
    # Initialize logging
    LogManager.initialize_logging(retention_days=3)
    logger = logging.getLogger('main')
    logger.info("Betting system starting up")
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, handle_shutdown_signal)
    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    
    try:
        # Initialize components with updated config path
        logger.info("Initializing components")
        config_manager = ConfigManager()  # Will use the new default path: web/config/betting_config.json
        state_manager = BettingStateManager()
        
        betfair_client = BetfairClient(
            app_key=os.getenv('BETFAIR_APP_KEY'),
            cert_file=os.getenv('BETFAIR_CERT_FILE'),
            key_file=os.getenv('BETFAIR_KEY_FILE')
        )
        
        # Login to Betfair
        logger.info("Logging into Betfair API")
        login_successful = await betfair_client.login()
        
        if not login_successful:
            logger.error("Failed to login to Betfair")
            print("Failed to login to Betfair - check credentials and certificates")
            return
        
        # Import these here to avoid circular imports
        from .betting_system import BettingSystem
        from .repositories.account_repository import AccountRepository
        from .repositories.bet_repository import BetRepository
        
        # Initialize additional components needed for BettingSystem
        account_repository = AccountRepository()
        bet_repository = BetRepository()
        
        # Initialize betting system for enhanced data
        betting_system = BettingSystem(
            betfair_client=betfair_client,
            bet_repository=bet_repository,
            account_repository=account_repository,
            config_manager=config_manager
        )
            
        # Initialize betting service
        betting_service = BettingService(
            betfair_client=betfair_client,
            state_manager=state_manager,
            config_manager=config_manager
        )
        
        # Initialize command handler with betting_system reference
        cmd_handler = CommandHandler(
            betting_service, 
            state_manager, 
            config_manager,
            betting_system
        )
        
        # Show help
        await cmd_handler.cmd_help()
        
        # Show initial status
        await cmd_handler.cmd_status()
        
        # Start the enhanced bet data updater task
        enhanced_data_task = asyncio.create_task(
            update_enhanced_bet_data(betting_system)
        )
        
        # Start main tasks
        service_task = asyncio.create_task(betting_service.start())
        command_task = asyncio.create_task(run_command_loop(cmd_handler, betting_service))
        
        # Wait for shutdown event or tasks to complete
        await shutdown_event.wait()
        
        # Cancel tasks
        logger.info("Shutting down tasks")
        
        if not service_task.done():
            service_task.cancel()
            
        if not command_task.done():
            command_task.cancel()
            
        if not enhanced_data_task.done():
            enhanced_data_task.cancel()
            
        # Wait for tasks to complete
        await asyncio.gather(service_task, command_task, enhanced_data_task, return_exceptions=True)
        
        logger.info("System shutdown complete")
        
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
    finally:
        # Final cleanup
        logging.shutdown()

if __name__ == "__main__":
    print("Starting Betfair Compound Betting System")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Process interrupted by user")
    except Exception as e:
        print(f"ERROR: Process terminated due to error: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        print("Process shutdown complete")