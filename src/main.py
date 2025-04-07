"""
main.py

Entry point for the betting system with simplified flow and command-line interface.
Refactored to use BettingStateManager as the single source of truth, removing
event sourcing, repositories, and BettingSystem components from this execution path.
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
from typing import Dict, Any, Optional

# Core components for the simplified flow
from .betting_service import BettingService
from .betfair_client import BetfairClient
from .betting_state_manager import BettingStateManager
from .config_manager import ConfigManager
from .log_manager import LogManager
# Removed imports: BettingSystem, AccountRepository, BetRepository, commands package

# Global variables for shutdown control
shutdown_event = None
logger = logging.getLogger('main') # Define logger at module level

class CommandHandler:
    """Handles command-line input and operations using the State Manager."""

    def __init__(
        self,
        betting_service: BettingService, # Keep service for potential actions if needed later
        state_manager: BettingStateManager,
        config_manager: ConfigManager
        # Removed betting_system parameter
    ):
        self.betting_service = betting_service
        self.state_manager = state_manager
        self.config_manager = config_manager
        self.should_exit = False
        self.cmd_logger = logging.getLogger('CommandHandler') # Separate logger for commands

    async def handle_command(self, command: str) -> None:
        """Process a command from user input."""
        parts = command.strip().split()
        if not parts:
            # Default to status if Enter is pressed
            await self.cmd_status()
            return

        cmd = parts[0].lower()
        args = parts[1:]

        try:
            if cmd in ['help', 'h', '?']:
                await self.cmd_help()
            elif cmd in ['status', 's']:
                await self.cmd_status()
            elif cmd in ['bet', 'b']:
                await self.cmd_bet_details()
            elif cmd in ['history', 'hist']:
                # Allow specifying limit, e.g., history 20
                limit = int(args[0]) if args else 10
                await self.cmd_history(limit)
            elif cmd in ['odds', 'o']:
                await self.cmd_odds(*args)
            elif cmd in ['cancel', 'c']:
                await self.cmd_cancel_bet()
            elif cmd in ['reset', 'r']:
                await self.cmd_reset(*args)
            elif cmd in ['quit', 'exit', 'q']:
                await self.cmd_quit()
            else:
                print(f"Unknown command: {cmd}")
                print("Type 'help' for a list of available commands.")
        except Exception as e:
             self.cmd_logger.error(f"Error executing command '{cmd}': {e}", exc_info=True)
             print(f"An error occurred while executing '{cmd}': {e}")

    async def cmd_help(self) -> None:
        """Display help information."""
        print("\n=== Available Commands ===")
        print("help, h, ?         - Show this help message")
        print("status, s          - Show current betting system status")
        print("bet, b             - Show details of active bet")
        print("history, hist [N]  - Show last N settled bets (default: 10)")
        print("odds [min] [max]   - View or change target odds range")
        print("cancel, c          - [DRY RUN ONLY] Cancel the current active bet")
        print("reset [stake]      - Reset the betting system with optional initial stake")
        print("quit, exit, q      - Exit the application")
        print("========================\n")

    async def cmd_status(self) -> None:
        """Display current system status using State Manager."""
        try:
            stats = self.state_manager.get_stats_summary()

            print("\n" + "="*60)
            print("BETTING SYSTEM STATUS SUMMARY")
            print("="*60)
            print(f"Current Cycle: #{stats['current_cycle']}")
            print(f"Current Bet in Cycle: #{stats['current_bet_in_cycle']}")
            print(f"Current Balance: £{stats['current_balance']:.2f}")
            print(f"Next Bet Stake: £{stats['next_stake']:.2f}")
            print(f"Target Amount: £{stats['target_amount']:.2f}")
            print(f"Total Cycles Completed: {stats['total_cycles']}")
            print(f"Total Bets Placed: {stats['total_bets_placed']}")
            print(f"Successful Bets: {stats['total_wins']}")
            print(f"Win Rate: {stats['win_rate']:.1f}%")
            print(f"Total Money Lost: £{stats['total_money_lost']:.2f}")
            print(f"Total Commission Paid: £{stats['total_commission_paid']:.2f}")
            print(f"Highest Balance Reached: £{stats['highest_balance']:.2f}")

            config = self.config_manager.get_config()
            betting_config = config.get('betting', {})
            min_odds = betting_config.get('min_odds', 3.0)
            max_odds = betting_config.get('max_odds', 4.0)

            print("\nCurrent Configuration:")
            print(f"Mode: {'DRY RUN' if config.get('system', {}).get('dry_run', True) else 'LIVE'}")
            print(f"Target Odds Range: {min_odds} - {max_odds}")
            print(f"Initial Stake: £{betting_config.get('initial_stake', 1.0):.2f}")
            print("="*60 + "\n")
        except Exception as e:
            self.cmd_logger.error("Error retrieving system status: %s", e, exc_info=True)
            print(f"Error displaying status: {e}")

    async def cmd_bet_details(self) -> None:
        """
        Display details of current active bet, using enhanced data if available
        from the background updater task (reads active_bet.json).
        """
        try:
            active_bet = self.state_manager.get_active_bet()

            if not active_bet:
                print("\nNo active bet currently placed.")
                return

            print("\n" + "="*75)
            print("ACTIVE BET DETAILS")
            print("="*75)

            # The active_bet from state manager now potentially contains 'current_market'
            # if the background task has updated it.
            display_data = active_bet

            # Basic details
            print(f"Market ID: {display_data.get('market_id')}")
            print(f"Event: {display_data.get('event_name', 'Unknown Event')}")
            print(f"Cycle #{display_data.get('cycle_number', '?')}, Bet #{display_data.get('bet_in_cycle', '?')} in cycle")
            print(f"Selection: {display_data.get('team_name', 'Unknown')} @ {display_data.get('odds', 0.0)}")
            print(f"Selection ID: {display_data.get('selection_id')}")
            print(f"Stake: £{display_data.get('stake', 0.0):.2f}")

            # Market start time
            market_start_time = display_data.get('market_start_time')
            if market_start_time:
                try:
                    # Handle potential Z suffix for UTC
                    if market_start_time.endswith('Z'):
                        market_start_time = market_start_time[:-1] + '+00:00'
                    start_dt = datetime.fromisoformat(market_start_time)
                    # Ensure timezone awareness if not present
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=timezone.utc)
                    # Convert to local time for display if desired, or keep as UTC
                    # formatted_time = start_dt.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
                    formatted_time = start_dt.strftime('%Y-%m-%d %H:%M:%S UTC')
                    print(f"Kick Off Time: {formatted_time}")
                except ValueError:
                    self.cmd_logger.warning(f"Could not parse market start time: {market_start_time}")
                    print(f"Kick Off Time: {market_start_time} (unparsed)")

            # Enhanced market data if available (populated by background task)
            market_info = display_data.get('current_market')
            if market_info:
                is_inplay = market_info.get('inplay', False)
                market_status = market_info.get('status', 'Unknown')
                print(f"In Play Status: {market_status} {'(In Play)' if is_inplay else ''}")

                runners = market_info.get('runners', [])
                if runners:
                    sorted_runners = sorted(runners, key=lambda r: r.get('sortPriority', 999))

                    print("\nCurrent Market Odds:")
                    for runner in sorted_runners:
                        selection_id = runner.get('selectionId')
                        team_name = runner.get('teamName', runner.get('runnerName', 'Unknown'))

                        back_prices = runner.get('ex', {}).get('availableToBack', [])
                        current_odds = back_prices[0].get('price', 0.0) if back_prices else 0.0

                        is_our_selection = selection_id == display_data.get('selection_id')
                        selection_marker = " <<< OUR BET" if is_our_selection else ""

                        print(f"  {team_name}: {current_odds:.2f}{selection_marker}")
            else:
                 print("Current market odds not available (updater task might not have run yet)")

            # Placement time
            placement_time_str = display_data.get('timestamp')
            if placement_time_str:
                try:
                    # Handle potential Z suffix for UTC
                    if placement_time_str.endswith('Z'):
                         placement_time_str = placement_time_str[:-1] + '+00:00'
                    dt = datetime.fromisoformat(placement_time_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    # formatted_time = dt.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
                    formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S UTC')
                    print(f"\nBet Placed: {formatted_time}")
                except ValueError:
                    self.cmd_logger.warning(f"Could not parse bet placement time: {placement_time_str}")
                    print(f"\nBet Placed: {placement_time_str} (unparsed)")

            print("="*75 + "\n")

        except Exception as e:
            self.cmd_logger.error("Error retrieving active bet details: %s", e, exc_info=True)
            print(f"Error displaying active bet: {e}")


    async def cmd_history(self, limit: int = 10) -> None:
        """Display betting history using State Manager."""
        try:
            if limit <= 0:
                limit = 10
            bets = self.state_manager.get_bet_history(limit)

            if not bets:
                print("\nNo settled bets found.")
                return

            print("\n" + "="*95) # Increased width for commission
            print(f"SETTLED BET HISTORY (Last {len(bets)} bets)")
            print("="*95)

            print(f"{'Time':<20} {'Event':<25} {'Selection':<20} {'Stake':>7} {'Result':>7} {'Profit/Loss':>12}")
            print("-" * 95)

            for bet in bets:
                settlement_time_str = bet.get('settlement_time', 'Unknown')
                try:
                    if settlement_time_str.endswith('Z'):
                        settlement_time_str = settlement_time_str[:-1] + '+00:00'
                    dt = datetime.fromisoformat(settlement_time_str)
                    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                    formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S')
                except ValueError:
                    formatted_time = settlement_time_str[:19] # Truncate if unparseable

                won = bet.get('won', False)
                stake = bet.get('stake', 0.0)
                profit = bet.get('profit', 0.0) # Net profit
                commission = bet.get('commission', 0.0)

                event_name = bet.get('event_name', 'Unknown Event')[:25] # Truncate
                selection_name = (bet.get('team_name', 'Unknown') + f" @ {bet.get('odds', 0.0):.2f}")[:20] # Truncate

                if won:
                    result_marker = "WON"
                    profit_loss_display = f"+£{profit:.2f}"
                    if commission > 0:
                         profit_loss_display += f" (C:£{commission:.2f})"
                else:
                    result_marker = "LOST"
                    profit_loss_display = f"-£{stake:.2f}"

                print(f"{formatted_time:<20} {event_name:<25} {selection_name:<20} £{stake:>6.2f} {result_marker:>7} {profit_loss_display:>12}")

            print("="*95 + "\n")

        except Exception as e:
            self.cmd_logger.error("Error retrieving bet history: %s", e, exc_info=True)
            print(f"Error displaying bet history: {e}")


    async def cmd_odds(self, *args) -> None:
        """View or change target odds range using Config Manager."""
        try:
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

                # Update configuration via ConfigManager
                success_min = self.config_manager.update_config_value('betting', 'min_odds', new_min)
                success_max = self.config_manager.update_config_value('betting', 'max_odds', new_max)

                if success_min and success_max:
                    print(f"\nTarget odds range updated to: {new_min} - {new_max}")
                    print("Configuration file saved.")
                else:
                     print("\nFailed to update odds range in configuration.")

            except ValueError:
                print("Invalid odds values. Please use numeric values.")
            except Exception as update_e:
                 self.cmd_logger.error("Error updating config file: %s", update_e, exc_info=True)
                 print(f"Error saving configuration: {update_e}")

        except Exception as e:
            self.cmd_logger.error("Error in cmd_odds: %s", e, exc_info=True)
            print(f"Error handling odds command: {e}")

    async def cmd_cancel_bet(self) -> None:
        """[DRY RUN ONLY] Cancel the current active bet using State Manager."""
        try:
            config = self.config_manager.get_config()
            dry_run = config.get('system', {}).get('dry_run', True)

            if not dry_run:
                print("\nERROR: Cancel bet command can only be used in [DRY RUN] mode.")
                return

            active_bet = self.state_manager.get_active_bet()

            if not active_bet:
                print("\nNo active bet to cancel.")
                return

            print("\n" + "="*75)
            print("[DRY RUN] CANCELING ACTIVE BET")
            print("="*75)

            event_name = active_bet.get('event_name', 'Unknown Event')
            team_name = active_bet.get('team_name', 'Unknown')
            odds = active_bet.get('odds', 0.0)
            stake = active_bet.get('stake', 0.0)

            print(f"Event: {event_name}")
            print(f"Selection: {team_name} @ {odds}")
            print(f"Stake: £{stake:.2f}")

            print("\nAre you sure you want to cancel this bet?")
            print("Type 'yes' to confirm or anything else to abort.")

            # Use input() directly as this runs synchronously within the async command handler
            confirm = input("> ").strip().lower()
            if confirm != 'yes':
                print("Bet cancellation aborted.")
                return

            # --- Perform Cancellation via State Manager ---
            # 1. Restore the stake (add back to balance)
            self.state_manager.update_balance(stake, "[DRY RUN] Bet cancellation - stake refund")

            # 2. Reset the active bet state (clears active bet, adjusts counters)
            self.state_manager.reset_active_bet()
            # Note: state_manager._save_state() is called within reset_active_bet

            print("\nBet successfully canceled. System is ready to find a new bet.")
            print(f"£{stake:.2f} has been returned to your balance.")
            print("="*75 + "\n")

        except Exception as e:
            self.cmd_logger.error("Error canceling bet: %s", e, exc_info=True)
            print(f"Error canceling bet: {e}")

    async def cmd_reset(self, *args) -> None:
        """Reset the betting system using State Manager."""
        try:
            config = self.config_manager.get_config()
            configured_stake = config.get('betting', {}).get('initial_stake', 1.0)

            initial_stake = configured_stake
            if args and len(args) > 0:
                try:
                    stake_arg = float(args[0])
                    if stake_arg > 0:
                        initial_stake = stake_arg
                    else:
                        print("Initial stake must be positive.")
                        return
                except ValueError:
                    print(f"Invalid stake amount: {args[0]}. Using configured default: £{configured_stake:.2f}")

            print(f"\nAre you sure you want to reset the betting system with initial stake: £{initial_stake:.2f}?")
            print("This will clear all bet history and reset the account balance.")
            print("Type 'yes' to confirm or anything else to cancel.")

            confirm = input("> ").strip().lower()
            if confirm != 'yes':
                print("Reset cancelled.")
                return

            print(f"Resetting betting system with initial stake: £{initial_stake:.2f}...")

            # Update configuration if stake changed via argument
            if initial_stake != configured_stake:
                if not self.config_manager.update_config_value('betting', 'initial_stake', initial_stake):
                     print("Warning: Failed to update initial stake in configuration file.")

            # Reset state via StateManager
            self.state_manager.reset_state(initial_stake)

            print("Reset complete! System is ready for new betting cycle.")
            await self.cmd_status() # Show updated status

        except Exception as e:
            self.cmd_logger.error("Error during system reset: %s", e, exc_info=True)
            print(f"Error during reset: {e}")

    async def cmd_quit(self) -> None:
        """Signal the application to exit."""
        self.should_exit = True
        print("\nShutting down betting system...")
        # Signal the main loop to stop
        if shutdown_event:
            shutdown_event.set()


def handle_shutdown_signal(signum, frame):
    """Handle shutdown signals (Ctrl+C)."""
    global shutdown_event
    print("\nShutdown signal received. Exiting gracefully...")
    if shutdown_event and not shutdown_event.is_set():
        shutdown_event.set()
    else:
         # If already set or not initialized, force exit
         sys.exit(1)


async def run_command_loop(cmd_handler: CommandHandler) -> None:
    """Run interactive command loop while the betting service runs."""
    loop = asyncio.get_running_loop()
    try:
        print("Command loop started. Type 'help' for commands.")
        while not cmd_handler.should_exit and not shutdown_event.is_set():
            # Use asyncio's ability to run blocking input in an executor
            try:
                command = await loop.run_in_executor(
                    None, # Default executor
                    lambda: input("Enter command: ")
                )
                await cmd_handler.handle_command(command)
            except EOFError: # Handle case where input stream is closed
                 logger.warning("EOF received, exiting command loop.")
                 await cmd_handler.cmd_quit()
                 break
            except RuntimeError as e:
                 # Handle potential errors if loop is closing during input
                 if "Event loop is closed" in str(e):
                      logger.warning("Event loop closed during input, exiting command loop.")
                      break
                 else:
                      raise # Re-raise other runtime errors
            # Add a small sleep to prevent tight looping if input fails unexpectedly
            await asyncio.sleep(0.1)

    except asyncio.CancelledError:
        logger.info("Command loop cancelled.")
    except Exception as e:
         logger.error("Error in command loop: %s", e, exc_info=True)
    finally:
        logger.info("Command loop finished.")


async def update_enhanced_bet_data(
    betfair_client: BetfairClient, # Changed dependency
    state_manager: BettingStateManager, # Added dependency
    data_dir: str = 'web/data/betting',
    interval: int = 30
) -> None:
    """
    Background task to periodically update active bet data in active_bet.json
    with enhanced market information using BetfairClient directly.
    """
    updater_logger = logging.getLogger('EnhancedBetUpdater')
    updater_logger.info(f"Starting enhanced bet data updater task (interval: {interval}s)")

    data_path = Path(data_dir)
    active_bet_file = data_path / 'active_bet.json'

    try:
        while not shutdown_event.is_set():
            active_bet_data = None
            try:
                # Check if an active bet logically exists via the state manager
                # This is more reliable than just checking the file
                current_active_bet = state_manager.get_active_bet()

                if current_active_bet and 'market_id' in current_active_bet:
                    market_id = current_active_bet['market_id']
                    updater_logger.debug(f"Found active bet for market {market_id}. Fetching enhanced data.")

                    # Fetch fresh market data using BetfairClient
                    market_info = await betfair_client.get_fresh_market_data(market_id)

                    if market_info:
                        # Merge market info into the bet data
                        # Important: Use a copy to avoid modifying the state manager's internal state directly
                        enhanced_bet_data = current_active_bet.copy()
                        enhanced_bet_data['current_market'] = market_info

                        # Write the enhanced data specifically to the JSON file for the dashboard
                        # Use the state manager's storage utility for atomic writes
                        if state_manager.storage.write_json('active_bet.json', enhanced_bet_data):
                            updater_logger.debug(f"Successfully updated active_bet.json for market {market_id}")
                        else:
                            updater_logger.error(f"Failed to write enhanced data to active_bet.json for market {market_id}")
                    else:
                        updater_logger.warning(f"Could not retrieve fresh market data for active bet {market_id}")
                        # Optionally clear current_market if fetch fails? Or leave stale data?
                        # Leaving stale data for now.

                else:
                    updater_logger.debug("No active bet found in state manager.")
                    # Ensure the file reflects no active bet if state manager says so
                    # Check if the file exists and contains data, then clear it
                    if active_bet_file.exists():
                         try:
                              with open(active_bet_file, 'r') as f:
                                   content = f.read().strip()
                              if content and content != '{}': # Check if not empty
                                   if state_manager.storage.write_json('active_bet.json', {}):
                                        updater_logger.info("Cleared active_bet.json as no active bet exists in state.")
                                   else:
                                        updater_logger.error("Failed to clear active_bet.json.")
                         except Exception as read_err:
                              updater_logger.error(f"Error reading active_bet.json before clearing: {read_err}")


            except Exception as e:
                updater_logger.error(f"Error in enhanced bet data update cycle: {e}", exc_info=True)

            # Wait for the next interval or until shutdown
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
                if shutdown_event.is_set():
                     break # Exit loop if shutdown event is set during wait
            except asyncio.TimeoutError:
                continue # Timeout reached, continue to next iteration

    except asyncio.CancelledError:
        updater_logger.info("Enhanced bet data updater task cancelled.")
    finally:
        updater_logger.info("Enhanced bet data updater task finished.")


async def main():
    """Entry point for the refactored betting system."""
    global shutdown_event
    shutdown_event = asyncio.Event()

    load_dotenv()

    # Initialize logging FIRST
    LogManager.initialize_logging(log_dir='web/logs', retention_days=3)
    # Logger defined globally now

    logger.info("Betting system starting up...")

    # Setup signal handlers
    signal.signal(signal.SIGINT, handle_shutdown_signal)
    signal.signal(signal.SIGTERM, handle_shutdown_signal)

    # Initialize core components
    config_manager = None
    state_manager = None
    betfair_client = None
    betting_service = None
    tasks = []

    try:
        logger.info("Initializing components...")
        config_manager = ConfigManager(config_file='web/config/betting_config.json')
        state_manager = BettingStateManager(data_dir='web/data/betting')

        # Validate Betfair credentials from environment
        app_key = os.getenv('BETFAIR_APP_KEY')
        cert_file = os.getenv('BETFAIR_CERT_FILE')
        key_file = os.getenv('BETFAIR_KEY_FILE')
        username = os.getenv('BETFAIR_USERNAME')
        password = os.getenv('BETFAIR_PASSWORD')

        if not all([app_key, cert_file, key_file, username, password]):
             logger.error("Missing Betfair credentials or certificate paths in environment variables.")
             print("ERROR: Missing Betfair credentials or certificate paths. Check .env file or environment variables.")
             return

        if not Path(cert_file).exists() or not Path(key_file).exists():
             logger.error(f"Betfair certificate or key file not found at specified paths: {cert_file}, {key_file}")
             print(f"ERROR: Betfair certificate or key file not found. Check paths in .env file.")
             print(f"Cert file path: {Path(cert_file).resolve()}")
             print(f"Key file path: {Path(key_file).resolve()}")
             return

        betfair_client = BetfairClient(app_key=app_key, cert_file=cert_file, key_file=key_file)

        logger.info("Logging into Betfair API...")
        if not await betfair_client.login():
            logger.error("Failed to login to Betfair API.")
            print("ERROR: Failed to login to Betfair. Check credentials, app key, and certificate validity.")
            await betfair_client.close_session() # Attempt graceful close
            return
        logger.info("Betfair login successful.")

        # Initialize the main betting service
        betting_service = BettingService(
            betfair_client=betfair_client,
            state_manager=state_manager,
            config_manager=config_manager
        )

        # Initialize command handler
        cmd_handler = CommandHandler(
            betting_service=betting_service,
            state_manager=state_manager,
            config_manager=config_manager
        )

        # --- Start Background Tasks ---
        logger.info("Starting background tasks...")

        # Task 1: Betting Service main loop
        service_task = asyncio.create_task(betting_service.start(), name="BettingService")
        tasks.append(service_task)

        # Task 2: Enhanced Bet Data Updater for Dashboard
        # Pass betfair_client and state_manager
        updater_task = asyncio.create_task(
            update_enhanced_bet_data(betfair_client, state_manager, interval=30),
            name="EnhancedBetUpdater"
        )
        tasks.append(updater_task)

        # Task 3: Command Loop (Run last as it might block)
        # Show initial status before starting command loop
        await cmd_handler.cmd_status()
        command_task = asyncio.create_task(run_command_loop(cmd_handler), name="CommandLoop")
        tasks.append(command_task)

        # Wait for shutdown signal
        await shutdown_event.wait()
        logger.info("Shutdown signal detected. Stopping tasks...")

    except Exception as e:
        logger.error(f"Fatal error during startup or main execution: {e}", exc_info=True)
        print(f"ERROR: A critical error occurred: {e}")
        # Ensure shutdown event is set if an error occurs
        if shutdown_event and not shutdown_event.is_set():
             shutdown_event.set()
    finally:
        logger.info("Initiating shutdown sequence...")

        # Stop the betting service first (gracefully)
        if betting_service:
            await betting_service.stop()

        # Cancel all running tasks
        for task in tasks:
            if task and not task.done():
                try:
                    task.cancel()
                    logger.info(f"Cancelled task: {task.get_name()}")
                except Exception as cancel_err:
                     logger.error(f"Error cancelling task {task.get_name()}: {cancel_err}")

        # Wait for tasks to finish cancellation
        if tasks:
             await asyncio.gather(*tasks, return_exceptions=True)
             logger.info("All tasks gathered.")

        # Close Betfair client session
        if betfair_client:
            await betfair_client.close_session()
            logger.info("Betfair client session closed.")

        logger.info("System shutdown complete.")
        logging.shutdown() # Flush and close all handlers


if __name__ == "__main__":
    print("Starting Betfair Compound Betting System...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProcess interrupted by user (KeyboardInterrupt).")
    except Exception as e:
        print(f"\nERROR: Process terminated due to unexpected error: {e}")
        # Use logger if available, otherwise print traceback
        if logger:
             logger.critical("Unhandled exception caused process termination.", exc_info=True)
        else:
             import traceback
             traceback.print_exc()
    finally:
        print("Process shutdown finished.")