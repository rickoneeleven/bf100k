"""
betting_service.py

Main betting service that coordinates betting operations.
Refactored to use BettingStateManager as the single source of truth for state.
Relies on BetfairClient for external API interactions (market data, results).
Result checking uses get_fresh_market_data for resilience.
Spread width protection logic remains.
Manual intervention logging for potential issues remains, but does not drive state changes.
"""

import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

# Assuming these helper functions are still relevant to market analysis logic
def get_max_spread_percentage(odds):
    """Determine the maximum acceptable spread percentage based on the odds range."""
    if odds <= 0: return 100.0 # Avoid division by zero, effectively no limit
    if odds < 2.0: return 0.75
    elif odds < 4.0: return 1.5
    elif odds < 10.0: return 2.5
    else: return 3.5

def is_spread_acceptable(back_odds, lay_odds):
    """Check if the spread between back and lay odds is acceptable."""
    if back_odds <= 0 or lay_odds <= 0 or lay_odds < back_odds:
        return False
    max_spread_percentage = get_max_spread_percentage(back_odds)
    spread_percentage = ((lay_odds - back_odds) / back_odds) * 100
    return spread_percentage <= max_spread_percentage

class BettingService:
    """
    Main service coordinating betting operations, using BettingStateManager for state.
    """

    def __init__(
        self,
        betfair_client, # For API calls
        state_manager,  # For all internal state
        config_manager  # For configuration
    ):
        self.betfair_client = betfair_client
        self.state_manager = state_manager
        self.config_manager = config_manager
        self.logger = logging.getLogger('BettingService')

        # Get configuration at initialization
        self.config = config_manager.get_config()
        self.dry_run = self.config.get('system', {}).get('dry_run', True)

        # Shutdown flag
        self._shutdown_flag = asyncio.Event()

    async def scan_markets(self) -> Optional[Dict]:
        """
        Scan available markets for betting opportunities.
        Uses state_manager for active bet checks and stake calculation.

        Returns:
            Dict containing betting opportunity if found, None otherwise
        """
        try:
            # === State Check ===
            if self.state_manager.has_active_bet():
                self.logger.debug("Active bet exists - skipping market scan")
                return None

            # === Configuration ===
            betting_config = self.config.get('betting', {})
            liquidity_factor = betting_config.get('liquidity_factor', 1.1)
            min_odds = betting_config.get('min_odds', 3.5)
            max_odds = betting_config.get('max_odds', 10.0) # Added max_odds
            min_liquidity = betting_config.get('min_liquidity', 100000)

            # === Get Next Stake (from State Manager) ===
            next_stake = self.state_manager.get_next_stake()

            # Get current cycle info from state for logging
            current_state = self.state_manager.get_current_state()
            self.logger.info(
                f"Scanning markets - Cycle #{current_state.current_cycle}, "
                f"Bet #{current_state.current_bet_in_cycle + 1} in cycle, "
                f"Next stake: £{next_stake:.2f}"
            )

            # === Market Fetching (via Betfair Client) ===
            market_config = self.config.get('market_selection', {})
            max_markets_fetch = market_config.get('max_markets', 1000)
            hours_ahead = market_config.get('hours_ahead', 4)
            # include_inplay is handled within betfair_client now

            markets = await self.betfair_client.get_football_markets(
                max_results=max_markets_fetch,
                hours_ahead=hours_ahead
            )

            if not markets:
                self.logger.info("No markets found matching initial criteria.")
                return None

            # === Market Filtering and Analysis ===
            top_markets_limit = market_config.get('top_markets', 10)
            top_markets = markets[:top_markets_limit]

            self.logger.info(f"Analyzing the top {len(top_markets)} markets by traded volume.")
            # Optional: Log top markets details (can be verbose)
            # for idx, market in enumerate(top_markets):
            #    self.logger.debug(f"Top Market #{idx+1}: {market.get('event', {}).get('name', 'N/A')} (ID: {market.get('marketId')})")

            for market_summary in top_markets:
                market_id = market_summary.get('marketId')
                event_summary = market_summary.get('event', {})
                event_name_summary = event_summary.get('name', 'Unknown Event')

                self.logger.debug(f"Analyzing market: {event_name_summary} (ID: {market_id})")

                # Get detailed market data using the resilient method
                market_data = await self.betfair_client.get_fresh_market_data(market_id)

                if not market_data:
                    self.logger.warning(f"Could not get fresh data for market {market_id}")
                    continue # Skip to next market

                # --- Core Selection Logic ---
                # Check overall market liquidity
                total_matched = market_data.get('totalMatched', 0)
                if total_matched < min_liquidity:
                    self.logger.debug(f"Skipping market {market_id}: Insufficient liquidity £{total_matched:,.2f} < £{min_liquidity:,.2f}")
                    continue

                # Check market status (only OPEN or INPLAY)
                market_status = market_data.get('status')
                is_inplay = market_data.get('inplay', False)
                if market_status != 'OPEN' and not is_inplay:
                     self.logger.debug(f"Skipping market {market_id}: Status is {market_status}")
                     continue

                event_id = market_data.get('event', {}).get('id', event_summary.get('id', 'Unknown'))

                runners = market_data.get('runners', [])
                if not runners:
                    self.logger.debug(f"No runners found for market {market_id}")
                    continue

                # Analyze runners (consider top 2 favorites, check odds, liquidity, spread)
                # Sort by sortPriority to identify favorites consistently
                runners = sorted(runners, key=lambda r: r.get('sortPriority', 999))

                all_selections = []
                for runner in runners:
                    selection_id = runner.get('selectionId')
                    team_name = runner.get('teamName', runner.get('runnerName', 'Unknown')) # Prefer teamName if available
                    runner_ex = runner.get('ex', {})
                    available_to_back = runner_ex.get('availableToBack', [])

                    if not available_to_back: continue

                    best_back = available_to_back[0]
                    back_price = best_back.get('price', 0)
                    available_size = best_back.get('size', 0)

                    if back_price <= 0: continue # Skip invalid odds

                    # Check spread acceptability
                    available_to_lay = runner_ex.get('availableToLay', [])
                    lay_price = available_to_lay[0].get('price', 0) if available_to_lay else 0
                    if lay_price > 0 and not is_spread_acceptable(back_price, lay_price):
                         spread_perc = ((lay_price - back_price) / back_price) * 100
                         max_spread = get_max_spread_percentage(back_price)
                         self.logger.debug(f"Skipping {team_name} (ID: {selection_id}) in {market_id}: Wide spread {spread_perc:.1f}% > {max_spread:.1f}% ({back_price}/{lay_price})")
                         continue

                    all_selections.append({
                        'selection_id': selection_id,
                        'odds': back_price,
                        'available_volume': available_size,
                        'team_name': team_name,
                        'sort_priority': runner.get('sortPriority', 999) # Keep sort priority
                    })

                # --- Apply Strategy Filters (Top 2 Favs, Odds Range, Liquidity) ---
                # Sort by odds to get favorites
                all_selections.sort(key=lambda x: x['odds'])
                top_2_favorites = all_selections[:2]

                valid_opportunities = []
                for selection in top_2_favorites:
                    # Check odds range
                    if not (min_odds <= selection['odds'] <= max_odds):
                        self.logger.debug(f"Skipping {selection['team_name']} (ID: {selection['selection_id']}): Odds {selection['odds']} outside range {min_odds}-{max_odds}")
                        continue

                    # Check liquidity
                    required_liquidity = next_stake * liquidity_factor
                    if selection['available_volume'] < required_liquidity:
                        self.logger.debug(f"Skipping {selection['team_name']} (ID: {selection['selection_id']}): Insufficient liquidity £{selection['available_volume']:.2f} < £{required_liquidity:.2f}")
                        continue

                    valid_opportunities.append(selection)

                if valid_opportunities:
                    # Prioritize the one with the highest odds within the valid range
                    valid_opportunities.sort(key=lambda x: x['odds'], reverse=True)
                    best_opportunity = valid_opportunities[0]

                    self.logger.info(
                        f"Found betting opportunity in market {market_id}: {event_name_summary}, "
                        f"Selection: {best_opportunity['team_name']} (ID: {best_opportunity['selection_id']}) @ {best_opportunity['odds']}"
                    )

                    # Create bet details dictionary
                    bet_details = {
                        "market_id": market_id,
                        "event_id": event_id,
                        "event_name": event_name_summary, # Use name from summary fetch
                        "selection_id": best_opportunity['selection_id'],
                        "team_name": best_opportunity['team_name'],
                        "competition": market_data.get('competition', {}).get('name', market_summary.get('competition',{}).get('name','Unknown')),
                        "odds": best_opportunity['odds'],
                        "stake": next_stake,
                        "available_volume": best_opportunity['available_volume'], # For logging/info
                        "market_start_time": market_data.get('marketStartTime', market_summary.get('marketStartTime')),
                        "inplay": is_inplay # Use fresh inplay status
                        # Cycle info will be added by state_manager.record_bet_placed
                    }
                    return bet_details # Return the first valid opportunity found

            # No suitable markets found after checking top N
            self.logger.info("No suitable betting opportunities found in the top markets analysis.")
            return None

        except Exception as e:
            self.logger.error(f"Error scanning markets: {e}", exc_info=True)
            return None

    async def place_bet(self, bet_details: Dict) -> bool:
        """
        Place a bet based on identified opportunity.
        Uses state_manager to record the bet placement.
        Actual API call for LIVE mode is TODO here.

        Args:
            bet_details: Dict containing betting opportunity details

        Returns:
            True if state updated successfully, False otherwise
        """
        try:
            stake = bet_details.get('stake')
            selection_name = bet_details.get('team_name', 'Unknown')
            event_name = bet_details.get('event_name', 'Unknown')
            odds = bet_details.get('odds')
            market_id = bet_details.get('market_id')

            self.logger.info(
                f"Processing bet placement for {event_name} - {selection_name} @ {odds} with stake £{stake:.2f}"
            )

            if self.dry_run:
                self.logger.info(f"[DRY RUN] Simulating bet placement for market {market_id}.")
                # Record the bet in the state manager
                self.state_manager.record_bet_placed(bet_details)
                self.logger.info(f"[DRY RUN] Bet recorded in state manager for market {market_id}.")
                return True
            else:
                # === LIVE MODE ===
                # TODO: Implement actual Betfair placeOrders API call here
                # 1. Construct the placeInstruction payload
                # place_instruction = {
                #     "orderType": "LIMIT",
                #     "selectionId": bet_details['selection_id'],
                #     "handicap": 0,
                #     "side": "BACK",
                #     "limitOrder": {
                #         "size": f"{stake:.2f}",
                #         "price": odds,
                #         "persistenceType": "LAPSE" # Or "PERSIST", "MARKET_ON_CLOSE"
                #     }
                # }
                # instructions = [place_instruction]
                # params = {'marketId': market_id, 'instructions': instructions}
                #
                # 2. Make the API call using self.betfair_client._make_api_call
                # placement_result = await self.betfair_client._make_api_call(
                #     'SportsAPING/v1.0/placeOrders', params
                # )
                #
                # 3. Check placement_result for success/failure/errors
                # if placement_result and placement_result.get('status') == 'SUCCESS':
                #     bet_id = placement_result['instructionReports'][0].get('betId')
                #     self.logger.info(f"[LIVE] Bet placed successfully for market {market_id}. Bet ID: {bet_id}")
                #     # Add bet_id to bet_details if needed
                #     bet_details['betfair_bet_id'] = bet_id
                #     # Record in state manager ONLY after successful placement
                #     self.state_manager.record_bet_placed(bet_details)
                #     return True
                # else:
                #     error_code = placement_result.get('errorCode') if placement_result else 'UNKNOWN'
                #     self.logger.error(f"[LIVE] Bet placement failed for market {market_id}. Result: {placement_result}, Error: {error_code}")
                #     return False

                self.logger.warning("[LIVE MODE] Actual bet placement API call not implemented. Simulating success.")
                # For now, record in state manager to allow flow testing
                self.state_manager.record_bet_placed(bet_details)
                return True

        except Exception as e:
            self.logger.error(f"Error during place_bet processing for market {bet_details.get('market_id', 'N/A')}: {e}", exc_info=True)
            return False

    async def check_bet_result(self) -> bool:
        """
        Check the result of the current active bet.
        Uses state_manager for active bet data and BetfairClient for results.
        Updates state via state_manager.

        Returns:
            True if bet was settled (state updated), False otherwise.
        """
        try:
            # === Get Active Bet (from State Manager) ===
            active_bet = self.state_manager.get_active_bet()
            if not active_bet:
                self.logger.debug("No active bet found to check result for.")
                return False

            market_id = active_bet.get('market_id')
            selection_id = active_bet.get('selection_id')
            team_name = active_bet.get('team_name', 'Unknown')

            if not market_id or not selection_id:
                self.logger.error(f"Active bet data is incomplete: {active_bet}. Cannot check result.")
                # Consider how to handle this - maybe force reset/cancel? For now, return False.
                # self.state_manager.reset_active_bet() # Potentially dangerous
                return False

            self.logger.info(f"Checking result for bet: Market {market_id}, Selection {selection_id} ({team_name})")

            # === Fetch Market Data/Status (via Betfair Client) ===
            market_data = await self.betfair_client.get_fresh_market_data(market_id)

            if not market_data:
                # Log detailed warning but DO NOT auto-settle based on inability to fetch
                self.logger.warning(
                    f"ATTENTION NEEDED: Could not retrieve market data for {market_id}. "
                    f"Manual verification required for selection {selection_id} ({team_name})."
                )
                # Check for potential issues based on time (logging only)
                self._log_potential_issues(active_bet, market_data)
                return False # Cannot determine result without market data

            # === Check Market Status ===
            market_status = market_data.get('status')
            if market_status not in ['CLOSED', 'SETTLED']:
                self.logger.info(f"Market {market_id} not yet settled. Current status: {market_status}")
                # Check for potential issues based on time (logging only)
                self._log_potential_issues(active_bet, market_data)
                return False # Market not settled

            # --- Market is CLOSED or SETTLED ---
            self.logger.info(f"Market {market_id} has status {market_status}. Getting definitive result.")

            # === Fetch Definitive Result (via Betfair Client) ===
            # Note: get_market_result internally calls get_fresh_market_data again,
            # could potentially reuse market_data if API allows direct result query without full book.
            # Assuming get_market_result is the correct way for now.
            won, result_message = await self.betfair_client.get_market_result(market_id, selection_id)
            self.logger.info(f"Result determined for market {market_id}: Won={won}, Message='{result_message}'")

            # === Calculate Profit/Commission ===
            stake = active_bet.get('stake', 0.0)
            odds = active_bet.get('odds', 0.0)
            net_profit = 0.0
            commission = 0.0
            gross_profit = 0.0
            commission_rate = 0.05 # Example: 5% - TODO: Make configurable?

            if won:
                gross_profit = stake * (odds - 1)
                commission = gross_profit * commission_rate
                net_profit = gross_profit - commission
                self.logger.info(
                    f"Bet WON! Market: {market_id}. Gross: £{gross_profit:.2f}, Comm: £{commission:.2f}, Net: £{net_profit:.2f}"
                )
            else:
                self.logger.info(
                    f"Bet LOST. Market: {market_id}. Lost Stake: £{stake:.2f}. Reason: {result_message}"
                )
                # net_profit, commission, gross_profit remain 0.0

            # === Update State (via State Manager) ===
            self.state_manager.record_bet_result(
                bet_details=active_bet, # Pass the original bet details
                won=won,
                profit=net_profit, # Pass net profit
                commission=commission # Pass calculated commission
            )
            # state_manager handles updating balance, stats, history, and clearing active bet internally

            # === Check Target Reached (via State Manager) ===
            # Check AFTER recording result, as balance is updated there
            if self.state_manager.check_target_reached():
                 # state_manager logs this and handles cycle reset internally
                 pass # Logging and cycle reset handled within check_target_reached

            return True # Bet was settled and state updated

        except Exception as e:
            active_market = active_bet.get('market_id', 'N/A') if 'active_bet' in locals() else 'N/A'
            self.logger.error(f"Error checking bet result for market {active_market}: {e}", exc_info=True)
            return False # Failed to check or settle

    def _log_potential_issues(self, bet: Dict, market_data: Optional[Dict]) -> bool:
        """
        Identify and LOG potential issues with a bet (e.g., timeout)
        but DO NOT auto-settle based on these checks.
        Returns True if potential issues logged, False otherwise.
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

            issue_found = False
            issue_details = []

            # --- Check based on Market Start Time ---
            market_start_time_str = market_data.get('marketStartTime') if market_data else bet.get('market_start_time')
            market_start_time = None
            if market_start_time_str:
                try:
                    if market_start_time_str.endswith('Z'): market_start_time_str = market_start_time_str[:-1] + '+00:00'
                    market_start_time = datetime.fromisoformat(market_start_time_str)
                    if market_start_time.tzinfo is None: market_start_time = market_start_time.replace(tzinfo=timezone.utc)
                except ValueError:
                    issue_details.append(f"Could not parse market start time: {market_start_time_str}")

            market_status = market_data.get('status', 'Unknown') if market_data else 'Unknown'
            is_inplay = market_data.get('inplay', False) if market_data else False

            if market_start_time:
                time_since_start = now - market_start_time
                # Check for very old events still not settled
                if time_since_start > timedelta(hours=event_timeout_hours) and market_status not in ['CLOSED', 'SETTLED']:
                    issue_details.append(
                        f"Market started {time_since_start.total_seconds() / 3600:.1f} hours ago "
                        f"(> {event_timeout_hours}hr limit) but status is {market_status}."
                    )
                    issue_found = True

                # Check for potentially stuck in-play markets
                max_inplay_duration_hours = 4
                if is_inplay and time_since_start > timedelta(hours=max_inplay_duration_hours):
                    issue_details.append(
                         f"Market in-play for {time_since_start.total_seconds() / 3600:.1f} hours "
                         f"(> {max_inplay_duration_hours}hr expected)."
                    )
                    issue_found = True

            # --- Check based on Bet Placement Time ---
            try:
                placement_time_str = bet['timestamp']
                if placement_time_str.endswith('Z'): placement_time_str = placement_time_str[:-1] + '+00:00'
                placement_time = datetime.fromisoformat(placement_time_str)
                if placement_time.tzinfo is None: placement_time = placement_time.replace(tzinfo=timezone.utc)

                bet_age = now - placement_time
                max_bet_age_days = 3
                if bet_age > timedelta(days=max_bet_age_days):
                     issue_details.append(f"Bet is {bet_age.days} days old (> {max_bet_age_days} day limit).")
                     issue_found = True
            except (KeyError, ValueError) as e:
                issue_details.append(f"Error processing bet timestamp: {e}")
                issue_found = True # Flag as issue if timestamp is bad

            # --- Log Warning if Issues Found ---
            if issue_found:
                 self.logger.warning(
                     f"ATTENTION NEEDED: Potential issue with bet on Market {market_id} "
                     f"({event_name} - {team_name} ID: {selection_id}). "
                     f"Details: {'; '.join(issue_details)}. "
                     f"Current Status: {market_status}. Manual verification required."
                 )
                 return True

            return False # No issues logged

        except Exception as e:
            self.logger.error(f"Error checking for potential bet issues: {e}", exc_info=True)
            return False

    async def run_betting_cycle(self) -> None:
        """Execute one iteration of the betting logic."""
        try:
            # Check for active bet first (using state manager)
            if self.state_manager.has_active_bet():
                self.logger.info("Active bet exists - checking for results...")
                settled = await self.check_bet_result()
                if settled:
                    self.logger.info("Active bet was settled in this cycle.")
                # else:
                #     self.logger.info("Active bet result not yet available or check failed.")
                # No action needed if not settled, wait for next cycle
                return

            # No active bet, scan for new opportunities
            self.logger.info("No active bet found. Scanning for new opportunities...")
            opportunity = await self.scan_markets()

            if opportunity:
                self.logger.info(
                    f"Found opportunity: {opportunity.get('event_name', 'N/A')} - {opportunity.get('team_name', 'N/A')} @ {opportunity.get('odds', 'N/A')}"
                )
                # Place bet (updates state via state manager)
                success = await self.place_bet(opportunity)
                if success:
                    self.logger.info(f"Bet placement processed successfully for market {opportunity.get('market_id')}")
                else:
                    # Placing bet failed, state manager should not have recorded it
                    self.logger.error(f"Bet placement failed for market {opportunity.get('market_id')}. State not changed.")
            # else:
            #     self.logger.info("No suitable betting opportunities found in this cycle.")

        except Exception as e:
            self.logger.error(f"Unhandled error in betting cycle: {e}", exc_info=True)

    async def start(self) -> None:
        """Start the betting service main loop."""
        self.logger.info(f"Starting betting service in {'DRY RUN' if self.dry_run else 'LIVE'} mode")
        self._shutdown_flag.clear() # Ensure flag is clear on start

        polling_interval = self.config.get('market_selection', {}).get('polling_interval_seconds', 60)
        self.logger.info(f"Using polling interval: {polling_interval} seconds")

        while not self._shutdown_flag.is_set():
            cycle_start_time = asyncio.get_event_loop().time()
            try:
                await self.run_betting_cycle()

            except asyncio.CancelledError:
                self.logger.info("Betting service task cancelled during cycle.")
                break # Exit loop on cancellation
            except Exception as e:
                self.logger.error(f"Unhandled error in main betting loop: {e}", exc_info=True)
                # Wait briefly before next cycle after error to avoid tight loop
                await asyncio.sleep(15)

            # Calculate time elapsed and wait for the remainder of the interval
            cycle_end_time = asyncio.get_event_loop().time()
            elapsed_time = cycle_end_time - cycle_start_time
            wait_time = max(0, polling_interval - elapsed_time)

            if not self._shutdown_flag.is_set():
                 self.logger.debug(f"Cycle took {elapsed_time:.2f}s. Waiting {wait_time:.2f}s for next cycle.")
                 try:
                     # Wait for the remaining interval, but check shutdown flag frequently
                     await asyncio.wait_for(self._shutdown_flag.wait(), timeout=wait_time)
                     # If wait_for finishes without TimeoutError, shutdown was triggered
                     if self._shutdown_flag.is_set():
                          self.logger.info("Shutdown triggered during wait interval.")
                          break
                 except asyncio.TimeoutError:
                     pass # Timeout reached, proceed to next cycle normally
                 except asyncio.CancelledError:
                      self.logger.info("Betting service task cancelled during wait.")
                      break

        self.logger.info("Betting service loop stopped.")

    async def stop(self) -> None:
        """Stop the betting service."""
        if not self._shutdown_flag.is_set():
            self.logger.info("Stopping betting service...")
            self._shutdown_flag.set()
            # No internal tasks to cancel here, main loop will exit.
            # Betfair client closing is handled in main.py
            self.logger.info("Betting service shutdown signal sent.")
        else:
            self.logger.info("Betting service already stopping.")