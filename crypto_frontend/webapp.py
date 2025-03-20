from flask import Flask, render_template, jsonify, request
from datetime import datetime, timedelta
import json
from dbhandler import (get_strength_data, get_1h_strength_data, get_category_tokens, 
                      get_all_tokens, get_tokens_by_category, get_db_connection, 
                      RealDictCursor, get_all_strength_data, get_all_1h_strength_data)
import cache_manager
import pytz
import os
import random
from concurrent.futures import ThreadPoolExecutor
import time

app = Flask(__name__)

def load_categories():
    """Load categories from categories.json"""
    try:
        with open('static/data/categories.json') as f:
            categories = json.load(f)['categories']
            print(f"Loaded categories: {categories}")
            return categories
    except Exception as e:
        print(f"Error loading categories: {e}")
        return []

def load_category_colors():
    """Load category colors from categorycolors.json"""
    try:
        with open('static/data/categorycolors.json') as f:
            colors = json.load(f)['categoryColors']
            print(f"Loaded category colors: {colors}")
            return colors
    except Exception as e:
        print(f"Error loading category colors: {e}")
        return {}

@app.route('/')
def index():
    start_time = time.time()
    print("\n=== Starting index route ===")
    
    # Load all categories
    cat_start = time.time()
    categories = load_categories()
    print(f"Categories loaded: {len(categories)} items (took {time.time() - cat_start:.2f}s)")
    
    # Load category colors
    color_start = time.time()
    category_colors = load_category_colors()
    print(f"Category colors loaded: {len(category_colors)} items (took {time.time() - color_start:.2f}s)")
    
    # All calculation types
    calc_types = {
        'top_5': 'Top 5 in category',
        'top_10': 'Top 10 in category',
        'top_15': 'Top 15 in category',
        'top_20': 'Top 20 in category',
        'top_100_mc': 'Top 100 overall',
        'top_200_mc': 'Top 200 overall'
    }
    
    # Initialize data dict
    all_data = {}
    
    # Try to load from cache first with time windows
    cache_start = time.time()
    data_10min, data_1h = cache_manager.get_cached_data_for_charts()
    
    if data_10min is not None and data_1h is not None:
        print(f"Using cached data (took {time.time() - cache_start:.2f}s)")
        
        # Add 10min chart data
        for calc_type in calc_types.keys():
            if calc_type in data_10min:
                all_data[calc_type] = data_10min[calc_type]
                
        # Add 1h chart data
        for calc_type in calc_types.keys():
            one_hour_type = f"{calc_type}_1h"
            if calc_type in data_1h:
                all_data[one_hour_type] = data_1h[calc_type]
        
        print("Available data types in cache:", list(all_data.keys()))
    else:
        print("No cache available - fetching initial data from SQL")
        sql_start = time.time()
        # Get initial data for all categories and calculation types (10min and 1h)
        for calc_type in calc_types.keys():
            # Get 10-minute data
            print(f"Fetching 10min data for calculation type: {calc_type}")
            data_10min = get_strength_data(categories, calc_type)
            if data_10min:
                print(f"Got 10min data for {calc_type}: {len(data_10min)} categories")
                all_data[calc_type] = data_10min
            else:
                print(f"No 10min data received for {calc_type}")
                all_data[calc_type] = {}
                
            # Get 1-hour data
            one_hour_type = f"{calc_type}_1h"
            print(f"Fetching 1-hour data for calculation type: {one_hour_type}")
            data_1h = get_1h_strength_data(categories, calc_type)
            if data_1h:
                print(f"Got 1-hour data for {one_hour_type}: {len(data_1h)} categories")
                all_data[one_hour_type] = data_1h
            else:
                print(f"No 1-hour data received for {one_hour_type}")
                all_data[one_hour_type] = {}
        
        # Cache the initial data after loading it
        if all_data:
            print("Caching initial data load")
            print("Data types being cached:", list(all_data.keys()))
            cache_manager.update_cache(all_data)
    
    # Pass all data to template
    template_data_start = time.time()
    
    # Time the JSON serialization specifically
    json_start = time.time()
    serialized_data = json.dumps(all_data)
    json_time = time.time() - json_start
    print(f"JSON serialization took {json_time:.2f}s for {len(serialized_data)} bytes")
    
    # Time the template data dictionary creation
    dict_start = time.time()
    template_data = {
        'preloaded_data': serialized_data,
        'categories': categories,
        'category_colors': category_colors,
        'calculation_types': calc_types,  # Keep original calc_types for dropdown
    }
    dict_time = time.time() - dict_start
    print(f"Dictionary creation took {dict_time:.2f}s")
    
    template_data_time = time.time() - template_data_start
    print(f"Template data preparation took {template_data_time:.2f}s")
    
    print("\nTemplate data:")
    print(f"- Categories count: {len(categories)}")
    print(f"- Category colors count: {len(category_colors)}")
    print(f"- Calculation types: {list(calc_types.keys())}")
    print(f"- Available data types: {list(all_data.keys())}")
    print(f"Total time taken: {time.time() - start_time:.2f}s")
    print("=== End index route ===\n")
    
    return render_template('index.html', **template_data)

@app.route('/api/categories')
def get_categories():
    categories = load_categories()
    print(f"API - Returning categories: {categories}")
    return jsonify(categories)

@app.route('/api/stats/<category>')
def get_stats(category):
    print(f"API - Getting stats for category: {category}")
    # Synthetic data for demonstration
    stats = []
    for i in range(10):
        stats.append({
            'overall_rank': i + 1,
            'category_rank': i + 1,
            'symbol': f'TOKEN{i}',
            'strength_4h': random.uniform(-10, 10),
            'strength_12h': random.uniform(-10, 10),
            'price_4h': random.uniform(0.1, 1000),
            'price_24h': random.uniform(0.1, 1000),
            'market_cap': random.uniform(1000000, 1000000000)
        })
    return jsonify(stats)

@app.route('/api/check_updates')
def check_updates():
    try:
        # Get cached data
        cached_data = cache_manager.get_cached_data()
        if not cached_data:
            return jsonify({'has_updates': False})
        
        # Get last update time
        last_update = cache_manager.get_last_update_time()
        if not last_update:
            return jsonify({'has_updates': False})
            
        # Return cached data
        return jsonify({
            'has_updates': True,
            'data': cached_data,
            'timestamp': last_update.isoformat()
        })
        
    except Exception as e:
        print(f"Error checking for updates: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/search', methods=['GET'])
def search():
    print("\n=== Starting search route ===")
    
    # Get search parameters
    date_str = request.args.get('date')
    category = request.args.get('category')
    calc_type = request.args.get('calculation')
    
    print(f"Search parameters: date={date_str}, category={category}, calculation={calc_type}")
    
    if not all([date_str, category, calc_type]):
        return render_template('search_results.html', 
                             error="Missing required search parameters")
    
    # Get token data using dbhandler
    result = get_category_tokens(date_str, category, calc_type)
    
    if not result["success"]:
        return render_template('search_results.html', 
                             error=result["error"])
    
    print("=== End search route ===\n")
    return render_template('search_results.html',
                         date=date_str,
                         category=category,
                         calculation=calc_type,
                         tokens=result["data"])

@app.route('/token_list')
def token_list():
    """Display the complete list of cryptocurrencies"""
    print("\n=== Starting token list route ===")
    
    # Get all tokens using dbhandler
    result = get_all_tokens()
    
    if not result["success"]:
        return render_template('token_list.html', 
                             tokens=[],
                             error=result["error"])
    
    print("=== End token list route ===\n")
    return render_template('token_list.html',
                         tokens=result["data"])

@app.route('/category-explorer')
def category_explorer():
    """Render the category explorer page"""
    categories = load_categories()
    
    # Get all tokens in a single query instead of querying per category
    try:
        conn = get_db_connection()
        if not conn:
            return render_template('category_explorer.html', 
                                categories=categories,
                                all_tokens={})
            
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get all tokens and their categories in one query
        query = """
            SELECT symbol, name, category 
            FROM public."Token List"
            ORDER BY symbol ASC
        """
        
        cur.execute(query)
        rows = cur.fetchall()
        
        # Organize tokens by category
        all_tokens = {}
        for row in rows:
            for category in row['category']:
                if category not in all_tokens:
                    all_tokens[category] = []
                    
                # Get all categories except the current one
                other_categories = [cat for cat in row['category'] if cat != category]
                
                all_tokens[category].append({
                    'symbol': row['symbol'],
                    'name': row['name'],
                    'other_categories': other_categories
                })
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"Error loading category explorer: {e}")
        all_tokens = {}
        
    return render_template('category_explorer.html', 
                         categories=categories,
                         all_tokens=all_tokens)

@app.route('/api/tokens-by-category/<category>')
def tokens_by_category(category):
    """API endpoint to get tokens for a specific category"""
    result = get_tokens_by_category(category)
    return jsonify(result)

@app.route('/multi-category-search-results')
def multi_category_search_results():
    """Render the multi-category search results page"""
    start_time = time.time()
    print("\n=== Starting multi-category search ===")
    
    categories = request.args.get('categories', '').split(',')
    if not categories or '' in categories:
        return render_template('multi_category_search.html', error="No categories specified")

    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # First get matching tokens from Token List
                token_search_start = time.time()
                categories_array = "{" + ",".join(f'"{cat}"' for cat in categories) + "}"
                cur.execute("""
                    SELECT DISTINCT cmc_id, symbol, name 
                    FROM public."Token List" 
                    WHERE category @> %s::text[]
                """, (categories_array,))
                matching_tokens = cur.fetchall()
                print(f"Token search took: {time.time() - token_search_start:.2f}s")
                print(f"Found {len(matching_tokens)} matching tokens")

                if not matching_tokens:
                    return render_template('multi_category_search.html', 
                                        error=f"No tokens found matching all categories: {', '.join(categories)}")

                # Get the latest timestamp from tokenstrength
                timestamp_start = time.time()
                cur.execute("""
                    SELECT MAX(timestamp) as latest_time 
                    FROM public.tokenstrength
                """)
                latest_time = cur.fetchone()['latest_time']
                print(f"Getting latest timestamp took: {time.time() - timestamp_start:.2f}s")

                # Get current strength, 4h and 24h changes for each token
                strength_start = time.time()
                token_data = []
                
                # Batch query for current strengths
                cur.execute("""
                    SELECT cmc_id, strength 
                    FROM public.tokenstrength 
                    WHERE cmc_id = ANY(%s) AND timestamp = %s
                """, ([t['cmc_id'] for t in matching_tokens], latest_time))
                current_strengths = {row['cmc_id']: row['strength'] for row in cur.fetchall()}

                # Batch query for 4h ago strengths
                cur.execute("""
                    SELECT cmc_id, strength 
                    FROM public.tokenstrength 
                    WHERE cmc_id = ANY(%s) AND timestamp = %s
                """, ([t['cmc_id'] for t in matching_tokens], latest_time - timedelta(hours=4)))
                strengths_4h = {row['cmc_id']: row['strength'] for row in cur.fetchall()}

                # Batch query for 24h ago strengths
                cur.execute("""
                    SELECT cmc_id, strength 
                    FROM public.tokenstrength 
                    WHERE cmc_id = ANY(%s) AND timestamp = %s
                """, ([t['cmc_id'] for t in matching_tokens], latest_time - timedelta(hours=24)))
                strengths_24h = {row['cmc_id']: row['strength'] for row in cur.fetchall()}

                # Process all tokens
                for token in matching_tokens:
                    cmc_id = token['cmc_id']
                    current_str = current_strengths.get(cmc_id)
                    str_4h = current_str - strengths_4h.get(cmc_id, 0) if current_str and cmc_id in strengths_4h else None
                    str_24h = current_str - strengths_24h.get(cmc_id, 0) if current_str and cmc_id in strengths_24h else None

                    token_data.append({
                        'symbol': token['symbol'],
                        'name': token['name'],
                        'current_strength': current_str,
                        'strength_4h': str_4h,
                        'strength_24h': str_24h
                    })
                
                print(f"Getting and processing strengths took: {time.time() - strength_start:.2f}s")
                print(f"Total search time: {time.time() - start_time:.2f}s")
                print("=== End multi-category search ===\n")

                return render_template('multi_category_search.html',
                                    tokens=token_data,
                                    categories=categories)

    except Exception as e:
        print(f"Error in multi-category search: {e}")
        return render_template('multi_category_search.html', 
                            error="An error occurred while processing your search")

@app.route('/multi-category-search', methods=['POST'])
def multi_category_search():
    """Handle the multi-category search POST request"""
    data = request.get_json()
    categories = data.get('categories', [])
    
    if not categories:
        return jsonify({'error': 'No categories provided'}), 400
        
    return jsonify({'redirect': f'/multi-category-search-results?categories={",".join(categories)}'})

if __name__ == '__main__':
    # Use environment variable for cache directory if provided
    if os.environ.get('CACHE_DIR'):
        cache_manager.CACHE_DIR = os.environ.get('CACHE_DIR')
        # Update the file paths based on new cache directory
        cache_manager.CHART_DATA_FILE = os.path.join(cache_manager.CACHE_DIR, 'chart_data.json')
        cache_manager.LAST_UPDATE_FILE = os.path.join(cache_manager.CACHE_DIR, 'last_update.json')
    
    # Ensure cache directory exists
    cache_manager.ensure_cache_dir()
    
    # Get port from environment variable or default to 5000
    port = int(os.environ.get('PORT', 5000))
    
    # Run the Flask app
    app.run(host='0.0.0.0', port=port)