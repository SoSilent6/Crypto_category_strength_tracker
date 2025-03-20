// DOM Elements
const categorySelect1 = document.getElementById('category-select-1');
const categorySelect2 = document.getElementById('category-select-2');
const categorySelect3 = document.getElementById('category-select-3');
const searchButton = document.getElementById('multi-category-search-btn');
const searchCard = searchButton.closest('.search-feature-card');

// Create loading overlay
const loadingOverlay = document.createElement('div');
loadingOverlay.className = 'loading-overlay';
loadingOverlay.style.cssText = `
    display: none;
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background-color: rgba(16, 16, 22, 0.7);
    z-index: 999;
    justify-content: center;
    align-items: center;
    border-radius: 16px;  /* Match the card's border radius */
`;

// Create spinner
const spinner = document.createElement('div');
spinner.className = 'spinner';
spinner.style.cssText = `
    width: 40px;
    height: 40px;
    border: 3px solid var(--text);
    border-top: 3px solid var(--aqua);
    border-radius: 50%;
    animation: spin 1s linear infinite;
    display: none;  /* Hide spinner by default */
`;

// Add spinner animation
const styleSheet = document.createElement('style');
styleSheet.textContent = `
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
`;
document.head.appendChild(styleSheet);

loadingOverlay.appendChild(spinner);
searchCard.style.position = 'relative';
searchCard.appendChild(loadingOverlay);

// Create error popup element
const errorPopup = document.createElement('div');
errorPopup.className = 'error-popup';
errorPopup.style.cssText = `
    display: none;
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    background-color: var(--darker);
    border: 1px solid var(--aqua);
    padding: 20px;
    border-radius: 8px;
    z-index: 1000;
    color: var(--text);
    font-size: 16px;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    max-width: 400px;
    text-align: center;
`;
document.body.appendChild(errorPopup);

// Populate dropdowns when page loads
document.addEventListener('DOMContentLoaded', () => {
    populateDropdowns();
    setupEventListeners();
});

function populateDropdowns() {
    const categories = window.availableCategories;
    const dropdowns = [categorySelect1, categorySelect2, categorySelect3];

    dropdowns.forEach(dropdown => {
        // Keep the default "Select Category" option
        const defaultOption = dropdown.options[0];
        dropdown.innerHTML = '';
        dropdown.appendChild(defaultOption);

        // Add categories
        categories.forEach(category => {
            const option = document.createElement('option');
            option.value = category;
            option.textContent = category;
            dropdown.appendChild(option);
        });
    });
}

function setupEventListeners() {
    searchButton.addEventListener('click', handleSearch);
}

function validateSelections() {
    const selected = [
        categorySelect1.value,
        categorySelect2.value,
        categorySelect3.value
    ].filter(value => value !== '');

    // Check if only one category is selected
    if (selected.length === 1) {
        showError("Please select more than one category for this search.");
        return false;
    }

    // Check for duplicate selections
    const uniqueSelected = new Set(selected);
    if (uniqueSelected.size !== selected.length) {
        showError("Same categories selected, please select different categories.");
        return false;
    }

    return true;
}

function showError(message) {
    errorPopup.textContent = message;
    errorPopup.style.display = 'block';
    
    // Hide after 3 seconds
    setTimeout(() => {
        hideError();
    }, 3000);
}

function hideError() {
    errorPopup.style.display = 'none';
}

function showLoading() {
    loadingOverlay.style.display = 'flex';
    spinner.style.display = 'block';
    searchButton.disabled = true;
}

function hideLoading() {
    loadingOverlay.style.display = 'none';
    spinner.style.display = 'none';
    searchButton.disabled = false;
}

async function handleSearch() {
    hideError();

    if (!validateSelections()) {
        return;
    }

    const selectedCategories = [
        categorySelect1.value,
        categorySelect2.value,
        categorySelect3.value
    ].filter(value => value !== '');

    try {
        showLoading();
        const response = await fetch('/multi-category-search', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                categories: selectedCategories
            })
        });

        if (!response.ok) {
            throw new Error('Network response was not ok');
        }

        // Hide loading when navigating
        window.addEventListener('beforeunload', hideLoading, { once: true });
        
        // Redirect to results page
        window.location.href = '/multi-category-search-results?' + new URLSearchParams({
            categories: selectedCategories.join(',')
        });
    } catch (error) {
        hideLoading();
        showError("An error occurred while searching. Please try again.");
        console.error('Error:', error);
    }
}

// Also add page unload cleanup
window.addEventListener('beforeunload', () => {
    hideLoading();
    // Reset selections
    if (categorySelect1) categorySelect1.value = '';
    if (categorySelect2) categorySelect2.value = '';
    if (categorySelect3) categorySelect3.value = '';
});