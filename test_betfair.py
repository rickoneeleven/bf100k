import os
from dotenv import load_dotenv
from src.betfair_client import BetfairClient

def test_connection():
    # Load environment variables
    load_dotenv('env')
    
    # Initialize client
    client = BetfairClient(
        app_key=os.getenv('BETFAIR_APP_KEY'),
        cert_file=os.getenv('BETFAIR_CERT_FILE'),
        key_file=os.getenv('BETFAIR_KEY_FILE')
    )
    
    # Test login
    print("Attempting to login...")
    if client.login():
        print("✓ Login successful!")
        
        # Test listing event types
        print("\nFetching event types...")
        events = client.list_event_types()
        if events:
            print("✓ Successfully retrieved event types")
            print("\nAvailable events:")
            for event in events:
                print(f"- {event['eventType']['name']}")
        else:
            print("✗ Failed to retrieve event types")
    else:
        print("✗ Login failed!")

if __name__ == "__main__":
    test_connection()