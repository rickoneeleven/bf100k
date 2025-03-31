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
                   // Changed to still resolve but with null, indicates file not found = no active bet
                   return null;
                }
                console.error(`HTTP error! Status: ${response.status} for active_bet.json`);
                throw new Error(`HTTP error! Status: ${response.status}`);
            }
             // Check for explicit cancellation flag or empty object
            return response.json().then(data => {
                if (!data || Object.keys(data).length === 0 || data.is_canceled) {
                    console.log("Active bet file is empty, missing, or explicitly canceled.");
                    return null; // Treat empty/canceled as no active bet
                }
                return data; // Return valid bet data
            });
        })
        .then(data => {
            activeBetData = data; // Store null or bet data
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
                updateActiveBet(); // Update active bet uses global activeBetData
                updateBetHistory(); // Update bet history uses global historyData AND now needs stateData for initialStake
                updateConfigInfo(); // Update config info uses global configData
            } catch (error) {
                console.error('Error calculating values or updating UI:', error);
            }
        })
        .catch(error => {
            console.error('Error during data fetching or processing:', error);
        });
}


function calculateDerivedValues() {
    // Default values from config or hardcoded defaults
    const configInitialStake = configData?.betting?.initial_stake || 1.0; // Get from config first
    const stateInitialStake = stateData?.starting_stake || configInitialStake; // Use state if available, else config
    const initialStake = stateInitialStake; // Final initial stake to use

    // Initialize values based on stateData primarily
    let currentBalance = stateData?.current_balance || initialStake;
    let totalBets = stateData?.total_bets_placed || 0;
    let wins = stateData?.total_wins || 0;
    let losses = stateData?.total_losses || 0; // Use total_losses from state data
    let totalCommissionPaid = stateData?.total_commission_paid || 0;
    let highestBalance = stateData?.highest_balance || initialStake;
    let nextStake = stateData?.last_winning_profit > 0 ? (stateData.last_winning_profit + initialStake) : initialStake; // Use state logic for next stake

    // Calculate win rate
    const winRate = totalBets > 0 ? (wins / totalBets) * 100 : 0;

    // New calculation for Total Initial Stakes Lost based on user's definition
    const totalLossesCount = losses; // Use the total_losses count from state
    const cumulativeInitialStakeLoss = - (totalLossesCount * initialStake); // Calculate loss based on initial stake

    return {
        currentBalance, // Keep current balance as read from state
        targetAmount: stateData?.target_amount || 50000.0,
        currentCycle: stateData?.current_cycle || 1,
        currentBetInCycle: stateData?.current_bet_in_cycle || 0,
        initialStake, // The starting stake used for calculations
        nextStake,
        totalBets,
        wins,
        losses,
        winRate,
        totalProfitLoss: cumulativeInitialStakeLoss, // Use the new loss calculation here
        highestBalance,
        totalCommissionPaid,
        lastUpdated: stateData?.last_updated || new Date().toISOString() // Use state's last updated if available
    };
}


function fetchLogData() {
    // Fetch the latest system log file
    fetch('./logs/system.log')
        .then(response => {
            if (!response.ok) {
                // Check if the error is 404 (file not found)
                if (response.status === 404) {
                    console.warn('System log file not found.');
                    return ''; // Return empty string if log file doesn't exist yet
                }
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

    // Update total profit/loss (now representing cumulative initial stake loss)
    const profitLossElement = document.getElementById('profit-loss');
    if (profitLossElement) {
        const totalProfitLoss = calculatedValues.totalProfitLoss; // This now holds the cumulative loss
        // Format as negative or zero, as it represents a loss
        profitLossElement.textContent = `£${totalProfitLoss.toFixed(2)}`;
        // Apply 'negative' class if the loss is greater than 0 (i.e., totalProfitLoss is negative)
        profitLossElement.className = totalProfitLoss < 0 ? 'value negative' : 'value';
        // No need for the 'positive' class check anymore for this specific metric
    }

    // Format highest balance value (this still reflects actual highest balance)
    const highestBalanceElement = document.getElementById('highest-balance');
    if (highestBalanceElement) {
        highestBalanceElement.textContent = `£${calculatedValues.highestBalance.toFixed(2)}`;
    }

    // Update last updated timestamp using the value from calculatedValues (which comes from stateData if possible)
    let lastUpdatedTimestamp = 'Loading...';
    if (calculatedValues.lastUpdated) {
        try {
            lastUpdatedTimestamp = new Date(calculatedValues.lastUpdated).toLocaleString();
        } catch (e) {
            console.error("Error formatting last updated timestamp:", e);
            lastUpdatedTimestamp = calculatedValues.lastUpdated; // Fallback to ISO string
        }
    }
    document.getElementById('last-updated').textContent = lastUpdatedTimestamp;
}


function updateStatistics(calculatedValues) {
    document.getElementById('total-bets').textContent = calculatedValues.totalBets;
    document.getElementById('win-rate').textContent = `${calculatedValues.winRate.toFixed(1)}%`;
    document.getElementById('win-loss').textContent = `${calculatedValues.wins} / ${calculatedValues.losses}`;
    document.getElementById('commission-paid').textContent = `£${calculatedValues.totalCommissionPaid.toFixed(2)}`;
    // Highest balance is updated in updateSystemStatus now using state value directly
    // document.getElementById('highest-balance').textContent = `£${calculatedValues.highestBalance.toFixed(2)}`;
}

function updateActiveBet() {
    // Check if data is empty, null, or explicitly canceled
    const isActiveBetPresent = activeBetData && Object.keys(activeBetData).length > 0 && !activeBetData.is_canceled;

    if (!isActiveBetPresent) {
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
        try {
             const placedTime = new Date(activeBetData.timestamp);
             document.getElementById('placed-time').textContent = placedTime.toLocaleString();
        } catch (e) {
             console.error("Error formatting placed time:", e);
             document.getElementById('placed-time').textContent = 'Invalid Date';
        }
    } else {
        document.getElementById('placed-time').textContent = 'N/A';
    }

    // Display kick off time
    if (activeBetData.market_start_time) {
         try {
            const kickOffTime = new Date(activeBetData.market_start_time);
            document.getElementById('kick-off-time').textContent = kickOffTime.toLocaleString();
         } catch (e) {
             console.error("Error formatting kick off time:", e);
             document.getElementById('kick-off-time').textContent = 'Invalid Date';
         }
    } else {
        document.getElementById('kick-off-time').textContent = 'N/A';
    }


    // Display in play status with color coding
    let inPlayStatusText = 'Unknown'; // Default text
    let inPlayStatusClass = ''; // Default class
    let marketStatusText = 'Unknown'; // Default market status text

    if (activeBetData.current_market) {
        const marketInfo = activeBetData.current_market;
        marketStatusText = marketInfo.status || 'Unknown'; // Get market status (OPEN, SUSPENDED, CLOSED)

        if (marketInfo.inplay) {
            inPlayStatusText = 'In Play';
            inPlayStatusClass = 'status-inplay'; // Green for In Play
        } else if (marketStatusText === 'OPEN') {
            inPlayStatusText = 'Not Started';
            inPlayStatusClass = 'status-notinplay'; // Red for Not Started but Open
        } else {
            // Handle other statuses like SUSPENDED, CLOSED
            inPlayStatusText = marketStatusText.charAt(0).toUpperCase() + marketStatusText.slice(1).toLowerCase(); // Capitalize status
            inPlayStatusClass = 'status-notinplay'; // Red for other non-inplay statuses
        }
    } else {
        // If current_market data is missing, maybe fallback or show loading
         inPlayStatusText = 'Status Unknown';
         inPlayStatusClass = ''; // No specific color if status is unknown
    }

    // Update the UI element
    const inPlayStatusElement = document.getElementById('in-play-status');
    inPlayStatusElement.textContent = inPlayStatusText;
    inPlayStatusElement.className = `value ${inPlayStatusClass}`; // Apply the class


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

        // Find team 1, team 2, and draw runners based on typical sort priorities or name/ID
        // This assumes Sort Priority 1=Home, 2=Away, Draw has specific ID or name
        const team1Runner = sortedRunners.find(r => r.sortPriority === 1);
        const team2Runner = sortedRunners.find(r => r.sortPriority === 2);
        // More robust Draw detection
        const drawRunner = sortedRunners.find(r =>
            r.selectionId === 58805 ||
            (r.runnerName && r.runnerName.toLowerCase() === 'the draw') ||
             (r.teamName && r.teamName.toLowerCase() === 'draw')
        );


        // Update team names for labels, fallback to generic if runner not found
        const team1Name = team1Runner ? (team1Runner.teamName || team1Runner.runnerName || 'Team 1') : 'Team 1';
        const team2Name = team2Runner ? (team2Runner.teamName || team2Runner.runnerName || 'Team 2') : 'Team 2';

        // Update label text to include team names
        document.getElementById('team1-odds-label').textContent = `${team1Name} Win Odds:`;
        document.getElementById('team2-odds-label').textContent = `${team2Name} Win Odds:`;

        // Function to safely get best back price
        const getBestBackPrice = (runner) => {
            if (runner && runner.ex && runner.ex.availableToBack && runner.ex.availableToBack.length > 0) {
                 // Ensure price is a number
                const price = parseFloat(runner.ex.availableToBack[0].price);
                return !isNaN(price) ? price : null;
            }
            return null;
        };


        // Update odds display for team 1
        team1Odds = getBestBackPrice(team1Runner);
        team1Element.textContent = team1Odds !== null ? team1Odds.toFixed(2) : 'N/A';


        // Update odds display for team 2
        team2Odds = getBestBackPrice(team2Runner);
        team2Element.textContent = team2Odds !== null ? team2Odds.toFixed(2) : 'N/A';


        // Update odds display for draw
        drawOdds = getBestBackPrice(drawRunner);
        drawElement.textContent = drawOdds !== null ? drawOdds.toFixed(2) : 'N/A';


        // Reset all classes before highlighting
        team1Element.className = 'value';
        team2Element.className = 'value';
        drawElement.className = 'value';

        // Find lowest odds among available odds and highlight in green
        const availableOdds = [];
        if (team1Odds !== null) availableOdds.push({ element: team1Element, odds: team1Odds });
        if (team2Odds !== null) availableOdds.push({ element: team2Element, odds: team2Odds });
        if (drawOdds !== null) availableOdds.push({ element: drawElement, odds: drawOdds });


        if (availableOdds.length > 0) {
            // Sort by odds (lowest first)
            availableOdds.sort((a, b) => a.odds - b.odds);

            // Highlight the lowest odds in green
            availableOdds[0].element.className = 'value positive';
        }

    } else {
        // Reset if no runner data
        document.getElementById('team1-odds-label').textContent = `Team 1 Win Odds:`;
        document.getElementById('team2-odds-label').textContent = `Team 2 Win Odds:`;
        team1Element.textContent = 'N/A';
        team2Element.textContent = 'N/A';
        drawElement.textContent = 'N/A';
         team1Element.className = 'value';
         team2Element.className = 'value';
         drawElement.className = 'value';
    }
}


function updateBetHistory() {
    const historyBody = document.getElementById('history-body');
    historyBody.innerHTML = ''; // Clear existing rows

    // Check if data has bets property and it's an array
    if (!historyData || !Array.isArray(historyData.bets) || historyData.bets.length === 0) {
        const row = document.createElement('tr');
        // Update colspan to 7
        row.innerHTML = '<td colspan="7">No bet history available</td>';
        historyBody.appendChild(row);
        return;
    }

    // --- Calculate Running Total Loss ---
    // Get initial stake - use stateData if available, else config, else default
    const configInitialStake = configData?.betting?.initial_stake || 1.0;
    const stateInitialStake = stateData?.starting_stake || configInitialStake;
    const initialStake = stateInitialStake;

    // Sort all bets chronologically (oldest first) to calculate running total
    const chronologicalBets = [...historyData.bets].filter(bet => bet.settlement_time).sort((a, b) => {
        try {
            return new Date(a.settlement_time) - new Date(b.settlement_time);
        } catch (e) { return 0; }
    });

    let runningLossCounter = 0;
    // Add the running total property to each bet object
    chronologicalBets.forEach(bet => {
        if (bet.won === false) { // If the bet was a loss
            runningLossCounter++;
        }
        // Store the cumulative loss amount (£2 * number of losses so far)
        bet.cumulativeLoss = -(runningLossCounter * initialStake);
    });
    // --- End Calculation ---

    // Sort bets by settlement time for display (newest first)
    const displaySortedBets = [...chronologicalBets].reverse(); // Reverse the chronological array

    // Take only the last 10 bets for display
    const recentBets = displaySortedBets.slice(0, 10);

    // Add each bet to the table
    recentBets.forEach(bet => {
        const row = document.createElement('tr');

        // Format settlement time safely
        let formattedTime = 'Unknown';
        if (bet.settlement_time) {
            try {
                 formattedTime = new Date(bet.settlement_time).toLocaleString();
            } catch (e) {
                 console.error("Error formatting settlement time:", e, bet.settlement_time);
                 formattedTime = 'Invalid Date';
            }
        }


        // Determine result and profit/loss display
        const isWin = bet.won === true; // Explicitly check for true
        const resultClass = isWin ? 'win' : 'loss';
        const resultText = isWin ? 'WON' : 'LOST';

        let profitLossText = 'N/A';
        const stake = parseFloat(bet.stake);
        const profit = parseFloat(bet.profit);

        if (!isNaN(stake)) {
            if (isWin && !isNaN(profit)) {
                profitLossText = `+£${profit.toFixed(2)}`;
            } else {
                // Loss or profit is NaN
                 profitLossText = `-£${stake.toFixed(2)}`;
            }
        }

        // Get the pre-calculated cumulative loss
        const cumulativeLoss = bet.cumulativeLoss !== undefined ? `£${bet.cumulativeLoss.toFixed(2)}` : 'N/A';


        row.innerHTML = `
            <td>${formattedTime}</td>
            <td>${bet.event_name || 'Unknown'}</td>
            <td>${bet.team_name || 'Unknown'} @ ${bet.odds || 'N/A'}</td>
            <td>£${!isNaN(stake) ? stake.toFixed(2) : '0.00'}</td>
            <td class="${resultClass}">${resultText}</td>
            <td class="${resultClass}">${profitLossText}</td>
            <td class="negative">${cumulativeLoss}</td> <!-- New Column Data -->
        `;

        historyBody.appendChild(row);
    });
}


function updateConfigInfo() {
    // Display mode (DRY RUN or LIVE)
    // Check configData exists and has system property before accessing dry_run
    const isDryRun = configData?.system?.dry_run !== false; // Default to true if missing or not explicitly false
    const modeElement = document.getElementById('mode');
    modeElement.textContent = isDryRun ? 'DRY RUN' : 'LIVE';

    if (!isDryRun) {
        modeElement.style.color = 'red';
        modeElement.style.fontWeight = 'bold';
    } else {
        modeElement.style.color = 'green'; // Keep green for Dry Run
        modeElement.style.fontWeight = 'normal'; // Reset font weight if needed
    }
}


function updateLogViewer(logData) {
    const logEntries = document.getElementById('log-entries');
    const logContainer = document.getElementById('log-container');
    const showAllLink = document.getElementById('show-all-logs');
    const showLessLink = document.getElementById('show-less-logs');

    // If log data is empty or null, display a message
    if (!logData || logData.trim() === '') {
        logEntries.textContent = 'No log entries found.';
        showAllLink.style.display = 'none';
        showLessLink.style.display = 'none';
        return;
    }

    // Split the log data into lines
    const lines = logData.split('\n');

    // Filter out empty lines
    const nonEmptyLines = lines.filter(line => line.trim() !== '');

    // Reverse the order so newest is at top
    const reversedLines = nonEmptyLines.reverse();

    // Store all log data in a data attribute for "Show All" functionality
    logContainer.setAttribute('data-full-log', reversedLines.join('\n'));

    // Check if currently showing all logs
    const isShowingAll = showLessLink.style.display === 'block';

    if (isShowingAll) {
        // If already showing all, just update the content
         logEntries.textContent = reversedLines.join('\n');
         // Keep "Show Less" visible, hide "Show All"
         showAllLink.style.display = 'none';
         showLessLink.style.display = 'block';
    } else {
        // Otherwise, show the initial limited view (e.g., first 10 lines)
        const initialLines = reversedLines.slice(0, 10);
        logEntries.textContent = initialLines.join('\n');

        // Show the "Show All" link only if there are more than 10 lines
        if (reversedLines.length > 10) {
            showAllLink.style.display = 'block';
        } else {
            showAllLink.style.display = 'none';
        }
        // Ensure "Show Less" is hidden initially
        showLessLink.style.display = 'none';
    }
}


// Function to handle "Show All" logs click
function showAllLogs() {
    const logEntries = document.getElementById('log-entries');
    const logContainer = document.getElementById('log-container');
    const showAllLink = document.getElementById('show-all-logs');
    const showLessLink = document.getElementById('show-less-logs');

    // Get the full log data
    const fullLog = logContainer.getAttribute('data-full-log');

    // Display all log entries
    logEntries.textContent = fullLog;

    // Hide the "Show All" link
    showAllLink.style.display = 'none';

    // Show the "Show Less" link instead
    showLessLink.style.display = 'block';
}

// Function to handle "Show Less" logs click
function showLessLogs() {
    const logEntries = document.getElementById('log-entries');
    const logContainer = document.getElementById('log-container');
    const showLessLink = document.getElementById('show-less-logs');
    const showAllLink = document.getElementById('show-all-logs');


    // Get the full log data
    const fullLog = logContainer.getAttribute('data-full-log');

    // Split into lines and take only the first 10
    const lines = fullLog.split('\n');
    const initialLines = lines.slice(0, 10);

    // Display limited log entries
    logEntries.textContent = initialLines.join('\n');

    // Hide the "Show Less" link
    showLessLink.style.display = 'none';

     // Show the "Show All" link only if there are actually more logs to show
    if (lines.length > 10) {
        showAllLink.style.display = 'block';
    } else {
        showAllLink.style.display = 'none'; // Keep hidden if less than 10 lines total
    }
}