document.addEventListener('DOMContentLoaded', function() {
    // Fetch data on page load
    fetchSystemData();
    fetchLogData();
    
    // Refresh data every 60 seconds
    setInterval(fetchSystemData, 60000);
    setInterval(fetchLogData, 60000);
});

function fetchSystemData() {
    console.log("Fetching system data...");
    
    // Fetch betting state data - using relative paths based on observed server structure
    fetch('./data/betting/betting_state.json')
        .then(response => {
            if (!response.ok) {
                console.error(`HTTP error! Status: ${response.status} for betting_state.json`);
                throw new Error(`HTTP error! Status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            console.log("Betting state data loaded:", data);
            updateSystemStatus(data);
            updateStatistics(data);
        })
        .catch(error => {
            console.error('Error fetching system data:', error);
            document.getElementById('balance').textContent = 'Error loading data';
        });
    
    // Fetch active bet data
    fetch('./data/betting/active_bet.json')
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
            console.log("Active bet data loaded:", data);
            updateActiveBet(data);
        })
        .catch(error => {
            console.error('Error fetching active bet:', error);
            // If file not found or empty, show no active bet
            document.getElementById('no-active-bet').style.display = 'block';
            document.getElementById('active-bet-details').style.display = 'none';
        });
    
    // Fetch bet history data
    fetch('./data/betting/bet_history.json')
        .then(response => {
            if (!response.ok) {
                console.error(`HTTP error! Status: ${response.status} for bet_history.json`);
                throw new Error(`HTTP error! Status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            console.log("Bet history data loaded:", data);
            updateBetHistory(data);
        })
        .catch(error => {
            console.error('Error fetching bet history:', error);
            document.getElementById('history-body').innerHTML = 
                '<tr><td colspan="6">Error loading bet history</td></tr>';
        });
    
    // Fetch configuration data
    fetch('./config/betting_config.json')
        .then(response => {
            if (!response.ok) {
                console.error(`HTTP error! Status: ${response.status} for betting_config.json`);
                throw new Error(`HTTP error! Status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            console.log("Config data loaded:", data);
            updateConfigInfo(data);
        })
        .catch(error => {
            console.error('Error fetching config data:', error);
            document.getElementById('mode').textContent = 'Config Error';
        });
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

function updateSystemStatus(data) {
    document.getElementById('balance').textContent = `£${data.current_balance.toFixed(2)}`;
    document.getElementById('target').textContent = `£${data.target_amount.toFixed(2)}`;
    document.getElementById('cycle').textContent = `#${data.current_cycle}`;
    document.getElementById('bet-in-cycle').textContent = `#${data.current_bet_in_cycle}`;
    document.getElementById('next-stake').textContent = `£${data.last_winning_profit > 0 ? data.last_winning_profit.toFixed(2) : data.starting_stake.toFixed(2)}`;
    
    // Update last updated timestamp
    const lastUpdated = new Date(data.last_updated);
    document.getElementById('last-updated').textContent = lastUpdated.toLocaleString();
}

function updateStatistics(data) {
    document.getElementById('total-bets').textContent = data.total_bets_placed;
    
    const winRate = data.total_bets_placed > 0 
        ? ((data.total_wins / data.total_bets_placed) * 100).toFixed(1) 
        : '0.0';
    document.getElementById('win-rate').textContent = `${winRate}%`;
    
    document.getElementById('win-loss').textContent = `${data.total_wins} / ${data.total_losses}`;
    document.getElementById('money-lost').textContent = `£${data.total_money_lost.toFixed(2)}`;
    document.getElementById('commission-paid').textContent = `£${data.total_commission_paid.toFixed(2)}`;
    document.getElementById('highest-balance').textContent = `£${data.highest_balance.toFixed(2)}`;
}

function updateActiveBet(data) {
    // Check if data is empty or null
    if (!data || Object.keys(data).length === 0) {
        document.getElementById('no-active-bet').style.display = 'block';
        document.getElementById('active-bet-details').style.display = 'none';
        return;
    }
    
    // Otherwise, update active bet details
    document.getElementById('no-active-bet').style.display = 'none';
    document.getElementById('active-bet-details').style.display = 'block';
    
    document.getElementById('event-name').textContent = data.event_name || 'Unknown Event';
    document.getElementById('selection').textContent = data.team_name || 'Unknown';
    document.getElementById('odds').textContent = data.odds || 'N/A';
    document.getElementById('stake').textContent = `£${data.stake ? data.stake.toFixed(2) : '0.00'}`;
    document.getElementById('market-id').textContent = data.market_id || 'N/A';
    
    // Format timestamp
    if (data.timestamp) {
        const placedTime = new Date(data.timestamp);
        document.getElementById('placed-time').textContent = placedTime.toLocaleString();
    } else {
        document.getElementById('placed-time').textContent = 'N/A';
    }
}

function updateBetHistory(data) {
    const historyBody = document.getElementById('history-body');
    historyBody.innerHTML = '';
    
    // Check if data has bets property and it's not empty
    if (!data || !data.bets || data.bets.length === 0) {
        const row = document.createElement('tr');
        row.innerHTML = '<td colspan="6">No bet history available</td>';
        historyBody.appendChild(row);
        return;
    }
    
    // Sort bets by settlement time (newest first)
    const sortedBets = data.bets.sort((a, b) => {
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

function updateConfigInfo(data) {
    // Display mode (DRY RUN or LIVE)
    const isDryRun = data.system && data.system.dry_run !== false;
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