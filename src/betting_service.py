"""
betting_service.py

Main betting service that coordinates betting operations.
Refactored to use actual Betfair results in both live and dry run modes.
"""

import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

from .betfair_client import BetfairClient
from .betting_state_manager import BettingStateManager
from .config_manager import ConfigManager

class BettingService:
    """
    Main service that coordinates betting operations with simplified flow.
    """
    
    def __init__(
        self,
        betfair_client: BetfairClient,
        state_manager: BettingStateManager,
        config_manager: ConfigManager
    ):
        self.betfair_client = betfair_client
        self.state_manager = state_manager
        self.config_manager = config_manager
        
        # Get configuration
        self.config = config_manager.get_config()
        self.dry_run = self.config.get('system', {}).get('dry_run', True)
        
        # Setup logging
        self.logger = logging.getLogger('BettingService')
        
        # Shutdown flag
        self.shutdown_flag = False
    
    async def scan_markets(self) -> Optional[Dict]:
        """
        Scan available markets for betting opportunities with focus on high-liquidity markets.
        
        Returns:
            Dict containing betting opportunity if found, None otherwise
        """
        try:
            # Skip if there's an active bet
            if self.state_manager.has_active_bet():
                self.logger.info("Active bet exists - skipping market scan")
                return None
            
            # Get betting configuration
            betting_config = self.config.get('betting', {})
            liquidity_factor = betting_config.get('liquidity_factor', 1.1)
            
            # Get next stake amount
            next_stake = self.state_manager.get_next_stake()
            
            # Get current state
            state = self.state_manager.get_current_state()
            
            self.logger.info(
                f"Scanning markets - Cycle #{state.current_cycle}, "
                f"Bet #{state.current_bet_in_cycle + 1} in cycle, "
                f"Next stake: £{next_stake:.2f}"
            )
            
            # Get football markets for the next 4 hours
            market_config = self.config.get('market_selection', {})
            max_markets = market_config.get('max_markets', 1000)  # Request a large number of markets
            hours_ahead = market_config.get('hours_ahead', 4)     # Look 4 hours ahead
            markets = await self.betfair_client.get_football_markets(max_markets, hours_ahead)
            
            if not markets:
                self.logger.info("No markets found")
                return None
            
            # Markets should already be sorted by MAXIMUM_TRADED from the API call
            # Take only the top N markets with the highest traded volume
            top_markets_limit = market_config.get('top_markets', 10)  # Default to top 10
            top_markets = markets[:top_markets_limit]
            
            self.logger.info(f"Analyzing the top {len(top_markets)} markets by traded volume out of {len(markets)} total markets")
            
            # Log the selected markets to provide visibility
            for idx, market in enumerate(top_markets):
                market_id = market.get('marketId')
                event = market.get('event', {})
                event_name = event.get('name', 'Unknown Event')
                total_matched = market.get('totalMatched', 0)
                market_start = market.get('marketStartTime', 'Unknown')
                
                self.logger.info(
                    f"Top Market #{idx+1}: {event_name} (ID: {market_id}), "
                    f"Total Matched: £{total_matched}, Start: {market_start}"
                )
            
            # Analyze each of the top markets sequentially
            for market in top_markets:
                market_id = market.get('marketId')
                event = market.get('event', {})
                event_name = event.get('name', 'Unknown Event')
                
                self.logger.info(f"Analyzing market: {event_name} (ID: {market_id})")
                
                # Get detailed market data
                market_data = await self.betfair_client.get_market_data(market_id)
                
                if not market_data:
                    self.logger.warning(f"Could not get data for market {market_id}")
                    continue
                
                # We're no longer skipping in-play markets
                
                # Get event details
                event_id = event.get('id', 'Unknown')
                
                # Process runners
                runners = market_data.get('runners', [])
                
                # Sort runners by sortPriority
                runners = sorted(runners, key=lambda r: r.get('sortPriority', 999))
                
                # Find the Draw selection (usually has ID 58805 or team name "Draw")
                draw_runner = None
                for runner in runners:
                    selection_id = str(runner.get('selectionId', ''))
                    team_name = runner.get('teamName', '').lower()
                    
                    if selection_id == '58805' or team_name == 'draw' or team_name == 'the draw':
                        draw_runner = runner
                        break
                
                if not draw_runner:
                    self.logger.debug(f"No Draw selection found in market {market_id}")
                    continue
                
                # Get Draw odds
                draw_ex = draw_runner.get('ex', {})
                draw_available_to_back = draw_ex.get('availableToBack', [{}])[0]
                
                if not draw_available_to_back:
                    self.logger.debug("No back prices available for Draw")
                    continue
                
                draw_odds = draw_available_to_back.get('price', 0)
                draw_available_size = draw_available_to_back.get('size', 0)
                
                # Check liquidity against the stake plus liquidity factor
                if draw_available_size < next_stake * liquidity_factor:
                    self.logger.debug(
                        f"Insufficient liquidity: {draw_available_size} < "
                        f"{next_stake * liquidity_factor} (stake * factor)"
                    )
                    continue
                
                # Get odds for both teams to check if Draw odds are higher
                team_runners = [r for r in runners if r != draw_runner]
                team_odds = []
                
                for team_runner in team_runners:
                    team_ex = team_runner.get('ex', {})
                    team_available_to_back = team_ex.get('availableToBack', [{}])[0]
                    if team_available_to_back:
                        team_odds.append(team_available_to_back.get('price', 0))
                
                # Check if Draw odds are higher than both team odds
                if len(team_odds) >= 2 and not all(draw_odds > team_odd for team_odd in team_odds):
                    self.logger.debug(f"Draw odds {draw_odds} not higher than both team odds {team_odds}")
                    continue
                
                # Found a betting opportunity
                self.logger.info(
                    f"Found betting opportunity: {event_name}, "
                    f"Draw @ {draw_odds}, Available: £{draw_available_size}"
                )
                
                # Create bet details
                bet_details = {
                    "market_id": market_id,
                    "event_id": event_id,
                    "event_name": event_name,
                    "selection_id": draw_runner.get('selectionId'),
                    "team_name": "Draw",
                    "competition": market_data.get('competition', {}).get('name', 'Unknown'),
                    "odds": draw_odds,
                    "stake": next_stake,
                    "available_volume": draw_available_size,
                    "market_start_time": market_data.get('marketStartTime')
                }
                
                return bet_details
            
            # No suitable markets found
            self.logger.info("No suitable betting opportunities found in the top markets")
            return None
            
        except Exception as e:
            self.logger.error(f"Error scanning markets: {str(e)}")
            return None

    async def place_bet(self, bet_details: Dict) -> bool:
        """
        Place a bet based on identified opportunity.
        In dry run mode, this simulates bet placement without actually placing a bet.
        
        Args:
            bet_details: Dict containing betting opportunity details
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.logger.info(
                f"Placing bet on event: {bet_details.get('event_name')}, "
                f"Selection: {bet_details.get('team_name')}, "
                f"Odds: {bet_details.get('odds')}, "
                f"Stake: £{bet_details.get('stake')}"
            )
            
            if self.dry_run:
                self.logger.info(
                    f"[DRY RUN] Simulating bet placement: "
                    f"Match: {bet_details.get('event_name')}, "
                    f"Selection: {bet_details.get('team_name')}, "
                    f"Odds: {bet_details.get('odds')}, "
                    f"Stake: £{bet_details.get('stake')}"
                )
                
                # Record bet in state manager
                self.state_manager.record_bet_placed(bet_details)
                return True
            
            # TODO: Implement actual Betfair bet placement in live mode
            # For now, just record the bet in our state manager
            self.state_manager.record_bet_placed(bet_details)
            return True
            
        except Exception as e:
            self.logger.error(f"Error placing bet: {str(e)}")
            return False

    async def check_bet_result(self) -> bool:
        """
        Check the result of the current active bet using actual Betfair results
        regardless of dry run status.
        
        Returns:
            True if bet was settled, False otherwise
        """
        try:
            # Get active bet
            active_bet = self.state_manager.get_active_bet()
            if not active_bet:
                return False
                
            market_id = active_bet.get('market_id')
            selection_id = active_bet.get('selection_id')
            team_name = active_bet.get('team_name', 'Unknown')
            
            self.logger.info(
                f"Checking result for bet: Market {market_id}, "
                f"Selection {selection_id} ({team_name})"
            )
            
            # Get market data to check status
            market_data = await self.betfair_client.get_market_data(market_id)
            if not market_data:
                self.logger.warning(f"Could not retrieve market data for {market_id}")
                return False
                
            # Check if market is settled
            market_status = market_data.get('status')
            if market_status not in ['CLOSED', 'SETTLED']:
                # Check if the market should have timed out based on start time
                if self._should_timeout_bet(active_bet, market_data):
                    self.logger.warning(f"Market {market_id} has timed out. Forcing settlement as loss.")
                    # Force settlement as a loss
                    won = False
                    result_message = "Market timed out"
                else:
                    self.logger.info(f"Market not yet settled. Current status: {market_status}")
                    return False
            else:
                # Get actual result from Betfair
                won, result_message = await self.betfair_client.get_market_result(
                    market_id, selection_id
                )
                
                self.logger.info(f"Using actual Betfair result: {result_message}")
            
            # Calculate profit and commission
            stake = active_bet.get('stake', 0.0)
            odds = active_bet.get('odds', 0.0)
            
            if won:
                gross_profit = stake * (odds - 1)
                commission = gross_profit * 0.05  # 5% Betfair commission
                net_profit = gross_profit - commission
                
                self.logger.info(
                    f"Bet won! Gross profit: £{gross_profit:.2f}, "
                    f"Commission: £{commission:.2f}, "
                    f"Net profit: £{net_profit:.2f}"
                )
            else:
                gross_profit = 0
                commission = 0
                net_profit = 0
                
                self.logger.info(f"Bet lost. Lost stake: £{stake:.2f}")
            
            # Record result in state manager
            self.state_manager.record_bet_result(
                active_bet, won, net_profit, commission
            )
            
            # Check if target amount reached
            if won and self.state_manager.check_target_reached():
                self.logger.info("Target amount reached! Starting new cycle.")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error checking bet result: {str(e)}")
            return False
    
    def _should_timeout_bet(self, bet: Dict, market_data: Dict) -> bool:
        """
        Determine if a bet should be timed out based on market start time
        and current time.
        
        Args:
            bet: Bet details
            market_data: Current market data
            
        Returns:
            True if the bet should timeout, False otherwise
        """
        try:
            now = datetime.now(timezone.utc)
            
            # Get market start time from market data or bet details
            market_start_time = None
            if 'marketStartTime' in market_data:
                market_start_time = datetime.fromisoformat(
                    market_data['marketStartTime'].replace('Z', '+00:00')
                )
            elif 'market_start_time' in bet:
                market_start_time = datetime.fromisoformat(
                    bet['market_start_time'].replace('Z', '+00:00')
                )
            
            # Get bet placement time
            placement_time = datetime.fromisoformat(bet['timestamp'])
            
            # If market is in-play, check how long it's been in-play
            is_inplay = market_data.get('inplay', False)
            if is_inplay and market_start_time:
                # Most sports events don't last more than 4 hours
                inplay_duration = now - market_start_time
                max_inplay_hours = 4
                
                if inplay_duration.total_seconds() > max_inplay_hours * 3600:
                    self.logger.info(
                        f"Market has been in-play for {inplay_duration.total_seconds() / 3600:.1f} hours, "
                        f"exceeding the {max_inplay_hours} hour limit."
                    )
                    return True
            
            # If we have market start time and it's in the past, check for excessive delay
            if market_start_time and market_start_time < now:
                delay = now - market_start_time
                max_delay_hours = 6  # Allow up to 6 hours delay for results
                
                if delay.total_seconds() > max_delay_hours * 3600:
                    self.logger.info(
                        f"Market was scheduled to start {delay.total_seconds() / 3600:.1f} hours ago "
                        f"but has not settled yet (exceeding {max_delay_hours} hour threshold)."
                    )
                    return True
            
            # Check if bet is very old regardless of market start time
            bet_age = now - placement_time
            max_bet_age_days = 3  # Maximum bet age (3 days)
            
            if bet_age.total_seconds() > max_bet_age_days * 24 * 3600:
                self.logger.info(
                    f"Bet is {bet_age.total_seconds() / (24 * 3600):.1f} days old, "
                    f"exceeding the {max_bet_age_days} day limit."
                )
                return True
            
            # If none of the timeout conditions are met, don't timeout
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking bet timeout: {str(e)}")
            # Default to not timing out if there's an error
            return False

    async def run_betting_cycle(self) -> None:
        """Execute one complete betting cycle."""
        try:
            # Skip if already has active bet
            if self.state_manager.has_active_bet():
                # Check for results instead (using actual Betfair results)
                self.logger.info("Active bet exists - checking for results")
                await self.check_bet_result()
                return
                
            # Scan markets for opportunities
            opportunity = await self.scan_markets()
            if opportunity:
                # Place bet (simulated placement in dry run mode)
                self.logger.info(
                    f"Found betting opportunity: {opportunity['event_name']}, "
                    f"Selection: {opportunity['team_name']}, "
                    f"Odds: {opportunity['odds']}"
                )
                
                success = await self.place_bet(opportunity)
                if success:
                    mode_indicator = "[DRY RUN] " if self.dry_run else ""
                    self.logger.info(f"{mode_indicator}Bet successfully placed")
                else:
                    self.logger.error("Failed to place bet")
                    
        except Exception as e:
            self.logger.error(f"Error in betting cycle: {str(e)}")

    async def start(self) -> None:
        """Start the betting service main loop."""
        self.logger.info(
            f"Starting betting service in {'DRY RUN' if self.dry_run else 'LIVE'} mode"
        )
        
        # Main loop
        while not self.shutdown_flag:
            try:
                # Run one betting cycle
                await self.run_betting_cycle()
                
                # Wait for next cycle
                if not self.shutdown_flag:
                    interval = self.config.get('market_selection', {}).get('polling_interval_seconds', 60)
                    self.logger.info(f"Waiting {interval} seconds until next cycle")
                    await asyncio.sleep(interval)
                    
            except asyncio.CancelledError:
                self.logger.info("Betting service task cancelled")
                break
            except Exception as e:
                self.logger.error(f"Error in main loop: {str(e)}")
                # Shorter error retry interval
                await asyncio.sleep(5)
                
        self.logger.info("Betting service stopped")

    async def stop(self) -> None:
        """Stop the betting service."""
        self.logger.info("Stopping betting service")
        self.shutdown_flag = True
        await self.betfair_client.close_session()
        self.logger.info("Betting service resources released")