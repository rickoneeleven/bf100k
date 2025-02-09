# Betfair Football Compound Betting System

A Python-based system that interfaces with the Betfair API to execute a compound betting strategy, focusing on Match Odds markets for football matches.

## System Requirements

### System-Level Dependencies
Before installing Python packages, ensure you have the necessary system-level SSL dependencies:
```bash
sudo apt-get update
sudo apt-get install python3-dev libffi-dev libssl-dev
```

### Python Setup
1. Create and activate a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
```

2. Install required packages:
```bash
pip install -r requirements.txt
```

## Configuration
1. Copy the example environment file:
```bash
cp .env.example .env
```

2. Update the `.env` file with your Betfair credentials:
```
BETFAIR_USERNAME=your_username
BETFAIR_PASSWORD=your_password
BETFAIR_APP_KEY=your_app_key
BETFAIR_CERT_FILE=path_to_cert
BETFAIR_KEY_FILE=path_to_key
```

## Running the System
Run the system using the Python module flag:
```bash
python3 -m src.main
```

Note: The system defaults to dry run mode for safety.

## Project Structure
```
project/
├── src/             # Source code
│   ├── commands/    # Command pattern implementations
│   └── repositories/# Data storage implementations
├── config/          # Configuration files
└── data/           # Data storage
    └── betting/    # Betting data files
```