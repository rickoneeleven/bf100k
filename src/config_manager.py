"""
config_manager.py

Manages configuration settings for the betting system.
Handles loading, validation, and access to configurable parameters.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
import aiofiles

class ConfigManager:
    def __init__(self, config_file: str = 'config/betting_config.json'):
        self.config_file = Path(config_file)
        self.config_dir = self.config_file.parent
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Default configuration
        self.default_config = {
            "betting": {
                "initial_stake": 1.0,  # Starting stake amount in GBP
                "target_amount": 50000.0,  # Target goal amount in GBP
                "min_odds": 3.0,  # Minimum odds to consider for betting
                "max_odds": 4.0,  # Maximum odds to consider for betting
                "liquidity_factor": 1.1,  # Required liquidity multiplier (stake * factor)
            },
            "market_selection": {
                "max_markets": 10,  # Maximum number of markets to retrieve
                "sport_id": "1",  # 1 = Soccer/Football
                "market_type": "MATCH_ODDS",  # Market type to focus on
                "max_polling_attempts": 60,  # Number of attempts to find matching markets
                "polling_interval_seconds": 60  # Seconds between polling attempts
            },
            "result_checking": {
                "check_interval_minutes": 5,  # Minutes between result checks
                "max_check_attempts": 24,  # Maximum number of result check attempts
                "event_timeout_hours": 12  # Hours after which to consider an event timed out
            },
            "system": {
                "dry_run": True,  # Default to dry run for safety
                "log_level": "INFO"  # Logging level
            }
        }
        
        # Setup logging
        self.logger = logging.getLogger('ConfigManager')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('web/logs/config_manager.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        
        # Ensure config file exists with defaults
        self._ensure_config_file()
        
        # Current loaded configuration
        self.config = self.default_config.copy()
        
    def _ensure_config_file(self) -> None:
        """Ensure config file exists with default values if it doesn't exist"""
        if not self.config_file.exists():
            self.logger.info(f"Creating default configuration file at {self.config_file}")
            with open(self.config_file, 'w') as f:
                json.dump(self.default_config, f, indent=2)
                
    def load_config(self) -> Dict[str, Any]:
        """
        Load configuration from file (synchronous version)
        Used during initialization
        
        Returns:
            Dict containing configuration values
        """
        try:
            if not self.config_file.exists():
                self.logger.warning(f"Config file not found at {self.config_file}, using defaults")
                return self.default_config
                
            with open(self.config_file, 'r') as f:
                config = json.load(f)
                
            # Validate and merge with defaults to ensure all keys exist
            # Even if the config file is missing some settings
            result = self._merge_with_defaults(config)
            self.config = result
            self.logger.info(f"Configuration loaded from {self.config_file}")
            return result
            
        except Exception as e:
            self.logger.error(f"Error loading configuration: {str(e)}")
            self.logger.warning("Using default configuration")
            return self.default_config
            
    async def load_config_async(self) -> Dict[str, Any]:
        """
        Load configuration from file asynchronously
        
        Returns:
            Dict containing configuration values
        """
        try:
            if not self.config_file.exists():
                self.logger.warning(f"Config file not found at {self.config_file}, using defaults")
                return self.default_config
                
            async with aiofiles.open(self.config_file, 'r') as f:
                content = await f.read()
                config = json.loads(content)
                
            # Validate and merge with defaults to ensure all keys exist
            result = self._merge_with_defaults(config)
            self.config = result
            self.logger.info(f"Configuration loaded asynchronously from {self.config_file}")
            return result
            
        except Exception as e:
            self.logger.error(f"Error loading configuration asynchronously: {str(e)}")
            self.logger.warning("Using default configuration")
            return self.default_config
            
    def _merge_with_defaults(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge loaded configuration with defaults to ensure all required keys exist
        
        Args:
            config: Loaded configuration
            
        Returns:
            Complete configuration with defaults for missing values
        """
        result = self.default_config.copy()
        
        # Update with values from loaded config
        for section, values in config.items():
            if section in result:
                if isinstance(values, dict) and isinstance(result[section], dict):
                    # Merge section dictionaries
                    for key, value in values.items():
                        if key in result[section]:
                            result[section][key] = value
                        else:
                            self.logger.warning(f"Unknown configuration key: {section}.{key}")
                else:
                    # Override entire section
                    result[section] = values
            else:
                self.logger.warning(f"Unknown configuration section: {section}")
                
        return result
        
    async def save_config_async(self, config: Dict[str, Any] = None) -> None:
        """
        Save configuration to file asynchronously
        
        Args:
            config: Configuration to save (uses current config if None)
        """
        try:
            if config is None:
                config = self.config
                
            # Ensure directory exists
            self.config_dir.mkdir(parents=True, exist_ok=True)
            
            async with aiofiles.open(self.config_file, 'w') as f:
                await f.write(json.dumps(config, indent=2))
                
            self.logger.info(f"Configuration saved to {self.config_file}")
            
        except Exception as e:
            self.logger.error(f"Error saving configuration: {str(e)}")
            raise
            
    def save_config(self, config: Dict[str, Any] = None) -> None:
        """
        Save configuration to file (synchronous version)
        
        Args:
            config: Configuration to save (uses current config if None)
        """
        try:
            if config is None:
                config = self.config
                
            # Ensure directory exists
            self.config_dir.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
                
            self.logger.info(f"Configuration saved to {self.config_file}")
            
        except Exception as e:
            self.logger.error(f"Error saving configuration: {str(e)}")
            raise
            
    def get_config(self) -> Dict[str, Any]:
        """
        Get the current configuration
        
        Returns:
            Current configuration dictionary
        """
        return self.config
        
    def get_betting_config(self) -> Dict[str, Any]:
        """Get betting-specific configuration"""
        return self.config.get("betting", self.default_config["betting"])
        
    def get_market_selection_config(self) -> Dict[str, Any]:
        """Get market selection configuration"""
        return self.config.get("market_selection", self.default_config["market_selection"])
        
    def get_result_checking_config(self) -> Dict[str, Any]:
        """Get result checking configuration"""
        return self.config.get("result_checking", self.default_config["result_checking"])
        
    def get_system_config(self) -> Dict[str, Any]:
        """Get system configuration"""
        return self.config.get("system", self.default_config["system"])
        
    def update_config_value(self, section: str, key: str, value: Any) -> bool:
        """
        Update a specific configuration value
        
        Args:
            section: Configuration section
            key: Configuration key
            value: New value
            
        Returns:
            bool: True if update was successful, False otherwise
        """
        try:
            if section not in self.config:
                self.logger.error(f"Unknown configuration section: {section}")
                return False
                
            if key not in self.config[section]:
                self.logger.error(f"Unknown configuration key: {section}.{key}")
                return False
                
            # Validate value type
            current_value = self.config[section][key]
            if not isinstance(value, type(current_value)):
                self.logger.error(
                    f"Invalid value type for {section}.{key}. "
                    f"Expected {type(current_value).__name__}, got {type(value).__name__}"
                )
                return False
                
            # Update value
            self.config[section][key] = value
            self.logger.info(f"Updated configuration: {section}.{key} = {value}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error updating configuration: {str(e)}")
            return False
            
    async def get_initial_stake(self) -> float:
        """Convenience method to get initial stake"""
        betting_config = self.get_betting_config()
        return float(betting_config.get("initial_stake", 1.0))
        
    async def get_target_amount(self) -> float:
        """Convenience method to get target amount"""
        betting_config = self.get_betting_config()
        return float(betting_config.get("target_amount", 50000.0))
        
    async def get_odds_range(self) -> tuple[float, float]:
        """Convenience method to get odds range"""
        betting_config = self.get_betting_config()
        min_odds = float(betting_config.get("min_odds", 3.0))
        max_odds = float(betting_config.get("max_odds", 4.0))
        return min_odds, max_odds
        
    async def is_dry_run(self) -> bool:
        """Convenience method to check if in dry run mode"""
        system_config = self.get_system_config()
        return bool(system_config.get("dry_run", True))