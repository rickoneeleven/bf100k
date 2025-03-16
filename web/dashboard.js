document.addEventListener('DOMContentLoaded', function() {
    // Fetch data on page load
    fetchSystemData();
    fetchLogData();
    
    // Refresh data every 60 seconds
    setInterval(fetchSystemData, 60000);
    setInterval(fetchLogData, 60000);
});

// Global variables to store all data for cross-calculations
let stateData = null;
let activeBetData = null;
let historyData = null;
let configData = null;

function fetchSystemData() {
    // Create an object to track all fetch promises
    const fetchPromises = {};
    
    // Fetch betting state data
    fetchPromises.state = fetch('./data/betting/betting_state.json')
        .then(response => {
            if (!response.ok) {
                console.error(`HTTP error! Status: ${response.status} for betting_state.json`);
                throw new Error(`HTTP error! Status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            stateData = data;
            return data;
        })
        .catch(error => {
            console.error('Error fetching system data:', error);
            document.getElementById('target').textContent = 'Error loading data';
            return null;
        });
    
    // Fetch active bet data
    fetchPromises.activeBet = fetch('./data/betting/active_bet.json')
        .then(response => {
            if (!response.ok) {
                // If file returns 404, treat as no active bet
                if (response.status === 404) {
                    throw new Error('No active bet file found');
                }
                console.error(`HTTP error! Status: ${response.status} for active_bet.json`);
                throw new Error(`HTTP error! Status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            // Check if response is empty object
            if (data && Object.keys(data).length === 0) {
                activeBetData = null;
                return null;
            }
            activeBetData = data;
            return data;
        })
        .catch(error => {
            console.error('Error fetching active bet:', error);
            activeBetData = null;
            return null;
        });
    
    // Fetch bet history data
    fetchPromises.history = fetch('./data/betting/bet_history.json')
        .then(response => {
            if (!response.ok) {
                console.error(`HTTP error! Status: ${response.status} for bet_history.json`);
                throw new Error(`HTTP error! Status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            historyData = data;
            return data;
        })
        .catch(error => {
            console.error('Error fetching bet history:', error);
            historyData = null;
            return null;
        });
    
    // Fetch configuration data
    fetchPromises.config = fetch('./config/betting_config.json')
        .then(response => {
            if (!response.ok) {
                console.error(`HTTP error! Status: ${response.status} for betting_config.json`);
                throw new Error(`HTTP error! Status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            configData = data;
            return data;
        })
        .catch(error => {
            console.error('Error fetching config data:', error);
            configData = null;
            return null;
        });
    
    // When all data is fetched, update the UI with recalculated values
    Promise.all(Object.values(fetchPromises))
        .then(() => {
            try {
                // Calculate all derived values
                const calculatedValues = calculateDerivedValues();
                
                // Update UI with calculated values
                updateSystemStatus(calculatedValues);
                updateStatistics(calculatedValues);
                updateActiveBet();
                updateBetHistory();
                updateConfigInfo();
            } catch (error) {
                console.error('Error calculating values:', error);
            }
        })
        .catch(error => {
            console.error('Error updating dashboard:', error);
        });
}

function calculateDerivedValues() {
    // Default values in case data is missing
    const initialStake = configData?.betting?.initial_stake || 1.0;
    
    // Initialize values
    let currentBalance = initialStake;
    let totalBets = 0;
    let wins = 0;
    let losses = 0;
    let totalMoneyWon = 0;
    let totalCommissionPaid = 0;
    let highestBalance = initialStake;
    let nextStake = initialStake;
    
    // Simple balance tracking to avoid complex bet replay
    if (historyData && historyData.bets && historyData.bets.length > 0) {
        const bets = historyData.bets;
        
        // Sort bets chronologically
        const sortedBets = bets.sort((a, b) => {
            return new Date(a.settlement_time) - new Date(b.settlement_time);
        });
        
        totalBets = bets.length;
        
        // Find wins and losses
        wins = bets.filter(bet => bet.won).length;
        losses = bets.filter(bet => !bet.won).length;
        
        // Total money won
        totalMoneyWon = bets.filter(bet => bet.won)
            .reduce((sum, bet) => sum + (bet.profit || 0), 0);
            
        // Total commission paid
        totalCommissionPaid = bets.filter(bet => bet.won)
            .reduce((sum, bet) => sum + (bet.commission || 0), 0);
            
        // Find the winning bet with largest profit
        const maxWinningBet = [...bets].filter(bet => bet.won)
            .sort((a, b) => (b.profit || 0) - (a.profit || 0))[0];
            
        if (maxWinningBet) {
            // Set highest balance to initial stake + highest profit
            highestBalance = initialStake + (maxWinningBet.profit || 0);
        }
        
        // Get current balance from most recent win/loss sequence
        currentBalance = initialStake;
        sortedBets.forEach(bet => {
            if (bet.won) {
                currentBalance += (bet.profit || 0);
                nextStake = bet.profit || 0;
            } else {
                currentBalance -= (bet.stake || 0);
                nextStake = initialStake;
            }
        });
        
        // If there's an active bet, the stake is already deducted from balance
        if (activeBetData && Object.keys(activeBetData).length > 0) {
            // Nothing to do - balance already accounts for active bet stake
        }
    }
    
    // Calculate win rate
    const winRate = totalBets > 0 ? (wins / totalBets) * 100 : 0;
    
    // Calculate total profit/loss directly
    const totalProfitLoss = currentBalance - initialStake;
    
    return {
        currentBalance,
        targetAmount: stateData?.target_amount || 50000.0,
        currentCycle: stateData?.current_cycle || 1,
        currentBetInCycle: stateData?.current_bet_in_cycle || 0,
        initialStake,
        nextStake,
        totalBets,
        wins,
        losses,
        winRate,
        totalMoneyWon,
        totalProfitLoss,
        highestBalance,
        totalCommissionPaid,
        lastUpdated: new Date().toISOString()
    };
}

function fetchLogData() {
    // Fetch the latest system log file
    fetch('./logs/system.log')
        .then(response => {
            if (!response.ok) {
                console.error(`HTTP error! Status: ${response.status} for system.log`);
                throw new Error(`HTTP error! Status: ${response.status}`);
            }
            return response.text();
        })
        .then(data => {
            updateLogViewer(data);
        })
        .catch(error => {
            console.error('Error fetching logs:', error);
            document.getElementById('log-entries').textContent = 'Error loading logs: ' + error.message;
        });
}

function updateSystemStatus(calculatedValues) {
    document.getElementById('target').textContent = `£${calculatedValues.targetAmount.toFixed(2)}`;
    document.getElementById('cycle').textContent = `#${calculatedValues.currentCycle}`;
    document.getElementById('bet-in-cycle').textContent = `#${calculatedValues.currentBetInCycle}`;
    document.getElementById('next-stake').textContent = `£${calculatedValues.nextStake.toFixed(2)}`;
    
    // Add formatting for total profit/loss
    const profitLossElement = document.getElementById('profit-loss');
    if (profitLossElement) {
        const totalProfitLoss = calculatedValues.totalProfitLoss;
        const sign = totalProfitLoss >= 0 ? '+' : '';
        profitLossElement.textContent = `${sign}£${totalProfitLoss.toFixed(2)}`;
        profitLossElement.className = totalProfitLoss >= 0 ? 'value positive' : 'value negative';
    }
    
    // Format highest balance value
    const highestBalanceElement = document.getElementById('highest-balance');
    if (highestBalanceElement) {
        highestBalanceElement.textContent = `£${calculatedValues.highestBalance.toFixed(2)}`;
    }
    
    // Update last updated timestamp
    document.getElementById('last-updated').textContent = new Date().toLocaleString();
}

function updateStatistics(calculatedValues) {
    document.getElementById('total-bets').textContent = calculatedValues.totalBets;
    document.getElementById('win-rate').textContent = `${calculatedValues.winRate.toFixed(1)}%`;
    document.getElementById('win-loss').textContent = `${calculatedValues.wins} / ${calculatedValues.losses}`;
    document.getElementById('commission-paid').textContent = `£${calculatedValues.totalCommissionPaid.toFixed(2)}`;
    document.getElementById('highest-balance').textContent = `£${calculatedValues.highestBalance.toFixed(2)}`;
}

function updateActiveBet() {
    // Check if data is empty or null
    if (!activeBetData || Object.keys(activeBetData).length === 0) {
        document.getElementById('no-active-bet').style.display = 'block';
        document.getElementById('active-bet-details').style.display = 'none';
        return;
    }
    
    // Otherwise, update active bet details
    document.getElementById('no-active-bet').style.display = 'none';
    document.getElementById('active-bet-details').style.display = 'block';
    
    document.getElementById('event-name').textContent = activeBetData.event_name || 'Unknown Event';
    document.getElementById('selection').textContent = activeBetData.team_name || 'Unknown';
    document.getElementById('odds').textContent = activeBetData.odds || 'N/A';
    document.getElementById('stake').textContent = `£${activeBetData.stake ? activeBetData.stake.toFixed(2) : '0.00'}`;
    document.getElementById('market-id').textContent = activeBetData.market_id || 'N/A';
    
    // Format timestamp
    if (activeBetData.timestamp) {
        const placedTime = new Date(activeBetData.timestamp);
        document.getElementById('placed-time').textContent = placedTime.toLocaleString();
    } else {
        document.getElementById('placed-time').textContent = 'N/A';
    }
}

function updateBetHistory() {
    const historyBody = document.getElementById('history-body');
    historyBody.innerHTML = '';
    
    // Check if data has bets property and it's not empty
    if (!historyData || !historyData.bets || historyData.bets.length === 0) {
        const row = document.createElement('tr');
        row.innerHTML = '<td colspan="6">No bet history available</td>';
        historyBody.appendChild(row);
        return;
    }
    
    // Sort bets by settlement time (newest first)
    const sortedBets = historyData.bets.sort((a, b) => {
        return new Date(b.settlement_time) - new Date(a.settlement_time);
    });
    
    // Take only the last 10 bets
    const recentBets = sortedBets.slice(0, 10);
    
    // Add each bet to the table
    recentBets.forEach(bet => {
        const row = document.createElement('tr');
        
        // Format settlement time
        let formattedTime = 'Unknown';
        if (bet.settlement_time) {
            formattedTime = new Date(bet.settlement_time).toLocaleString();
        }
        
        // Determine result and profit/loss display
        const isWin = bet.won;
        const resultClass = isWin ? 'win' : 'loss';
        const resultText = isWin ? 'WON' : 'LOST';
        
        let profitLossText;
        if (isWin) {
            profitLossText = `+£${bet.profit.toFixed(2)}`;
        } else {
            profitLossText = `-£${bet.stake.toFixed(2)}`;
        }
        
        row.innerHTML = `
            <td>${formattedTime}</td>
            <td>${bet.event_name || 'Unknown'}</td>
            <td>${bet.team_name || 'Unknown'} @ ${bet.odds || 'N/A'}</td>
            <td>£${bet.stake ? bet.stake.toFixed(2) : '0.00'}</td>
            <td class="${resultClass}">${resultText}</td>
            <td class="${resultClass}">${profitLossText}</td>
        `;
        
        historyBody.appendChild(row);
    });
}

function updateConfigInfo() {
    // Display mode (DRY RUN or LIVE)
    const isDryRun = configData && configData.system && configData.system.dry_run !== false;
    document.getElementById('mode').textContent = isDryRun ? 'DRY RUN' : 'LIVE';
    
    if (!isDryRun) {
        document.getElementById('mode').style.color = 'red';
        document.getElementById('mode').style.fontWeight = 'bold';
    } else {
        document.getElementById('mode').style.color = 'green';
    }
}

function updateLogViewer(logData) {
    // Get the log entries element
    const logEntries = document.getElementById('log-entries');
    
    // Split the log data into lines
    const lines = logData.split('\n');
    
    // Take only the last 50 lines
    const recentLines = lines.slice(-50);
    
    // Join the lines back together
    logEntries.textContent = recentLines.join('\n');
    
    // Scroll to the bottom
    const logContent = document.getElementById('log-content');
    logContent.scrollTop = logContent.scrollHeight;
}