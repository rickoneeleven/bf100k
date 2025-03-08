"""
betfair_client.py - Fixed login method handling text/plain response
"""

import os
import json
import logging
import aiohttp
import ssl
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple

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

    async def get_football_markets_for_today(self) -> Optional[List[Dict]]:
        """Get top 5 football Match Odds markets for today, sorted by matched volume"""
        if not self.session_token:
            self.logger.error('No session token available - please login first')
            return None
            
        try:
            session = await self.ensure_session()
            
            today = datetime.now(timezone.utc).strftime('%Y-%m-%dT00:00:00Z')
            tomorrow = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59).strftime('%Y-%m-%dT%H:%M:%SZ')
            
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
                    'maxResults': 5,
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
                        return resp_json['result']
                    else:
                        self.logger.error(f'Error in response: {resp_json.get("error")}')
                        return None
                else:
                    self.logger.error(f'Request failed with status code: {resp.status}')
                    return None
                    
        except Exception as e:
            self.logger.error(f'Exception during get_football_markets_for_today: {str(e)}')
            return None

    async def list_market_book(
        self,
        market_ids: List[str],
        market_catalogue: List[Dict]
    ) -> Optional[List[Dict]]:
        """
        Get detailed market data including prices for specified markets
        
        Args:
            market_ids: List of market IDs to retrieve
            market_catalogue: Market catalogue data for mapping
        
        Returns:
            List of market books with mapped event data
        """
        if not self.session_token:
            self.logger.error('No session token available - please login first')
            return None
            
        try:
            session = await self.ensure_session()
            
            # Create market catalogue lookup
            catalogue_lookup = {market['marketId']: market for market in market_catalogue}
            
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
                        
                        # Add market data from catalogue
                        for market_book in market_books:
                            market_id = market_book['marketId']
                            if market_id in catalogue_lookup:
                                catalogue_data = catalogue_lookup[market_id]
                                market_book['event'] = catalogue_data.get('event', {})
                                market_book['competition'] = catalogue_data.get('competition', {})
                                market_book['marketStartTime'] = catalogue_data.get('marketStartTime')
                                
                                # Map runner names
                                runner_map = {
                                    r['selectionId']: r['runnerName'] 
                                    for r in catalogue_data.get('runners', [])
                                }
                                for runner in market_book.get('runners', []):
                                    selection_id = runner.get('selectionId')
                                    if selection_id in runner_map:
                                        runner['teamName'] = runner_map[selection_id]
                        
                        return market_books
                    else:
                        self.logger.error(f'Error in response: {resp_json.get("error")}')
                        return None
                else:
                    self.logger.error(f'Request failed with status code: {resp.status}')
                    return None
                    
        except Exception as e:
            self.logger.error(f'Exception during list_market_book: {str(e)}')
            return None

    async def get_markets_with_odds(self) -> Tuple[Optional[List[Dict]], Optional[List[Dict]]]:
        """
        Get both market catalogue and price data for top football markets
        Returns tuple of (market_catalogue, market_books) or (None, None) if error
        """
        # Get market catalogue data first
        markets = await self.get_football_markets_for_today()
        if not markets:
            return None, None
            
        # Get market IDs
        market_ids = [market['marketId'] for market in markets]
        
        # Get market books with catalogue data
        market_books = await self.list_market_book(market_ids, markets)
        if not market_books:
            return None, None
            
        return markets, market_books