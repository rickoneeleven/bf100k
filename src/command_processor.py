"""
command_processor.py

Handles command line input processing for the betting system.
Provides interactive commands during system operation with enhanced
bet details display showing consistent selection mapping.
Updated to display commission details in bet history.
"""

import logging
import asyncio
from typing import Dict, Any, Callable, List, Optional
import sys
import os
import time
from datetime import datetime

class CommandProcessor:
    def __init__(self, betting_system):
        self.betting_system = betting_system
        self.commands = {
            "help": self.cmd_help,
            "status": self.cmd_status,
            "reset": self.cmd_reset,
            "bet": self.cmd_bet_details,  # Enhanced bet details command
            "market": self.cmd_market_info,  # New command for market info
            "history": self.cmd_bet_history,  # New command for bet history
            "odds": self.cmd_odds_range,  # New command for changing odds range
            "debug": self.cmd_debug_info,  # New command for debugging information
            "quit": self.cmd_quit,
            "exit": self.cmd_quit
        }
        
        # Setup logging
        self.logger = logging.getLogger('CommandProcessor')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('web/logs/commands.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        
        # Control flags
        self.should_exit = False
    
    async def cmd_help(self, args: List[str] = None) -> None:
        """Display available commands"""
        print("\n=== Available Commands ===")
        print("help       - Show this help message")
        print("status     - Show current betting system status")
        print("bet        - Show detailed information about active bets")
        print("market     - Show available markets with current odds")
        print("history    - Show history of settled bets")
        print("odds       - View or change target odds range")
        print("debug      - Show additional debugging information")
        print("reset      - Reset the betting ledger and start fresh")
        print("quit/exit  - Exit the application")
        print("========================\n")
    
    async def cmd_status(self, args: List[str] = None) -> None:
        """Display current system status"""
        try:
            # Get account status and ledger info
            status = await self.betting_system.get_account_status()
            ledger = await self.betting_system.get_ledger_info()
            
            # Display summary
            print("\n" + "="*60)
            print("BETTING SYSTEM STATUS SUMMARY")
            print("="*60)
            print(f"Current Cycle: #{status['current_cycle']}")
            print(f"Current Bet in Cycle: #{status['current_bet_in_cycle']}")
            print(f"Current Balance: £{status['current_balance']:.2f}")
            print(f"Target Amount: £{status['target_amount']:.2f}")
            print(f"Total Cycles Completed: {status['total_cycles']}")
            print(f"Total Bets Placed: {status['total_bets_placed']}")
            print(f"Successful Bets: {status['successful_bets']}")
            print(f"Win Rate: {status['win_rate']:.1f}%")
            print(f"Total Money Lost: £{status['total_money_lost']:.2f}")
            print(f"Total Commission Paid: £{ledger.get('total_commission_paid', 0.0):.2f}")
            print(f"Highest Balance Reached: £{ledger['highest_balance']:.2f}")
            
            # Get next stake calculation based on compound strategy
            next_stake = await self.betting_system.betting_ledger.get_next_stake()
            print(f"Next Bet Stake: £{next_stake:.2f} (Compound Strategy)")
            
            # Show current configuration
            config = self.betting_system.config_manager.get_config()
            betting_config = config.get('betting', {})
            min_odds = betting_config.get('min_odds', 3.0)
            max_odds = betting_config.get('max_odds', 4.0)
            
            print("\nCurrent Configuration:")
            print(f"Mode: {'DRY RUN' if self.betting_system.dry_run else 'LIVE'}")
            print(f"Target Odds Range: {min_odds} - {max_odds}")
            print(f"Initial Stake: £{betting_config.get('initial_stake', 1.0):.2f}")
            print("="*60 + "\n")
        except Exception as e:
            print(f"Error displaying status: {str(e)}")
            self.logger.error(f"Error displaying status: {str(e)}")
    
    async def cmd_bet_details(self, args: List[str] = None) -> None:
        """Display detailed information about active bets with enhanced selection mapping"""
        try:
            active_bets = await self.betting_system.get_active_bet_details()
            
            if not active_bets:
                print("\nNo active bets currently placed.")
                return
                
            print("\n" + "="*75)
            print("ACTIVE BET DETAILS")
            print("="*75)
            
            for bet in active_bets:
                market_id = bet.get("market_id")
                print(f"Market ID: {market_id}")
                print(f"Event: {bet.get('event_name', 'Unknown Event')}")
                
                # Get selection details using selection_id for reliable mapping
                selection_id = bet.get('selection_id')
                team_name = bet.get('team_name', 'Unknown')
                odds = bet.get('odds', 0.0)
                
                print(f"Selection: {team_name} @ {odds}")
                print(f"Selection ID: {selection_id}")  # Display selection ID for debugging
                print(f"Stake: £{bet.get('stake', 0.0):.2f}")
                
                # Get current market data including in-play status and current odds
                market_info = bet.get('current_market')
                if market_info:
                    # Format market start time
                    market_start_time = market_info.get('marketStartTime', bet.get('market_start_time'))
                    if market_start_time and market_start_time != 'Unknown':
                        try:
                            start_dt = datetime.fromisoformat(market_start_time.replace('Z', '+00:00'))
                            formatted_time = start_dt.strftime('%Y-%m-%d %H:%M:%S')
                            print(f"Kickoff Time: {formatted_time}")
                        except:
                            print(f"Kickoff Time: {market_start_time}")
                    else:
                        print("Kickoff Time: Unknown")
                    
                    # Show in-play status
                    is_inplay = market_info.get('inplay', False)
                    market_status = market_info.get('status', 'Unknown')
                    print(f"Market Status: {market_status}")
                    print(f"In Play: {'Yes' if is_inplay else 'No'}")
                    
                    # Show total matched amount
                    total_matched = market_info.get('totalMatched', 0.0)
                    print(f"Total Matched: £{total_matched:.2f}")
                    
                    # Get current market prices for all selections - USING SELECTION ID FOR MAPPING
                    print("\nCurrent Market Odds:")
                    runners = market_info.get('runners', [])
                    
                    # Ensure runners are sorted by sortPriority for consistent display
                    runners = sorted(runners, key=lambda r: r.get('sortPriority', 999))
                    
                    for runner in runners:
                        current_selection_id = runner.get('selectionId')
                        current_team_name = runner.get('runnerName') or runner.get('teamName', 'Unknown')
                        
                        # Mark our selection based on selection ID comparison (not by order)
                        is_our_selection = current_selection_id == selection_id
                        selection_marker = " ← OUR BET" if is_our_selection else ""
                        
                        # Get current best back price
                        back_prices = runner.get('ex', {}).get('availableToBack', [])
                        current_odds = back_prices[0].get('price', 0.0) if back_prices else 0.0
                        
                        # Display sort priority for debugging
                        sort_priority = runner.get('sortPriority', 'Unknown')
                        
                        # Show detailed odds information
                        print(f"  {current_team_name}: {current_odds}{selection_marker} (ID: {current_selection_id}, Priority: {sort_priority})")
                        
                        # If this is our selection, compare current odds with backed odds
                        if is_our_selection and current_odds > 0:
                            backed_odds = bet.get('odds', 0.0)
                            odds_delta = current_odds - backed_odds
                            direction = "higher" if odds_delta > 0 else "lower"
                            percent_change = (abs(odds_delta) / backed_odds) * 100
                            print(f"  Odds Trend: {abs(odds_delta):.2f} {direction} than when backed ({percent_change:.1f}% change)")
                            
                            # Show available liquidity
                            available_size = back_prices[0].get('size', 0.0) if back_prices else 0.0
                            print(f"  Available Liquidity: £{available_size:.2f}")
                
                # Show bet placement time
                if 'timestamp' in bet:
                    try:
                        placement_time = datetime.fromisoformat(bet['timestamp'])
                        formatted_placement = placement_time.strftime('%Y-%m-%d %H:%M:%S')
                        print(f"\nBet Placed: {formatted_placement}")
                    except:
                        print(f"\nBet Placed: {bet['timestamp']}")
                
                print("="*75 + "\n")
                
        except Exception as e:
            print(f"Error retrieving bet details: {str(e)}")
            self.logger.error(f"Error retrieving bet details: {str(e)}")
            self.logger.exception(e)
    
    async def cmd_market_info(self, args: List[str] = None) -> None:
        """Display information about available markets"""
        try:
            print("\nFetching current market data...")
            
            # Use the market analysis command to get markets with odds
            max_markets = 5  # Default number of markets to show
            
            if args and len(args) > 0:
                try:
                    max_markets = int(args[0])
                except ValueError:
                    print(f"Invalid number of markets: {args[0]}. Using default: {max_markets}")
            
            # Get markets and odds
            markets, market_books = await self.betting_system.betfair_client.get_markets_with_odds(max_markets)
            
            if not markets or not market_books:
                print("No markets found or error retrieving market data.")
                return
                
            print("\n" + "="*80)
            print(f"TOP {len(markets)} FOOTBALL MARKETS BY VOLUME")
            print("="*80)
            
            for i, (market, market_book) in enumerate(zip(markets, market_books)):
                market_id = market.get('marketId')
                event = market.get('event', {})
                event_name = event.get('name', 'Unknown Event')
                competition = market.get('competition', {}).get('name', 'Unknown Competition')
                
                # Format market start time
                market_start_time = market.get('marketStartTime')
                formatted_time = "Unknown"
                if market_start_time:
                    try:
                        start_dt = datetime.fromisoformat(market_start_time.replace('Z', '+00:00'))
                        formatted_time = start_dt.strftime('%Y-%m-%d %H:%M:%S')
                    except:
                        formatted_time = market_start_time
                
                # Get market status
                is_inplay = market_book.get('inplay', False)
                total_matched = market_book.get('totalMatched', 0.0)
                
                # Print market header
                print(f"\n{i+1}. {event_name} ({competition})")
                print(f"   Market ID: {market_id}")
                print(f"   Start Time: {formatted_time}")
                print(f"   In Play: {'Yes' if is_inplay else 'No'}")
                print(f"   Total Matched: £{total_matched:.2f}")
                
                # Get runners
                runners = market_book.get('runners', [])
                
                # Ensure runners are sorted by sortPriority for consistent display
                runners = sorted(runners, key=lambda r: r.get('sortPriority', 999))
                
                print("   Current Odds:")
                
                # Check our criteria
                config = self.betting_system.config_manager.get_config()
                betting_config = config.get('betting', {})
                min_odds = betting_config.get('min_odds', 3.0)
                max_odds = betting_config.get('max_odds', 4.0)
                
                for runner in runners:
                    selection_id = runner.get('selectionId')
                    team_name = runner.get('teamName', runner.get('runnerName', 'Unknown'))
                    sort_priority = runner.get('sortPriority', 'Unknown')
                    
                    # Get current best back price
                    back_prices = runner.get('ex', {}).get('availableToBack', [])
                    current_odds = back_prices[0].get('price', 0.0) if back_prices else 0.0
                    
                    # Check if odds are in our target range
                    in_range = min_odds <= current_odds <= max_odds
                    range_marker = " ✓" if in_range else ""
                    
                    # Show detailed odds information
                    print(f"     {team_name}: {current_odds}{range_marker} (ID: {selection_id}, Priority: {sort_priority})")
            
            print("\n" + "="*80)
            print(f"Target Odds Range: {min_odds} - {max_odds}")
            print("="*80 + "\n")
                
        except Exception as e:
            print(f"Error retrieving market information: {str(e)}")
            self.logger.error(f"Error retrieving market information: {str(e)}")
            self.logger.exception(e)
    
    async def cmd_bet_history(self, args: List[str] = None) -> None:
        """Display history of settled bets with commission information"""
        try:
            settled_bets = await self.betting_system.get_settled_bets()
            
            if not settled_bets:
                print("\nNo settled bets found.")
                return
                
            # Sort by settlement time (most recent first)
            sorted_bets = sorted(
                settled_bets, 
                key=lambda x: x.get('settlement_time', ''), 
                reverse=True
            )
            
            # Limit to last 10 bets by default
            max_bets = 10
            if args and len(args) > 0:
                try:
                    max_bets = int(args[0])
                except ValueError:
                    print(f"Invalid number of bets: {args[0]}. Using default: {max_bets}")
            
            display_bets = sorted_bets[:max_bets]
            
            print("\n" + "="*75)
            print(f"SETTLED BET HISTORY (Last {len(display_bets)} of {len(sorted_bets)} bets)")
            print("="*75)
            
            total_won = 0
            total_lost = 0
            total_commission = 0.0
            
            for bet in display_bets:
                market_id = bet.get("market_id")
                event_name = bet.get('event_name', 'Unknown Event')
                team_name = bet.get('team_name', 'Unknown')
                selection_id = bet.get('selection_id', 'Unknown')
                
                odds = bet.get('odds', 0.0)
                stake = bet.get('stake', 0.0)
                won = bet.get('won', False)
                
                # Get profit and commission details
                gross_profit = bet.get('gross_profit', 0.0)
                commission = bet.get('commission', 0.0)
                net_profit = bet.get('profit', 0.0)
                
                total_commission += commission if won else 0.0
                
                if won:
                    total_won += 1
                else:
                    total_lost += 1
                
                # Format settlement time
                settlement_time = bet.get('settlement_time', 'Unknown')
                formatted_settlement = settlement_time
                if settlement_time != 'Unknown':
                    try:
                        settlement_dt = datetime.fromisoformat(settlement_time)
                        formatted_settlement = settlement_dt.strftime('%Y-%m-%d %H:%M:%S')
                    except:
                        pass
                
                # Display bet details
                result_marker = "✓ WON" if won else "✗ LOST"
                
                if won:
                    profit_display = f"+£{net_profit:.2f} (Commission: £{commission:.2f})"
                else:
                    profit_display = f"-£{stake:.2f}"
                
                print(f"\n{formatted_settlement} - {result_marker} - {profit_display}")
                print(f"Event: {event_name}")
                print(f"Selection: {team_name} (ID: {selection_id}) @ {odds}")
                print(f"Stake: £{stake:.2f}")
                
                if won:
                    print(f"Gross Profit: £{gross_profit:.2f}")
                    print(f"Commission (5%): £{commission:.2f}")
                    print(f"Net Profit: £{net_profit:.2f}")
            
            # Show summary
            win_rate = (total_won / len(display_bets)) * 100 if display_bets else 0
            print("\nSummary:")
            print(f"Won: {total_won}, Lost: {total_lost}")
            print(f"Win Rate: {win_rate:.1f}%")
            print(f"Total Commission Paid: £{total_commission:.2f}")
            print("="*75 + "\n")
                
        except Exception as e:
            print(f"Error retrieving bet history: {str(e)}")
            self.logger.error(f"Error retrieving bet history: {str(e)}")
            self.logger.exception(e)
    
    async def cmd_odds_range(self, args: List[str] = None) -> None:
        """View or change target odds range"""
        try:
            config = self.betting_system.config_manager.get_config()
            betting_config = config.get('betting', {})
            
            current_min = betting_config.get('min_odds', 3.0)
            current_max = betting_config.get('max_odds', 4.0)
            
            # If no args, just display current range
            if not args or len(args) < 2:
                print(f"\nCurrent target odds range: {current_min} - {current_max}")
                print("To change, use: odds <min> <max>")
                print("Example: odds 3.0 4.0")
                return
                
            # Parse new range
            try:
                new_min = float(args[0])
                new_max = float(args[1])
                
                # Validate range
                if new_min <= 1.0:
                    print("Minimum odds must be greater than 1.0")
                    return
                    
                if new_max <= new_min:
                    print("Maximum odds must be greater than minimum odds")
                    return
                
                # Update configuration
                self.betting_system.config_manager.update_config_value('betting', 'min_odds', new_min)
                self.betting_system.config_manager.update_config_value('betting', 'max_odds', new_max)
                
                # Save configuration
                self.betting_system.config_manager.save_config()
                
                print(f"\nTarget odds range updated: {new_min} - {new_max}")
            except ValueError:
                print("Invalid odds values. Please use numeric values.")
                
        except Exception as e:
            print(f"Error updating odds range: {str(e)}")
            self.logger.error(f"Error updating odds range: {str(e)}")
            self.logger.exception(e)
    
    async def cmd_debug_info(self, args: List[str] = None) -> None:
        """Display additional debugging information"""
        try:
            print("\n" + "="*75)
            print("DEBUGGING INFORMATION")
            print("="*75)
            
            # Get selection mapper stats
            mapping_stats = await self.betting_system.market_analysis.selection_mapper.get_mapping_stats()
            
            print("\nSelection Mapper Stats:")
            print(f"Total Events: {mapping_stats.get('total_events', 0)}")
            print(f"Total Mappings: {mapping_stats.get('total_mappings', 0)}")
            
            # Get active bets
            active_bets = await self.betting_system.bet_repository.get_active_bets()
            
            if active_bets:
                print("\nActive Bet Raw Data:")
                for i, bet in enumerate(active_bets):
                    print(f"\nBet #{i+1}:")
                    for key, value in bet.items():
                        print(f"  {key}: {value}")
            
            # Get ledger information for next stake calculation
            ledger = await self.betting_system.get_ledger_info()
            next_stake = await self.betting_system.betting_ledger.get_next_stake()
            
            print("\nLedger Information:")
            print(f"Current cycle: {ledger['current_cycle']}")
            print(f"Bets in current cycle: {ledger['current_bet_in_cycle']}")
            print(f"Starting stake: £{ledger['starting_stake']:.2f}")
            print(f"Last winning profit: £{ledger.get('last_winning_profit', 0.0):.2f}")
            print(f"Next bet stake: £{next_stake:.2f}")
            print(f"Total commission paid: £{ledger.get('total_commission_paid', 0.0):.2f}")
            
            # Show system configuration
            config = self.betting_system.config_manager.get_config()
            
            print("\nSystem Configuration:")
            for section, values in config.items():
                print(f"\n{section.upper()}:")
                for key, value in values.items():
                    print(f"  {key}: {value}")
            
            print("="*75 + "\n")
                
        except Exception as e:
            print(f"Error retrieving debug information: {str(e)}")
            self.logger.error(f"Error retrieving debug information: {str(e)}")
            self.logger.exception(e)
    
    async def cmd_reset(self, args: List[str] = None) -> None:
        """Reset the betting ledger and system"""
        try:
            # Get the configured initial stake from config_manager
            config = self.betting_system.config_manager.get_config()
            configured_stake = config.get('betting', {}).get('initial_stake', 1.0)
            
            initial_stake = configured_stake  # Use configured value as default
            if args and len(args) > 0:
                try:
                    initial_stake = float(args[0])
                except ValueError:
                    print(f"Invalid stake amount: {args[0]}. Using configured default: £{configured_stake}")
            
            
            # Ask for confirmation
            print(f"\nAre you sure you want to reset the betting system with initial stake: £{initial_stake}?")
            print("This will clear all bet history and reset the account balance.")
            print("Type 'yes' to confirm or anything else to cancel.")
            
            confirm = input("> ").strip().lower()
            if confirm != 'yes':
                print("Reset cancelled.")
                return
            
            print(f"Resetting betting system with initial stake: £{initial_stake}...")
            await self.betting_system.reset_system(initial_stake)
            print("Reset complete! System is ready for new betting cycle.")
            
            # Show updated status
            await self.cmd_status()
            
        except Exception as e:
            print(f"Error during reset: {str(e)}")
            self.logger.error(f"Error during reset: {str(e)}")
            self.logger.exception(e)
    
    async def cmd_quit(self, args: List[str] = None) -> None:
        """Exit the application"""
        print("Initiating shutdown sequence...")
        self.should_exit = True
        # Actual shutdown is handled in the main loop
    
    async def process_command(self, command_line: str) -> None:
        """Process a command entered by the user"""
        parts = command_line.strip().split()
        if not parts:
            return
            
        command = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []
        
        if command in self.commands:
            try:
                await self.commands[command](args)
            except Exception as e:
                print(f"Error executing command '{command}': {str(e)}")
                self.logger.error(f"Error executing command '{command}': {str(e)}")
                self.logger.exception(e)
        else:
            print(f"Unknown command: {command}")
            print("Type 'help' for a list of available commands.")
            
    def print_countdown(self, seconds_left: int) -> None:
        """Print countdown with overwrite"""
        sys.stdout.write(f"\rNext cycle in {seconds_left} seconds. Enter command or press Enter for status: ")
        sys.stdout.flush()