"""
debug_compare.py

Compare environment loading between the two scripts to identify the issue.
"""

import os
from dotenv import load_dotenv

def debug_env():
    print("Before load_dotenv():")
    print(f"BETFAIR_USERNAME: {'set' if os.getenv('BETFAIR_USERNAME') else 'not set'}")
    print(f"BETFAIR_APP_KEY: {'set' if os.getenv('BETFAIR_APP_KEY') else 'not set'}")
    print(f"BETFAIR_CERT_FILE: {'set' if os.getenv('BETFAIR_CERT_FILE') else 'not set'}")
    
    print("\nLoading .env file...")
    load_dotenv()
    
    print("\nAfter load_dotenv():")
    print(f"BETFAIR_USERNAME: {'set' if os.getenv('BETFAIR_USERNAME') else 'not set'}")
    print(f"BETFAIR_APP_KEY: {'set' if os.getenv('BETFAIR_APP_KEY') else 'not set'}")
    print(f"BETFAIR_CERT_FILE: {'set' if os.getenv('BETFAIR_CERT_FILE') else 'not set'}")
    
    if os.getenv('BETFAIR_CERT_FILE'):
        print(f"\nCert file path: {os.getenv('BETFAIR_CERT_FILE')}")
        print(f"File exists: {os.path.exists(os.getenv('BETFAIR_CERT_FILE'))}")

if __name__ == "__main__":
    debug_env()