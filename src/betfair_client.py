# -*- coding: utf-8 -*-
"""
betfair_client.py

Simplified Betfair API client with improved result checking functionality,
enhanced logging, and automatic re-login attempt on session issues.
"""

import os
import json
import logging
import aiohttp
import ssl
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Tuple, Any

class BetfairClient:
    # Constants for API calls
    CERT_LOGIN_URL = 'https://identitysso-cert.betfair.com/api/certlogin'
    BETTING_URL = 'https://api.betfair.com/exchange/betting/json-rpc/v1'
    HEADERS_BASE = {'content-type': 'application/json'}

    def __init__(self, app_key: str, cert_file: str, key_file: str):
        self.app_key = app_key
        self.cert_file = cert_file
        self.key_file = key_file
        self.session_token = None
        self._http_session = None
        self._ssl_context = None # Cache SSL context

        # Setup logging
        self.logger = logging.getLogger('BetfairClient')
        if not self.logger.handlers:
             # Configure logger if it has no handlers (e.g., running standalone)
             self.logger.setLevel(logging.INFO)
             handler = logging.StreamHandler() # Or FileHandler
             formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
             handler.setFormatter(formatter)
             self.logger.addHandler(handler)

    def _create_ssl_context(self) -> Optional[ssl.SSLContext]:
        """Creates and caches the SSL context."""
        if self._ssl_context is None:
            try:
                self.logger.debug("Creating SSL context")
                ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                ssl_context.load_cert_chain(self.cert_file, self.key_file)
                self._ssl_context = ssl_context
            except Exception as e:
                self.logger.error(f"Failed to create SSL context: {e}", exc_info=True)
                self._ssl_context = None # Ensure it's None on failure
        return self._ssl_context

    async def ensure_session(self) -> Optional[aiohttp.ClientSession]:
        """Ensure a valid HTTP session exists and return it"""
        if self._http_session is None or self._http_session.closed:
            try:
                self.logger.debug("Creating new aiohttp ClientSession")
                self._http_session = aiohttp.ClientSession()
            except Exception as e:
                self.logger.error(f"Failed to create aiohttp ClientSession: {e}", exc_info=True)
                return None
        return self._http_session

    async def close_session(self) -> None:
        """Close the HTTP session if it exists"""
        if self._http_session and not self._http_session.closed:
            self.logger.info("Closing aiohttp ClientSession")
            await self._http_session.close()
            self._http_session = None
        else:
            self.logger.debug("No active aiohttp ClientSession to close or already closed.")

    async def login(self) -> bool:
        """Login to Betfair API using certificate-based authentication"""
        try:
            self.logger.info("Attempting to login to Betfair")
            session = await self.ensure_session()
            if not session:
                self.logger.error("Failed to get valid aiohttp session for login.")
                return False

            # Get credentials from environment
            username = os.getenv('BETFAIR_USERNAME')
            password = os.getenv('BETFAIR_PASSWORD')

            if not username or not password:
                self.logger.error("Missing Betfair credentials (BETFAIR_USERNAME, BETFAIR_PASSWORD) in environment variables")
                return False

            if not self.app_key:
                self.logger.error("Missing Betfair app key (BETFAIR_APP_KEY)")
                return False

            payload = {'username': username, 'password': password}
            headers = {'X-Application': self.app_key}

            # Create SSL context
            ssl_context = self._create_ssl_context()
            if not ssl_context:
                return False # Error already logged in _create_ssl_context

            self.logger.debug("Sending login request...")
            async with session.post(
                self.CERT_LOGIN_URL,
                data=payload,
                headers=headers,
                ssl=ssl_context
            ) as resp:
                resp_text = await resp.text() # Read response text regardless of status
                self.logger.debug(f"Login response status: {resp.status}")

                if resp.status == 200:
                    try:
                        resp_json = json.loads(resp_text)
                        self.logger.debug(f"Login response JSON: {resp_json}")

                        if resp_json.get('loginStatus') == 'SUCCESS':
                            self.session_token = resp_json.get('sessionToken')
                            if self.session_token:
                                self.logger.info('Successfully logged in to Betfair.')
                                return True
                            else:
                                self.logger.error("Login SUCCESS but no sessionToken received.")
                                return False
                        else:
                            self.logger.error(f"Login failed: Status={resp_json.get('loginStatus')}, Error={resp_json.get('error')}")
                            return False
                    except json.JSONDecodeError:
                        self.logger.error(f"Login failed: Could not decode JSON response. Response text: {resp_text}")
                        return False
                else:
                    self.logger.error(f"Login request failed. Status: {resp.status}, Response: {resp_text}")
                    return False

        except aiohttp.ClientError as e:
             self.logger.error(f"Network error during login: {e}", exc_info=True)
             return False
        except Exception as e:
            self.logger.error(f"Unexpected exception during login: {e}", exc_info=True)
            return False

    async def _make_api_call(self, method: str, params: Dict, attempt_relogin: bool = True) -> Optional[Dict]:
        """
        Internal helper to make Betfair API calls with error handling and re-login attempt.

        Args:
            method: The API method name (e.g., 'SportsAPING/v1.0/listMarketBook').
            params: Dictionary of parameters for the API call.
            attempt_relogin: Whether to attempt a re-login if the call fails due to session issues.

        Returns:
            The 'result' part of the JSON response if successful, None otherwise.
        """
        if not self.session_token:
            self.logger.error('No session token available. Trying to login first.')
            if not await self.login():
                 return None # Login failed

        session = await self.ensure_session()
        if not session:
             self.logger.error("Failed to get valid aiohttp session for API call.")
             return None

        payload = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params,
            'id': 1
        }
        headers = {
            **self.HEADERS_BASE,
            'X-Application': self.app_key,
            'X-Authentication': self.session_token
        }

        try:
            self.logger.debug(f"Making API call: Method={method}, Params={params}")
            async with session.post(self.BETTING_URL, json=payload, headers=headers) as resp:
                resp_text = await resp.text()
                self.logger.debug(f"API call response status: {resp.status}, Method: {method}")

                if resp.status == 200:
                    try:
                        resp_json = json.loads(resp_text)
                        # Check for errors within the JSON response even if status is 200
                        if 'error' in resp_json:
                            error_info = resp_json['error']
                            self.logger.error(f"API error received (Status 200): Code={error_info.get('code')}, Message={error_info.get('message')}, Data={error_info.get('data')}")
                            # Specific check for potential session errors
                            if attempt_relogin and error_info.get('code') in [-32099]: # Example: INVALID_SESSION_INFORMATION
                                self.logger.warning("Potential session issue detected. Attempting re-login.")
                                self.session_token = None # Force re-login
                                if await self.login():
                                    self.logger.info("Re-login successful. Retrying API call once.")
                                    # Retry the call WITHOUT allowing another re-login attempt
                                    return await self._make_api_call(method, params, attempt_relogin=False)
                                else:
                                    self.logger.error("Re-login failed. Cannot proceed with API call.")
                                    return None
                            return None # Return None on other API errors

                        # Check if 'result' key exists and is not empty
                        if 'result' in resp_json and resp_json['result']:
                             self.logger.debug(f"API call successful: Method={method}")
                             return resp_json['result']
                        else:
                             # This is the key case from the user's logs
                             self.logger.error(f"API call returned status 200 but 'result' is missing or empty. Method: {method}. Response JSON: {resp_json}")
                             # Consider attempting re-login here as well, as it might indicate a session issue
                             if attempt_relogin:
                                  self.logger.warning("Empty result received. Attempting re-login as potential session issue.")
                                  self.session_token = None # Force re-login
                                  if await self.login():
                                       self.logger.info("Re-login successful. Retrying API call once.")
                                       return await self._make_api_call(method, params, attempt_relogin=False)
                                  else:
                                       self.logger.error("Re-login failed. Cannot proceed with API call.")
                                       return None
                             return None # Return None if result is missing/empty after check/retry

                    except json.JSONDecodeError:
                        self.logger.error(f"API call failed: Could not decode JSON response. Status: {resp.status}, Method: {method}. Response text: {resp_text}")
                        return None
                else:
                    self.logger.error(f"API call HTTP error. Status: {resp.status}, Method: {method}. Response: {resp_text}")
                    # Optionally check status code here for specific re-login triggers (e.g., 401 Unauthorized)
                    return None

        except aiohttp.ClientError as e:
             self.logger.error(f"Network error during API call: Method={method}. Error: {e}", exc_info=True)
             return None
        except Exception as e:
            self.logger.error(f"Unexpected exception during API call: Method={method}. Error: {e}", exc_info=True)
            return None

    async def get_football_markets(self, max_results: int = 1000, hours_ahead: int = 4) -> Optional[List[Dict]]:
        """
        Get football Match Odds markets, including in-play markets, sorted by matched volume.
        Uses the internal _make_api_call helper.

        Args:
            max_results: Maximum number of markets to return (split between upcoming and in-play).
            hours_ahead: How many hours into the future to search for markets.

        Returns:
            List of markets if successful, None otherwise.
        """
        now = datetime.now(timezone.utc)
        future = now + timedelta(hours=hours_ahead)
        today_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')
        future_str = future.strftime('%Y-%m-%dT%H:%M:%SZ')

        self.logger.info(f"Searching for football markets (upcoming and in-play) until {future_str}")

        all_markets = []

        # 1. Get upcoming markets
        upcoming_params = {
            'filter': {
                'eventTypeIds': ['1'],  # 1 is Football
                'marketTypeCodes': ['MATCH_ODDS'],
                'marketStartTime': {'from': today_str, 'to': future_str}
            },
            'maxResults': max_results // 2,
            'marketProjection': ['EVENT', 'COMPETITION', 'MARKET_START_TIME', 'RUNNER_DESCRIPTION'],
            'sort': 'MAXIMUM_TRADED'
        }
        upcoming_result = await self._make_api_call('SportsAPING/v1.0/listMarketCatalogue', upcoming_params)
        if upcoming_result:
            all_markets.extend(upcoming_result)
            self.logger.info(f"Found {len(upcoming_result)} upcoming football markets.")
        else:
            self.logger.warning("Failed to retrieve upcoming football markets.")
            # Continue to try in-play even if upcoming fails

        # 2. Get in-play markets
        inplay_params = {
            'filter': {
                'eventTypeIds': ['1'],
                'marketTypeCodes': ['MATCH_ODDS'],
                'inPlayOnly': True
            },
            'maxResults': max_results // 2,
            'marketProjection': ['EVENT', 'COMPETITION', 'MARKET_START_TIME', 'RUNNER_DESCRIPTION'],
            'sort': 'MAXIMUM_TRADED'
        }
        inplay_result = await self._make_api_call('SportsAPING/v1.0/listMarketCatalogue', inplay_params)
        if inplay_result:
            all_markets.extend(inplay_result)
            self.logger.info(f"Found {len(inplay_result)} in-play football markets.")
        else:
            self.logger.warning("Failed to retrieve in-play football markets.")

        if not all_markets:
             self.logger.info("No football markets found matching criteria.")
             return None # Return None if both calls failed or returned empty

        # Sort combined list by total matched volume (descending)
        # Note: 'totalMatched' isn't part of the projection, sorting relies on Betfair's 'MAXIMUM_TRADED' sort.
        # If accurate sorting is critical, 'totalMatched' needs to be fetched separately (e.g., via listMarketBook).
        # For now, we rely on Betfair's sort parameter.

        # Limit to the requested total number of markets
        limited_markets = all_markets[:max_results]

        markets_found = len(limited_markets)
        # Correctly count in-play from the final list
        # MarketCatalogue doesn't directly return 'inPlayAvailable', rely on filter used.
        # This count is approximate based on separate fetches.
        in_play_count_approx = len(inplay_result) if inplay_result else 0
        upcoming_count_approx = len(upcoming_result) if upcoming_result else 0

        self.logger.info(f"Returning a total of {markets_found} football markets "
                         f"(approx {in_play_count_approx} in-play, {upcoming_count_approx} upcoming)")

        return limited_markets

    async def get_market_data(self, market_id: str) -> Optional[Dict]:
        """
        Get detailed market data including prices (catalogue + book).
        Deprecated in favor of get_fresh_market_data but kept for potential compatibility.
        Uses the internal _make_api_call helper.
        """
        self.logger.warning("get_market_data is deprecated, use get_fresh_market_data instead.")

        # 1. Get Market Catalogue
        catalogue_params = {
            'filter': {'marketIds': [market_id]},
            'maxResults': 1,
            'marketProjection': ['EVENT', 'COMPETITION', 'MARKET_START_TIME', 'RUNNER_DESCRIPTION', 'MARKET_DESCRIPTION']
        }
        catalogue_result = await self._make_api_call('SportsAPING/v1.0/listMarketCatalogue', catalogue_params)

        if not catalogue_result:
            self.logger.error(f'No catalogue data found or API call failed for market {market_id}')
            return None
        catalogue_data = catalogue_result[0]

        # 2. Get Market Book
        book_params = {
            'marketIds': [market_id],
            'priceProjection': {
                'priceData': ['EX_BEST_OFFERS'],
                'exBestOffersOverrides': {'bestPricesDepth': 3}
            }
        }
        book_result = await self._make_api_call('SportsAPING/v1.0/listMarketBook', book_params)

        if not book_result:
            self.logger.error(f'No book data found or API call failed for market {market_id}')
            # Return catalogue data only if book fails? Or None? Returning None for consistency.
            return None
        book_data = book_result[0]

        # 3. Merge data
        try:
            market_data = {**book_data}
            market_data['event'] = catalogue_data.get('event', {})
            market_data['competition'] = catalogue_data.get('competition', {})
            market_data['marketName'] = catalogue_data.get('marketName', 'Unknown') # Note: MARKET_DESCRIPTION needed for marketName
            market_data['marketStartTime'] = catalogue_data.get('marketStartTime')

            runner_map = {
                str(r.get('selectionId')): {
                    'runnerName': r.get('runnerName', 'Unknown'),
                    'sortPriority': r.get('sortPriority', 999)
                }
                for r in catalogue_data.get('runners', [])
            }

            for runner in market_data.get('runners', []):
                selection_id = str(runner.get('selectionId'))
                if selection_id in runner_map:
                    runner['teamName'] = runner_map[selection_id]['runnerName'] # Use teamName for consistency
                    runner['sortPriority'] = runner_map[selection_id]['sortPriority']
                else:
                     runner['teamName'] = 'Unknown Runner'
                     runner['sortPriority'] = 999

            market_data['runners'] = sorted(
                market_data.get('runners', []),
                key=lambda r: r.get('sortPriority', 999)
            )
            return market_data
        except Exception as e:
             self.logger.error(f"Error merging market data for {market_id}: {e}", exc_info=True)
             return None

    async def get_fresh_market_data(self, market_id: str, price_depth: int = 3) -> Optional[Dict]:
        """
        Get fresh market data (book first, then catalogue) with improved error handling.
        Suitable for critical operations like result checking.
        Uses the internal _make_api_call helper.

        Args:
            market_id: Betfair market ID.
            price_depth: Depth of price data to request.

        Returns:
            Market data dictionary (potentially partial if catalogue fails) or None if book fails.
        """
        self.logger.debug(f"Getting fresh market data for market_id: {market_id}")

        # 1. Get Market Book (contains status)
        book_params = {
            'marketIds': [market_id],
            'priceProjection': {
                'priceData': ['EX_BEST_OFFERS'],
                'exBestOffersOverrides': {'bestPricesDepth': price_depth}
            }
        }
        book_result = await self._make_api_call('SportsAPING/v1.0/listMarketBook', book_params)

        if not book_result:
            # Error logged within _make_api_call, including the case of 200 OK with empty result
            self.logger.error(f"Failed to retrieve critical book data for market {market_id}. Cannot proceed.")
            return None # Cannot proceed without book data (status is essential)
        book_data = book_result[0]
        self.logger.debug(f"Successfully retrieved book data for {market_id}. Status: {book_data.get('status')}")


        # 2. Get Market Catalogue (for enrichment)
        catalogue_params = {
            'filter': {'marketIds': [market_id]},
            'maxResults': 1,
            'marketProjection': ['EVENT', 'COMPETITION', 'MARKET_START_TIME', 'RUNNER_DESCRIPTION']
            # Add 'MARKET_DESCRIPTION' if 'marketName' is needed
        }
        catalogue_result = await self._make_api_call('SportsAPING/v1.0/listMarketCatalogue', catalogue_params)

        if not catalogue_result:
            self.logger.warning(f"Returning partial market data for {market_id} (missing catalogue data)")
            # Return book data only, as it contains the essential status info
            return book_data
        catalogue_data = catalogue_result[0]

        # 3. Merge book and catalogue data
        try:
            market_data = {**book_data} # Start with book data (includes status)
            market_data['event'] = catalogue_data.get('event', {})
            market_data['competition'] = catalogue_data.get('competition', {})
            # market_data['marketName'] = catalogue_data.get('marketName', 'Unknown') # Requires MARKET_DESCRIPTION projection
            market_data['marketStartTime'] = catalogue_data.get('marketStartTime')

            # Create map for runner enrichment
            runner_map = {
                str(r.get('selectionId')): {
                    'runnerName': r.get('runnerName', 'Unknown'),
                    'sortPriority': r.get('sortPriority', 999)
                }
                for r in catalogue_data.get('runners', [])
            }

            # Enrich runners in the book data
            for runner in market_data.get('runners', []):
                selection_id = str(runner.get('selectionId'))
                if selection_id in runner_map:
                    runner['teamName'] = runner_map[selection_id]['runnerName'] # Use teamName for consistency
                    runner['sortPriority'] = runner_map[selection_id]['sortPriority']
                else:
                     # Should ideally not happen if catalogue fetch worked, but handle defensively
                     runner['teamName'] = runner.get('runnerName', 'Unknown Runner')
                     runner['sortPriority'] = runner.get('sortPriority', 999)


            # Sort runners by sortPriority
            market_data['runners'] = sorted(
                market_data.get('runners', []),
                key=lambda r: r.get('sortPriority', 999)
            )

            self.logger.debug(f"Successfully merged book and catalogue data for {market_id}")
            return market_data

        except Exception as e:
             self.logger.error(f"Error merging market data for {market_id}: {e}", exc_info=True)
             # Return partial (book) data if merging fails
             self.logger.warning(f"Returning partial market data for {market_id} due to merging error.")
             return book_data


    async def get_market_result(self, market_id: str, selection_id: int) -> Tuple[bool, str]:
        """
        Get the result of a specific selection in a market.

        Args:
            market_id: Betfair market ID.
            selection_id: Betfair selection ID.

        Returns:
            Tuple of (won: bool, status_message: str).
        """
        try:
            market_data = await self.get_fresh_market_data(market_id)
            if not market_data:
                # Error already logged by get_fresh_market_data
                return False, "Could not retrieve market data to determine result"

            market_status = market_data.get('status')
            if market_status not in ['CLOSED', 'SETTLED']:
                # This case should ideally be handled before calling get_market_result,
                # but check again defensively.
                self.logger.warning(f"Attempted to get result for market {market_id} which is not settled. Status: {market_status}")
                return False, f"Market not settled ({market_status})"

            # Find the runner corresponding to the selection_id
            target_runner = None
            for runner in market_data.get('runners', []):
                if runner.get('selectionId') == selection_id:
                    target_runner = runner
                    break

            if not target_runner:
                 # This is unexpected if market data was retrieved successfully
                 self.logger.error(f"Selection ID {selection_id} not found in market data for {market_id}. Data: {market_data}")
                 return False, "Selection ID not found in market data"

            runner_status = target_runner.get('status', 'UNKNOWN').upper()

            if runner_status == 'WINNER':
                self.logger.info(f"Selection {selection_id} WINNER in market {market_id}")
                return True, "Selection won"
            else:
                # Status could be LOSER, REMOVED, etc.
                self.logger.info(f"Selection {selection_id} {runner_status} in market {market_id}")
                return False, f"Selection {runner_status.lower()}"

        except Exception as e:
            self.logger.error(f'Exception during get_market_result for {market_id}: {e}', exc_info=True)
            return False, f"Error checking result: {str(e)}"


    async def get_markets_with_odds(self, max_markets: int = 10, hours_ahead: int = 4) -> Tuple[List[Dict], List[Dict]]:
        """
        Get football markets with their corresponding odds.
        Combines catalogue and book calls for efficiency.
        Uses the internal _make_api_call helper.

        Args:
            max_markets: Maximum number of markets to return.
            hours_ahead: How many hours into the future to search for markets.

        Returns:
            Tuple of (market_catalogues, market_books) or ([], []) on failure.
        """
        try:
            # 1. Get Market Catalogues first
            market_catalogues = await self.get_football_markets(max_markets, hours_ahead)
            if not market_catalogues:
                self.logger.warning("No market catalogues found in get_markets_with_odds.")
                return [], []

            market_ids = [market.get('marketId') for market in market_catalogues if market.get('marketId')]
            if not market_ids:
                 self.logger.warning("No valid market IDs found from catalogues.")
                 return market_catalogues, [] # Return catalogues even if IDs are missing

            # 2. Get Market Books for these markets
            book_params = {
                'marketIds': market_ids,
                'priceProjection': {
                    'priceData': ['EX_BEST_OFFERS'],
                    'exBestOffersOverrides': {'bestPricesDepth': 1} # Only need best price
                }
            }
            market_books_result = await self._make_api_call('SportsAPING/v1.0/listMarketBook', book_params)

            if not market_books_result:
                self.logger.warning(f"Failed to retrieve market books for {len(market_ids)} markets.")
                return market_catalogues, [] # Return catalogues even if books fail

            # 3. Enrich market books with runner names from catalogues
            market_map = {market.get('marketId'): market for market in market_catalogues}

            for book in market_books_result:
                market_id = book.get('marketId')
                if market_id in market_map:
                    catalogue = market_map[market_id]
                    runner_map = {
                        str(r.get('selectionId')): {
                            'runnerName': r.get('runnerName', 'Unknown'),
                            'sortPriority': r.get('sortPriority', 999)
                        }
                        for r in catalogue.get('runners', [])
                    }

                    for runner in book.get('runners', []):
                        selection_id = str(runner.get('selectionId'))
                        if selection_id in runner_map:
                            runner['teamName'] = runner_map[selection_id]['runnerName']
                            runner['sortPriority'] = runner_map[selection_id]['sortPriority']
                        else:
                             runner['teamName'] = 'Unknown Runner'
                             runner['sortPriority'] = 999
                else:
                     self.logger.warning(f"Market book found for {market_id} but no matching catalogue data.")

            return market_catalogues, market_books_result

        except Exception as e:
            self.logger.error(f'Exception during get_markets_with_odds: {e}', exc_info=True)
            return [], []