"""
betfair_client.py

Simplified Betfair API client with clear, focused functionality.
"""

import os
import json
import logging
import aiohttp
import ssl
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Tuple, Any

class BetfairClient:
    def __init__(self, app_key: str, cert_file: str, key_file: str):
        self.app_key = app_key
        self.cert_file = cert_file
        self.key_file = key_file
        self.session_token = None
        self._http_session = None
        
        # Setup logging
        self.logger = logging.getLogger('BetfairClient')
        
        # API endpoints
        self.cert_login_url = 'https://identitysso-cert.betfair.com/api/certlogin'
        self.betting_url = 'https://api.betfair.com/exchange/betting/json-rpc/v1'
        
    async def ensure_session(self) -> aiohttp.ClientSession:
        """Ensure a valid HTTP session exists and return it"""
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def close_session(self) -> None:
        """Close the HTTP session if it exists"""
        if self._http_session and not self._http_session.closed:
            print("Closing aiohttp ClientSession")
            await self._http_session.close()
            self._http_session = None

    async def login(self) -> bool:
        """Login to Betfair API using certificate-based authentication"""
        try:
            self.logger.info("Attempting to login to Betfair")
            session = await self.ensure_session()
            
            # Get credentials from environment
            username = os.getenv('BETFAIR_USERNAME')
            password = os.getenv('BETFAIR_PASSWORD')
            
            if not username or not password:
                self.logger.error("Missing Betfair credentials in environment variables")
                return False
                
            if not self.app_key:
                self.logger.error("Missing Betfair app key")
                return False
                
            payload = {
                'username': username,
                'password': password
            }
            
            # Create SSL context
            ssl_context = ssl.create_default_context()
            ssl_context.load_cert_chain(self.cert_file, self.key_file)
            
            # Send login request
            async with session.post(
                self.cert_login_url,
                data=payload,
                headers={'X-Application': self.app_key},
                ssl=ssl_context
            ) as resp:
                if resp.status == 200:
                    resp_text = await resp.text()
                    resp_json = json.loads(resp_text)
                    
                    if resp_json.get('loginStatus') == 'SUCCESS':
                        self.session_token = resp_json['sessionToken']
                        self.logger.info('Successfully logged in to Betfair')
                        return True
                    else:
                        self.logger.error(f"Login failed: {resp_json.get('loginStatus')}")
                        return False
                else:
                    self.logger.error(f"Login request failed with status code: {resp.status}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Exception during login: {str(e)}")
            return False

    async def get_football_markets(self, max_results: int = 10) -> Optional[List[Dict]]:
        """Get football Match Odds markets, sorted by matched volume"""
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

    async def get_market_data(self, market_id: str) -> Optional[Dict]:
        """Get detailed market data including prices"""
        if not self.session_token:
            self.logger.error('No session token available - please login first')
            return None
            
        try:
            session = await self.ensure_session()
            
            # Get market catalogue
            catalogue_payload = {
                'jsonrpc': '2.0',
                'method': 'SportsAPING/v1.0/listMarketCatalogue',
                'params': {
                    'filter': {
                        'marketIds': [market_id]
                    },
                    'maxResults': 1,
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
            
            # Get market book
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
            
            # Get catalogue data
            async with session.post(self.betting_url, json=catalogue_payload, headers=headers) as resp:
                if resp.status != 200:
                    self.logger.error(f'Catalogue request failed with status code: {resp.status}')
                    return None
                    
                catalogue_json = await resp.json()
                if 'result' not in catalogue_json or not catalogue_json['result']:
                    self.logger.error(f'No catalogue data found for market {market_id}')
                    return None
                    
                catalogue_data = catalogue_json['result'][0]
            
            # Get book data
            async with session.post(self.betting_url, json=book_payload, headers=headers) as resp:
                if resp.status != 200:
                    self.logger.error(f'Book request failed with status code: {resp.status}')
                    return None
                    
                book_json = await resp.json()
                if 'result' not in book_json or not book_json['result']:
                    self.logger.error(f'No book data found for market {market_id}')
                    return None
                    
                book_data = book_json['result'][0]
            
            # Merge catalogue and book data
            market_data = {**book_data}
            market_data['event'] = catalogue_data.get('event', {})
            market_data['competition'] = catalogue_data.get('competition', {})
            market_data['marketName'] = catalogue_data.get('marketName', 'Unknown')
            market_data['marketStartTime'] = catalogue_data.get('marketStartTime')
            
            # Create a map of runners by selection ID
            runner_map = {
                str(r.get('selectionId')): {
                    'runnerName': r.get('runnerName', 'Unknown'),
                    'sortPriority': r.get('sortPriority', 999)
                }
                for r in catalogue_data.get('runners', [])
            }
            
            # Add runner names and sort by priority
            for runner in market_data.get('runners', []):
                selection_id = str(runner.get('selectionId'))
                if selection_id in runner_map:
                    runner['teamName'] = runner_map[selection_id]['runnerName']
                    runner['sortPriority'] = runner_map[selection_id]['sortPriority']
            
            # Sort runners by sortPriority
            market_data['runners'] = sorted(
                market_data.get('runners', []),
                key=lambda r: r.get('sortPriority', 999)
            )
            
            return market_data
                    
        except Exception as e:
            self.logger.error(f'Exception during get_market_data: {str(e)}')
            return None

    async def get_market_result(self, market_id: str, selection_id: int) -> Tuple[bool, str]:
        """Get the result of a specific selection in a market"""
        try:
            # Check market status
            market_data = await self.get_market_data(market_id)
            if not market_data:
                return False, "Could not retrieve market data"
                
            # Check if market is settled
            if market_data.get('status') not in ['CLOSED', 'SETTLED']:
                return False, f"Market not yet settled. Status: {market_data.get('status')}"
                
            # For closed/settled markets, check the winners
            winners = []
            for runner in market_data.get('runners', []):
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