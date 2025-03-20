import Chart from 'chart.js/auto';
import 'chartjs-adapter-date-fns';
import zoomPlugin from 'chartjs-plugin-zoom';

Chart.register(zoomPlugin);

// Set global chart defaults
Chart.defaults.set('plugins.zoom', {
    pan: {
        enabled: true,
        mode: 'xy',
        threshold: 0,
    },
    zoom: {
        wheel: {
            enabled: true,
            mode: 'y',
            speed: 0.1
        },
        pinch: {
            enabled: true,
            mode: 'y'
        },
        limits: {
            y: {
                min: 0,
                max: 2,
                minRange: 0.1
            }
        },
        animate: {
            duration: 1000,
            easing: 'easeInOutQuart'
        }
    }
});

// Calculation Methods Group
const CalculationMethods = {
    SimpleMovingAverage: {
        name: 'Simple Moving Average',
        calculate: (data) => data // Placeholder for actual SMA calculation
    },
    ExponentialChange: {
        name: 'Exponential Change',
        calculate: (data) => data // Placeholder for exponential calculation
    },
    RelativeStrength: {
        name: 'Relative Strength',
        calculate: (data) => data // Placeholder for RS calculation
    }
};

// Mapping between dropdown values and database calculation types
const calculationTypeMapping = {
    'Top5Category': 'top_5',
    'Top10Category': 'top_10',
    'Top15Category': 'top_15',
    'Top20Category': 'top_20',
    'Top100Overall': 'top_100_mc',
    'Top200Overall': 'top_200_mc'
};

// Time interval configurations
const TimeIntervals = {
    TenMinutes: {
        label: '10Min',
        minutes: 10,
        points: 20
    }
};

// Current calculation type
let currentCalculationType = 'top_5';  // default to Top 5 in category

// Maximum number of points that can be displayed when zoomed out
const EXTENDED_DATA_MAX = 300;

// Initialize chart
let chart = null;
window.tenMinChart = null;

function initChart() {
    console.log('%c 10-MIN CHART DEBUG INFO ', 'background: #ff0000; color: white; font-size: 20px;');
    console.log('Available data types in window.preloadedData:', JSON.stringify(Object.keys(window.preloadedData), null, 2));
    console.log('Full preloaded data:', window.preloadedData);
    
    if (chart) {
        chart.destroy();
    }
    const ctx = document.getElementById('strengthChart').getContext('2d');
    
    // Get data for current calculation type
    const data = window.preloadedData ? window.preloadedData[currentCalculationType] : {};
    console.log('Looking for data type:', currentCalculationType);
    console.log('Found data:', JSON.stringify(data, null, 2));
    
    // Create datasets from the data, limiting to last 48 points
    const datasets = Object.entries(data).map(([category, points]) => {
        const color = window.categoryColors[category] || '#787c99';
        // Take only the last 48 points
        const limitedPoints = points.slice(-48);
        return {
            label: category,
            data: limitedPoints.map(p => ({
                x: new Date(p.timestamp),
                y: p.strength
            })),
            borderColor: color,
            backgroundColor: color,
            borderWidth: 2,
            pointRadius: 4,
            pointHoverRadius: 6,
            pointBackgroundColor: color,
            pointHoverBackgroundColor: 'white',
            pointBorderColor: 'transparent',
            pointHoverBorderColor: color,
            pointBorderWidth: 0,
            pointHoverBorderWidth: 2,
            tension: 0.4
        };
    });
    
    // Calculate initial view window to show last 15 points with extra space
    const latestTime = new Date(Math.max(...Object.values(data).flatMap(d => d.map(p => new Date(p.timestamp).getTime()))));
    const startTime = new Date(latestTime.getTime() - (10 * 60 * 1000 * 14)); // Show last 15 points (14 intervals)
    const endTime = new Date(latestTime.getTime() + (10 * 60 * 1000 * 3));   // Add 3 intervals of space on right
    
    const chartData = {
        datasets: datasets
    };

    chart = new Chart(ctx, {
        type: 'line',
        data: chartData,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            aspectRatio: 1,
            transitions: {
                zoom: {
                    animation: {
                        duration: 0
                    }
                }
            },
            interaction: {
                intersect: true,
                mode: 'nearest',
                axis: 'xy',
                radius: 8
            },
            hover: {
                mode: 'nearest',
                intersect: true,
                axis: 'x'
            },
            elements: {
                point: {
                    radius: 8
                }
            },
            spanGaps: true,
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'minute', // Keep as minute for 10min chart
                        stepSize: 10,   // Keep as 10 for 10min chart
                        displayFormats: {
                            minute: 'HH:mm'
                        }
                    },
                    grid: {
                        color: '#1D1D29'
                    },
                    ticks: {
                        color: '#787c99',
                        source: 'data',
                        autoSkip: false,
                        callback: function(value, index, values) {
                            const date = new Date(value);
                            const minutes = date.getMinutes();
                            if (minutes % 10 === 0) {
                                return date.getHours().toString().padStart(2, '0') + ':' + 
                                       minutes.toString().padStart(2, '0');
                            }
                            return '';
                        }
                    },
                    min: startTime,
                    max: endTime,
                    title: {
                        display: true,
                        text: 'Time (Singapore Time)',
                        color: '#787c99',
                        font: {
                            size: 16
                        },
                        padding: {
                            top: 10
                        }
                    }
                },
                y: {
                    beginAtZero: true,
                    grid: {
                        color: '#1D1D29'
                    },
                    ticks: {
                        color: '#787c99',
                        callback: function(value) {
                            return value.toFixed(2);
                        }
                    },
                    title: {
                        display: true,
                        text: 'Score',
                        color: '#787c99',
                        font: {
                            size: 16
                        }
                    }
                }
            },
            plugins: {
                zoom: {
                    pan: {
                        enabled: true,
                        mode: 'xy',
                        threshold: 0,  // no threshold for panning
                    },
                    zoom: {
                        mode: 'x',  // Set the main zoom mode to X-axis only
                        scaleMode: 'y',  // Use Y-axis zoom when mouse is over the Y-axis
                        wheel: {
                            enabled: true,
                            mode: 'x',
                            speed: 0.1
                        },
                        pinch: {
                            enabled: true,
                            mode: 'x'
                        },
                        limits: {
                            y: {
                                min: 0,
                                max: 2,
                                minRange: 0.1
                            }
                        }
                    }
                },
                legend: {
                    display: false  // hide the legend
                },
                tooltip: {
                    mode: 'nearest',
                    intersect: true,
                    backgroundColor: '#1D1D29',
                    titleColor: '#787c99',
                    bodyColor: '#787c99',
                    borderColor: '#787c99',
                    borderWidth: 1
                }
            },
            onZoomComplete: function(context) {  
                console.log('🔍 Zoom event triggered');
                const {min, max} = context.chart.scales.x;
                console.log('Time range:', {min, max});
                
                // Get all available data for current calculation type
                const allData = window.preloadedData[currentCalculationType];
                console.log('Available data for calculation type:', currentCalculationType);
                console.log('First category data:', Object.entries(allData)[0]);
                
                // Update each dataset with points that fall within the zoomed time range
                context.chart.data.datasets.forEach((dataset, index) => {
                    console.log(`Processing dataset ${index}: ${dataset.label}`);
                    const categoryData = allData[dataset.label];
                    if (categoryData) {
                        console.log(`Found ${categoryData.length} total points for ${dataset.label}`);
                        // Filter points within the visible time range and limit to EXTENDED_DATA_MAX
                        const visiblePoints = categoryData
                            .filter(p => {
                                const timestamp = new Date(p.timestamp);
                                return timestamp >= min && timestamp <= max;
                            })
                            .slice(-EXTENDED_DATA_MAX)
                            .map(p => ({
                                x: new Date(p.timestamp),
                                y: p.strength
                            }));
                        console.log(`Filtered to ${visiblePoints.length} points for visible range`);
                        console.log('First and last points:', {
                            first: visiblePoints[0],
                            last: visiblePoints[visiblePoints.length - 1]
                        });
                        dataset.data = visiblePoints;
                    } else {
                        console.warn(`No data found for category ${dataset.label}`);
                    }
                });
                
                console.log('Updating chart without animation');
                context.chart.update('none'); // Update without animation
            }
        }
    });

    // Add zoom event listener after chart creation
    chart.options.plugins.zoom.zoom.onZoomComplete = function(context) {
        console.log('🔍 Zoom event triggered');
        const {min, max} = chart.scales.x;
        console.log('Time range:', {min, max});
        
        // Get all available data for current calculation type
        const allData = window.preloadedData[currentCalculationType];
        console.log('Available data for calculation type:', currentCalculationType);
        console.log('First category data:', Object.entries(allData)[0]);
        
        // Update each dataset with points that fall within the zoomed time range
        chart.data.datasets.forEach((dataset, index) => {
            console.log(`Processing dataset ${index}: ${dataset.label}`);
            const categoryData = allData[dataset.label];
            if (categoryData) {
                console.log(`Found ${categoryData.length} total points for ${dataset.label}`);
                // Filter points within the visible time range and limit to EXTENDED_DATA_MAX
                const visiblePoints = categoryData
                    .filter(p => {
                        const timestamp = new Date(p.timestamp);
                        return timestamp >= min && timestamp <= max;
                    })
                    .slice(-EXTENDED_DATA_MAX)
                    .map(p => ({
                        x: new Date(p.timestamp),
                        y: p.strength
                    }));
                console.log(`Filtered to ${visiblePoints.length} points for visible range`);
                console.log('First and last points:', {
                    first: visiblePoints[0],
                    last: visiblePoints[visiblePoints.length - 1]
                });
                dataset.data = visiblePoints;
            } else {
                console.warn(`No data found for category ${dataset.label}`);
            }
        });
        
        console.log('Updating chart without animation');
        chart.update('none'); // Update without animation
    };

    window.tenMinChart = chart;  // Store in global variable
}

function updateCalculationMethod(method) {
    if (!chart) return;
    
    const data = window.preloadedData[calculationTypeMapping[method]];
    
    // Update each dataset with limited points
    chart.data.datasets.forEach((dataset, index) => {
        const categoryData = data[dataset.label];
        if (categoryData) {
            // Take only the last 48 points
            const limitedPoints = categoryData.slice(-48);
            dataset.data = limitedPoints.map(d => ({
                x: new Date(d.timestamp),
                y: d.strength
            }));
        }
    });
    
    // Calculate view window to show last 15 points with extra space
    const latestTime = new Date(Math.max(...Object.values(data).flatMap(d => d.map(p => new Date(p.timestamp).getTime()))));
    const startTime = new Date(latestTime.getTime() - (10 * 60 * 1000 * 14)); // Show last 15 points (14 intervals)
    const endTime = new Date(latestTime.getTime() + (10 * 60 * 1000 * 3));   // Add 3 intervals of space on right
    
    // Update chart scales
    chart.options.scales.x.min = startTime;
    chart.options.scales.x.max = endTime;
    
    chart.update();
}

function updateChartCategories(category, visible) {
    if (!chart) return;
    
    const datasetIndex = chart.data.datasets.findIndex(ds => ds.label === category);
    if (datasetIndex !== -1) {
        chart.setDatasetVisibility(datasetIndex, visible);
        chart.update();
    }
}

function updateChartInterval(interval) {
    if (!chart) return;
    
    // Only process if it's the 10Min interval
    if (interval !== 'TenMinutes') return;
    
    const data = window.preloadedData[currentCalculationType];
    if (!data) return;
    
    // Calculate view window to show last 15 points with extra space
    const latestTime = new Date(Math.max(...Object.values(data).flatMap(d => d.map(p => new Date(p.timestamp).getTime()))));
    const startTime = new Date(latestTime.getTime() - (10 * 60 * 1000 * 14)); // Show last 15 points (14 intervals)
    const endTime = new Date(latestTime.getTime() + (10 * 60 * 1000 * 3));   // Add 3 intervals of space on right
    
    // Update chart scales
    chart.options.scales.x.min = startTime;
    chart.options.scales.x.max = endTime;
    chart.update();
}

// Export functions and objects
export {
    initChart,
    updateCalculationMethod,
    updateChartCategories,
    updateChartInterval,
    TimeIntervals
};