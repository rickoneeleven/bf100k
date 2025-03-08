"""
betfair_client.py

Enhanced Betfair API client with additional capabilities:
- Real result checking through Betfair API
- Improved market discovery with consistent selection mapping
- More robust connection handling
- Fixed odds mapping between initial market discovery and active bet display
"""

import os
import json
import logging
import aiohttp
import ssl
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Tuple, Any

class BetfairClient:
    def __init__(self, app_key: str, cert_file: str, key_file: str):
        self.app_key = app_key
        self.cert_file = cert_file
        self.key_file = key_file
        self.session_token = None
        self._http_session = None
        self._session_lock = asyncio.Lock()
        
        # Setup logging
        self.logger = logging.getLogger('BetfairClient')
        self.logger.setLevel(logging.INFO)
        
        # Ensure log directory exists
        log_dir = os.path.dirname('web/logs/betfair_client.log')
        os.makedirs(log_dir, exist_ok=True)
        
        handler = logging.FileHandler('web/logs/betfair_client.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        
        # API endpoints
        self.cert_login_url = 'https://identitysso-cert.betfair.com/api/certlogin'
        self.betting_url = 'https://api.betfair.com/exchange/betting/json-rpc/v1'
        
        # Check if files exist
        if not os.path.exists(self.cert_file):
            print(f"WARNING: Certificate file does not exist: {self.cert_file}")
            self.logger.error(f"Certificate file does not exist: {self.cert_file}")
        if not os.path.exists(self.key_file):
            print(f"WARNING: Key file does not exist: {self.key_file}")
            self.logger.error(f"Key file does not exist: {self.key_file}")

    async def ensure_session(self) -> aiohttp.ClientSession:
        """Ensure a valid HTTP session exists and return it"""
        if self._http_session is None or self._http_session.closed:
            print("Creating new aiohttp ClientSession")
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def close_session(self) -> None:
        """Close the HTTP session if it exists"""
        if self._http_session and not self._http_session.closed:
            print("Closing aiohttp ClientSession")
            await self._http_session.close()
            self._http_session = None

    async def __aenter__(self):
        await self.ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close_session()

    async def login(self) -> bool:
        """Login to Betfair API using certificate-based authentication"""
        try:
            print("Attempting to login to Betfair...")
            session = await self.ensure_session()
            
            # Get credentials from environment
            username = os.getenv('BETFAIR_USERNAME')
            password = os.getenv('BETFAIR_PASSWORD')
            
            print(f"Username: {username[:3]}{'*' * (len(username) - 3) if username else 'None'}")
            print(f"Password: {'*' * (len(password)) if password else 'None'}")
            print(f"App Key: {self.app_key[:3]}{'*' * (len(self.app_key) - 3) if self.app_key else 'None'}")
            print(f"Cert File: {self.cert_file}")
            print(f"Key File: {self.key_file}")
            
            if not username or not password:
                print("ERROR: Missing Betfair credentials in environment variables")
                self.logger.error("Missing Betfair credentials in environment variables")
                return False
                
            if not self.app_key:
                print("ERROR: Missing Betfair app key")
                self.logger.error("Missing Betfair app key")
                return False
                
            payload = {
                'username': username,
                'password': password
            }
            
            print("Creating SSL context...")
            try:
                ssl_context = ssl.create_default_context()
                ssl_context.load_cert_chain(self.cert_file, self.key_file)
                print("SSL context created successfully")
            except Exception as ssl_error:
                print(f"ERROR creating SSL context: {str(ssl_error)}")
                self.logger.error(f"SSL context creation failed: {str(ssl_error)}")
                return False
            
            print(f"Sending login request to {self.cert_login_url}...")
            try:
                async with session.post(
                    self.cert_login_url,
                    data=payload,
                    headers={'X-Application': self.app_key},
                    ssl=ssl_context
                ) as resp:
                    print(f"Received response with status code: {resp.status}")
                    
                    if resp.status == 200:
                        try:
                            # First get the text response
                            resp_text = await resp.text()
                            print(f"Response text: {resp_text[:100]}...")
                            
                            # Then parse it as JSON
                            resp_json = json.loads(resp_text)
                            
                            if resp_json.get('loginStatus') == 'SUCCESS':
                                self.session_token = resp_json['sessionToken']
                                print("Login SUCCESS - session token obtained")
                                self.logger.info('Successfully logged in to Betfair')
                                return True
                            else:
                                print(f"Login FAILED with status: {resp_json.get('loginStatus')}")
                                if 'error' in resp_json:
                                    print(f"Error details: {resp_json['error']}")
                                self.logger.error(f"Login failed: {resp_json.get('loginStatus')}")
                                return False
                        except json.JSONDecodeError as e:
                            print(f"Failed to parse login response: {resp_text}")
                            self.logger.error(f"Failed to parse login response: {resp_text}")
                            return False
                    else:
                        print(f"Login request failed with status code: {resp.status}")
                        try:
                            err_text = await resp.text()
                            print(f"Error response: {err_text[:200]}")
                        except:
                            print("Could not read error response")
                        
                        self.logger.error(f"Login request failed with status code: {resp.status}")
                        return False
            except Exception as req_error:
                print(f"ERROR during login request: {str(req_error)}")
                self.logger.error(f"Exception during login request: {str(req_error)}")
                return False
                    
        except Exception as e:
            print(f"EXCEPTION during login: {str(e)}")
            self.logger.error(f"Exception during login: {str(e)}")
            return False

    async def get_football_markets(self, max_results: int = 10) -> Optional[List[Dict]]:
        """
        Get football Match Odds markets, sorted by matched volume
        
        Args:
            max_results: Maximum number of markets to return
            
        Returns:
            List of market data or None if error
        """
        if not self.session_token:
            self.logger.error('No session token available - please login first')
            return None
            
        try:
            session = await self.ensure_session()
            
            # Set time window from now to 12 hours in the future
            now = datetime.now(timezone.utc)
            future = now + timedelta(hours=12)
            
            today = now.strftime('%Y-%m-%dT%H:%M:%SZ')
            tomorrow = future.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            self.logger.info(f"Looking for football markets from {today} to {tomorrow}")
            
            payload = {
                'jsonrpc': '2.0',
                'method': 'SportsAPING/v1.0/listMarketCatalogue',
                'params': {
                    'filter': {
                        'eventTypeIds': ['1'],  # 1 is Football
                        'marketTypeCodes': ['MATCH_ODDS'],
                        'marketStartTime': {
                            'from': today,
                            'to': tomorrow
                        },
                        'inPlayOnly': False
                    },
                    'maxResults': max_results,
                    'marketProjection': [
                        'EVENT',
                        'MARKET_START_TIME',
                        'RUNNER_DESCRIPTION',
                        'COMPETITION'
                    ],
                    'sort': 'MAXIMUM_TRADED'
                },
                'id': 1
            }
            
            headers = {
                'X-Application': self.app_key,
                'X-Authentication': self.session_token,
                'content-type': 'application/json'
            }
            
            async with session.post(self.betting_url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    resp_json = await resp.json()
                    if 'result' in resp_json:
                        self.logger.info(f"Found {len(resp_json['result'])} football markets")
                        return resp_json['result']
                    else:
                        self.logger.error(f'Error in response: {resp_json.get("error")}')
                        return None
                else:
                    self.logger.error(f'Request failed with status code: {resp.status}')
                    return None
                    
        except Exception as e:
            self.logger.error(f'Exception during get_football_markets: {str(e)}')
            return None

    async def _get_market_catalogue_for_ids(self, market_ids: List[str]) -> Optional[List[Dict]]:
        """
        Get market catalogue data for specific market IDs
        
        Args:
            market_ids: List of market IDs to retrieve catalogue data for
            
        Returns:
            List of market catalogue data or None if error
        """
        if not self.session_token:
            self.logger.error('No session token available - please login first')
            return None
            
        try:
            session = await self.ensure_session()
            
            payload = {
                'jsonrpc': '2.0',
                'method': 'SportsAPING/v1.0/listMarketCatalogue',
                'params': {
                    'filter': {
                        'marketIds': market_ids
                    },
                    'maxResults': len(market_ids),
                    'marketProjection': [
                        'EVENT',
                        'COMPETITION',
                        'MARKET_START_TIME',
                        'RUNNER_DESCRIPTION',
                        'MARKET_DESCRIPTION'
                    ]
                },
                'id': 1
            }
            
            headers = {
                'X-Application': self.app_key,
                'X-Authentication': self.session_token,
                'content-type': 'application/json'
            }
            
            async with session.post(self.betting_url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    resp_json = await resp.json()
                    if 'result' in resp_json:
                        return resp_json['result']
                    else:
                        self.logger.error(f'Error in response: {resp_json.get("error")}')
                        return None
                else:
                    self.logger.error(f'Request failed with status code: {resp.status}')
                    return None
                    
        except Exception as e:
            self.logger.error(f'Exception during _get_market_catalogue_for_ids: {str(e)}')
            self.logger.exception(e)
            return None

    async def list_market_book(
        self,
        market_ids: List[str],
        market_catalogue: List[Dict] = None
    ) -> Optional[List[Dict]]:
        """
        Get detailed market data including prices for specified markets with improved selection mapping
        
        Args:
            market_ids: List of market IDs to retrieve
            market_catalogue: Market catalogue data for mapping (if None, will fetch fresh data)
        
        Returns:
            List of market books with mapped event data and properly sorted runners
        """
        if not self.session_token:
            self.logger.error('No session token available - please login first')
            return None
            
        try:
            session = await self.ensure_session()
            
            # Get fresh catalogue data if not provided
            if not market_catalogue:
                market_catalogue = await self._get_market_catalogue_for_ids(market_ids)
                if not market_catalogue:
                    self.logger.warning("Failed to get market catalogue data for mapping")
            
            # Create market catalogue lookup
            catalogue_lookup = {market['marketId']: market for market in market_catalogue} if market_catalogue else {}
            
            payload = {
                'jsonrpc': '2.0',
                'method': 'SportsAPING/v1.0/listMarketBook',
                'params': {
                    'marketIds': market_ids,
                    'priceProjection': {
                        'priceData': ['EX_BEST_OFFERS'],
                        'exBestOffersOverrides': {
                            'bestPricesDepth': 1
                        }
                    }
                },
                'id': 1
            }
            
            headers = {
                'X-Application': self.app_key,
                'X-Authentication': self.session_token,
                'content-type': 'application/json'
            }
            
            async with session.post(self.betting_url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    resp_json = await resp.json()
                    if 'result' in resp_json:
                        market_books = resp_json['result']
                        
                        # Add market data from catalogue and map runners consistently
                        for market_book in market_books:
                            market_id = market_book['marketId']
                            
                            # Add catalogue data if available
                            if market_id in catalogue_lookup:
                                catalogue_data = catalogue_lookup[market_id]
                                market_book['event'] = catalogue_data.get('event', {})
                                market_book['competition'] = catalogue_data.get('competition', {})
                                market_book['marketStartTime'] = catalogue_data.get('marketStartTime')
                                market_book['marketName'] = catalogue_data.get('marketName', 'Unknown Market')
                                
                                # Create consistent runner mapping by selection ID
                                runner_map = {
                                    str(r['selectionId']): {
                                        'runnerName': r.get('runnerName', 'Unknown'),
                                        'sortPriority': r.get('sortPriority', 999)
                                    } 
                                    for r in catalogue_data.get('runners', [])
                                }
                                
                                # Map runner details consistently using selection ID as the key
                                for runner in market_book.get('runners', []):
                                    selection_id = str(runner.get('selectionId'))
                                    if selection_id in runner_map:
                                        runner['teamName'] = runner_map[selection_id]['runnerName']
                                        runner['sortPriority'] = runner_map[selection_id]['sortPriority']
                                
                                # Sort runners by sortPriority for consistent ordering
                                market_book['runners'] = sorted(
                                    market_book.get('runners', []),
                                    key=lambda r: r.get('sortPriority', 999)
                                )
                        
                        return market_books
                    else:
                        self.logger.error(f'Error in response: {resp_json.get("error")}')
                        return None
                else:
                    self.logger.error(f'Request failed with status code: {resp.status}')
                    return None
                    
        except Exception as e:
            self.logger.error(f'Exception during list_market_book: {str(e)}')
            self.logger.exception(e)
            return None

    async def get_markets_with_odds(self, max_results: int = 10) -> Tuple[Optional[List[Dict]], Optional[List[Dict]]]:
        """
        Get both market catalogue and price data for top football markets with enhanced mapping
        
        Args:
            max_results: Maximum number of markets to return
            
        Returns:
            Tuple of (market_catalogue, market_books) or (None, None) if error
        """
        # Get market catalogue data first
        markets = await self.get_football_markets(max_results)
        if not markets:
            return None, None
            
        # Get market IDs
        market_ids = [market['marketId'] for market in markets]
        
        # Get market books with improved catalogue data mapping
        market_books = await self.list_market_book(market_ids, markets)
        if not market_books:
            return None, None
        
        self.logger.info(f"Retrieved {len(market_books)} market books with enhanced mapping")
        
        return markets, market_books
        
    async def check_market_status(self, market_id: str) -> Optional[Dict]:
        """
        Check current status of a market with enhanced data and consistent runner mapping
        
        Args:
            market_id: Betfair market ID
            
        Returns:
            Enhanced market status information or None if error
        """
        if not self.session_token:
            self.logger.error('No session token available - please login first')
            return None
            
        try:
            session = await self.ensure_session()
            
            # Get market catalogue data first for event details and start time
            catalogue_data = None
            catalogue_data_list = await self._get_market_catalogue_for_ids([market_id])
            if catalogue_data_list and len(catalogue_data_list) > 0:
                catalogue_data = catalogue_data_list[0]
            
            # Get market book data with prices
            book_payload = {
                'jsonrpc': '2.0',
                'method': 'SportsAPING/v1.0/listMarketBook',
                'params': {
                    'marketIds': [market_id],
                    'priceProjection': {
                        'priceData': ['EX_BEST_OFFERS'],
                        'exBestOffersOverrides': {
                            'bestPricesDepth': 3
                        }
                    }
                },
                'id': 1
            }
            
            headers = {
                'X-Application': self.app_key,
                'X-Authentication': self.session_token,
                'content-type': 'application/json'
            }
            
            # Get market price data
            market_book = None
            async with session.post(self.betting_url, json=book_payload, headers=headers) as resp:
                if resp.status == 200:
                    resp_json = await resp.json()
                    if 'result' in resp_json and resp_json['result']:
                        market_book = resp_json['result'][0]
                        
                        # If we have catalogue data, merge it with market book
                        if catalogue_data:
                            # Add event and competition details
                            market_book['event'] = catalogue_data.get('event', {})
                            market_book['competition'] = catalogue_data.get('competition', {})
                            market_book['marketName'] = catalogue_data.get('marketName', 'Unknown Market')
                            market_book['marketStartTime'] = catalogue_data.get('marketStartTime')
                            
                            # Create consistent runner mapping by selection ID
                            runner_map = {
                                str(r['selectionId']): {
                                    'runnerName': r.get('runnerName', 'Unknown'),
                                    'sortPriority': r.get('sortPriority', 999)
                                } 
                                for r in catalogue_data.get('runners', [])
                            }
                            
                            # Update runner details using consistent mapping
                            for runner in market_book.get('runners', []):
                                selection_id = str(runner.get('selectionId'))
                                if selection_id in runner_map:
                                    runner['runnerName'] = runner_map[selection_id]['runnerName']
                                    runner['sortPriority'] = runner_map[selection_id]['sortPriority']
                            
                            # Sort runners by sortPriority for consistent ordering
                            market_book['runners'] = sorted(
                                market_book.get('runners', []),
                                key=lambda r: r.get('sortPriority', 999)
                            )
                        
                        self.logger.info(
                            f"Market {market_id} status: {market_book.get('status')}, "
                            f"Inplay: {market_book.get('inplay')}"
                        )
                        return market_book
                    else:
                        error_msg = resp_json.get('error', 'Unknown error')
                        self.logger.error(f'Error checking market status: {error_msg}')
                        return None
                else:
                    self.logger.error(f'Request failed with status code: {resp.status}')
                    return None
                    
        except Exception as e:
            self.logger.error(f'Exception during check_market_status: {str(e)}')
            self.logger.exception(e)
            return None
            
    async def check_settled_market(self, market_id: str) -> Optional[Dict]:
        """
        Check if a market has been settled and get the results
        
        Args:
            market_id: Betfair market ID
            
        Returns:
            Settlement information or None if error/not settled
        """
        if not self.session_token:
            self.logger.error('No session token available - please login first')
            return None
            
        try:
            session = await self.ensure_session()
            
            # First, check if the market is closed
            market_status = await self.check_market_status(market_id)
            if not market_status:
                self.logger.warning(f"Failed to get market status for {market_id}")
                return None
                
            # Only proceed if market is CLOSED or SETTLED
            if market_status.get('status') not in ['CLOSED', 'SETTLED']:
                self.logger.info(
                    f"Market {market_id} is not yet settled. "
                    f"Current status: {market_status.get('status')}"
                )
                return None
                
            # Get market results using listClearedOrders
            payload = {
                'jsonrpc': '2.0',
                'method': 'SportsAPING/v1.0/listClearedOrders',
                'params': {
                    'betStatus': 'SETTLED',
                    'marketIds': [market_id]
                },
                'id': 1
            }
            
            headers = {
                'X-Application': self.app_key,
                'X-Authentication': self.session_token,
                'content-type': 'application/json'
            }
            
            async with session.post(self.betting_url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    resp_json = await resp.json()
                    if 'result' in resp_json:
                        self.logger.info(f"Got settlement data for market {market_id}")
                        return resp_json['result']
                    else:
                        error_msg = resp_json.get('error', 'Unknown error')
                        self.logger.error(f'Error checking settled market: {error_msg}')
                        return None
                else:
                    self.logger.error(f'Request failed with status code: {resp.status}')
                    return None
                    
        except Exception as e:
            self.logger.error(f'Exception during check_settled_market: {str(e)}')
            return None
            
    async def get_market_result(self, market_id: str, selection_id: int) -> Tuple[bool, str]:
        """
        Get the result of a specific selection in a market
        
        Args:
            market_id: Betfair market ID
            selection_id: Selection ID to check
            
        Returns:
            Tuple of (won: bool, status_message: str)
        """
        try:
            # First check market status
            market_status = await self.check_market_status(market_id)
            if not market_status:
                return False, "Could not retrieve market status"
                
            # Check if market is settled
            if market_status.get('status') not in ['CLOSED', 'SETTLED']:
                return False, f"Market not yet settled. Status: {market_status.get('status')}"
                
            # For closed/settled markets, check the winners
            winners = []
            for runner in market_status.get('runners', []):
                if runner.get('status') == 'WINNER':
                    winners.append(runner.get('selectionId'))
                    
            # Check if our selection is a winner
            if selection_id in winners:
                self.logger.info(f"Selection {selection_id} won in market {market_id}")
                return True, "Selection won"
            else:
                self.logger.info(f"Selection {selection_id} lost in market {market_id}")
                return False, "Selection lost"
                
        except Exception as e:
            self.logger.error(f'Exception during get_market_result: {str(e)}')
            return False, f"Error checking result: {str(e)}"