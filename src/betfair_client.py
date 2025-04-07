# -*- coding: utf-8 -*-
"""
betfair_client.py

Simplified Betfair API client with improved result checking functionality,
enhanced logging, and automatic re-login attempt on session issues.
Corrected SSL context purpose and login headers.
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
    # Base headers ONLY for JSON-RPC calls (betting API)
    JSON_RPC_HEADERS_BASE = {'content-type': 'application/json'}

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
        """Creates and caches the SSL context for client certificate authentication."""
        if self._ssl_context is None:
            try:
                self.logger.debug("Creating SSL context for client authentication")
                # Create a default context suitable for client use.
                ssl_context = ssl.create_default_context()
                # Load the client certificate and key.
                self.logger.debug(f"Loading client cert chain: cert='{self.cert_file}', key='{self.key_file}'")
                ssl_context.load_cert_chain(self.cert_file, self.key_file)
                self._ssl_context = ssl_context
                self.logger.debug("SSL context created successfully.")
            except FileNotFoundError:
                self.logger.error(f"SSL Error: Certificate or Key file not found. Cert: '{self.cert_file}', Key: '{self.key_file}'", exc_info=True)
                self._ssl_context = None
            except ssl.SSLError as e:
                 self.logger.error(f"SSL Error loading certificate chain: {e}", exc_info=True)
                 self._ssl_context = None
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
            # Ensure App Key is present first
            if not self.app_key:
                self.logger.error("Missing Betfair app key (check BETFAIR_APP_KEY env var)")
                return False

            # Get or create SSL context
            ssl_context = self._create_ssl_context()
            if not ssl_context:
                 self.logger.error("Cannot proceed with login due to SSL context creation failure.")
                 return False

            # Ensure session is available
            session = await self.ensure_session()
            if not session:
                self.logger.error("Failed to get valid aiohttp session for login.")
                return False

            # Get credentials
            username = os.getenv('BETFAIR_USERNAME')
            password = os.getenv('BETFAIR_PASSWORD')
            if not username or not password:
                self.logger.error("Missing Betfair credentials (check BETFAIR_USERNAME, BETFAIR_PASSWORD env vars)")
                return False

            self.logger.info("Attempting to login to Betfair via cert...")
            payload = {'username': username, 'password': password}
            # ** LOGIN HEADERS - DO NOT SET Content-Type for form data **
            login_headers = {'X-Application': self.app_key}

            self.logger.debug(f"Login URL: {self.CERT_LOGIN_URL}")
            self.logger.debug(f"Login Headers: {login_headers}") # Log the actual headers used
            self.logger.debug(f"Login Payload (sent as data): {payload}")

            async with session.post(
                self.CERT_LOGIN_URL,
                data=payload,           # Use 'data' for form-encoding
                headers=login_headers,  # Use specific login headers
                ssl=ssl_context         # Pass the specific context
            ) as resp:
                resp_text = await resp.text()
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
                            login_status = resp_json.get('loginStatus', 'UNKNOWN')
                            login_error = resp_json.get('error', 'N/A')
                            self.logger.error(f"Login failed: Status={login_status}, Error={login_error}")
                            if "CERT_AUTH_REQUIRED" in str(login_error):
                                 self.logger.error("Hint: Ensure the correct certificate/key files are specified and accessible.")
                            elif "INVALID_USERNAME_OR_PASSWORD" in str(login_status):
                                 self.logger.error("Hint: Double-check BETFAIR_USERNAME and BETFAIR_PASSWORD environment variables.")
                            return False
                    except json.JSONDecodeError:
                        self.logger.error(f"Login failed: Could not decode JSON response. Response text: {resp_text}")
                        return False
                else:
                    # Log the 400 error here again with response
                    self.logger.error(f"Login request failed. Status: {resp.status}, Response: {resp_text}")
                    return False

        except aiohttp.ClientError as e:
             if isinstance(e, aiohttp.ClientConnectorSSLError):
                  self.logger.error(f"SSL connection error during login: {e}", exc_info=False) # Keep log cleaner
             else:
                  self.logger.error(f"Network error during login: {e}", exc_info=False)
             return False
        except Exception as e:
            self.logger.error(f"Unexpected exception during login: {e}", exc_info=True)
            return False

    async def _make_api_call(self, method: str, params: Dict, attempt_relogin: bool = True) -> Optional[Dict]:
        """
        Internal helper to make Betfair API calls (JSON-RPC) with error handling and re-login attempt.
        """
        if not self.session_token:
            self.logger.error(f'No session token available for {method}. Trying to login first.')
            if not await self.login():
                 self.logger.error(f"Login attempt failed within _make_api_call for {method}.")
                 return None

        session = await self.ensure_session()
        if not session:
             self.logger.error(f"Failed to get valid aiohttp session for API call {method}.")
             return None

        payload = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params,
            'id': 1
        }
        # ** JSON-RPC HEADERS - Use application/json here **
        headers = {
            **self.JSON_RPC_HEADERS_BASE,
            'X-Application': self.app_key,
            'X-Authentication': self.session_token
        }

        try:
            self.logger.debug(f"Making API call: Method={method}, Params={json.dumps(params)}")
            # Use 'json' parameter for JSON-RPC calls
            async with session.post(self.BETTING_URL, json=payload, headers=headers) as resp:
                resp_text = await resp.text()
                self.logger.debug(f"API call response status: {resp.status}, Method: {method}")

                if resp.status == 200:
                    try:
                        resp_json = json.loads(resp_text)
                        if 'error' in resp_json:
                            error_info = resp_json['error']
                            error_code = error_info.get('data', {}).get('APINGException', {}).get('errorCode', 'N/A')
                            error_details = error_info.get('data', {}).get('APINGException', {}).get('errorDetails', 'N/A')
                            self.logger.error(f"API error received (Status 200): Code={error_code}, Details={error_details}, Method={method}, FullError={error_info}")

                            if attempt_relogin and error_code == 'INVALID_SESSION_INFORMATION':
                                self.logger.warning(f"INVALID_SESSION_INFORMATION detected for {method}. Attempting re-login.")
                                self.session_token = None
                                if await self.login():
                                    self.logger.info("Re-login successful. Retrying API call once.")
                                    return await self._make_api_call(method, params, attempt_relogin=False)
                                else:
                                    self.logger.error("Re-login failed. Cannot proceed with API call.")
                                    return None
                            return None

                        if 'result' in resp_json:
                             if isinstance(resp_json['result'], list) and not resp_json['result']:
                                  self.logger.debug(f"API call returned empty list result (valid for {method}).")
                             elif not resp_json['result'] and not isinstance(resp_json['result'], list):
                                  self.logger.warning(f"API call returned non-list empty result for {method}. Response: {resp_json}")

                             self.logger.debug(f"API call successful: Method={method}")
                             return resp_json['result']
                        else:
                             self.logger.error(f"API call returned status 200 but 'result' key is MISSING. Method: {method}. Response JSON: {resp_json}")
                             if attempt_relogin:
                                  self.logger.warning(f"Missing 'result' key for {method}. Attempting re-login.")
                                  self.session_token = None
                                  if await self.login():
                                       self.logger.info("Re-login successful. Retrying API call once.")
                                       return await self._make_api_call(method, params, attempt_relogin=False)
                                  else:
                                       self.logger.error("Re-login failed. Cannot proceed with API call.")
                                       return None
                             return None

                    except json.JSONDecodeError:
                        self.logger.error(f"API call failed: Could not decode JSON response. Status: {resp.status}, Method: {method}. Response text: {resp_text}")
                        return None
                else:
                    self.logger.error(f"API call HTTP error. Status: {resp.status}, Method: {method}. Response: {resp_text}")
                    return None

        except aiohttp.ClientError as e:
             self.logger.error(f"Network error during API call: Method={method}. Error: {e}", exc_info=False)
             return None
        except Exception as e:
            self.logger.error(f"Unexpected exception during API call: Method={method}. Error: {e}", exc_info=True)
            return None

    # --- Methods using _make_api_call (No changes needed below this line from previous version) ---

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
        upcoming_result_count = 0
        inplay_result_count = 0


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
        if upcoming_result is not None: # Check for None explicitly, as empty list is valid
            all_markets.extend(upcoming_result)
            upcoming_result_count = len(upcoming_result)
            self.logger.info(f"Found {upcoming_result_count} upcoming football markets.")
        else:
            self.logger.warning("Failed to retrieve upcoming football markets or API call failed.")
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
        if inplay_result is not None: # Check for None explicitly
            all_markets.extend(inplay_result)
            inplay_result_count = len(inplay_result)
            self.logger.info(f"Found {inplay_result_count} in-play football markets.")
        else:
            self.logger.warning("Failed to retrieve in-play football markets or API call failed.")

        if not all_markets:
             self.logger.info("No football markets found matching criteria.")
             return None # Return None if both calls failed or returned empty

        # Rely on Betfair's sort parameter 'MAXIMUM_TRADED'. Explicit sorting client-side
        # would require fetching 'totalMatched' via listMarketBook.

        # Limit to the requested total number of markets
        limited_markets = all_markets[:max_results]
        markets_found = len(limited_markets)

        self.logger.info(f"Returning a total of {markets_found} football markets "
                         f"(approx {inplay_result_count} in-play, {upcoming_result_count} upcoming)")

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

        # Check if book_result is None (API call failed or returned error/missing result)
        if book_result is None:
            # Error logged within _make_api_call
            self.logger.error(f"Failed to retrieve critical book data for market {market_id}. Cannot proceed.")
            return None

        # Check if book_result is an empty list (valid case, means market doesn't exist or isn't accessible)
        if isinstance(book_result, list) and not book_result:
             self.logger.warning(f"listMarketBook returned empty list for market {market_id}. Market might not exist or is inaccessible.")
             return None # Treat as failure to get data

        # If we have a result, it should be a list containing one book
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

        # Check if catalogue_result is None or empty list
        if catalogue_result is None or (isinstance(catalogue_result, list) and not catalogue_result):
            self.logger.warning(f"Returning partial market data for {market_id} (missing or failed catalogue data)")
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
            # Get fresh data, which includes status and runner results
            market_data = await self.get_fresh_market_data(market_id)
            if not market_data:
                # Error already logged by get_fresh_market_data
                return False, "Could not retrieve market data to determine result"

            market_status = market_data.get('status')
            # Only proceed if the market is definitively settled
            if market_status not in ['CLOSED', 'SETTLED']:
                self.logger.warning(f"Attempted to get result for market {market_id} which is not settled. Status: {market_status}")
                return False, f"Market not settled ({market_status})"

            # Find the runner corresponding to the selection_id
            target_runner = None
            for runner in market_data.get('runners', []):
                # Ensure comparison is correct type (selection_id is int, runner['selectionId'] might be str/int)
                if str(runner.get('selectionId')) == str(selection_id):
                    target_runner = runner
                    break

            if not target_runner:
                 self.logger.error(f"Selection ID {selection_id} not found in CLOSED/SETTLED market data for {market_id}. Data: {market_data}")
                 return False, "Selection ID not found in settled market data"

            # Get the status of our specific runner
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
            # Check for None or empty list
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

            # Check for None or empty list
            if not market_books_result:
                self.logger.warning(f"Failed to retrieve market books for {len(market_ids)} markets or API call failed.")
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