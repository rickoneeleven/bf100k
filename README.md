# Event-Sourced Betting Cycle Management

## Introduction

This refactoring introduces an event-sourced approach to betting cycle management to solve issues with inconsistent cycle tracking. The core problem with the previous implementation was its reliance on direct state manipulation, which led to race conditions and ambiguous cycle state.

## Key Components

### 1. Event Store (`src/event_store.py`)

The central component that stores all betting events and provides methods to derive system state from event history.

- Events are immutable and append-only
- State is calculated on-demand by replaying events
- Supports event types: BET_PLACED, BET_WON, BET_LOST, TARGET_REACHED, SYSTEM_RESET

### 2. Betting Ledger (`src/betting_ledger.py`)

Refactored to use the event store for state management instead of direct file manipulation:

- Now delegates state management to the event store
- Adds events for each bet placement and result
- Provides a consistent API for other system components

### 3. Command Classes

Updated to work with the event-sourced approach:

- `place_bet_command.py` - Records BET_PLACED events
- `settle_bet_command.py` - Records BET_WON or BET_LOST events
- `market_analysis_command.py` - Uses derived state for decision making

### 4. Betting System (`src/betting_system.py`)

Main coordinator that uses event-derived state for all cycle-related operations.

## How Bet Cycles Work Now

The system now follows a simple, explicit rule for cycle management:

1. Each bet placement is recorded as a BET_PLACED event
2. A won bet is recorded as a BET_WON event
3. A lost bet is recorded as a BET_LOST event, which implicitly ends the cycle
4. Target reached is recorded as a TARGET_REACHED event, which also ends the cycle
5. Current cycle is calculated as (total number of BET_LOST and TARGET_REACHED events) + 1
6. Bet number in cycle is calculated by counting BET_PLACED events since the last cycle reset

## Key Advantages

1. **Simplified Logic**: Cycle management has a single source of truth (the event store)
2. **Deterministic State**: Cycle state can always be rebuilt from event history
3. **Audit Trail**: Complete history of all betting actions preserved
4. **No Race Conditions**: Events are added sequentially with proper locking
5. **Consistency**: Cycle tracking will remain consistent even after crashes or errors

## Concrete Example

Starting from scratch:

1. System initialized with cycle = 1
2. First bet placed: BET_PLACED added
   - Current cycle: 1
   - Bet in cycle: 1
3. First bet wins: BET_WON added
   - Current cycle: still 1
   - Bet in cycle: still 1
   - Last winning profit stored
4. Second bet placed: BET_PLACED added
   - Current cycle: still 1
   - Bet in cycle: now 2
5. Second bet loses: BET_LOST added
   - Current cycle: incremented to 2
   - Bet in cycle: reset to 0
   - Last winning profit reset to 0

After a reset or system restart, reading the event stream would rebuild the exact same state.

## Test Scenarios

### Scenario 1: Winning, then losing

```
[BET_PLACED] -> [BET_WON] -> [BET_PLACED] -> [BET_LOST]
```

After all these events, the system will be in cycle 2, with 0 bets in the current cycle, and no last winning profit.

### Scenario 2: Three consecutive losses

```
[BET_PLACED] -> [BET_LOST] -> [BET_PLACED] -> [BET_LOST] -> [BET_PLACED] -> [BET_LOST]
```

After all these events, the system will be in cycle 4, with 0 bets in the current cycle.