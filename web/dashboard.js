/**
 * Dashboard Application - Main JavaScript
 * Handles fetching data, processing and updating the UI components
 */

// Application state (shared data store)
const AppState = {
    state: null,        // betting state data
    activeBet: null,    // current active bet
    history: null,      // bet history
    config: null,       // configuration
    logs: null          // log data
};

// Constants
const ENDPOINTS = {
    STATE: './data/betting/betting_state.json',
    ACTIVE_BET: './data/betting/active_bet.json',
    HISTORY: './data/betting/bet_history.json',
    CONFIG: './config/betting_config.json',
    LOGS: './logs/system.log'
};

const REFRESH_INTERVAL = 60000; // 60 seconds

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
    setupEventListeners();
    startRefreshCycle();
});

/**
 * Initialize the application by fetching all required data
 */
function initializeApp() {
    try {
        DataService.fetchAllData().then(() => {
            UIUpdater.updateAllComponents();
        }).catch(error => {
            Logger.error('Failed to initialize app:', error);
        });
    } catch (error) {
        Logger.error('Error during app initialization:', error);
    }
}

/**
 * Set up event listeners for interactive elements
 */
function setupEventListeners() {
    document.getElementById('show-all-logs').addEventListener('click', function(e) {
        e.preventDefault();
        LogViewerController.showAllLogs();
    });

    document.getElementById('show-less-logs').addEventListener('click', function(e) {
        e.preventDefault();
        LogViewerController.showLessLogs();
    });
}

/**
 * Start the automatic refresh cycle for data
 */
function startRefreshCycle() {
    // Schedule regular data refreshes
    setInterval(() => {
        DataService.fetchAllData().then(() => {
            UIUpdater.updateAllComponents();
        }).catch(error => {
            Logger.error('Error refreshing data:', error);
        });
    }, REFRESH_INTERVAL);
}

/**
 * Data Service - Handles all data fetching operations
 */
const DataService = {
    /**
     * Fetch all required data from APIs
     * @returns {Promise} Promise that resolves when all data is fetched
     */
    fetchAllData: async function() {
        try {
            const fetchPromises = {
                state: this.fetchData(ENDPOINTS.STATE),
                activeBet: this.fetchActiveBet(),
                history: this.fetchData(ENDPOINTS.HISTORY),
                config: this.fetchData(ENDPOINTS.CONFIG),
                logs: this.fetchLogData()
            };

            const results = await Promise.allSettled(Object.entries(fetchPromises).map(
                ([key, promise]) => promise.then(data => ({ key, data }))
            ));

            // Process results, storing successful ones in AppState
            results.forEach(result => {
                if (result.status === 'fulfilled' && result.value) {
                    AppState[result.value.key] = result.value.data;
                }
            });

            return true;
        } catch (error) {
            Logger.error('Error fetching all data:', error);
            throw error;
        }
    },

    /**
     * Fetch data from a specific endpoint
     * @param {string} endpoint - API endpoint
     * @returns {Promise} Promise resolving to the fetched data
     */
    fetchData: async function(endpoint) {
        try {
            const response = await fetch(endpoint);
            if (!response.ok) {
                Logger.error(`HTTP error! Status: ${response.status} for ${endpoint}`);
                throw new Error(`HTTP error! Status: ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            Logger.error(`Error fetching data from ${endpoint}:`, error);
            throw error;
        }
    },

    /**
     * Special handler for fetching active bet data
     * @returns {Promise} Promise resolving to active bet data or null
     */
    fetchActiveBet: async function() {
        try {
            const response = await fetch(ENDPOINTS.ACTIVE_BET);
            
            // Handle 404 as a valid scenario (no active bet)
            if (response.status === 404) {
                return null;
            }
            
            if (!response.ok) {
                Logger.error(`HTTP error! Status: ${response.status} for active_bet.json`);
                throw new Error(`HTTP error! Status: ${response.status}`);
            }

            const data = await response.json();
            
            // Check if bet is canceled or empty
            if (!data || Object.keys(data).length === 0 || data.is_canceled) {
                return null;
            }
            
            return data;
        } catch (error) {
            Logger.error('Error fetching active bet:', error);
            return null;
        }
    },

    /**
     * Fetch log data
     * @returns {Promise} Promise resolving to the log data
     */
    fetchLogData: async function() {
        try {
            const response = await fetch(ENDPOINTS.LOGS);
            
            if (response.status === 404) {
                Logger.warn('System log file not found.');
                return '';
            }
            
            if (!response.ok) {
                Logger.error(`HTTP error! Status: ${response.status} for system.log`);
                throw new Error(`HTTP error! Status: ${response.status}`);
            }
            
            return await response.text();
        } catch (error) {
            Logger.error('Error fetching logs:', error);
            throw error;
        }
    }
};

/**
 * Data Processor - Processes raw data into usable format for UI
 */
const DataProcessor = {
    /**
     * Calculate all values derived from the app state
     * @returns {Object} Object containing all calculated values
     */
    calculateDerivedValues: function() {
        try {
            if (!AppState.state) {
                Logger.warn('State data missing when calculating values');
                return this.getDefaultValues();
            }

            // Get configuration values with fallbacks
            const configInitialStake = this.getConfigValueSafely(['config', 'betting', 'initial_stake'], 1.0);
            const stateInitialStake = this.getConfigValueSafely(['state', 'starting_stake'], configInitialStake);
            const initialStake = stateInitialStake;
            
            // Gather values from state with fallbacks
            const currentBalance = this.getConfigValueSafely(['state', 'current_balance'], initialStake);
            const totalBets = this.getConfigValueSafely(['state', 'total_bets_placed'], 0);
            const wins = this.getConfigValueSafely(['state', 'total_wins'], 0);
            const losses = this.getConfigValueSafely(['state', 'total_losses'], 0);
            const totalCommissionPaid = this.getConfigValueSafely(['state', 'total_commission_paid'], 0);
            const highestBalance = this.getConfigValueSafely(['state', 'highest_balance'], initialStake);
            
            // Logic for next stake calculation
            const hasWinningProfit = AppState.state && AppState.state.last_winning_profit > 0;
            const nextStake = hasWinningProfit 
                ? (AppState.state.last_winning_profit + initialStake) 
                : initialStake;
            
            // Calculate win rate
            const winRate = totalBets > 0 ? (wins / totalBets) * 100 : 0;
            
            // Calculate total initial stakes lost
            const cumulativeInitialStakeLoss = -(losses * initialStake);
            
            return {
                currentBalance,
                targetAmount: this.getConfigValueSafely(['state', 'target_amount'], 50000.0),
                currentCycle: this.getConfigValueSafely(['state', 'current_cycle'], 1),
                currentBetInCycle: this.getConfigValueSafely(['state', 'current_bet_in_cycle'], 0),
                initialStake,
                nextStake,
                totalBets,
                wins,
                losses,
                winRate,
                totalProfitLoss: cumulativeInitialStakeLoss,
                highestBalance,
                totalCommissionPaid,
                lastUpdated: this.getConfigValueSafely(['state', 'last_updated'], new Date().toISOString())
            };
        } catch (error) {
            Logger.error('Error calculating derived values:', error);
            return this.getDefaultValues();
        }
    },

    /**
     * Safely extracts a value from nested objects with fallback
     * @param {Array} path - Path to the value as array of keys
     * @param {*} defaultValue - Default value if path doesn't exist
     * @returns {*} Value from path or default
     */
    getConfigValueSafely: function(path, defaultValue) {
        try {
            let current = AppState;
            
            for (const key of path) {
                if (current === null || current === undefined || !Object.prototype.hasOwnProperty.call(current, key)) {
                    return defaultValue;
                }
                current = current[key];
            }
            
            return (current === null || current === undefined) ? defaultValue : current;
        } catch (error) {
            Logger.error(`Error accessing config path ${path.join('.')}:`, error);
            return defaultValue;
        }
    },

    /**
     * Generate default values when data is unavailable
     * @returns {Object} Default values
     */
    getDefaultValues: function() {
        return {
            currentBalance: 0,
            targetAmount: 50000.0,
            currentCycle: 1,
            currentBetInCycle: 0,
            initialStake: 1.0,
            nextStake: 1.0,
            totalBets: 0,
            wins: 0,
            losses: 0,
            winRate: 0,
            totalProfitLoss: 0,
            highestBalance: 0,
            totalCommissionPaid: 0,
            lastUpdated: new Date().toISOString()
        };
    },

    /**
     * Process bet history data by adding running totals
     * @returns {Array} Processed bet history array
     */
    processHistoryData: function() {
        try {
            if (!AppState.history || !Array.isArray(AppState.history.bets) || AppState.history.bets.length === 0) {
                return [];
            }

            // Get initial stake
            const configInitialStake = this.getConfigValueSafely(['config', 'betting', 'initial_stake'], 1.0);
            const stateInitialStake = this.getConfigValueSafely(['state', 'starting_stake'], configInitialStake);
            const initialStake = stateInitialStake;

            // Sort chronologically (oldest first)
            const chronologicalBets = [...AppState.history.bets]
                .filter(bet => bet.settlement_time)
                .sort((a, b) => {
                    try {
                        return new Date(a.settlement_time) - new Date(b.settlement_time);
                    } catch (e) {
                        Logger.error('Error sorting bet history:', e);
                        return 0;
                    }
                });

            // Calculate running loss counter
            let runningLossCounter = 0;
            const processedBets = chronologicalBets.map(bet => {
                const betCopy = { ...bet };
                
                if (betCopy.won === false) {
                    runningLossCounter++;
                }
                
                betCopy.cumulativeLoss = -(runningLossCounter * initialStake);
                return betCopy;
            });

            // Return the most recent bets first
            return processedBets.reverse();
        } catch (error) {
            Logger.error('Error processing history data:', error);
            return [];
        }
    }
};

/**
 * UI Updater - Updates all UI components with processed data
 */
const UIUpdater = {
    /**
     * Update all UI components
     */
    updateAllComponents: function() {
        try {
            const calculatedValues = DataProcessor.calculateDerivedValues();
            
            this.updateSystemStatus(calculatedValues);
            this.updateStatistics(calculatedValues);
            this.updateActiveBet();
            this.updateBetHistory();
            this.updateConfigInfo();
            this.updateLogViewer();
        } catch (error) {
            Logger.error('Error updating UI components:', error);
        }
    },

    /**
     * Update system status section
     * @param {Object} calculatedValues - Processed data values
     */
    updateSystemStatus: function(calculatedValues) {
        try {
            this.updateElement('target', `£${calculatedValues.targetAmount.toFixed(2)}`);
            this.updateElement('cycle', `#${calculatedValues.currentCycle}`);
            this.updateElement('bet-in-cycle', `#${calculatedValues.currentBetInCycle}`);
            this.updateElement('next-stake', `£${calculatedValues.nextStake.toFixed(2)}`);

            // Update total profit/loss with appropriate styling
            const totalProfitLoss = calculatedValues.totalProfitLoss;
            this.updateElement('profit-loss', `£${totalProfitLoss.toFixed(2)}`, {
                className: totalProfitLoss < 0 ? 'value negative' : 'value'
            });

            // Update highest balance
            this.updateElement('highest-balance', `£${calculatedValues.highestBalance.toFixed(2)}`);

            // Format and update timestamp
            let formattedTimestamp = 'Loading...';
            if (calculatedValues.lastUpdated) {
                try {
                    formattedTimestamp = this.formatTimestamp(calculatedValues.lastUpdated);
                } catch (e) {
                    Logger.error('Error formatting timestamp:', e);
                    formattedTimestamp = calculatedValues.lastUpdated;
                }
            }
            this.updateElement('last-updated', formattedTimestamp);
        } catch (error) {
            Logger.error('Error updating system status:', error);
        }
    },

    /**
     * Update statistics section
     * @param {Object} calculatedValues - Processed data values
     */
    updateStatistics: function(calculatedValues) {
        try {
            this.updateElement('total-bets', calculatedValues.totalBets);
            this.updateElement('win-rate', `${calculatedValues.winRate.toFixed(1)}%`);
            this.updateElement('win-loss', `${calculatedValues.wins} / ${calculatedValues.losses}`);
            this.updateElement('commission-paid', `£${calculatedValues.totalCommissionPaid.toFixed(2)}`);
        } catch (error) {
            Logger.error('Error updating statistics:', error);
        }
    },

    /**
     * Update active bet section
     */
    updateActiveBet: function() {
        try {
            // Check if active bet exists
            const isActiveBetPresent = AppState.activeBet && 
                                      Object.keys(AppState.activeBet).length > 0 && 
                                      !AppState.activeBet.is_canceled;

            // Toggle visibility based on bet presence
            this.toggleElementVisibility('no-active-bet', !isActiveBetPresent);
            this.toggleElementVisibility('active-bet-details', isActiveBetPresent);

            if (!isActiveBetPresent) {
                return;
            }

            // Update basic bet details
            this.updateElement('event-name', AppState.activeBet.event_name || 'Unknown Event');
            this.updateElement('selection', AppState.activeBet.team_name || 'Unknown');
            this.updateElement('odds', AppState.activeBet.odds || 'N/A');
            this.updateElement('stake', `£${AppState.activeBet.stake ? AppState.activeBet.stake.toFixed(2) : '0.00'}`);
            this.updateElement('market-id', AppState.activeBet.market_id || 'N/A');

            // Format and update timestamps
            this.updateBetTimestamps();

            // Update in-play status
            this.updateInPlayStatus();

            // Update odds display
            this.updateOddsDisplay();
        } catch (error) {
            Logger.error('Error updating active bet:', error);
        }
    },

    /**
     * Update bet history section
     */
    updateBetHistory: function() {
        try {
            const historyBody = document.getElementById('history-body');
            if (!historyBody) {
                Logger.error('History body element not found');
                return;
            }

            historyBody.innerHTML = ''; // Clear existing rows

            // Process bet history data
            const processedBets = DataProcessor.processHistoryData();
            
            if (processedBets.length === 0) {
                const row = document.createElement('tr');
                row.innerHTML = '<td colspan="7">No bet history available</td>';
                historyBody.appendChild(row);
                return;
            }

            // Take only the last 10 bets for display
            const recentBets = processedBets.slice(0, 10);

            // Add each bet to the table
            recentBets.forEach(bet => {
                const row = this.createBetHistoryRow(bet);
                historyBody.appendChild(row);
            });
        } catch (error) {
            Logger.error('Error updating bet history:', error);
        }
    },

    /**
     * Create a table row for a bet history entry
     * @param {Object} bet - Bet data
     * @returns {HTMLElement} Table row element
     */
    createBetHistoryRow: function(bet) {
        const row = document.createElement('tr');

        // Format settlement time
        let formattedTime = 'Unknown';
        if (bet.settlement_time) {
            try {
                formattedTime = this.formatTimestamp(bet.settlement_time);
            } catch (e) {
                Logger.error('Error formatting settlement time:', e, bet.settlement_time);
                formattedTime = 'Invalid Date';
            }
        }

        // Determine result and profit/loss display
        const isWin = bet.won === true;
        const resultClass = isWin ? 'win' : 'loss';
        const resultText = isWin ? 'WON' : 'LOST';

        // Format profit/loss text
        let profitLossText = 'N/A';
        const stake = parseFloat(bet.stake);
        const profit = parseFloat(bet.profit);

        if (!isNaN(stake)) {
            if (isWin && !isNaN(profit)) {
                profitLossText = `+£${profit.toFixed(2)}`;
            } else {
                profitLossText = `-£${stake.toFixed(2)}`;
            }
        }

        // Get cumulative loss
        const cumulativeLoss = bet.cumulativeLoss !== undefined 
            ? `£${bet.cumulativeLoss.toFixed(2)}` 
            : 'N/A';

        // Populate row
        row.innerHTML = `
            <td>${formattedTime}</td>
            <td>${bet.event_name || 'Unknown'}</td>
            <td>${bet.team_name || 'Unknown'} @ ${bet.odds || 'N/A'}</td>
            <td>£${!isNaN(stake) ? stake.toFixed(2) : '0.00'}</td>
            <td class="${resultClass}">${resultText}</td>
            <td class="${resultClass}">${profitLossText}</td>
            <td class="negative">${cumulativeLoss}</td>
        `;

        return row;
    },

    /**
     * Update configuration info section
     */
    updateConfigInfo: function() {
        try {
            // Check if config exists and has system property
            const isDryRun = DataProcessor.getConfigValueSafely(['config', 'system', 'dry_run'], true) !== false;
            
            const modeElement = document.getElementById('mode');
            if (modeElement) {
                modeElement.textContent = isDryRun ? 'DRY RUN' : 'LIVE';
                
                // Apply styling based on mode
                if (!isDryRun) {
                    modeElement.style.color = 'red';
                    modeElement.style.fontWeight = 'bold';
                } else {
                    modeElement.style.color = 'green';
                    modeElement.style.fontWeight = 'normal';
                }
            }
        } catch (error) {
            Logger.error('Error updating config info:', error);
        }
    },

    /**
     * Update log viewer with formatted log data
     */
    updateLogViewer: function() {
        try {
            LogViewerController.updateLogDisplay(AppState.logs);
        } catch (error) {
            Logger.error('Error updating log viewer:', error);
        }
    },

    /**
     * Update bet timestamps including placement and kick-off times
     */
    updateBetTimestamps: function() {
        // Update placement time
        if (AppState.activeBet.timestamp) {
            try {
                const placedTime = this.formatTimestamp(AppState.activeBet.timestamp);
                this.updateElement('placed-time', placedTime);
            } catch (e) {
                Logger.error('Error formatting placed time:', e);
                this.updateElement('placed-time', 'Invalid Date');
            }
        } else {
            this.updateElement('placed-time', 'N/A');
        }

        // Update kick-off time
        if (AppState.activeBet.market_start_time) {
            try {
                const kickOffTime = this.formatTimestamp(AppState.activeBet.market_start_time);
                this.updateElement('kick-off-time', kickOffTime);
            } catch (e) {
                Logger.error('Error formatting kick-off time:', e);
                this.updateElement('kick-off-time', 'Invalid Date');
            }
        } else {
            this.updateElement('kick-off-time', 'N/A');
        }
    },

    /**
     * Update in-play status for active bet
     */
    updateInPlayStatus: function() {
        let inPlayStatusText = 'Unknown';
        let inPlayStatusClass = '';
        let marketStatusText = 'Unknown';

        if (AppState.activeBet.current_market) {
            const marketInfo = AppState.activeBet.current_market;
            marketStatusText = marketInfo.status || 'Unknown';

            if (marketInfo.inplay) {
                inPlayStatusText = 'In Play';
                inPlayStatusClass = 'status-inplay';
            } else if (marketStatusText === 'OPEN') {
                inPlayStatusText = 'Not Started';
                inPlayStatusClass = 'status-notinplay';
            } else {
                inPlayStatusText = this.capitalizeFirstLetter(marketStatusText);
                inPlayStatusClass = 'status-notinplay';
            }
        } else {
            inPlayStatusText = 'Status Unknown';
        }

        // Update the UI element
        const inPlayStatusElement = document.getElementById('in-play-status');
        if (inPlayStatusElement) {
            inPlayStatusElement.textContent = inPlayStatusText;
            inPlayStatusElement.className = `value ${inPlayStatusClass}`;
        }
    },

    /**
     * Update odds display for all teams and highlight lowest odds
     */
    updateOddsDisplay: function() {
        const team1Element = document.getElementById('team1-odds');
        const team2Element = document.getElementById('team2-odds');
        const drawElement = document.getElementById('draw-odds');
        
        if (!team1Element || !team2Element || !drawElement) {
            Logger.error('Odds display elements not found');
            return;
        }

        // Reset all classes before updating
        team1Element.className = 'value';
        team2Element.className = 'value';
        drawElement.className = 'value';

        if (!AppState.activeBet.current_market || !AppState.activeBet.current_market.runners) {
            // Reset if no runner data
            this.updateElement('team1-odds-label', 'Team 1 Win Odds:');
            this.updateElement('team2-odds-label', 'Team 2 Win Odds:');
            team1Element.textContent = 'N/A';
            team2Element.textContent = 'N/A';
            drawElement.textContent = 'N/A';
            return;
        }

        const runners = AppState.activeBet.current_market.runners;

        // Sort runners by sortPriority
        const sortedRunners = [...runners].sort((a, b) => {
            return (a.sortPriority || 999) - (b.sortPriority || 999);
        });

        // Find team 1, team 2, and draw runners
        const team1Runner = sortedRunners.find(r => r.sortPriority === 1);
        const team2Runner = sortedRunners.find(r => r.sortPriority === 2);
        const drawRunner = sortedRunners.find(r => 
            r.selectionId === 58805 || 
            (r.runnerName && r.runnerName.toLowerCase() === 'the draw') ||
            (r.teamName && r.teamName.toLowerCase() === 'draw')
        );

        // Update team names for labels
        const team1Name = team1Runner ? (team1Runner.teamName || team1Runner.runnerName || 'Team 1') : 'Team 1';
        const team2Name = team2Runner ? (team2Runner.teamName || team2Runner.runnerName || 'Team 2') : 'Team 2';

        this.updateElement('team1-odds-label', `${team1Name} Win Odds:`);
        this.updateElement('team2-odds-label', `${team2Name} Win Odds:`);

        // Get odds values
        const team1Odds = this.getBestBackPrice(team1Runner);
        const team2Odds = this.getBestBackPrice(team2Runner);
        const drawOdds = this.getBestBackPrice(drawRunner);

        // Update odds display
        team1Element.textContent = team1Odds !== null ? team1Odds.toFixed(2) : 'N/A';
        team2Element.textContent = team2Odds !== null ? team2Odds.toFixed(2) : 'N/A';
        drawElement.textContent = drawOdds !== null ? drawOdds.toFixed(2) : 'N/A';

        // Highlight lowest odds
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
    },

    /**
     * Helper method to get best back price from runner
     * @param {Object} runner - Runner data
     * @returns {number|null} Best back price or null
     */
    getBestBackPrice: function(runner) {
        if (runner && 
            runner.ex && 
            runner.ex.availableToBack && 
            runner.ex.availableToBack.length > 0) {
            
            const price = parseFloat(runner.ex.availableToBack[0].price);
            return !isNaN(price) ? price : null;
        }
        return null;
    },

    /**
     * Helper method to update element text and optional properties
     * @param {string} id - Element ID
     * @param {string} content - Content to set
     * @param {Object} options - Optional properties to set
     */
    updateElement: function(id, content, options = {}) {
        const element = document.getElementById(id);
        if (element) {
            element.textContent = content;
            
            if (options.className) {
                element.className = options.className;
            }
            
            if (options.style) {
                Object.assign(element.style, options.style);
            }
        }
    },

    /**
     * Helper method to toggle element visibility
     * @param {string} id - Element ID
     * @param {boolean} isVisible - Whether element should be visible
     */
    toggleElementVisibility: function(id, isVisible) {
        const element = document.getElementById(id);
        if (element) {
            element.style.display = isVisible ? 'block' : 'none';
        }
    },

    /**
     * Format timestamp to locale string
     * @param {string} timestamp - ISO timestamp
     * @returns {string} Formatted date string
     */
    formatTimestamp: function(timestamp) {
        return new Date(timestamp).toLocaleString();
    },

    /**
     * Capitalize first letter of a string
     * @param {string} str - Input string
     * @returns {string} String with first letter capitalized
     */
    capitalizeFirstLetter: function(str) {
        return str.charAt(0).toUpperCase() + str.slice(1).toLowerCase();
    }
};

/**
 * Log Viewer Controller - Handles log display functionality
 */
const LogViewerController = {
    /**
     * Update log display with formatted content
     * @param {string} logData - Raw log data
     */
    updateLogDisplay: function(logData) {
        const logEntries = document.getElementById('log-entries');
        const logContainer = document.getElementById('log-container');
        const showAllLink = document.getElementById('show-all-logs');
        const showLessLink = document.getElementById('show-less-logs');

        if (!logEntries || !logContainer || !showAllLink || !showLessLink) {
            Logger.error('Log viewer elements not found');
            return;
        }

        // Handle empty log data
        if (!logData || logData.trim() === '') {
            logEntries.innerHTML = '<span class="log-empty">No log entries found.</span>';
            showAllLink.style.display = 'none';
            showLessLink.style.display = 'none';
            return;
        }

        // Process log data
        const lines = logData.split('\n').filter(line => line.trim() !== '');
        const reversedLines = lines.reverse();
        const formattedLines = this.formatLogLines(reversedLines);

        // Store full log data
        logContainer.setAttribute('data-full-log', formattedLines.join('\n'));

        // Check current display state
        const isShowingAll = showLessLink.style.display === 'block';

        if (isShowingAll) {
            // Update full display
            logEntries.innerHTML = formattedLines.join('<br>');
            showAllLink.style.display = 'none';
            showLessLink.style.display = 'block';
        } else {
            // Show limited view
            const initialLines = formattedLines.slice(0, 10);
            logEntries.innerHTML = initialLines.join('<br>');
            
            // Toggle button visibility based on log size
            showAllLink.style.display = reversedLines.length > 10 ? 'block' : 'none';
            showLessLink.style.display = 'none';
        }
    },

    /**
     * Format log lines with color coding
     * @param {Array} lines - Log lines
     * @returns {Array} Formatted HTML lines
     */
    formatLogLines: function(lines) {
        return lines.map(line => {
            // Parse log line components using regex
            const parts = line.match(/^(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2},\d{3})\s+-\s+(\w+)\s+-\s+(\w+)\s+-\s+(.*)$/);
            
            if (parts) {
                const [, timestamp, service, level, message] = parts;
                
                // Determine class based on log level
                let levelClass = '';
                if (level === 'INFO') levelClass = 'log-level-info';
                else if (level === 'DEBUG') levelClass = 'log-level-debug';
                else if (level === 'ERROR') levelClass = 'log-level-error';
                else if (level === 'WARNING') levelClass = 'log-level-warning';
                
                // Return formatted HTML
                return `<span class="timestamp">${timestamp}</span> - ${service} - <span class="${levelClass}">${level}</span> - ${message}`;
            }
            
            // Return original line if no match
            return line;
        });
    },

    /**
     * Show all log entries
     */
    showAllLogs: function() {
        const logEntries = document.getElementById('log-entries');
        const logContainer = document.getElementById('log-container');
        const showAllLink = document.getElementById('show-all-logs');
        const showLessLink = document.getElementById('show-less-logs');

        if (!logEntries || !logContainer || !showAllLink || !showLessLink) {
            Logger.error('Log viewer elements not found');
            return;
        }

        // Get full log data
        const fullLog = logContainer.getAttribute('data-full-log');
        
        // Update display
        logEntries.innerHTML = fullLog.replace(/\n/g, '<br>');
        
        // Toggle button visibility
        showAllLink.style.display = 'none';
        showLessLink.style.display = 'block';
    },

    /**
     * Show limited log entries
     */
    showLessLogs: function() {
        const logEntries = document.getElementById('log-entries');
        const logContainer = document.getElementById('log-container');
        const showAllLink = document.getElementById('show-all-logs');
        const showLessLink = document.getElementById('show-less-logs');

        if (!logEntries || !logContainer || !showAllLink || !showLessLink) {
            Logger.error('Log viewer elements not found');
            return;
        }

        // Get full log data
        const fullLog = logContainer.getAttribute('data-full-log');
        
        // Split and limit to first 10 lines
        const lines = fullLog.split('\n');
        const initialLines = lines.slice(0, 10);
        
        // Update display
        logEntries.innerHTML = initialLines.join('<br>');
        
        // Toggle button visibility
        showLessLink.style.display = 'none';
        showAllLink.style.display = lines.length > 10 ? 'block' : 'none';
    }
};

/**
 * Logger - Handles console logging
 */
const Logger = {
    /**
     * Log error message
     * @param {string} message - Error message
     * @param {Error|Object} error - Error object or details
     */
    error: function(message, error) {
        console.error(`[ERROR] ${message}`, error || '');
    },
    
    /**
     * Log warning message
     * @param {string} message - Warning message
     */
    warn: function(message) {
        console.warn(`[WARNING] ${message}`);
    },
    
    /**
     * Log info message
     * @param {string} message - Info message
     */
    info: function(message) {
        console.info(`[INFO] ${message}`);
    }
};