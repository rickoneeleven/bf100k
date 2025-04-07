# Simplified Betfair Betting System

## Introduction

This system implements an automated betting approach for Betfair, focusing on a defined strategy and cycle management. It uses a straightforward state management system to track betting operations reliably.

## System Architecture

### Directory Structure

```
project_root/
├── src/                         # Source code
│   ├── __init__.py
│   ├── betting_service.py       # Main betting service logic
│   ├── betting_state_manager.py # Central state management
│   ├── betfair_client.py        # Betfair API client
│   ├── config_manager.py        # Configuration management
│   ├── log_manager.py           # Log management
│   ├── main.py                  # Entry point & Command Handler
│   └── simple_file_storage.py   # Atomic file storage helper
├── web/                         # Web interface & data
│   ├── config/                  # Configuration directory
│   │   └── betting_config.json  # Main configuration file
│   ├── data/                    # Data storage
│   │   └── betting/             # Betting state files
│   ├── logs/                    # Log files
│   ├── dashboard.html           # Dashboard interface
│   ├── dashboard.css            # Dashboard styling
│   ├── dashboard.js             # Dashboard functionality
│   └── check_files.sh           # File verification script
├── .env_example                 # Environment variable template
└── requirements.txt             # Dependencies
```

### Key Components

#### 1. Betting State Manager (`src/betting_state_manager.py`)

The central component responsible for managing the application's state.

*   Uses `SimpleFileStorage` for atomic reads/writes to JSON files.
*   Manages state including current balance, cycle progress, statistics, and active bet details.
*   Primary state files:
    *   `web/data/betting/betting_state.json`: Stores core balance, cycle, and statistical data.
    *   `web/data/betting/active_bet.json`: Holds details of the currently active bet, or an empty object if none. Updated periodically with market data by a background task.
    *   `web/data/betting/bet_history.json`: Stores records of settled bets.

#### 2. Betting Service (`src/betting_service.py`)

Coordinates the main betting logic loop.

*   Uses `BettingStateManager` to check for active bets and get the next stake.
*   Uses `BetfairClient` to fetch market data and scan for opportunities based on configured strategy.
*   Calls `BettingStateManager` to record placed bets.
*   Uses `BetfairClient` to check results of active bets.
*   Calls `BettingStateManager` to record settled bets and check if the target is reached.

#### 3. Betfair Client (`src/betfair_client.py`)

Handles all communication with the Betfair API, including login, fetching market data, and retrieving market results.

#### 4. Configuration Manager (`src/config_manager.py`)

Loads and manages system configuration from `web/config/betting_config.json`.

#### 5. Main Entry Point (`src/main.py`)

*   Initializes all core components (`ConfigManager`, `BettingStateManager`, `BetfairClient`, `BettingService`).
*   Starts the `BettingService` main loop.
*   Runs a background task to update `active_bet.json` with fresh market data for the dashboard.
*   Provides an interactive Command Line Interface (CLI) via its internal `CommandHandler` for monitoring and control.

#### 6. Web Dashboard (`web/`)

A web-based interface for monitoring the system's status.

*   Displays current betting status, cycle, balance, and statistics.
*   Shows details of the active bet, including live market odds (updated periodically).
*   Shows recent bet history.
*   Reads data directly from the JSON files in `web/data/betting/` and logs from `web/logs/`.
*   Reads configuration from `web/config/betting_config.json`.

## Configuration

The system configuration is stored in `web/config/betting_config.json` with the following structure:

```json
{
  "betting": {
    "initial_stake": 1.0,
    "target_amount": 50000.0,
    "liquidity_factor": 1.1,
    "min_odds": 3.5,
    "max_odds": 10.0, // Added max_odds example
    "min_liquidity": 100000
  },
  "market_selection": {
    "max_markets": 1000,
    "top_markets": 10,
    "hours_ahead": 4,
    "sport_id": "1",
    "market_type": "MATCH_ODDS",
    "polling_interval_seconds": 60,
    "include_inplay": true
  },
  "result_checking": {
    "check_interval_minutes": 5, // Note: Check happens within main polling interval now
    "event_timeout_hours": 12 // Used for logging potential issues
  },
  "system": {
    "dry_run": true,
    "log_level": "INFO" // Root logger level (DEBUG recommended for development)
  }
}
```

## How Bet Cycles Work

The system follows these rules for cycle management, managed by `BettingStateManager`:

1.  **Bet Placement:** Recorded by `record_bet_placed`. Balance is decremented by stake, `total_bets_placed` and `current_bet_in_cycle` are incremented.
2.  **Bet Won:** Recorded by `record_bet_result`. Balance is increased by (stake + net profit), `total_wins` incremented, `last_winning_profit` updated, `total_commission_paid` updated.
3.  **Bet Lost:** Recorded by `record_bet_result`. `total_losses` incremented, `total_money_lost` increased by stake, `last_winning_profit` reset to 0. **Cycle resets:** `total_cycles` incremented, `current_cycle` incremented, `current_bet_in_cycle` reset to 0.
4.  **Target Reached:** Checked by `check_target_reached` after a winning bet. If balance >= target, `last_winning_profit` reset to 0. **Cycle resets:** `total_cycles` incremented, `current_cycle` incremented, `current_bet_in_cycle` reset to 0.
5.  **Next Stake Calculation:** `get_next_stake` returns (`last_winning_profit` + `starting_stake`) if `last_winning_profit > 0`, otherwise returns `starting_stake`.

## Running the System

### Prerequisites

*   Python 3.8+
*   Betfair API credentials and certificate files.
*   Required Python packages listed in `requirements.txt`.

### Installation

1.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

2.  Configure Betfair API credentials and certificate paths in environment variables (or a `.env` file):
    ```bash
    # Example using .env file
    # BETFAIR_USERNAME=your_username
    # BETFAIR_PASSWORD=your_password
    # BETFAIR_APP_KEY=your_app_key
    # BETFAIR_CERT_FILE=certs/client-2048.crt # Relative path example
    # BETFAIR_KEY_FILE=certs/client-2048.key # Relative path example
    ```
    *Ensure the certificate files exist at the specified paths.*

3.  Adjust settings in `web/config/betting_config.json` as needed (e.g., set `dry_run` to `false` for live betting).

### Starting the System

Run the main entry point from the project root directory:

```bash
python -m src.main
```

### Accessing the Dashboard

The dashboard reads data files directly. Ensure your web server (e.g., Nginx, Apache) is configured to serve the `web/` directory and has read permissions for the files within `web/data/betting/` and `web/logs/`. Access it via a web browser, e.g.:

```
http://yourdomain.com/web/dashboard.html
# Or if running locally with a simple server:
# http://localhost:8000/dashboard.html (adjust port if needed)
```

*Note: The dashboard relies on periodic browser refreshes or manual refreshing to get the latest data.*

### Command Line Interface

The system provides an interactive command-line interface via `src/main.py` with the following commands:

*   `help` (or `h`, `?`) - Show available commands
*   `status` (or `s`) - Show current betting system status
*   `bet` (or `b`) - Show details of the active bet (includes live market data if available)
*   `history [N]` (or `hist [N]`) - Show last N settled bets (default: 10)
*   `odds [min] [max]` (or `o [min] [max]`) - View or change target odds range in config
*   `cancel` (or `c`) - \[DRY RUN ONLY] Cancel the current active bet
*   `reset [stake]` (or `r [stake]`) - Reset the betting system state with an optional initial stake
*   `quit` (or `exit`, `q`) - Exit the application

## System Maintenance

### Log Management

Logs are stored in the `web/logs` directory (e.g., `system.log`, `BetfairClient.log`). Log rotation is handled by `LogManager`. Use the `log_level` setting in `betting_config.json` (`DEBUG`, `INFO`, `WARNING`, `ERROR`) to control verbosity.

### Verifying Installation

Use the provided script to verify required files and directories are present:

```bash
./web/check_files.sh
```
*(Ensure the script has execute permissions: `chmod +x web/check_files.sh`)*

### Resetting the System

To reset the betting system state (balance, history, cycles) to start fresh:

1.  Use the `reset` command in the CLI, optionally providing a new initial stake (e.g., `reset 5.0`).
2.  This clears `betting_state.json`, `active_bet.json`, and `bet_history.json`, then initializes the state with the specified (or configured) initial stake.

