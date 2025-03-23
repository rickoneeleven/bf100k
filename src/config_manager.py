"""
config_manager.py

Simplified configuration management.
Path updated to use web/config directory for web accessibility.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

class ConfigManager:
    def __init__(self, config_file: str = 'web/config/betting_config.json'):
        self.config_file = Path(config_file)
        self.config_dir = self.config_file.parent
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Default configuration
        self.default_config = {
        "betting": {
            "initial_stake": 1.0,
            "target_amount": 50000.0,
            "liquidity_factor": 1.1,
            "min_odds": 3.5,         # Minimum odds to consider for any selection
            "min_liquidity": 100000  # Minimum matched amount on market (£100k)
        },
        "market_selection": {
            "max_markets": 1000,  # Total markets to fetch
            "top_markets": 10,    # Number of top markets to analyze
            "hours_ahead": 4,     # Hours ahead to search for markets
            "sport_id": "1",
            "market_type": "MATCH_ODDS",
            "polling_interval_seconds": 60,
            "include_inplay": True  # Include in-play markets in search
        },
        "result_checking": {
            "check_interval_minutes": 5,
            "event_timeout_hours": 12
        },
        "system": {
            "dry_run": True,
            "log_level": "INFO"
        }
    }
            
        # Setup logging
        self.logger = logging.getLogger('ConfigManager')
        
        # Ensure config file exists
        self._ensure_config_file()
        
        # Load configuration
        self.config = self.load_config()
        
    def _ensure_config_file(self) -> None:
        """Ensure config file exists with default values if it doesn't exist"""
        if not self.config_file.exists():
            self.logger.info(f"Creating default configuration file at {self.config_file}")
            with open(self.config_file, 'w') as f:
                json.dump(self.default_config, f, indent=2)
                
    def load_config(self) -> Dict[str, Any]:
        """Load configuration from file"""
        try:
            if not self.config_file.exists():
                self.logger.warning(f"Config file not found at {self.config_file}, using defaults")
                return self.default_config
                
            with open(self.config_file, 'r') as f:
                config = json.load(f)
                
            # Merge with defaults for missing keys
            result = self._merge_with_defaults(config)
            self.logger.info(f"Configuration loaded from {self.config_file}")
            return result
            
        except Exception as e:
            self.logger.error(f"Error loading configuration: {str(e)}")
            return self.default_config
            
    def _merge_with_defaults(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Merge loaded configuration with defaults for missing values"""
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
                    # Override entire section
                    result[section] = values
                    
        return result
        
    def save_config(self) -> None:
        """Save configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
                
            self.logger.info(f"Configuration saved to {self.config_file}")
            
        except Exception as e:
            self.logger.error(f"Error saving configuration: {str(e)}")
            
    def get_config(self) -> Dict[str, Any]:
        """Get the current configuration"""
        return self.config
        
    def update_config_value(self, section: str, key: str, value: Any) -> bool:
        """
        Update a specific configuration value
        
        Args:
            section: Configuration section
            key: Configuration key
            value: New value
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if section not in self.config:
                self.logger.error(f"Unknown configuration section: {section}")
                return False
                
            if key not in self.config[section]:
                self.logger.error(f"Unknown configuration key: {section}.{key}")
                return False
                
            # Update value
            self.config[section][key] = value
            self.logger.info(f"Updated configuration: {section}.{key} = {value}")
            
            # Save updated config
            self.save_config()
            return True
            
        except Exception as e:
            self.logger.error(f"Error updating configuration: {str(e)}")
            return False