# Event-Sourced Betting Cycle Management

## Introduction

This system implements an event-sourced approach to betting cycle management for consistent and reliable tracking of betting operations. The event-sourced architecture solves issues with inconsistent cycle tracking by maintaining an immutable record of all betting events.

## System Architecture

### Directory Structure

```
project_root/
├── src/                         # Source code
│   ├── commands/                # Command pattern implementations
│   ├── repositories/            # Data access layer
│   ├── betting_ledger.py        # Event-sourced betting ledger
│   ├── betting_service.py       # Main betting service
│   ├── betting_state_manager.py # State management
│   ├── betting_system.py        # System coordinator
│   ├── betfair_client.py        # API client
│   ├── config_manager.py        # Configuration management
│   ├── event_store.py           # Event storage
│   ├── log_manager.py           # Log management
│   ├── main.py                  # Entry point
│   └── selection_mapper.py      # Selection mapping utilities
├── web/                         # Web interface
│   ├── config/                  # Configuration directory
│   │   └── betting_config.json  # Main configuration file
│   ├── data/                    # Data storage
│   │   └── betting/             # Betting data
│   ├── logs/                    # Log files
│   ├── dashboard.html           # Dashboard interface
│   ├── dashboard.css            # Dashboard styling
│   ├── dashboard.js             # Dashboard functionality
│   └── check_files.sh           # File verification script
└── requirements.txt             # Dependencies
```

### Key Components

#### 1. Event Store (`src/event_store.py`)

The central component that stores all betting events and provides methods to derive system state from event history.

- Events are immutable and append-only
- State is calculated on-demand by replaying events
- Supports event types: BET_PLACED, BET_WON, BET_LOST, TARGET_REACHED, SYSTEM_RESET

#### 2. Betting Ledger (`src/betting_ledger.py`)

Uses the event store for state management:

- Delegates state management to the event store
- Adds events for each bet placement and result
- Provides a consistent API for other system components

#### 3. Command Classes

Implements the command pattern for system operations:

- `place_bet_command.py` - Records BET_PLACED events
- `settle_bet_command.py` - Records BET_WON or BET_LOST events
- `market_analysis_command.py` - Uses derived state for decision making

#### 4. Betting System (`src/betting_system.py`)

Main coordinator that uses event-derived state for all cycle-related operations.

#### 5. Web Dashboard

Web-based monitoring interface:
- Displays current betting status
- Shows active bets and bet history
- Visualizes system statistics
- Reads configuration from `web/config/betting_config.json`

## Configuration

The system configuration is stored in `web/config/betting_config.json` with the following structure:

```json
{
  "betting": {
    "initial_stake": 1.0,
    "target_amount": 50000.0,
    "min_odds": 3.0,
    "max_odds": 4.0,
    "liquidity_factor": 1.1
  },
  "market_selection": {
    "max_markets": 10,
    "sport_id": "1",
    "market_type": "MATCH_ODDS",
    "polling_interval_seconds": 60
  },
  "result_checking": {
    "check_interval_minutes": 5,
    "event_timeout_hours": 12
  },
  "system": {
    "dry_run": true,
    "log_level": "INFO"
  }
}
```

## How Bet Cycles Work

The system follows these rules for cycle management:

1. Each bet placement is recorded as a BET_PLACED event
2. A won bet is recorded as a BET_WON event
3. A lost bet is recorded as a BET_LOST event, which implicitly ends the cycle
4. Target reached is recorded as a TARGET_REACHED event, which also ends the cycle
5. Current cycle is calculated as (total number of BET_LOST and TARGET_REACHED events) + 1
6. Bet number in cycle is calculated by counting BET_PLACED events since the last cycle reset

## Running the System

### Prerequisites

- Python 3.8+
- Betfair API credentials
- Required Python packages listed in `requirements.txt`

### Installation

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Configure Betfair API credentials in environment variables:
   ```
   BETFAIR_APP_KEY=your_app_key
   BETFAIR_USERNAME=your_username
   BETFAIR_PASSWORD=your_password
   BETFAIR_CERT_FILE=path/to/certificate.pem
   BETFAIR_KEY_FILE=path/to/private_key.pem
   ```

3. Adjust settings in `web/config/betting_config.json` as needed

### Starting the System

Run the main entry point:
```
python -m src.main
```

### Accessing the Dashboard

The dashboard is accessible via a web browser at:
```
http://localhost/web/dashboard.html
```

### Command Line Interface

The system provides an interactive command-line interface with the following commands:

- `help` - Show available commands
- `status` - Show current betting system status
- `bet` - Show details of active bet
- `history` - Show betting history
- `odds` - View or change target odds range
- `reset` - Reset the betting system
- `quit` - Exit the application

## System Maintenance

### Log Management

Logs are stored in the `web/logs` directory with automatic rotation and cleanup.

### Verifying Installation

Use the provided script to verify all required files are present:
```
./web/check_files.sh
```

### Resetting the System

To reset the betting system to start fresh:
1. Use the `reset` command in the CLI with the desired initial stake
2. Or call the reset method in the API: `await betting_system.reset_system(initial_stake)`