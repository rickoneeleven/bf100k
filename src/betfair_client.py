"""
betfair_client.py

Core client for interacting with the Betfair API. Handles authentication,
session management, and basic market operations. Part of the Betfair Football
Market Analysis Tool.
"""

import os
import json
import logging
import requests
from datetime import datetime, timezone
from typing import Optional, Dict, List

class BetfairClient:
    """
    Core client for interacting with Betfair API
    """
    
    def __init__(self, app_key: str, cert_file: str, key_file: str):
        self.app_key = app_key
        self.cert_file = cert_file
        self.key_file = key_file
        self.session_token = None
        
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
        
    def login(self) -> bool:
        """
        Login to Betfair API using certificate-based authentication
        Returns True if successful, False otherwise
        """
        try:
            payload = {
                'username': os.getenv('BETFAIR_USERNAME'),
                'password': os.getenv('BETFAIR_PASSWORD')
            }
            
            resp = requests.post(
                self.cert_login_url,
                cert=(self.cert_file, self.key_file),
                data=payload,
                headers={'X-Application': self.app_key}
            )
            
            if resp.status_code == 200:
                resp_json = resp.json()
                if resp_json['loginStatus'] == 'SUCCESS':
                    self.session_token = resp_json['sessionToken']
                    self.logger.info('Successfully logged in to Betfair API')
                    return True
                else:
                    self.logger.error(f'Login failed: {resp_json["loginStatus"]}')
                    return False
            else:
                self.logger.error(f'Login request failed with status code: {resp.status_code}')
                return False
                
        except Exception as e:
            self.logger.error(f'Exception during login: {str(e)}')
            return False
            
    def list_event_types(self) -> Optional[List[Dict]]:
        """
        List all event types (sports) available on Betfair
        Returns list of event types or None if request fails
        """
        if not self.session_token:
            self.logger.error('No session token available - please login first')
            return None
            
        try:
            payload = {
                'jsonrpc': '2.0',
                'method': 'SportsAPING/v1.0/listEventTypes',
                'params': {
                    'filter': {}
                },
                'id': 1
            }
            
            headers = {
                'X-Application': self.app_key,
                'X-Authentication': self.session_token,
                'content-type': 'application/json'
            }
            
            resp = requests.post(
                self.betting_url,
                data=json.dumps(payload),
                headers=headers
            )
            
            if resp.status_code == 200:
                resp_json = resp.json()
                if 'result' in resp_json:
                    self.logger.info('Successfully retrieved event types')
                    return resp_json['result']
                else:
                    self.logger.error(f'Error in response: {resp_json.get("error")}')
                    return None
            else:
                self.logger.error(f'Request failed with status code: {resp.status_code}')
                return None
                
        except Exception as e:
            self.logger.error(f'Exception during list_event_types: {str(e)}')
            return None
            
    def get_football_markets_for_today(self) -> Optional[List[Dict]]:
        """
        Get all football markets for today
        Returns list of markets or None if request fails
        """
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
                        'marketStartTime': {
                            'from': today,
                            'to': tomorrow
                        },
                        'inPlayOnly': False
                    },
                    'maxResults': 1000,
                    'marketProjection': [
                        'EVENT',
                        'MARKET_START_TIME',
                        'RUNNER_DESCRIPTION'
                    ]
                },
                'id': 1
            }
            
            headers = {
                'X-Application': self.app_key,
                'X-Authentication': self.session_token,
                'content-type': 'application/json'
            }
            
            resp = requests.post(
                self.betting_url,
                data=json.dumps(payload),
                headers=headers
            )
            
            if resp.status_code == 200:
                resp_json = resp.json()
                if 'result' in resp_json:
                    self.logger.info('Successfully retrieved football markets')
                    return resp_json['result']
                else:
                    self.logger.error(f'Error in response: {resp_json.get("error")}')
                    return None
            else:
                self.logger.error(f'Request failed with status code: {resp.status_code}')
                return None
                
        except Exception as e:
            self.logger.error(f'Exception during get_football_markets_for_today: {str(e)}')
            return None
            
    def get_market_volumes(self, market_ids: List[str], batch_size: int = 25) -> Optional[List[Dict]]:
        """
        Get matched volumes for a list of market IDs
        Processes in batches to respect API limits
        Returns list of market books or None if request fails
        """
        if not self.session_token:
            self.logger.error('No session token available - please login first')
            return None
            
        try:
            all_results = []
            
            # Process in batches
            for i in range(0, len(market_ids), batch_size):
                batch = market_ids[i:i + batch_size]
                
                payload = {
                    'jsonrpc': '2.0',
                    'method': 'SportsAPING/v1.0/listMarketBook',
                    'params': {
                        'marketIds': batch,
                        'priceProjection': {
                            'priceData': ['EX_BEST_OFFERS']
                        }
                    },
                    'id': 1
                }
                
                headers = {
                    'X-Application': self.app_key,
                    'X-Authentication': self.session_token,
                    'content-type': 'application/json'
                }
                
                resp = requests.post(
                    self.betting_url,
                    data=json.dumps(payload),
                    headers=headers
                )
                
                if resp.status_code == 200:
                    resp_json = resp.json()
                    if 'result' in resp_json:
                        all_results.extend(resp_json['result'])
                    else:
                        self.logger.error(f'Error in response: {resp_json.get("error")}')
                        return None
                else:
                    self.logger.error(f'Request failed with status code: {resp.status_code}')
                    return None
                    
            self.logger.info(f'Successfully retrieved volumes for {len(all_results)} markets')
            return all_results
                
        except Exception as e:
            self.logger.error(f'Exception during get_market_volumes: {str(e)}')
            return None