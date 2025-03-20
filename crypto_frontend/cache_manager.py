import json
import os
from datetime import datetime
import pytz
import threading
import time
from dbhandler import get_strength_data, get_latest_timestamp

CACHE_DIR = 'static/cache'
CHART_DATA_FILE = os.path.join(CACHE_DIR, 'chart_data.json')
LAST_UPDATE_FILE = os.path.join(CACHE_DIR, 'last_update.json')
CHECK_INTERVAL = 1  # Check SQL every 1 second

# Global flag to control background thread
should_continue = True

# Lock for cache access
cache_lock = threading.Lock()

def ensure_cache_dir():
    """Ensure cache directory exists"""
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

def get_cached_data():
    """Get data from cache if it exists"""
    try:
        if os.path.exists(CHART_DATA_FILE):
            with cache_lock:
                with open(CHART_DATA_FILE) as f:
                    return json.load(f)
    except Exception as e:
        print(f"Error reading cache: {e}")
    return None

def get_cached_data_with_window(hours=None):
    """Get data from cache with optional time window filter
    
    Args:
        hours (int): Optional number of hours of data to return (e.g. 24 for last 24 hours)
        
    Returns:
        dict: Filtered chart data or None if error
    """
    try:
        start_time = time.time()
        
        # Get full data
        read_start = time.time()
        data = get_cached_data()
        print(f"Reading cache took {time.time() - read_start:.2f}s")
        
        if not data or not hours:
            return data
            
        # Get current time from last_update.json
        time_start = time.time()
        latest_time = get_last_update_time()
        print(f"Getting last update time took {time.time() - time_start:.2f}s")
        
        if not latest_time:
            return data
            
        # Calculate cutoff time
        from datetime import timedelta
        cutoff_time = latest_time - timedelta(hours=hours)
        
        # Filter data
        filter_start = time.time()
        filtered_data = {}
        for calc_type, categories in data.items():
            filtered_data[calc_type] = {}
            for category, points in categories.items():
                filtered_points = []
                for point in points:
                    point_time = datetime.fromisoformat(point['timestamp'].replace('Z', '+00:00'))
                    if point_time >= cutoff_time:
                        filtered_points.append(point)
                if filtered_points:
                    filtered_data[calc_type][category] = filtered_points
        
        print(f"Filtering data took {time.time() - filter_start:.2f}s")
        print(f"Total cache operation took {time.time() - start_time:.2f}s")
        print(f"Original data size: {len(str(data))} bytes")
        print(f"Filtered data size: {len(str(filtered_data))} bytes")
        
        return filtered_data
        
    except Exception as e:
        print(f"Error filtering cached data: {e}")
        return None

def get_last_update_time(debug=False):
    """Get the timestamp of last cached data"""
    try:
        if os.path.exists(LAST_UPDATE_FILE) and os.path.getsize(LAST_UPDATE_FILE) > 0:
            with cache_lock:
                with open(LAST_UPDATE_FILE) as f:
                    data = json.load(f)
                    # Try both old and new timestamp keys
                    timestamp = data.get('timestamp') or data.get('last_data_point')
                    if timestamp:
                        # Parse as naive datetime (no timezone)
                        dt = datetime.fromisoformat(timestamp.replace('+00:00', ''))
                        if debug:
                            print(f"Found cache timestamp (naive): {dt}")
                        return dt
                    else:
                        print("WARNING: No timestamp found in last_update.json")
                        return None
        else:
            if debug:
                print("No last_update.json file or file is empty")
            return None
    except Exception as e:
        print(f"Error reading last update time: {e}")
        return None

def find_latest_timestamp(data):
    """Find the latest timestamp in the chart data"""
    try:
        latest = None
        
        for calc_type, category_data in data.items():
            # Skip empty calculation types
            if not category_data:
                continue
                
            for category, points in category_data.items():
                # Skip empty categories
                if not points:
                    continue
                    
                for point in points:
                    ts = datetime.fromisoformat(point['timestamp'].replace('Z', '+00:00'))
                    if not latest or ts > latest:
                        latest = ts
        
        return latest
        
    except Exception as e:
        print(f"Error finding latest timestamp: {e}")
        return None

def load_categories():
    """Load categories from categories.json"""
    try:
        with open('static/data/categories.json') as f:
            categories = json.load(f)['categories']
            return categories
    except Exception as e:
        print(f"Error loading categories: {e}")
        return []

def update_cache(new_data):
    """Update cache with current chart data"""
    ensure_cache_dir()
    
    # Generate unique temporary filenames
    import uuid
    temp_id = str(uuid.uuid4())
    temp_chart_file = f"{CHART_DATA_FILE}.{temp_id}.tmp"
    temp_update_file = f"{LAST_UPDATE_FILE}.{temp_id}.tmp"
    
    try:
        with cache_lock:  # Use lock for thread safety
            # Load existing cache data
            existing_data = {}
            if os.path.exists(CHART_DATA_FILE):
                try:
                    with open(CHART_DATA_FILE, 'r') as f:
                        existing_data = json.load(f)
                except json.JSONDecodeError:
                    print("Warning: Could not decode existing cache, starting fresh")
                except Exception as e:
                    print(f"Warning: Error reading cache file: {e}")
            
            # Create temporary merged data with deep merge
            merged_data = {}
            for calc_type in set(list(existing_data.keys()) + list(new_data.keys())):
                merged_data[calc_type] = {}
                
                # Get all categories from both datasets
                existing_categories = existing_data.get(calc_type, {})
                new_categories = new_data.get(calc_type, {})
                all_categories = set(list(existing_categories.keys()) + list(new_categories.keys()))
                
                for category in all_categories:
                    # Get existing and new data points
                    existing_points = existing_categories.get(category, [])
                    new_points = new_categories.get(category, [])
                    
                    # Combine points and remove duplicates based on timestamp
                    all_points = existing_points + new_points
                    seen_timestamps = set()
                    unique_points = []
                    
                    for point in all_points:
                        ts = point['timestamp']
                        if ts not in seen_timestamps:
                            seen_timestamps.add(ts)
                            unique_points.append(point)
                    
                    # Sort points by timestamp
                    unique_points.sort(key=lambda x: x['timestamp'])
                    merged_data[calc_type][category] = unique_points
            
            try:
                # Write merged data to temporary file first
                with open(temp_chart_file, 'w') as f:
                    json.dump(merged_data, f)
                
                # Find the latest timestamp in new data only
                latest_ts = find_latest_timestamp(new_data)
                if not latest_ts:
                    raise Exception("No valid timestamp found in new data")
                
                # Write timestamp to temporary file
                with open(temp_update_file, 'w') as f:
                    json.dump({
                        'last_data_point': latest_ts.isoformat()
                    }, f)
                
                # If everything succeeded, rename temp files to actual files
                # Use different names to avoid conflicts
                if os.path.exists(CHART_DATA_FILE):
                    os.replace(CHART_DATA_FILE, f"{CHART_DATA_FILE}.old")
                if os.path.exists(LAST_UPDATE_FILE):
                    os.replace(LAST_UPDATE_FILE, f"{LAST_UPDATE_FILE}.old")
                
                os.replace(temp_chart_file, CHART_DATA_FILE)
                os.replace(temp_update_file, LAST_UPDATE_FILE)
                
                # Clean up old files
                if os.path.exists(f"{CHART_DATA_FILE}.old"):
                    os.remove(f"{CHART_DATA_FILE}.old")
                if os.path.exists(f"{LAST_UPDATE_FILE}.old"):
                    os.remove(f"{LAST_UPDATE_FILE}.old")
                
                print(f"Cache updated with chart data up to: {latest_ts}")
                
            except Exception as e:
                # Clean up temp files if they exist
                for temp_file in [temp_chart_file, temp_update_file]:
                    try:
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                    except:
                        pass
                raise e
                
    except Exception as e:
        print(f"Error updating cache: {e}")
        # Don't raise - cache errors shouldn't break the chart

def background_update_checker():
    """Background thread to check for new SQL data and update cache"""
    print("Starting background update checker...")
    print("Monitoring SQL for new data...")
    
    # Import here to avoid circular imports
    from dbhandler import get_all_strength_data, get_all_1h_strength_data
    import json
    
    # Load categories
    def load_categories():
        try:
            with open('static/data/categories.json') as f:
                return json.load(f)['categories']
        except Exception as e:
            print(f"Error loading categories: {e}")
            return []
    
    while should_continue:
        try:
            # Get latest SQL timestamp
            sql_time = get_latest_timestamp(debug=False)
            if not sql_time:
                time.sleep(CHECK_INTERVAL)
                continue
            
            # Get last cache update time
            cache_time = get_last_update_time(debug=False)
            
            # If we have new data, update the cache
            if not cache_time or sql_time > cache_time:
                print(f"\nNew data available in SQL")
                print(f"SQL timestamp: {sql_time}")
                print(f"Cache timestamp: {cache_time}")
                
                # Load categories
                categories = load_categories()
                print(f"Loaded categories: {categories}")
                
                # Collect ALL new data before any cache updates
                new_data = {}
                try:
                    # Get data for all calculation types
                    calc_types = ['top_5', 'top_10', 'top_15', 'top_20', 'top_100_mc', 'top_200_mc']
                    
                    # Get all 10-minute data in one query
                    data_10min = get_all_strength_data(categories, calc_types, cache_time)
                    if not data_10min:
                        raise Exception("Failed to get 10min data")
                        
                    # Get all 1-hour data in one query
                    data_1h = get_all_1h_strength_data(categories, calc_types, cache_time)
                    if not data_1h:
                        raise Exception("Failed to get 1h data")
                    
                    # Organize data into the expected format
                    for calc_type in calc_types:
                        new_data[calc_type] = data_10min.get(calc_type, {})
                        new_data[f"{calc_type}_1h"] = data_1h.get(calc_type, {})
                    
                    # Only update cache if ALL data was collected successfully
                    print("Updating cache with new data types:", list(new_data.keys()))
                    update_cache(new_data)
                    print("Cache updated successfully")
                    
                except Exception as e:
                    print(f"Failed to collect all chart data: {e}")
            
            time.sleep(CHECK_INTERVAL)
            
        except Exception as e:
            print(f"Error checking SQL: {e}")
            time.sleep(CHECK_INTERVAL)

def start_background_checker():
    """Start the background checking thread"""
    global should_continue
    should_continue = True
    thread = threading.Thread(target=background_update_checker)
    thread.daemon = True  # Thread will exit when main program exits
    thread.start()

def stop_background_checker():
    """Stop the background checking thread"""
    global should_continue
    should_continue = False

def get_cached_data_for_charts():
    """Get both 24h and 48h data in a single cache read.
    For 1h data, only includes points at the start of each hour.
    
    Returns:
        tuple: (data_10min, data_1h) filtered chart data or (None, None) if error
    """
    try:
        start_time = time.time()
        
        # Read cache only ONCE
        read_start = time.time()
        data = get_cached_data()
        print(f"Reading cache took {time.time() - read_start:.2f}s")
        
        if not data:
            return None, None
            
        # Get current time from last_update.json
        time_start = time.time()
        latest_time = get_last_update_time()
        print(f"Getting last update time took {time.time() - time_start:.2f}s")
        
        if not latest_time:
            return None, None
            
        # Calculate cutoff times
        from datetime import timedelta
        cutoff_24h = latest_time - timedelta(hours=24)
        cutoff_48h = latest_time - timedelta(hours=48)
        
        # Filter data for both windows at once
        filter_start = time.time()
        data_10min = {}  # For 10-minute charts
        data_1h = {}     # For 1-hour charts
        
        for calc_type, categories in data.items():
            # Skip _1h types in 10min data
            if not calc_type.endswith('_1h'):
                data_10min[calc_type] = {}
                for category, points in categories.items():
                    points_24h = []
                    for point in points:
                        point_time = datetime.fromisoformat(point['timestamp'].replace('Z', '+00:00'))
                        if point_time >= cutoff_24h:
                            points_24h.append(point)
                    if points_24h:
                        data_10min[calc_type][category] = points_24h
            
            # Process 1h data separately
            base_type = calc_type.replace('_1h', '')
            if base_type in data:  # If we have the base type
                data_1h[base_type] = {}
                for category, points in data[base_type].items():
                    points_48h = []
                    for point in points:
                        point_time = datetime.fromisoformat(point['timestamp'].replace('Z', '+00:00'))
                        # Only include points at the start of each hour
                        if point_time >= cutoff_48h and point_time.minute == 0:
                            points_48h.append(point)
                    if points_48h:
                        data_1h[base_type][category] = points_48h
        
        print(f"Filtering both windows took {time.time() - filter_start:.2f}s")
        print(f"Total cache operation took {time.time() - start_time:.2f}s")
        print(f"Original data size: {len(str(data))} bytes")
        print(f"10min data size: {len(str(data_10min))} bytes")
        print(f"1h data size: {len(str(data_1h))} bytes")
        
        return data_10min, data_1h
        
    except Exception as e:
        print(f"Error getting chart data: {e}")
        return None, None