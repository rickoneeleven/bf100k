document.addEventListener('DOMContentLoaded', function() {
    // Fetch data on page load
    fetchSystemData();
    fetchLogData();
    
    // Add event listeners for the log show/hide functionality
    document.getElementById('show-all-logs').addEventListener('click', function(e) {
        e.preventDefault();
        showAllLogs();
    });
    
    document.getElementById('show-less-logs').addEventListener('click', function(e) {
        e.preventDefault();
        showLessLogs();
    });
    
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
                // For next stake, use profit + initial stake (full balance)
                nextStake = (bet.profit || 0) + initialStake;
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
    
    // Format placement timestamp
    if (activeBetData.timestamp) {
        const placedTime = new Date(activeBetData.timestamp);
        document.getElementById('placed-time').textContent = placedTime.toLocaleString();
    } else {
        document.getElementById('placed-time').textContent = 'N/A';
    }
    
    // Display kick off time
    if (activeBetData.market_start_time) {
        const kickOffTime = new Date(activeBetData.market_start_time);
        document.getElementById('kick-off-time').textContent = kickOffTime.toLocaleString();
    } else {
        document.getElementById('kick-off-time').textContent = 'N/A';
    }

    // Display in play status with color coding
    let inPlayStatus = 'Unknown';
    let inPlayStatusElement = document.getElementById('in-play-status');
    
    if (activeBetData.current_market) {
        inPlayStatus = activeBetData.current_market.inplay ? 'In Play' : 'Not Started';
        if (activeBetData.current_market.status && activeBetData.current_market.status !== 'OPEN') {
            inPlayStatus = activeBetData.current_market.status;
        }
    }
    inPlayStatusElement.textContent = inPlayStatus;
    
    // Add color coding - green for In Play, red for other statuses
    if (inPlayStatus === 'In Play') {
        inPlayStatusElement.classList.add('status-inplay');
        inPlayStatusElement.classList.remove('status-notinplay');
    } else {
        inPlayStatusElement.classList.add('status-notinplay');
        inPlayStatusElement.classList.remove('status-inplay');
    }

    // Variables to track odds and elements for highlighting
    let team1Element = document.getElementById('team1-odds');
    let team2Element = document.getElementById('team2-odds');
    let drawElement = document.getElementById('draw-odds');
    let team1Odds = null;
    let team2Odds = null;
    let drawOdds = null;
    
    // Display current odds for team 1, team 2, and draw
    if (activeBetData.current_market && activeBetData.current_market.runners) {
        const runners = activeBetData.current_market.runners;
        
        // Sort runners by sortPriority
        const sortedRunners = [...runners].sort((a, b) => {
            return (a.sortPriority || 999) - (b.sortPriority || 999);
        });
        
        // Find team 1, team 2, and draw runners
        const team1Runner = sortedRunners.find(r => r.sortPriority === 1);
        const team2Runner = sortedRunners.find(r => r.sortPriority === 2);
        const drawRunner = sortedRunners.find(r => {
            return r.selectionId === 58805 || 
                (r.teamName && r.teamName.toLowerCase() === 'draw');
        });
        
        // Update team names for labels
        const team1Name = team1Runner && (team1Runner.teamName || team1Runner.runnerName || 'Team 1');
        const team2Name = team2Runner && (team2Runner.teamName || team2Runner.runnerName || 'Team 2');
        
        // Update label text to include team names
        document.getElementById('team1-odds-label').textContent = `${team1Name} Win Odds:`;
        document.getElementById('team2-odds-label').textContent = `${team2Name} Win Odds:`;
        
        // Update odds display for team 1
        if (team1Runner && team1Runner.ex && team1Runner.ex.availableToBack && team1Runner.ex.availableToBack.length > 0) {
            team1Odds = team1Runner.ex.availableToBack[0].price || null;
            team1Element.textContent = team1Odds || 'N/A';
        } else {
            team1Element.textContent = 'N/A';
        }
        
        // Update odds display for team 2
        if (team2Runner && team2Runner.ex && team2Runner.ex.availableToBack && team2Runner.ex.availableToBack.length > 0) {
            team2Odds = team2Runner.ex.availableToBack[0].price || null;
            team2Element.textContent = team2Odds || 'N/A';
        } else {
            team2Element.textContent = 'N/A';
        }
        
        // Update odds display for draw
        if (drawRunner && drawRunner.ex && drawRunner.ex.availableToBack && drawRunner.ex.availableToBack.length > 0) {
            drawOdds = drawRunner.ex.availableToBack[0].price || null;
            drawElement.textContent = drawOdds || 'N/A';
        } else {
            drawElement.textContent = 'N/A';
        }
        
        // Reset all classes before highlighting
        team1Element.className = 'value';
        team2Element.className = 'value';
        drawElement.className = 'value';
        
        // Find lowest odds and highlight in green
        if (team1Odds !== null && team2Odds !== null && drawOdds !== null) {
            const allOdds = [
                { element: team1Element, odds: team1Odds },
                { element: team2Element, odds: team2Odds },
                { element: drawElement, odds: drawOdds }
            ];
            
            // Sort by odds (lowest first)
            allOdds.sort((a, b) => a.odds - b.odds);
            
            // Highlight the lowest odds in green
            if (allOdds.length > 0 && allOdds[0].odds) {
                allOdds[0].element.className = 'value positive';
            }
        }
    } else {
        team1Element.textContent = 'N/A';
        team2Element.textContent = 'N/A';
        drawElement.textContent = 'N/A';
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
    const logContainer = document.getElementById('log-container');
    
    // Split the log data into lines
    const lines = logData.split('\n');
    
    // Filter out empty lines
    const nonEmptyLines = lines.filter(line => line.trim() !== '');
    
    // Reverse the order so newest is at top
    const reversedLines = nonEmptyLines.reverse();
    
    // Store all log data in a data attribute for "Show All" functionality
    logContainer.setAttribute('data-full-log', reversedLines.join('\n'));
    
    // Take only the first 10 lines initially
    const initialLines = reversedLines.slice(0, 10);
    
    // Join the lines back together
    logEntries.textContent = initialLines.join('\n');
    
    // Show the "Show All" link if there are more than 10 lines
    const showAllLink = document.getElementById('show-all-logs');
    if (reversedLines.length > 10) {
        showAllLink.style.display = 'block';
    } else {
        showAllLink.style.display = 'none';
    }
}

// Function to handle "Show All" logs click
function showAllLogs() {
    const logEntries = document.getElementById('log-entries');
    const logContainer = document.getElementById('log-container');
    const showAllLink = document.getElementById('show-all-logs');
    
    // Get the full log data
    const fullLog = logContainer.getAttribute('data-full-log');
    
    // Display all log entries
    logEntries.textContent = fullLog;
    
    // Hide the "Show All" link
    showAllLink.style.display = 'none';
    
    // Show a "Show Less" link instead
    const showLessLink = document.getElementById('show-less-logs');
    showLessLink.style.display = 'block';
}

// Function to handle "Show Less" logs click
function showLessLogs() {
    const logEntries = document.getElementById('log-entries');
    const logContainer = document.getElementById('log-container');
    const showLessLink = document.getElementById('show-less-logs');
    
    // Get the full log data
    const fullLog = logContainer.getAttribute('data-full-log');
    
    // Split into lines and take only the first 10
    const lines = fullLog.split('\n');
    const initialLines = lines.slice(0, 10);
    
    // Display limited log entries
    logEntries.textContent = initialLines.join('\n');
    
    // Hide the "Show Less" link
    showLessLink.style.display = 'none';
    
    // Show the "Show All" link
    const showAllLink = document.getElementById('show-all-logs');
    showAllLink.style.display = 'block';
}