/**
 * Performance Monitor for Crypto Narrative Tracker
 * 
 * This module tracks chart toggle events, data reloading events, and other performance metrics
 * to help debug and optimize the application.
 */

console.log('Performance Monitor: Module loaded');

// Store original console methods for later use
const originalConsole = {
    log: console.log,
    warn: console.warn,
    error: console.error,
    info: console.info
};

// Track chart toggle events
let toggleEvents = {
    count: 0,
    lastToggle: null,
    history: []
};

// Track data reloading events
let reloadEvents = {
    count: 0,
    lastReload: null,
    history: []
};

// Initialize the performance monitor
function initPerformanceMonitor() {
    console.log('Performance Monitor: Initializing');
    
    // Wait for DOM to be fully loaded
    document.addEventListener('DOMContentLoaded', () => {
        // Set up interval toggle button monitoring
        const intervalButtons = document.querySelectorAll('.interval-toggle');
        
        intervalButtons.forEach(button => {
            button.addEventListener('click', function(event) {
                const interval = this.textContent.trim();
                const timestamp = new Date();
                
                // Record toggle event
                toggleEvents.count++;
                toggleEvents.lastToggle = {
                    from: toggleEvents.lastToggle ? toggleEvents.lastToggle.to : null,
                    to: interval,
                    timestamp: timestamp
                };
                
                // Keep history of last 10 toggle events
                toggleEvents.history.push(toggleEvents.lastToggle);
                if (toggleEvents.history.length > 10) {
                    toggleEvents.history.shift();
                }
                
                // Log the toggle event with a distinctive style
                console.log(
                    `%c CHART TOGGLE EVENT #${toggleEvents.count} %c ${interval} %c ${timestamp.toISOString()}`,
                    'background: #4CAF50; color: white; font-weight: bold; padding: 2px 5px;',
                    'background: #2196F3; color: white; font-weight: bold; padding: 2px 5px;',
                    'background: #333; color: white; padding: 2px 5px;'
                );
                
                // Log the current state of window.preloadedData
                console.log('Current preloadedData keys:', Object.keys(window.preloadedData || {}));
                
                // Check if the appropriate chart data exists
                const dataKey = interval === '10Min' ? 'top_5' : 'top_5_1h';
                if (window.preloadedData && window.preloadedData[dataKey]) {
                    console.log(`Data for ${dataKey} exists with ${Object.keys(window.preloadedData[dataKey]).length} categories`);
                } else {
                    console.warn(`No data found for ${dataKey}`);
                }
            }, true); // Use capture to ensure this runs before the regular event handler
        });
        
        console.log('Performance Monitor: Toggle event tracking initialized');
        
        // Monitor for data reloading events by intercepting fetch
        const originalFetch = window.fetch;
        window.fetch = async function(url, options) {
            const response = await originalFetch(url, options);
            
            // Clone the response so we can read it and still return the original
            const clone = response.clone();
            
            // Check if this is a check_updates request with force_reload
            if (url.includes('/api/check_updates') && url.includes('force_reload=true')) {
                try {
                    const data = await clone.json();
                    const timestamp = new Date();
                    
                    // Record reload event
                    reloadEvents.count++;
                    reloadEvents.lastReload = {
                        url: url,
                        timestamp: timestamp,
                        dataSize: JSON.stringify(data).length,
                        keyCount: data.data ? Object.keys(data.data).length : 0
                    };
                    
                    // Keep history of last 10 reload events
                    reloadEvents.history.push(reloadEvents.lastReload);
                    if (reloadEvents.history.length > 10) {
                        reloadEvents.history.shift();
                    }
                    
                    // Log the reload event
                    console.log(
                        `%c DATA RELOAD EVENT #${reloadEvents.count} %c ${timestamp.toISOString()}`,
                        'background: #FF5722; color: white; font-weight: bold; padding: 2px 5px;',
                        'background: #333; color: white; padding: 2px 5px;'
                    );
                    console.log(`Data size: ${reloadEvents.lastReload.dataSize} bytes, Keys: ${reloadEvents.lastReload.keyCount}`);
                } catch (e) {
                    console.error('Error monitoring data reload:', e);
                }
            }
            
            return response;
        };
        
        console.log('Performance Monitor: Data reload tracking initialized');
    });
}

// Expose the toggle events data
function getToggleEvents() {
    return toggleEvents;
}

// Expose the reload events data
function getReloadEvents() {
    return reloadEvents;
}

// Expose a method to log the current state
function logCurrentState() {
    console.log('=== PERFORMANCE MONITOR STATE ===');
    console.log('Toggle Events:', toggleEvents);
    console.log('Reload Events:', reloadEvents);
    console.log('Current Chart Type:', window.chartState ? window.chartState.currentInterval : 'Unknown');
    console.log('Current Calculation Method:', window.chartState ? window.chartState.calculationMethod : 'Unknown');
    console.log('Available Preloaded Data Keys:', window.preloadedData ? Object.keys(window.preloadedData) : 'No data');
    console.log('================================');
}

// Initialize the monitor
initPerformanceMonitor();

// Export the public API
export {
    getToggleEvents,
    getReloadEvents,
    logCurrentState
};