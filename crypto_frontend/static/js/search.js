// Import flatpickr for date picking
import flatpickr from "flatpickr";

console.log('search.js: Module loaded');

document.addEventListener('DOMContentLoaded', function() {
    console.log('search.js: DOMContentLoaded event fired');
    
    // Initialize date picker
    const datePicker = flatpickr("#dateSelect", {
        defaultDate: 'today',
        minDate: '2025-01-01',
        maxDate: '2027-12-31',
        dateFormat: 'Y-m-d',
        theme: 'dark'
    });

    // Set up calculation method options
    const calculationTypeMapping = {
        'Top 5 in category': 'top_5',
        'Top 10 in category': 'top_10',
        'Top 15 in category': 'top_15',
        'Top 20 in category': 'top_20',
        'Top 100 overall': 'top_100_mc',
        'Top 200 overall': 'top_200_mc'
    };

    // Populate calculation dropdown
    const calculationSelect = document.querySelector('#calculationSelect');
    if (calculationSelect) {
        Object.entries(calculationTypeMapping).forEach(([display, value]) => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = display;
            calculationSelect.appendChild(option);
        });
    }

    // Populate category dropdown from preloaded data
    const categorySelect = document.querySelector('#categorySelect');
    if (categorySelect && window.availableCategories) {
        console.log('Populating categories:', window.availableCategories);
        window.availableCategories.forEach(category => {
            const option = document.createElement('option');
            option.value = category;
            option.textContent = category;
            categorySelect.appendChild(option);
        });
    } else {
        console.error('Category select or availableCategories not found');
    }

    // Handle search form submission
    const searchForm = document.querySelector('#searchForm');
    if (searchForm) {
        searchForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const date = datePicker.selectedDates[0];
            const category = categorySelect.value;
            const calculation = calculationSelect.value;

            if (!date || !category || !calculation) {
                alert('Please fill in all search fields');
                return;
            }

            // Format date as YYYY-MM-DD without timezone conversion
            const formattedDate = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;

            // Redirect to search results
            const searchParams = new URLSearchParams({
                date: formattedDate,
                category: category,
                calculation: calculation
            });

            window.location.href = `/search?${searchParams.toString()}`;
        });
    }
});