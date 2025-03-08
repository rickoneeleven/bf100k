"""
command_processor.py

Handles command line input processing for the betting system.
Provides interactive commands during system operation.
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
            print(f"Highest Balance Reached: £{ledger['highest_balance']:.2f}")
            print("="*60 + "\n")
        except Exception as e:
            print(f"Error displaying status: {str(e)}")
            self.logger.error(f"Error displaying status: {str(e)}")
    
    async def cmd_reset(self, args: List[str] = None) -> None:
        """Reset the betting ledger and system"""
        try:
            initial_stake = 1.0
            if args and len(args) > 0:
                try:
                    initial_stake = float(args[0])
                except ValueError:
                    print(f"Invalid stake amount: {args[0]}. Using default: £1.0")
            
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