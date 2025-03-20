import { initChart as init10MinChart, updateCalculationMethod as update10MinCalc, updateChartCategories as update10MinCategories, updateChartInterval } from './graph.js';
import { initChart as init1HChart, updateCalculationMethod as update1HCalc, updateChartCategories as update1HCategories } from './graph_1h.js';

console.log('dashboard.js: Module loaded');

// Global state management
window.chartState = {
    calculationMethod: 'Top5Category',
    visibleCategories: new Set(),
    soloCategory: null,
    currentInterval: '10Min'
};

// Function to apply state to current chart
function applyChartState() {
    console.log('Applying chart state:', window.chartState);
    
    // Apply calculation method
    if (window.chartState.currentInterval === '10Min') {
        update10MinCalc(window.chartState.calculationMethod);
    } else {
        update1HCalc(window.chartState.calculationMethod);
    }
    
    // Apply category visibility
    const allCategories = Array.from(document.querySelectorAll('.category-checkbox input[type="checkbox"]'))
        .map(toggle => toggle.parentElement.querySelector('.category-name').textContent)
        .filter(name => name !== 'All');
        
    allCategories.forEach(category => {
        const isVisible = window.chartState.soloCategory 
            ? category === window.chartState.soloCategory
            : window.chartState.visibleCategories.has(category);
            
        if (window.chartState.currentInterval === '10Min') {
            update10MinCategories(category, isVisible);
        } else {
            update1HCategories(category, isVisible);
        }
    });
}

// Track current calculation type and chart type
let currentCalculationType = 'top_5';  // default value
let currentChartType = '10min';  // default to 10min chart

// Define default checked categories
const defaultCheckedCategories = [
    'Computing Networks',
    'AI Agents',
    'AI Infrastructure',
    'Decentralized Exchanges',
    'Exchange Tokens',
    'RWA Protocols',
    'Oracle Networks'
];

document.addEventListener('DOMContentLoaded', function() {
    console.log('dashboard.js: DOMContentLoaded event fired');
    
    try {
        // Set up calculation method change handler
        const calculationSelect = document.querySelector('#calculationSelect, .calculation-group select');
        console.log('dashboard.js: Found calculation select:', calculationSelect);
        
        if (calculationSelect) {
            const calculationTypeMapping = {
                'Top5Category': 'top_5',
                'Top10Category': 'top_10',
                'Top15Category': 'top_15',
                'Top20Category': 'top_20',
                'Top100Overall': 'top_100_mc',
                'Top200Overall': 'top_200_mc'
            };
            calculationSelect.addEventListener('change', function() {
                window.chartState.calculationMethod = this.value;
                currentCalculationType = calculationTypeMapping[this.value];
                applyChartState();
            });
            
            // Set initial value to Top5Category
            calculationSelect.value = 'Top5Category';
        }

        // Initialize 10min chart (default)
        console.log('dashboard.js: About to initialize 10min chart');
        init10MinChart(window.chartState.calculationMethod);
        
        // Load categories when the page loads
        console.log('dashboard.js: Calling loadCategories()');
        loadCategories().catch(error => {
            console.error('dashboard.js: Error in loadCategories:', error);
        });
        
        // Handle interval toggle buttons
        const intervalButtons = document.querySelectorAll('.interval-toggle');
        intervalButtons.forEach(button => {
            button.addEventListener('click', function() {
                // Remove active class from all buttons
                intervalButtons.forEach(btn => btn.classList.remove('active'));
                // Add active class to clicked button
                this.classList.add('active');
                
                const interval = this.textContent.trim();
                // Convert interval to server format (1H -> 1h, 10Min -> 10min)
                const serverInterval = interval.toLowerCase();
                window.chartState.currentInterval = interval;
                
                if (interval === '10Min') {
                    if (window.oneHourChart) {
                        window.oneHourChart.destroy();
                        window.oneHourChart = null;
                    }
                    init10MinChart(window.chartState.calculationMethod);
                } else if (interval === '1H') {
                    if (window.tenMinChart) {
                        window.tenMinChart.destroy();
                        window.tenMinChart = null;
                    }
                    init1HChart(window.chartState.calculationMethod);
                }
                applyChartState();
            });
        });

        // Check for updates every 5 seconds
        async function checkForUpdates() {
            try {
                const serverInterval = window.chartState.currentInterval.toLowerCase();
                const response = await fetch(`/api/check_updates?interval=${serverInterval}`);
                const result = await response.json();
                
                if (result.has_updates && result.data) {
                    console.log('dashboard.js: New data available, storing in preloadedData');
                    
                    // Just store the new data without updating chart
                    Object.entries(result.data).forEach(([calcType, calcData]) => {
                        if (!window.preloadedData[calcType]) {
                            window.preloadedData[calcType] = {};
                        }
                        Object.entries(calcData).forEach(([category, points]) => {
                            window.preloadedData[calcType][category] = points;
                        });
                    });
                }
            } catch (error) {
                console.error('dashboard.js: Error checking for updates:', error);
            }
        }
        
        // Check for updates every 5 seconds (5000 milliseconds)
        setInterval(checkForUpdates, 5000);

    } catch (error) {
        console.error('dashboard.js: Error in DOMContentLoaded:', error);
    }
});

// Update both charts' categories
function updateBothChartsCategories(category, visible) {
    update10MinCategories(category, visible);
    update1HCategories(category, visible);
}

// Load categories from preloaded data
async function loadCategories() {
    console.log('dashboard.js: Starting to load categories...');
    try {
        console.log('dashboard.js: Using preloaded categories:', window.availableCategories);
        
        const categoryList = document.querySelector('.category-list');
        console.log('dashboard.js: Found category list element:', categoryList);
        if (!categoryList) {
            throw new Error('Category list element not found');
        }
        
        // Clear existing categories
        categoryList.innerHTML = '';
        
        // First add the "All" category
        const allLi = document.createElement('li');
        allLi.innerHTML = `
            <div class="category-item">
                <div class="placeholder-solo"></div>
                <label class="category-checkbox">
                    <input type="checkbox">
                    <span class="checkmark"></span>
                    <span class="category-name">All</span>
                </label>
            </div>
        `;
        categoryList.appendChild(allLi);
        
        // Add remaining categories from preloaded data
        console.log('dashboard.js: Adding categories to DOM...');
        window.availableCategories
            .filter(category => category !== 'All')
            .forEach((category) => {
                console.log('dashboard.js: Adding category:', category);
                const li = document.createElement('li');
                const color = window.categoryColors[category] || '#64748B';
                const isChecked = defaultCheckedCategories.includes(category);
                
                // Add to visible categories if checked by default
                if (isChecked) {
                    window.chartState.visibleCategories.add(category);
                }
                
                li.innerHTML = `
                    <div class="category-item">
                        <button type="button" class="solo-button" data-category="${category}">S</button>
                        <label class="category-checkbox">
                            <input type="checkbox" ${isChecked ? 'checked' : ''}>
                            <span class="checkmark"></span>
                            <span class="category-name">${category}</span>
                            <span class="category-indicator" style="--indicator-color: ${color}"></span>
                        </label>
                    </div>
                `;
                categoryList.appendChild(li);

                // If not checked by default, also update the chart visibility
                if (!isChecked) {
                    updateBothChartsCategories(category, false);
                }
            });
        
        console.log('dashboard.js: Categories added to DOM, initializing toggles...');
        initializeCategoryToggles();
    } catch (error) {
        console.error('Error loading categories:', error);
        console.error('Error details:', {
            name: error.name,
            message: error.message,
            stack: error.stack
        });
    }
}

// Initialize category toggle listeners
function initializeCategoryToggles() {
    console.log('dashboard.js: Initializing category toggle listeners');
    const categoryToggles = document.querySelectorAll('.category-checkbox input[type="checkbox"]');
    const soloButtons = document.querySelectorAll('.solo-button');
    
    // Initialize visible categories
    categoryToggles.forEach(toggle => {
        const categoryName = toggle.parentElement.querySelector('.category-name').textContent;
        if (categoryName !== 'All' && toggle.checked) {
            window.chartState.visibleCategories.add(categoryName);
        }
    });
    
    // Stop event propagation from solo button to prevent triggering checkbox
    soloButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            e.stopPropagation();
            const category = this.dataset.category;
            
            if (window.chartState.soloCategory === category) {
                // Turn off solo mode
                window.chartState.soloCategory = null;
                this.classList.remove('active');
            } else {
                // Enable solo mode for this category
                soloButtons.forEach(btn => btn.classList.remove('active'));
                this.classList.add('active');
                window.chartState.soloCategory = category;
            }
            
            applyChartState();
        });
    });

    categoryToggles.forEach(toggle => {
        toggle.addEventListener('change', function() {
            const categoryName = this.parentElement.querySelector('.category-name').textContent;
            
            if (categoryName === 'All') {
                const allChecked = this.checked;
                categoryToggles.forEach(otherToggle => {
                    const otherCategoryName = otherToggle.parentElement.querySelector('.category-name').textContent;
                    if (otherCategoryName !== 'All') {
                        otherToggle.checked = allChecked;
                        if (allChecked) {
                            window.chartState.visibleCategories.add(otherCategoryName);
                        } else {
                            window.chartState.visibleCategories.delete(otherCategoryName);
                        }
                    }
                });
            } else {
                if (this.checked) {
                    window.chartState.visibleCategories.add(categoryName);
                } else {
                    window.chartState.visibleCategories.delete(categoryName);
                }
            }
            applyChartState();
        });
    });
}