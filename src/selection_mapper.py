"""
selection_mapper.py

Handles persistent mapping between Betfair selection IDs and team names.
Implements thread-safe file operations with automatic cleanup of old mappings.
"""

import json
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional, Any
import aiofiles
from filelock import FileLock

class SelectionMapper:
    def __init__(self, data_dir: str = 'web/data/betting', retention_days: int = 30):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        
        # File paths and locks
        self.mapping_file = self.data_dir / 'selection_mappings.json'
        self.lock_file = self.data_dir / 'selection_mappings.lock'
        self.file_lock = FileLock(str(self.lock_file))
        
        # Initialize cache
        self.cache: Dict[str, str] = {}
        self.cache_lock = asyncio.Lock()
        
        # Setup logging
        self.logger = logging.getLogger('SelectionMapper')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('web/logs/selection_mapper.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        
        # Initialize storage if needed
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        """Initialize storage file if it doesn't exist (sync operation during init)"""
        if not self.mapping_file.exists():
            initial_data = {
                "mappings": {},
                "last_cleanup": datetime.now(timezone.utc).isoformat()
            }
            with open(self.mapping_file, 'w') as f:
                json.dump(initial_data, f, indent=2)

    async def _load_mappings(self) -> Dict[str, Any]:
        """Load mappings from file with lock"""
        try:
            with self.file_lock:
                async with aiofiles.open(self.mapping_file, 'r') as f:
                    content = await f.read()
                    return json.loads(content)
        except Exception as e:
            self.logger.error(f"Error loading mappings: {str(e)}")
            return {"mappings": {}, "last_cleanup": datetime.now(timezone.utc).isoformat()}

    async def _save_mappings(self, data: Dict[str, Any]) -> None:
        """Save mappings to file with lock"""
        try:
            with self.file_lock:
                async with aiofiles.open(self.mapping_file, 'w') as f:
                    await f.write(json.dumps(data, indent=2))
        except Exception as e:
            self.logger.error(f"Error saving mappings: {str(e)}")
            raise

    async def _cleanup_old_mappings(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Remove mappings older than retention period"""
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
            current_mappings = data["mappings"]
            
            # Filter out old mappings
            updated_mappings = {
                selection_id: mapping_data
                for selection_id, mapping_data in current_mappings.items()
                if datetime.fromisoformat(mapping_data["created_at"]) > cutoff_date
            }
            
            # Update data with cleaned mappings
            data["mappings"] = updated_mappings
            data["last_cleanup"] = datetime.now(timezone.utc).isoformat()
            
            removed_count = len(current_mappings) - len(updated_mappings)
            if removed_count > 0:
                self.logger.info(f"Cleaned up {removed_count} old mappings")
            
            return data
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {str(e)}")
            return data

    async def add_mapping(self, selection_id: str, team_name: str) -> None:
        """
        Add or update a selection ID to team name mapping
        
        Args:
            selection_id: Betfair selection ID
            team_name: Team name to map to
        """
        try:
            # Load current mappings
            data = await self._load_mappings()
            
            # Add/update mapping
            data["mappings"][selection_id] = {
                "team_name": team_name,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            
            # Cleanup old mappings
            data = await self._cleanup_old_mappings(data)
            
            # Save updated mappings
            await self._save_mappings(data)
            
            # Update cache
            async with self.cache_lock:
                self.cache[selection_id] = team_name
                
            self.logger.info(f"Added mapping: {selection_id} -> {team_name}")
            
        except Exception as e:
            self.logger.error(f"Error adding mapping: {str(e)}")
            raise

    async def get_team_name(self, selection_id: str) -> Optional[str]:
        """
        Get team name for a selection ID
        
        Args:
            selection_id: Betfair selection ID
            
        Returns:
            Team name if found, None otherwise
        """
        try:
            # Check cache first
            async with self.cache_lock:
                if selection_id in self.cache:
                    return self.cache[selection_id]
            
            # Load from file if not in cache
            data = await self._load_mappings()
            mapping = data["mappings"].get(selection_id)
            
            if mapping:
                team_name = mapping["team_name"]
                # Update cache
                async with self.cache_lock:
                    self.cache[selection_id] = team_name
                return team_name
                
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting team name: {str(e)}")
            return None

    async def force_cleanup(self) -> None:
        """Force cleanup of old mappings"""
        try:
            data = await self._load_mappings()
            cleaned_data = await self._cleanup_old_mappings(data)
            await self._save_mappings(cleaned_data)
            
            # Clear cache after cleanup
            async with self.cache_lock:
                self.cache.clear()
                
            self.logger.info("Forced cleanup completed")
            
        except Exception as e:
            self.logger.error(f"Error during forced cleanup: {str(e)}")
            raise

    async def get_mapping_stats(self) -> Dict[str, Any]:
        """Get statistics about current mappings"""
        try:
            data = await self._load_mappings()
            mappings = data["mappings"]
            
            # Calculate stats
            total_mappings = len(mappings)
            last_cleanup = data["last_cleanup"]
            oldest_mapping = min(
                (m["created_at"] for m in mappings.values()),
                default=None
            ) if mappings else None
            
            return {
                "total_mappings": total_mappings,
                "last_cleanup": last_cleanup,
                "oldest_mapping": oldest_mapping
            }
            
        except Exception as e:
            self.logger.error(f"Error getting mapping stats: {str(e)}")
            return {
                "total_mappings": 0,
                "last_cleanup": None,
                "oldest_mapping": None
            }