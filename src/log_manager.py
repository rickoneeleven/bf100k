"""
log_manager.py

Improved log management with proper rotation and truncation.
"""

import os
import logging
import glob
import shutil
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional
import io

class LogManager:
    """Manages application logging with automatic rotation and size limits."""
    
    @staticmethod
    def setup_logger(
        name: str, 
        log_file: str, 
        level=logging.INFO, 
        retention_days: int = 3,
        max_size_mb: int = 5
    ) -> logging.Logger:
        """
        Set up a logger with time-based rotation and size limits.
        
        Args:
            name: Logger name
            log_file: Path to log file
            level: Logging level
            retention_days: Number of days to keep log files
            max_size_mb: Maximum size in MB before rotation
            
        Returns:
            Configured logger instance
        """
        logger = logging.getLogger(name)
        logger.setLevel(level)
        
        # Remove any existing handlers
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        
        # Create log directory
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        # Custom handler that handles both time and size rotation
        class SizeRotatingHandler(TimedRotatingFileHandler):
            def __init__(self, filename, max_bytes=0, **kwargs):
                self.max_bytes = max_bytes
                super().__init__(filename, **kwargs)
                
            def emit(self, record):
                # Check file size before emitting
                try:
                    if os.path.exists(self.baseFilename):
                        if os.path.getsize(self.baseFilename) >= self.max_bytes:
                            self.doRollover()
                except Exception:
                    pass
                super().emit(record)
        
        # Set up handler
        handler = SizeRotatingHandler(
            log_file,
            when='D',  # Daily rotation
            interval=1,
            backupCount=retention_days,
            max_bytes=max_size_mb * 1024 * 1024  # Convert MB to bytes
        )
        
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        return logger
    
    @staticmethod
    def truncate_old_logs(log_dir: str = 'web/logs', retention_days: int = 3) -> None:
        """Remove log files older than retention period."""
        try:
            print(f"Removing logs older than {retention_days} days in {log_dir}")
            
            # Create directory if it doesn't exist
            os.makedirs(log_dir, exist_ok=True)
            
            # Get current time
            now = datetime.now()
            cutoff = now - timedelta(days=retention_days)
            
            # Find all log files in the directory
            log_pattern = os.path.join(log_dir, '*.log*')
            log_files = glob.glob(log_pattern)
            
            for log_file in log_files:
                # Skip directories
                if os.path.isdir(log_file):
                    continue
                    
                # Check file modification time
                file_time = datetime.fromtimestamp(os.path.getmtime(log_file))
                if file_time < cutoff:
                    print(f"Removing old log file: {log_file}")
                    try:
                        os.remove(log_file)
                    except Exception as e:
                        print(f"Error removing {log_file}: {e}")
                
        except Exception as e:
            print(f"Error truncating old logs: {e}")
    
    @staticmethod
    def truncate_large_log_file(log_file: str, max_size_mb: int = 5) -> None:
        """Truncate a log file if it exceeds the specified size."""
        try:
            if not os.path.exists(log_file):
                return
                
            # Check file size
            file_size_mb = os.path.getsize(log_file) / (1024 * 1024)
            
            if file_size_mb > max_size_mb:
                print(f"Truncating log file {log_file} ({file_size_mb:.2f}MB)")
                
                # Read the last 1000 lines (this is more reliable than truncating)
                with open(log_file, 'r') as f:
                    # Use deque for better performance with large files
                    lines = []
                    for line in f:
                        lines.append(line)
                        if len(lines) > 1000:
                            lines.pop(0)
                
                # Write back only the last 1000 lines
                with open(log_file, 'w') as f:
                    f.write(f"Log truncated at {datetime.now().isoformat()} - Keeping last 1000 lines\n")
                    f.writelines(lines)
                
                print(f"Log file truncated to last 1000 lines")
                
        except Exception as e:
            print(f"Error truncating log file: {e}")
    
    @staticmethod
    def initialize_logging(log_dir: str = 'web/logs', retention_days: int = 3) -> None:
        """
        Initialize system-wide logging configuration.
        
        Args:
            log_dir: Directory for log files
            retention_days: Number of days to keep log files
        """
        try:
            # Create log directory
            os.makedirs(log_dir, exist_ok=True)
            
            # Remove old log files
            LogManager.truncate_old_logs(log_dir, retention_days)
            
            # Truncate existing log files if they're too large
            for log_file in glob.glob(os.path.join(log_dir, '*.log')):
                LogManager.truncate_large_log_file(log_file)
            
            # Set up root logger
            root_logger = LogManager.setup_logger(
                'root', 
                os.path.join(log_dir, 'system.log'),
                level=logging.INFO,
                retention_days=retention_days
            )
            
            # Add console output for development
            console = logging.StreamHandler()
            console.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            console.setFormatter(formatter)
            root_logger.addHandler(console)
            
            root_logger.info(f"Logging initialized with {retention_days} day retention")
            
        except Exception as e:
            print(f"Error initializing logging: {e}")