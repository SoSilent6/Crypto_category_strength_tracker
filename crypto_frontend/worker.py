import os
import cache_manager
from dbhandler import get_db_connection

# Use environment variable for cache directory if provided
if os.environ.get('CACHE_DIR'):
    cache_manager.CACHE_DIR = os.environ.get('CACHE_DIR')
    # Update the file paths based on new cache directory
    cache_manager.CHART_DATA_FILE = os.path.join(cache_manager.CACHE_DIR, 'chart_data.json')
    cache_manager.LAST_UPDATE_FILE = os.path.join(cache_manager.CACHE_DIR, 'last_update.json')

if __name__ == '__main__':
    # Ensure cache directory exists
    cache_manager.ensure_cache_dir()
    
    # Initialize database connection
    print("Initializing database connection...")
    get_db_connection()
    
    # Start the background checker
    print("Starting background worker...")
    cache_manager.start_background_checker()
    
    try:
        # Keep the worker running
        while True:
            pass
    except KeyboardInterrupt:
        print("Stopping background worker...")
        cache_manager.stop_background_checker()