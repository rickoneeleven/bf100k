Here's the raw Markdown text that you can copy directly:

```markdown
# Betfair Football Compound Betting System

A Python-based system that interfaces with the Betfair API to execute a compound betting strategy, focusing on Match Odds markets for football matches.

## Overview

This system implements an automated betting strategy that analyzes Betfair football markets to identify betting opportunities based on specific selection criteria. It uses context-aware team mapping, comprehensive error handling, and asynchronous operations to ensure reliable market analysis and bet placement.

## Selection Criteria & Betting Strategy

The system employs a specific set of criteria to identify betting opportunities:

- **Odds Range**: Targets selections with odds between 3.0 and 4.0 (configurable)
- **Liquidity Requirements**: Ensures the market has sufficient liquidity (1.1x the stake amount)
- **Market Status**: Only considers pre-game markets (not in-play)
- **Active Bet Limitation**: Only places one bet at a time (no concurrent active bets)
- **Compound Strategy**: The system uses available balance as the stake amount, implementing a compound betting approach

### Where Selection Logic is Implemented

The core selection logic is implemented in the following files:

- `src/commands/market_analysis_command.py`: 
  - `validate_market_criteria()` - Validates if markets meet betting criteria
  - `execute()` - Analyzes markets and identifies betting opportunities

- `src/betting_system.py`:
  - `scan_markets()` - Orchestrates the market scanning process

- `src/selection_mapper.py`:
  - Provides context-aware team name mapping for consistent selection identification

## System Architecture

The system is built using several design patterns for maintainability and testability:

- **Command Pattern**: Separates operations into discrete commands (market analysis, bet placement, settlement)
- **Repository Pattern**: Abstracts data access for bets and account information
- **Dependency Injection**: Components receive their dependencies for better testability

### Key Components

- `BettingSystem`: Main orchestrator that coordinates operations
- `BetfairClient`: Handles API communication with Betfair
- `MarketAnalysisCommand`: Analyzes markets for betting opportunities
- `PlaceBetCommand`: Handles bet placement operations
- `BetSettlementCommand`: Manages bet settlement
- `SelectionMapper`: Maintains context-aware mappings between selection IDs and team names
- `BetRepository` & `AccountRepository`: Handle persistent storage of betting data

## Error Handling & Safety Features

The system implements comprehensive error handling and safety features:

- **Dry Run Mode**: Default mode that simulates betting without placing actual bets
- **Comprehensive Logging**: Each component maintains detailed logs
- **Exception Handling**: Try/catch blocks with detailed error reporting
- **Validation**: Multiple validation steps before bet placement
- **Graceful Shutdown**: Proper cleanup of resources during shutdown

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
│   │   ├── market_analysis_command.py  # Market analysis logic
│   │   ├── place_bet_command.py        # Bet placement logic
│   │   └── settle_bet_command.py       # Bet settlement logic
│   ├── repositories/# Data storage implementations
│   │   ├── account_repository.py       # Account data management
│   │   └── bet_repository.py           # Bet data management
│   ├── betfair_client.py               # Betfair API client
│   ├── betting_system.py               # Main system orchestrator
│   ├── main.py                         # Entry point
│   └── selection_mapper.py             # Team name mapping logic
├── config/          # Configuration files
├── data/           # Data storage
    └── betting/    # Betting data files
```
```

You can now copy this text directly, including all the Markdown formatting.