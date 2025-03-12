"""
log_manager.py

Manages application logging with automatic rotation and retention.
Ensures logs are kept organized and prevents log files from growing too large.
Automatically truncates logs older than the specified retention period.
"""

import os
import logging
import glob
import shutil
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

class LogManager:
    """
    Central manager for application logging with automatic rotation and retention.
    """
    
    @staticmethod
    def setup_logger(name: str, log_file: str, level=logging.INFO, retention_days: int = 3) -> logging.Logger:
        """
        Set up a logger with time-based rotation and retention.
        
        Args:
            name: Logger name
            log_file: Path to log file
            level: Logging level
            retention_days: Number of days to keep log files
            
        Returns:
            Configured logger instance
        """
        logger = logging.getLogger(name)
        logger.setLevel(level)
        
        # Remove any existing handlers to prevent duplicates
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        
        # Create log directory if it doesn't exist
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        # Set up timed rotating handler
        handler = TimedRotatingFileHandler(
            log_file,
            when='D',  # Daily rotation
            interval=1,
            backupCount=retention_days  # Keep logs for specified days
        )
        
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        
        # Add the handler to the logger
        logger.addHandler(handler)
        
        return logger
    
    @staticmethod
    def truncate_old_logs(log_dir: str = 'web/logs', retention_days: int = 3) -> None:
        """
        Remove log files older than the specified retention period.
        
        Args:
            log_dir: Directory containing log files
            retention_days: Number of days to keep log files
        """
        try:
            print(f"Checking for old log files in {log_dir}...")
            
            # Create directory if it doesn't exist
            os.makedirs(log_dir, exist_ok=True)
            
            # Get current time
            now = datetime.now()
            cutoff = now - timedelta(days=retention_days)
            
            # Find all log files in the directory
            log_pattern = os.path.join(log_dir, '*.log*')
            log_files = glob.glob(log_pattern)
            
            removed_count = 0
            for log_file in log_files:
                # Skip directories
                if os.path.isdir(log_file):
                    continue
                    
                # Check file modification time
                file_time = datetime.fromtimestamp(os.path.getmtime(log_file))
                if file_time < cutoff:
                    try:
                        os.remove(log_file)
                        removed_count += 1
                    except Exception as e:
                        print(f"Error removing log file {log_file}: {e}")
            
            if removed_count > 0:
                print(f"Removed {removed_count} old log files")
            else:
                print("No old log files to remove")
                
        except Exception as e:
            print(f"Error truncating old logs: {e}")
    
    @staticmethod
    def truncate_large_log_file(log_file: str, max_size_mb: int = 10) -> None:
        """
        Truncate a log file if it exceeds the specified size.
        
        Args:
            log_file: Path to log file
            max_size_mb: Maximum size in megabytes
        """
        try:
            if not os.path.exists(log_file):
                return
                
            # Check file size
            file_size_mb = os.path.getsize(log_file) / (1024 * 1024)
            
            if file_size_mb > max_size_mb:
                print(f"Log file {log_file} exceeds {max_size_mb}MB (current: {file_size_mb:.2f}MB)")
                
                # Create backup with timestamp
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_file = f"{log_file}.{timestamp}.old"
                
                # Copy to backup
                shutil.copy2(log_file, backup_file)
                
                # Truncate original file
                with open(log_file, 'w') as f:
                    f.write(f"Log truncated at {datetime.now().isoformat()} - Previous content backed up to {os.path.basename(backup_file)}\n")
                
                print(f"Log file truncated and backed up to {backup_file}")
                
        except Exception as e:
            print(f"Error truncating large log file: {e}")
    
    @staticmethod
    def initialize_system_logging(log_dir: str = 'web/logs', retention_days: int = 3) -> None:
        """
        Initialize system-wide logging configuration.
        
        Args:
            log_dir: Directory for log files
            retention_days: Number of days to keep log files
        """
        try:
            # Create log directory
            os.makedirs(log_dir, exist_ok=True)
            
            # Set up root logger
            root_logger = LogManager.setup_logger(
                'root', 
                os.path.join(log_dir, 'system.log'),
                level=logging.INFO,
                retention_days=retention_days
            )
            
            # Truncate existing log files if they're too large
            for log_file in glob.glob(os.path.join(log_dir, '*.log')):
                LogManager.truncate_large_log_file(log_file)
            
            # Remove old log files
            LogManager.truncate_old_logs(log_dir, retention_days)
            
            root_logger.info(f"System logging initialized with {retention_days} day retention")
            
        except Exception as e:
            print(f"Error initializing system logging: {e}")

# Example usage in main.py:
# from src.log_manager import LogManager
# LogManager.initialize_system_logging()
# 
# # Then in each module:
# logger = LogManager.setup_logger('ComponentName', 'web/logs/component_name.log')