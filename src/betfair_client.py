"""
betfair_client.py

Async client for interacting with the Betfair API. Handles authentication,
session management, and basic market operations.
"""

import os
import json
import logging
import aiohttp
import ssl
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple

class BetfairClient:
    def __init__(self, app_key: str, cert_file: str, key_file: str):
        self.app_key = app_key
        self.cert_file = cert_file
        self.key_file = key_file
        self.session_token = None
        self.http_session = None
        
        # Setup logging
        self.logger = logging.getLogger('BetfairClient')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler('web/logs/betfair_client.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        
        # API endpoints
        self.cert_login_url = 'https://identitysso-cert.betfair.com/api/certlogin'
        self.betting_url = 'https://api.betfair.com/exchange/betting/json-rpc/v1'

    async def create_session(self):
        """Create HTTP session if not exists"""
        if not self.http_session or self.http_session.closed:
            self.http_session = aiohttp.ClientSession()

    async def close_session(self):
        """Close HTTP session if exists"""
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
            self.http_session = None

    async def __aenter__(self):
        """Async context manager entry"""
        await self.create_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close_session()

    async def login(self) -> bool:
        """Login to Betfair API using certificate-based authentication"""
        try:
            if not self.http_session:
                self.http_session = aiohttp.ClientSession()

            payload = {
                'username': os.getenv('BETFAIR_USERNAME'),
                'password': os.getenv('BETFAIR_PASSWORD')
            }
            
            # Create SSL context using standard ssl library
            ssl_context = ssl.create_default_context()
            ssl_context.load_cert_chain(self.cert_file, self.key_file)
            
            async with self.http_session.post(
                self.cert_login_url,
                data=payload,
                headers={'X-Application': self.app_key},
                ssl=ssl_context
            ) as resp:
                if resp.status == 200:
                    # First get the response as text
                    resp_text = await resp.text()
                    try:
                        # Then parse it as JSON
                        resp_json = json.loads(resp_text)
                        if resp_json.get('loginStatus') == 'SUCCESS':
                            self.session_token = resp_json['sessionToken']
                            self.logger.info('Successfully logged in to Betfair API')
                            return True
                        else:
                            self.logger.error(f'Login failed: {resp_json.get("loginStatus")}')
                            return False
                    except json.JSONDecodeError as e:
                        self.logger.error(f'Failed to parse login response: {resp_text}')
                        return False
                else:
                    self.logger.error(f'Login request failed with status code: {resp.status}')
                    return False
                    
        except Exception as e:
            self.logger.error(f'Exception during login: {str(e)}')
            return False

    async def get_football_markets_for_today(self) -> Optional[List[Dict]]:
        """Get top 5 football Match Odds markets for today, sorted by matched volume"""
        if not self.session_token:
            self.logger.error('No session token available - please login first')
            return None
            
        try:
            # Get today's date in ISO format
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
                        'RUNNER_DESCRIPTION'
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
            
            async with self.http_session.post(
                self.betting_url,
                json=payload,
                headers=headers
            ) as resp:
                if resp.status == 200:
                    resp_json = await resp.json()
                    if 'result' in resp_json:
                        self.logger.info('Successfully retrieved football markets')
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
        market_runners: Dict[str, List[Dict]] = None
    ) -> Optional[List[Dict]]:
        """
        Get detailed market data including prices for specified markets
        
        Args:
            market_ids: List of market IDs to retrieve
            market_runners: Optional dict mapping market IDs to runner information
        
        Returns:
            List of market books with mapped runner names or None if request fails
        """
        if not self.session_token:
            self.logger.error('No session token available - please login first')
            return None
            
        try:
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
            
            async with self.http_session.post(
                self.betting_url,
                json=payload,
                headers=headers
            ) as resp:
                if resp.status == 200:
                    resp_json = await resp.json()
                    if 'result' in resp_json:
                        market_books = resp_json['result']
                        
                        # Map runner names if market_runners provided
                        if market_runners:
                            for market_book in market_books:
                                market_id = market_book['marketId']
                                if market_id in market_runners:
                                    runner_map = {
                                        runner['selectionId']: runner['runnerName']
                                        for runner in market_runners[market_id]
                                    }
                                    
                                    # Add runner names to market book data
                                    for runner in market_book.get('runners', []):
                                        runner['runnerName'] = runner_map.get(
                                            runner['selectionId'],
                                            f"Unknown Runner ({runner['selectionId']})"
                                        )
                        
                        self.logger.info('Successfully retrieved market books')
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
            
        # Create runner mapping
        market_runners = {
            market['marketId']: market.get('runners', [])
            for market in markets
        }
        
        # Get all market IDs in order
        market_ids = [market['marketId'] for market in markets]
        
        # Get market books with runner names mapped
        market_books = await self.list_market_book(market_ids, market_runners)
        
        # Ensure market books are in same order as catalogs
        if market_books:
            market_books_dict = {book['marketId']: book for book in market_books}
            market_books = [market_books_dict[market_id] for market_id in market_ids]
        
        if not market_books:
            return None, None
            
        return markets, market_books