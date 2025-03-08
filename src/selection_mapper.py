"""
selection_mapper.py

Handles persistent mapping between Betfair selection IDs and team names.
Implements thread-safe file operations with context-aware mappings and special handling for the Draw.
"""

import json
import logging
import asyncio
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import aiofiles
from filelock import FileLock

class SelectionMapper:
    # Constants for team classification
    DRAW_VARIANTS = {'the draw', 'draw', 'empate', 'x'}
    
    # Known Draw selection ID (seems consistent across markets)
    KNOWN_DRAW_SELECTION_ID = "58805"
    
    def __init__(self, data_dir: str = 'web/data/betting', retention_days: int = 30):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        
        # File paths and locks
        self.mapping_file = self.data_dir / 'selection_mappings.json'
        self.lock_file = self.data_dir / 'selection_mappings.lock'
        self.file_lock = FileLock(str(self.lock_file))
        
        # Initialize cache with context awareness
        # Format: {event_id: {selection_id: team_name}}
        self.cache: Dict[str, Dict[str, str]] = {}
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
                "mappings": {},  # Format: {event_id: {selection_id: {team_name, created_at}}}
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
            updated_mappings = {}
            
            # Filter out old mappings while preserving event context
            for event_id, event_mappings in current_mappings.items():
                updated_event_mappings = {}
                for selection_id, mapping_data in event_mappings.items():
                    if datetime.fromisoformat(mapping_data["created_at"]) > cutoff_date:
                        updated_event_mappings[selection_id] = mapping_data
                
                if updated_event_mappings:
                    updated_mappings[event_id] = updated_event_mappings
            
            # Update data with cleaned mappings
            data["mappings"] = updated_mappings
            data["last_cleanup"] = datetime.now(timezone.utc).isoformat()
            
            return data
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {str(e)}")
            return data

    async def add_mapping(self, event_id: str, event_name: str, selection_id: str, team_name: str) -> None:
        """
        Add or update a selection ID to team name mapping with event context
        
        Args:
            event_id: Betfair event ID
            event_name: Event name for validation and logging
            selection_id: Betfair selection ID
            team_name: Team name to map to
        """
        try:
            # Special handling for known Draw selection ID
            if selection_id == self.KNOWN_DRAW_SELECTION_ID or team_name.lower() in self.DRAW_VARIANTS:
                team_name = "Draw"
                self.logger.debug(f"Recognized Draw selection: ID {selection_id}")
            else:
                # Validate team name against event name for non-draw selections
                validated_name = self._validate_team_name(event_name, team_name)
                if validated_name != team_name:
                    self.logger.info(
                        f"Team name corrected from '{team_name}' to '{validated_name}' "
                        f"based on event name '{event_name}'"
                    )
                    team_name = validated_name
            
            # Load current mappings
            data = await self._load_mappings()
            
            # Initialize event entry if needed
            if event_id not in data["mappings"]:
                data["mappings"][event_id] = {}
            
            # Add/update mapping
            data["mappings"][event_id][selection_id] = {
                "team_name": team_name,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "event_name": event_name
            }
            
            # Cleanup old mappings periodically
            if datetime.fromisoformat(data["last_cleanup"]) < datetime.now(timezone.utc) - timedelta(days=1):
                data = await self._cleanup_old_mappings(data)
            
            # Save updated mappings
            await self._save_mappings(data)
            
            # Update cache
            async with self.cache_lock:
                if event_id not in self.cache:
                    self.cache[event_id] = {}
                self.cache[event_id][selection_id] = team_name
                
            self.logger.info(
                f"Added mapping: Event '{event_name}' ({event_id}), "
                f"Selection ID {selection_id} -> '{team_name}'"
            )
            
        except Exception as e:
            self.logger.error(f"Error adding mapping: {str(e)}")
            self.logger.exception(e)
            raise

    def _validate_team_name(self, event_name: str, team_name: str) -> str:
        """
        Validate and potentially correct team name based on event name
        
        Args:
            event_name: Event name (typically "Team1 v Team2")
            team_name: Team name to validate
            
        Returns:
            Validated/corrected team name
        """
        # Skip validation for the Draw
        if team_name.lower() in self.DRAW_VARIANTS:
            return "Draw"
            
        try:
            # Extract teams from event name
            match = re.match(r'(.*?)\s+v(?:s)?\.?\s+(.*)', event_name, re.IGNORECASE)
            if not match:
                return team_name
                
            home_team, away_team = match.groups()
            
            # Normalize names for comparison
            home_team = home_team.strip().lower()
            away_team = away_team.strip().lower()
            team_name_lower = team_name.lower()
            
            # Check if the provided team name is already one of the teams
            if self._name_similarity(team_name_lower, home_team) > 0.6:
                return home_team.title()
            elif self._name_similarity(team_name_lower, away_team) > 0.6:
                return away_team.title()
                
            # If team name doesn't match either team in the event name,
            # return the original for now but log a warning
            self.logger.warning(
                f"Team name '{team_name}' doesn't match either team in event '{event_name}'"
            )
            return team_name
            
        except Exception as e:
            self.logger.error(f"Error validating team name: {str(e)}")
            return team_name

    def _name_similarity(self, name1: str, name2: str) -> float:
        """
        Calculate similarity between two team names
        
        Args:
            name1: First team name
            name2: Second team name
            
        Returns:
            Similarity score (0-1)
        """
        # Simple implementation - more sophisticated methods could be used
        name1_words = set(name1.split())
        name2_words = set(name2.split())
        
        if not name1_words or not name2_words:
            return 0
            
        common_words = name1_words.intersection(name2_words)
        return len(common_words) / max(len(name1_words), len(name2_words))

    async def get_team_name(self, event_id: str, selection_id: str) -> Optional[str]:
        """
        Get team name for a selection ID within a specific event context
        
        Args:
            event_id: Betfair event ID
            selection_id: Betfair selection ID
            
        Returns:
            Team name if found, None otherwise
        """
        try:
            # Special handling for known Draw selection ID
            if selection_id == self.KNOWN_DRAW_SELECTION_ID:
                return "Draw"
                
            # Check cache first
            async with self.cache_lock:
                if event_id in self.cache and selection_id in self.cache[event_id]:
                    return self.cache[event_id][selection_id]
            
            # Load from file if not in cache
            data = await self._load_mappings()
            
            if event_id in data["mappings"] and selection_id in data["mappings"][event_id]:
                team_name = data["mappings"][event_id][selection_id]["team_name"]
                
                # Update cache
                async with self.cache_lock:
                    if event_id not in self.cache:
                        self.cache[event_id] = {}
                    self.cache[event_id][selection_id] = team_name
                    
                return team_name
                
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting team name: {str(e)}")
            self.logger.exception(e)
            return None

    async def derive_teams_from_event(self, event_id: str, event_name: str, runners: List[Dict]) -> List[Dict]:
        """
        Derive team mappings from event name and runners data
        
        Args:
            event_id: Betfair event ID
            event_name: Event name (typically "Home v Away")
            runners: List of runner dictionaries from Betfair
            
        Returns:
            Updated runners list with proper team names
        """
        try:
            # First, log all runners to help with debugging
            self.logger.info(f"Processing event: '{event_name}' (ID: {event_id})")
            for runner in runners:
                self.logger.debug(
                    f"Runner: ID {runner.get('selectionId')}, Name: '{runner.get('teamName', 'Unknown')}'"
                )
            
            # Extract home and away teams from event name
            match = re.match(r'(.*?)\s+v(?:s)?\.?\s+(.*)', event_name, re.IGNORECASE)
            if not match:
                self.logger.warning(f"Couldn't parse teams from event name: {event_name}")
                return runners
                
            home_team, away_team = match.groups()
            home_team = home_team.strip()
            away_team = away_team.strip()
            
            # Identify the draw selection and team runners
            draw_runner = None
            team_runners = []
            
            for runner in runners:
                selection_id = str(runner.get('selectionId', ''))
                original_name = runner.get('teamName', '')
                
                # Special handling for the known Draw selection ID
                if selection_id == self.KNOWN_DRAW_SELECTION_ID or original_name.lower() in self.DRAW_VARIANTS:
                    draw_runner = runner
                    runner['teamName'] = 'Draw'
                    await self.add_mapping(event_id, event_name, selection_id, 'Draw')
                else:
                    team_runners.append(runner)
            
            # Map team runners to home and away
            if len(team_runners) >= 2:
                # First runner is home team
                home_runner = team_runners[0]
                home_runner['teamName'] = home_team
                await self.add_mapping(
                    event_id, 
                    event_name, 
                    str(home_runner.get('selectionId', '')),
                    home_team
                )
                
                # Second runner is away team
                away_runner = team_runners[1]
                away_runner['teamName'] = away_team
                await self.add_mapping(
                    event_id,
                    event_name,
                    str(away_runner.get('selectionId', '')),
                    away_team
                )
                
                self.logger.info(
                    f"Mapped teams for event '{event_name}': "
                    f"Home={home_team} (ID: {home_runner.get('selectionId')}), "
                    f"Away={away_team} (ID: {away_runner.get('selectionId')})"
                )
            else:
                self.logger.warning(
                    f"Not enough team runners found for event '{event_name}'. "
                    f"Found {len(team_runners)} team runners."
                )
            
            return runners
            
        except Exception as e:
            self.logger.error(f"Error deriving teams from event: {str(e)}")
            self.logger.exception(e)
            return runners

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
            total_events = len(mappings)
            total_mappings = sum(len(event_mappings) for event_mappings in mappings.values())
            last_cleanup = data["last_cleanup"]
            
            # Find oldest mapping
            oldest_mapping = None
            for event_mappings in mappings.values():
                for mapping_data in event_mappings.values():
                    if oldest_mapping is None or mapping_data["created_at"] < oldest_mapping:
                        oldest_mapping = mapping_data["created_at"]
            
            return {
                "total_events": total_events,
                "total_mappings": total_mappings,
                "last_cleanup": last_cleanup,
                "oldest_mapping": oldest_mapping
            }
            
        except Exception as e:
            self.logger.error(f"Error getting mapping stats: {str(e)}")
            return {
                "total_events": 0,
                "total_mappings": 0,
                "last_cleanup": None,
                "oldest_mapping": None
            }