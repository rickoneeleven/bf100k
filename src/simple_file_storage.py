"""
simple_file_storage.py

Provides atomic file operations for safely reading and writing JSON data.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional
import shutil
import tempfile

class SimpleFileStorage:
    """Simple storage class that provides atomic file operations."""
    
    def __init__(self, data_dir: str):
        """
        Initialize storage with data directory.
        
        Args:
            data_dir: Directory for storing data files
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger('SimpleFileStorage')
    
    def read_json(self, filename: str, default: Optional[Dict] = None) -> Dict:
        """
        Read JSON data from a file with error handling.
        
        Args:
            filename: Name of the file to read
            default: Default data to return if file doesn't exist or can't be read
            
        Returns:
            Dictionary containing file data or default value
        """
        file_path = self.data_dir / filename
        
        if not file_path.exists():
            self.logger.info(f"File {filename} not found, returning default")
            return default if default is not None else {}
        
        try:
            # Read directly without locking - we use atomic writes for consistency
            with open(file_path, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            self.logger.error(f"Error decoding JSON from {filename}")
            return default if default is not None else {}
        except Exception as e:
            self.logger.error(f"Error reading {filename}: {str(e)}")
            return default if default is not None else {}
    
    def write_json(self, filename: str, data: Dict) -> bool:
        """
        Write JSON data to a file atomically.
        
        Args:
            filename: Name of the file to write
            data: Dictionary data to write
            
        Returns:
            True if successful, False otherwise
        """
        file_path = self.data_dir / filename
        
        try:
            # Write to temporary file first
            with tempfile.NamedTemporaryFile(mode='w', dir=self.data_dir, delete=False) as temp_file:
                json.dump(data, temp_file, indent=2)
                temp_file_path = temp_file.name
            
            # Replace the original file with the temporary file atomically
            shutil.move(temp_file_path, file_path)
            return True
        except Exception as e:
            self.logger.error(f"Error writing {filename}: {str(e)}")
            # Clean up temporary file if it exists
            if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except:
                    pass
            return False