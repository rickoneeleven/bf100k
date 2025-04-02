"""
betting_service.py

Main betting service that coordinates betting operations.
Refactored to use actual Betfair results in both live and dry run modes.
Result checking improved to use get_fresh_market_data for resilience.
Added spread width protection to ensure bets are only placed when market spread is tight.
Removed automatic bet timeout settlement - now only identifies potential issues for manual resolution.
"""

import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any


def get_max_spread_percentage(odds):
    """
    Determine the maximum acceptable spread percentage based on the odds range.
    
    Args:
        odds: The back odds
        
    Returns:
        float: Maximum acceptable spread as a percentage
    """
    if odds < 2.0:
        return 0.75
    elif odds < 4.0:
        return 1.5
    elif odds < 10.0:
        return 2.5
    else:
        return 3.5


def is_spread_acceptable(back_odds, lay_odds):
    """
    Check if the spread between back and lay odds is acceptable.
    
    Args:
        back_odds: The back (blue) odds
        lay_odds: The lay (pink) odds
        
    Returns:
        bool: True if spread is acceptable, False otherwise
    """
    if back_odds <= 0 or lay_odds <= 0:
        return False
        
    max_spread_percentage = get_max_spread_percentage(back_odds)
    spread_percentage = ((lay_odds - back_odds) / back_odds) * 100
    
    return spread_percentage <= max_spread_percentage


class BettingService:
    """
    Main service that coordinates betting operations with simplified flow.
    """

    def __init__(
        self,
        betfair_client,
        state_manager,
        config_manager
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
        Updated to consider only the top 2 favorites with odds of 3.5+ and acceptable spreads.

        Returns:
            Dict containing betting opportunity if found, None otherwise
        """
        try:
            # Skip if there's an active bet
            if self.state_manager.has_active_bet():
                self.logger.info("Active bet exists - skipping market scan")
                return None

            betting_config = self.config.get('betting', {})
            liquidity_factor = betting_config.get('liquidity_factor', 1.1)
            min_odds = betting_config.get('min_odds', 3.5)
            # Use max_odds from config, default to 10.0 if not present
            max_odds = betting_config.get('max_odds', 10.0)
            min_liquidity = betting_config.get('min_liquidity', 100000) # Minimum market liquidity


            # Get next stake amount
            next_stake = self.state_manager.get_next_stake()

            # Get current state
            state = self.state_manager.get_current_state()

            self.logger.info(
                f"Scanning markets - Cycle #{state.current_cycle}, "
                f"Bet #{state.current_bet_in_cycle + 1} in cycle, "
                f"Next stake: ÃÂ£{next_stake:.2f}"
            )

            # Get football markets for the next N hours including in-play
            market_config = self.config.get('market_selection', {})
            max_markets_fetch = market_config.get('max_markets', 1000)  # Total markets to initially fetch
            hours_ahead = market_config.get('hours_ahead', 4)
            include_inplay = market_config.get('include_inplay', True)

            markets = await self.betfair_client.get_football_markets(
                max_results=max_markets_fetch,
                hours_ahead=hours_ahead
                # Note: get_football_markets now fetches both in-play and upcoming if include_inplay is True internally
            )

            if not markets:
                self.logger.info("No markets found matching initial criteria.")
                return None

            # Markets should already be sorted by MAXIMUM_TRADED from the API call
            # Take only the top N markets specified in config
            top_markets_limit = market_config.get('top_markets', 10)
            top_markets = markets[:top_markets_limit]

            self.logger.info(f"Analyzing the top {len(top_markets)} markets by traded volume out of {len(markets)} total found markets")

            # Log the selected markets to provide visibility
            for idx, market in enumerate(top_markets):
                market_id = market.get('marketId')
                event = market.get('event', {})
                event_name = event.get('name', 'Unknown Event')
                total_matched = market.get('totalMatched', 0)
                market_start = market.get('marketStartTime', 'Unknown')

                self.logger.info(
                    f"Top Market #{idx+1}: {event_name} (ID: {market_id}), "
                    f"Total Matched: ÃÂ£{total_matched:,.2f}, Start: {market_start}"
                )

            # Analyze each of the top markets sequentially
            for market in top_markets:
                market_id = market.get('marketId')
                event = market.get('event', {})
                event_name = event.get('name', 'Unknown Event')

                self.logger.info(f"Analyzing market: {event_name} (ID: {market_id})")

                # Get detailed market data using the resilient method
                market_data = await self.betfair_client.get_fresh_market_data(market_id)

                if not market_data:
                    self.logger.warning(f"Could not get data for market {market_id}")
                    continue

                # Check minimum market liquidity
                total_matched = market_data.get('totalMatched', 0)
                if total_matched < min_liquidity:
                    self.logger.info(f"Skipping market {market_id} with insufficient liquidity: ÃÂ£{total_matched:,.2f} < ÃÂ£{min_liquidity:,.2f}")
                    continue

                # Skip if market is not OPEN (e.g., SUSPENDED, CLOSED) unless it's INPLAY
                market_status = market_data.get('status')
                is_inplay = market_data.get('inplay', False)
                if market_status != 'OPEN' and not is_inplay:
                     self.logger.info(f"Skipping market {market_id} with status {market_status}")
                     continue

                # Get event details
                event_id = event.get('id', 'Unknown')

                # Process runners
                runners = market_data.get('runners', [])
                if not runners:
                    self.logger.info(f"No runners found for market {market_id}")
                    continue

                # Sort runners by sortPriority
                runners = sorted(runners, key=lambda r: r.get('sortPriority', 999))

                # Collect all selections with basic validation
                all_selections = []
                for runner in runners:
                    selection_id = runner.get('selectionId')
                    # Ensure teamName is populated (fallback to runnerName if needed)
                    team_name = runner.get('teamName', runner.get('runnerName', 'Unknown'))
                    if team_name == 'Unknown':
                         self.logger.warning(f"Runner {selection_id} in market {market_id} has unknown name.")

                    runner_ex = runner.get('ex', {})
                    available_to_back = runner_ex.get('availableToBack', [])

                    if not available_to_back:
                        self.logger.debug(f"No back prices available for {team_name} (ID: {selection_id})")
                        continue

                    # Get best back price and size
                    best_back = available_to_back[0]
                    back_price = best_back.get('price', 0)
                    available_size = best_back.get('size', 0)

                    if back_price == 0:
                        self.logger.debug(f"Zero odds found for {team_name} (ID: {selection_id})")
                        continue

                    # Get best lay price if available
                    available_to_lay = runner_ex.get('availableToLay', [])
                    lay_price = None
                    if available_to_lay:
                        lay_price = available_to_lay[0].get('price', 0)
                        
                        # Check if spread is acceptable
                        if lay_price > 0 and not is_spread_acceptable(back_price, lay_price):
                            spread_percentage = ((lay_price - back_price) / back_price) * 100
                            self.logger.info(
                                f"Skipping selection {team_name} (ID: {selection_id}) due to wide spread: "
                                f"{back_price}/{lay_price} ({spread_percentage:.2f}%), "
                                f"max allowed: {get_max_spread_percentage(back_price):.2f}%"
                            )
                            continue

                    self.logger.debug(f"Selection {team_name} (ID: {selection_id}): Odds: {back_price}, Available: ÃÂ£{available_size:.2f}")

                    all_selections.append({
                        'runner': runner,
                        'selection_id': selection_id,
                        'odds': back_price,
                        'available_volume': available_size,
                        'team_name': team_name
                    })

                # Sort by odds (lowest first) to identify favorites
                all_selections.sort(key=lambda x: x['odds'])

                # Take only the top 2 favorites by odds
                top_2_favorites = all_selections[:2]

                # Filter those by odds >= min_odds and <= max_odds and sufficient liquidity
                valid_opportunities = []
                for selection in top_2_favorites:
                    # Check odds range
                    if selection['odds'] < min_odds:
                        self.logger.debug(f"Odds too low for {selection['team_name']} (ID: {selection['selection_id']}): {selection['odds']} < {min_odds}")
                        continue
                    if selection['odds'] > max_odds:
                        self.logger.debug(f"Odds too high for {selection['team_name']} (ID: {selection['selection_id']}): {selection['odds']} > {max_odds}")
                        continue

                    # Check liquidity requirement
                    required_liquidity = next_stake * liquidity_factor
                    if selection['available_volume'] < required_liquidity:
                        self.logger.debug(
                            f"Insufficient liquidity for {selection['team_name']} (ID: {selection['selection_id']}): "
                            f"Available ÃÂ£{selection['available_volume']:.2f} < Required ÃÂ£{required_liquidity:.2f}"
                        )
                        continue

                    # This is a valid opportunity
                    valid_opportunities.append(selection)

                # If we have valid opportunities among the top 2 favorites, choose one
                if valid_opportunities:
                    # Prioritize the one with the highest odds within the valid range
                    valid_opportunities.sort(key=lambda x: x['odds'], reverse=True)
                    best_opportunity = valid_opportunities[0]

                    self.logger.info(
                        f"Found betting opportunity in market {market_id}: {event_name}, "
                        f"Selection: {best_opportunity['team_name']} (ID: {best_opportunity['selection_id']}) @ {best_opportunity['odds']}, "
                        f"Available: ÃÂ£{best_opportunity['available_volume']:.2f}"
                    )

                    # Create bet details
                    bet_details = {
                        "market_id": market_id,
                        "event_id": event_id,
                        "event_name": event_name,
                        "selection_id": best_opportunity['selection_id'],
                        "team_name": best_opportunity['team_name'],
                        "competition": market_data.get('competition', {}).get('name', 'Unknown'),
                        "odds": best_opportunity['odds'],
                        "stake": next_stake,
                        "available_volume": best_opportunity['available_volume'],
                        "market_start_time": market_data.get('marketStartTime'),
                        "inplay": market_data.get('inplay', False) # Use fresh inplay status
                    }

                    return bet_details

            # No suitable markets found
            self.logger.info("No suitable betting opportunities found in the top markets after filtering.")
            return None

        except Exception as e:
            self.logger.error(f"Error scanning markets: {str(e)}", exc_info=True)
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
                f"Attempting to place bet on event: {bet_details.get('event_name')}, "
                f"Selection: {bet_details.get('team_name')} (ID: {bet_details.get('selection_id')}), "
                f"Odds: {bet_details.get('odds')}, "
                f"Stake: ÃÂ£{bet_details.get('stake')}"
            )

            if self.dry_run:
                self.logger.info(
                    f"[DRY RUN] Simulating bet placement: "
                    f"Match: {bet_details.get('event_name')}, "
                    f"Selection: {bet_details.get('team_name')} (ID: {bet_details.get('selection_id')}), "
                    f"Odds: {bet_details.get('odds')}, "
                    f"Stake: ÃÂ£{bet_details.get('stake')}"
                )

                # Record bet in state manager ONLY in dry run
                # In LIVE mode, actual placement API call would be here
                self.state_manager.record_bet_placed(bet_details)
                return True

            else:
                 # TODO: Implement actual Betfair bet placement API call in LIVE mode
                self.logger.warning("[LIVE MODE] Actual bet placement API call not implemented yet.")
                # For now, still record the bet in state manager to allow testing flow
                # In a real live system, this recording should happen *after* successful API placement
                self.state_manager.record_bet_placed(bet_details)
                # Assume success for now until API call is implemented
                return True


        except Exception as e:
            self.logger.error(f"Error placing bet: {str(e)}", exc_info=True)
            return False

    async def check_bet_result(self) -> bool:
        """
        Check the result of the current active bet using actual Betfair results
        regardless of dry run status. Uses resilient market data retrieval.

        Returns:
            True if bet was settled, False otherwise
        """
        try:
            # Get active bet
            active_bet = self.state_manager.get_active_bet()
            if not active_bet:
                self.logger.debug("No active bet found to check result for.")
                return False # No active bet to check

            market_id = active_bet.get('market_id')
            selection_id = active_bet.get('selection_id')
            team_name = active_bet.get('team_name', 'Unknown')

            if not market_id or not selection_id:
                self.logger.error(f"Active bet data is incomplete: {active_bet}")
                # Potentially try to reset the invalid active bet state here
                # self.state_manager.reset_active_bet() # Consider implications
                return False

            self.logger.info(
                f"Checking result for bet: Market {market_id}, "
                f"Selection {selection_id} ({team_name})"
            )

            # Use the more resilient get_fresh_market_data method
            self.logger.debug(f"Calling get_fresh_market_data for market {market_id}")
            market_data = await self.betfair_client.get_fresh_market_data(market_id)

            if not market_data:
                # Log detailed warning but do not auto-settle
                self.logger.warning(
                    f"ATTENTION NEEDED: Could not retrieve market data for {market_id}, "
                    f"Selection: {selection_id} ({team_name}). "
                    f"Manual verification required."
                )
                return False
            else:
                # We have at least partial market data (book data)
                self.logger.debug(f"Successfully retrieved market data (potentially partial) for {market_id}. Status: {market_data.get('status')}")
                
                # Check if market is settled based on the status from book data
                market_status = market_data.get('status')
                if market_status not in ['CLOSED', 'SETTLED']:
                    # Check if the market is potentially stuck or delayed
                    if self._has_potential_issues(active_bet, market_data):
                        # Just log warning without settling
                        return False
                    else:
                        self.logger.info(f"Market {market_id} not yet settled. Current status: {market_status}")
                        return False
                else:
                    # Market is CLOSED or SETTLED, get the definitive result
                    self.logger.info(f"Market {market_id} has status {market_status}. Getting definitive result.")
                    won, result_message = await self.betfair_client.get_market_result(
                        market_id, selection_id
                    )
                    self.logger.info(f"Result determined for market {market_id}: Won={won}, Message='{result_message}'")

            # --- Settlement Logic ---
            # This part executes if market is settled (CLOSED/SETTLED)

            # Calculate profit and commission
            stake = active_bet.get('stake', 0.0)
            odds = active_bet.get('odds', 0.0)
            net_profit = 0.0
            commission = 0.0 # Default commission to 0

            if won:
                # Calculate gross profit based on stake and odds
                gross_profit = stake * (odds - 1)
                # Apply commission (e.g., 5%) - Make commission rate configurable?
                commission_rate = 0.05 # Example: 5%
                commission = gross_profit * commission_rate
                net_profit = gross_profit - commission

                self.logger.info(
                    f"Bet WON! Market: {market_id}, Selection: {selection_id}. "
                    f"Gross Profit: ÃÂ£{gross_profit:.2f}, "
                    f"Commission ({commission_rate*100}%): ÃÂ£{commission:.2f}, "
                    f"Net Profit: ÃÂ£{net_profit:.2f}"
                )
            else:
                # Loss results in zero profit and commission, loss of stake
                net_profit = 0.0
                commission = 0.0
                gross_profit = 0.0 # Explicitly set gross profit to 0 for losses
                self.logger.info(
                    f"Bet LOST. Market: {market_id}, Selection: {selection_id}. "
                    f"Lost Stake: ÃÂ£{stake:.2f}. Reason: {result_message}"
                 )

            # Record result in state manager
            # Pass the calculated net_profit and commission
            self.state_manager.record_bet_result(
                active_bet, won, net_profit, commission
            )

            # Check if target amount reached AFTER recording the result
            if won and self.state_manager.check_target_reached():
                self.logger.info(f"Target amount of ÃÂ£{self.state_manager.state.target_amount} reached! Resetting cycle.")
                # State manager's check_target_reached handles the cycle reset logic now

            return True # Bet was settled

        except Exception as e:
            self.logger.error(f"Error checking bet result for market {active_bet.get('market_id', 'N/A')}: {str(e)}", exc_info=True)
            return False

    def _has_potential_issues(self, bet: Dict, market_data: Dict) -> bool:
        """
        Identify potential issues with a bet but DON'T auto-settle.
        Only log warnings for manual attention.
        
        Args:
            bet: Bet details dictionary. Must contain 'timestamp'. Optionally 'market_start_time'.
            market_data: Current market data dictionary (can be empty or partial).
            
        Returns:
            True if issues are detected, False otherwise
        """
        try:
            now = datetime.now(timezone.utc)
            config = self.config_manager.get_config()
            timeout_config = config.get('result_checking', {})
            event_timeout_hours = timeout_config.get('event_timeout_hours', 12) # Default 12 hours
            
            market_id = bet.get("market_id", "Unknown")
            selection_id = bet.get("selection_id", "Unknown")
            team_name = bet.get("team_name", "Unknown")
            event_name = bet.get("event_name", "Unknown Event")

            # --- 1. Check based on Market Start Time and In-Play Status ---
            market_start_time_str = market_data.get('marketStartTime', bet.get('market_start_time'))
            market_start_time = None
            if market_start_time_str:
                try:
                    # Handle potential 'Z' for UTC
                    if market_start_time_str.endswith('Z'):
                         market_start_time_str = market_start_time_str[:-1] + '+00:00'
                    market_start_time = datetime.fromisoformat(market_start_time_str)
                    # Ensure timezone awareness if not present
                    if market_start_time.tzinfo is None:
                        market_start_time = market_start_time.replace(tzinfo=timezone.utc)
                except ValueError:
                    self.logger.warning(f"Could not parse market start time: {market_start_time_str}")

            is_inplay = market_data.get('inplay', False)
            market_status = market_data.get('status', 'Unknown')

            if market_start_time:
                # Calculate time since market start
                time_since_start = now - market_start_time

                # Check for very old events
                if time_since_start > timedelta(hours=event_timeout_hours):
                    self.logger.warning(
                        f"ATTENTION NEEDED: Market {market_id} ({event_name}) started "
                        f"{time_since_start.total_seconds() / 3600:.1f} hours ago "
                        f"(> {event_timeout_hours} hr expected duration) but status is {market_status}. "
                        f"Manual verification required."
                    )
                    return True

                # Specific check for potentially stuck in-play markets
                max_inplay_duration_hours = 4
                if is_inplay and time_since_start > timedelta(hours=max_inplay_duration_hours):
                    self.logger.warning(
                        f"ATTENTION NEEDED: Market {market_id} ({event_name}) has been in-play for "
                        f"{time_since_start.total_seconds() / 3600:.1f} hours "
                        f"(> {max_inplay_duration_hours} hr expected game duration). "
                        f"Selection: {team_name} (ID: {selection_id}). "
                        f"Manual verification required."
                    )
                    return True

            # --- 2. Check based on Bet Placement Time (Fallback) ---
            try:
                placement_time_str = bet['timestamp']
                # Handle potential 'Z' for UTC
                if placement_time_str.endswith('Z'):
                    placement_time_str = placement_time_str[:-1] + '+00:00'
                placement_time = datetime.fromisoformat(placement_time_str)
                # Ensure timezone awareness
                if placement_time.tzinfo is None:
                    placement_time = placement_time.replace(tzinfo=timezone.utc)

                bet_age = now - placement_time
                # Flag very old bets for manual attention
                max_bet_age_days = 3

                if bet_age > timedelta(days=max_bet_age_days):
                    self.logger.warning(
                        f"ATTENTION NEEDED: Bet on market {market_id} ({event_name}) is "
                        f"{bet_age.days} days old (> {max_bet_age_days} day threshold). "
                        f"Selection: {team_name} (ID: {selection_id}). "
                        f"Current market status: {market_status}. "
                        f"Manual verification required."
                    )
                    return True
            except (KeyError, ValueError) as e:
                self.logger.error(f"Error processing bet timestamp: {e}")

            # No issues detected
            return False

        except Exception as e:
            self.logger.error(f"Error checking bet issues: {str(e)}", exc_info=True)
            # Return False to avoid erroneously flagging bets with errors in the check itself
            return False

    async def run_betting_cycle(self) -> None:
        """Execute one iteration of the betting logic."""
        try:
            # Check for active bet first
            if self.state_manager.has_active_bet():
                # If active bet exists, try to check its result
                self.logger.info("Active bet exists - checking for results")
                settled = await self.check_bet_result()
                if settled:
                    self.logger.info("Active bet was settled.")
                else:
                    self.logger.info("Active bet result not yet available.")
                # Whether settled or not, wait for the next interval
                return

            # No active bet, scan for new opportunities
            self.logger.info("No active bet found. Scanning for new opportunities...")
            opportunity = await self.scan_markets()

            if opportunity:
                # Place bet (simulated or live based on dry_run)
                self.logger.info(
                    f"Found betting opportunity: {opportunity.get('event_name', 'N/A')}, "
                    f"Selection: {opportunity.get('team_name', 'N/A')} (ID: {opportunity.get('selection_id', 'N/A')}), "
                    f"Odds: {opportunity.get('odds', 'N/A')}"
                )

                success = await self.place_bet(opportunity)
                if success:
                    mode_indicator = "[DRY RUN] " if self.dry_run else "[LIVE] "
                    self.logger.info(f"{mode_indicator}Bet placement processed for market {opportunity.get('market_id')}")
                else:
                    self.logger.error(f"Failed to place bet for market {opportunity.get('market_id')}")
            else:
                self.logger.info("No suitable betting opportunities found in this cycle.")

        except Exception as e:
            self.logger.error(f"Error in betting cycle: {str(e)}", exc_info=True)

    async def start(self) -> None:
        """Start the betting service main loop."""
        self.logger.info(
            f"Starting betting service in {'DRY RUN' if self.dry_run else 'LIVE'} mode"
        )

        # Main loop
        while not self.shutdown_flag:
            try:
                # Run one betting cycle iteration
                await self.run_betting_cycle()

                # Wait for next cycle interval
                interval = self.config.get('market_selection', {}).get('polling_interval_seconds', 60)
                self.logger.info(f"Waiting {interval} seconds until next cycle check...")
                # Check shutdown flag periodically during sleep
                for _ in range(interval):
                    if self.shutdown_flag:
                        break
                    await asyncio.sleep(1)
                if self.shutdown_flag:
                     break # Exit loop if shutdown requested during sleep

            except asyncio.CancelledError:
                self.logger.info("Betting service task cancelled")
                break # Exit loop on cancellation
            except Exception as e:
                self.logger.error(f"Unhandled error in main betting loop: {str(e)}", exc_info=True)
                # Implement a short backoff before retrying after an error
                error_retry_interval = 15 # seconds
                self.logger.info(f"Waiting {error_retry_interval} seconds before retrying after error...")
                await asyncio.sleep(error_retry_interval)

        self.logger.info("Betting service stopped")

    async def stop(self) -> None:
        """Stop the betting service."""
        if not self.shutdown_flag:
             self.logger.info("Stopping betting service...")
             self.shutdown_flag = True
             # Close the Betfair client session gracefully
             if self.betfair_client:
                  await self.betfair_client.close_session()
             self.logger.info("Betting service resources released")
        else:
             self.logger.info("Betting service already stopping.")