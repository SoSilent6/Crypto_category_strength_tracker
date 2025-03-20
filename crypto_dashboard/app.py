from flask import Flask, jsonify
import psycopg2
import requests
import time
import threading
from datetime import datetime, timedelta
import pytz
import traceback
from psycopg2.extras import execute_values
import os
from dotenv import load_dotenv
import logging
import logging.handlers

# Load environment variables
load_dotenv()

# At the start of file
SGT = pytz.timezone('Asia/Singapore')

# After imports, add Papertrail setup
logger = logging.getLogger("app")
logger.setLevel(logging.INFO)

# Papertrail handler
handler = logging.handlers.SysLogHandler(
    address=('logs6.papertrailapp.com', 48110)
)
formatter = logging.Formatter(
    '%(asctime)s app.py: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
handler.setFormatter(formatter)
logger.addHandler(handler)

app = Flask(__name__)

fetch_in_progress = False         # global flag to indicate a fetch is running
fetch_lock = threading.Lock()     # lock to protect fetch_in_progress

def get_db_connection():
    logger.debug("Connecting to database...")
    try:
        conn = psycopg2.connect(
            "postgresql://crypto_database_465t_user:3Pn5YjUINXQWRTkMPx3OjiZCETYTlsSc@dpg-cuk9r98gph6c73bouo90-a.singapore-postgres.render.com/crypto_database_465t"
        )
        logger.debug("Database connection successful.")
        return conn
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        raise

def get_next_10min_mark(dt):
    """Always get the next future 10 minute mark"""
    minutes = dt.minute
    current_10min = (minutes // 10) * 10
    next_10min = current_10min + 10  # Always add 10 to get next mark
    
    # If we're in the next hour
    if next_10min == 60:
        next_10min = 0
        dt = dt + timedelta(hours=1)
    
    return dt.replace(minute=next_10min, second=0, microsecond=0)

def get_current_10min_mark(dt):
    """Get the current/previous 10 minute mark from given time"""
    minutes = dt.minute
    current_10min = (minutes // 10) * 10
    return dt.replace(minute=current_10min, second=0, microsecond=0)

def fetch_crypto_prices(cycle_timestamp):
    print("\n=== Starting Price Fetch Cycle ===")
    logger.info("\n=== Starting Price Fetch Cycle ===")
    
    print(f"Using timestamp for this cycle: {cycle_timestamp}")
    logger.info(f"Using timestamp for this cycle: {cycle_timestamp}")
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Use cycle_timestamp throughout instead of getting new time
    print(f"[PRICES] Preparing to store prices for timestamp: {cycle_timestamp}")
    logger.info(f"[PRICES] Preparing to store prices for timestamp: {cycle_timestamp}")
    
    # Get list of tokens to fetch
    cur.execute('SELECT cmc_id, symbol FROM public."Token List" ORDER BY cmc_id')
    tokens_to_fetch = cur.fetchall()
    print(f"[PRICES] Found {len(tokens_to_fetch)} tokens to fetch")
    logger.info(f"[PRICES] Found {len(tokens_to_fetch)} tokens to fetch")
    
    # Check and create missing columns
    print("[PRICES] Checking for new tokens and creating columns if needed...")
    logger.info("[PRICES] Checking for new tokens and creating columns if needed...")
    for cmc_id, symbol in tokens_to_fetch:
        column_name = f"{symbol}_{cmc_id}"  # e.g., "BTC_1", "ETH_1027"
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'prices' 
            AND column_name = %s
        """, (column_name,))
        
        if not cur.fetchone():
            print(f"[PRICES] Creating new column for token: {column_name}")
            logger.info(f"[PRICES] Creating new column for token: {column_name}")
            cur.execute(f"""
                ALTER TABLE public.prices 
                ADD COLUMN "{column_name}" numeric(24,8)
            """)
            conn.commit()
    
    # Initialize prices dictionary
    all_prices = {}
    failed_tokens = tokens_to_fetch
    max_retries = 3
    
    # Retry loop
    for attempt in range(max_retries):
        if not failed_tokens:
            break
            
        print(f"\n[PRICES] Attempt {attempt + 1}/{max_retries}")
        logger.info(f"[PRICES] Attempt {attempt + 1}/{max_retries}")
        print(f"[PRICES] Attempting to fetch {len(failed_tokens)} tokens")
        logger.info(f"[PRICES] Attempting to fetch {len(failed_tokens)} tokens")
        
        # Split remaining tokens into batches
        batch_size = 100
        token_batches = [failed_tokens[i:i + batch_size] for i in range(0, len(failed_tokens), batch_size)]
        print(f"[PRICES] Split into {len(token_batches)} batches")
        logger.info(f"[PRICES] Split into {len(token_batches)} batches")
        new_failed_tokens = []
        
        # Process each batch
        for batch_num, batch in enumerate(token_batches, 1):
            print(f"\n[PRICES] Processing batch {batch_num}/{len(token_batches)}")
            logger.info(f"[PRICES] Processing batch {batch_num}/{len(token_batches)}")
            batch_ids = [str(token[0]) for token in batch]
            
            url = 'https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest'
            headers = {
                'Accepts': 'application/json',
                'X-CMC_PRO_API_KEY': 'cf17e7be-a4c9-4bd3-9cd6-142956e71111',
            }
            params = {
                'id': ','.join(batch_ids),
                'convert': 'USD'
            }
            
            try:
                print(f"[PRICES] Sending API request to CoinMarketCap...")
                logger.info("[PRICES] Sending API request to CoinMarketCap...")
                response = requests.get(url, headers=headers, params=params)
                print(f"[PRICES] API Response status code: {response.status_code}")
                logger.info(f"[PRICES] API Response status code: {response.status_code}")
                data = response.json()['data']
                
                print(f"[PRICES] Successfully processed {len(data)} tokens in this batch")
                logger.info(f"[PRICES] Successfully processed {len(data)} tokens in this batch")
                for token in batch:
                    cmc_id = token[0]
                    symbol = token[1]
                    if str(cmc_id) in data:
                        price = data[str(cmc_id)]['quote']['USD']['price']
                        column_name = f"{symbol}_{cmc_id}"  # Create combined key
                        all_prices[column_name] = price     # Store with combined name
                    else:
                        new_failed_tokens.append(token)
                
                # After processing batch, count successes/failures
                complete_data = sum(1 for token in batch if str(token[0]) in data)
                incomplete_data = len(batch) - complete_data
                print(f"[PRICES] Batch {batch_num} results:")
                print(f"[PRICES] - Complete data: {complete_data} tokens")
                logger.info(f"[PRICES] Batch {batch_num} results:")
                logger.info(f"[PRICES] - Complete data: {complete_data} tokens")
                print(f"[PRICES] - Incomplete data: {incomplete_data} tokens")
                logger.info(f"[PRICES] - Incomplete data: {incomplete_data} tokens")
                
            except Exception as e:
                print(f"[PRICES] Error fetching batch: {e}")
                logger.error(f"[PRICES] Error fetching batch: {e}")
                new_failed_tokens.extend(batch)
            
            if batch_num < len(token_batches):
                print("[PRICES] Waiting 1 second before next batch...")
                logger.info("[PRICES] Waiting 1 second before next batch...")
                time.sleep(1)
        
        failed_tokens = new_failed_tokens
        
        if failed_tokens and attempt < max_retries - 1:
            print(f"\n[PRICES] {len(failed_tokens)} tokens failed.")
            print(f"[PRICES] Waiting 1 second before retry...")
            logger.info(f"[PRICES] {len(failed_tokens)} tokens failed.")
            logger.info("[PRICES] Waiting 1 second before retry...")
            time.sleep(1)
    
    if failed_tokens:
        print(f"\n[PRICES] {len(failed_tokens)} tokens failed after all retries")
        logger.error(f"[PRICES] {len(failed_tokens)} tokens failed after all retries")
        for token in failed_tokens:
            print(f"Failed to fetch: {token[1]}")
            logger.error(f"Failed to fetch: {token[1]}")
    
    # Build and execute query regardless of failures
    columns = ['timestamp'] + [f"{symbol}_{cmc_id}" for cmc_id, symbol in tokens_to_fetch]
    values = [cycle_timestamp] + [all_prices.get(f"{symbol}_{cmc_id}") for cmc_id, symbol in tokens_to_fetch]
    
    query = f'''
        INSERT INTO public.prices (timestamp, {', '.join(f'"{key}"' for key in columns[1:])})
        VALUES ({', '.join(['%s'] * len(values))})
    '''
    print(f"[PRICES] Executing database update with {len(columns)} columns...")
    logger.info(f"[PRICES] Executing database update with {len(columns)} columns...")
    cur.execute(query, values)
    conn.commit()
    print(f"[PRICES] Successfully committed price data for timestamp: {cycle_timestamp}")
    logger.info(f"[PRICES] Successfully committed price data for timestamp: {cycle_timestamp}")
    
    cur.execute('SELECT COUNT(*) FROM public.prices')
    count = cur.fetchone()[0]
    print(f"[PRICES] Total rows in prices table: {count}")
    logger.info(f"[PRICES] Total rows in prices table: {count}")
    
    cur.close()
    conn.close()
    print("[PRICES] Database connection closed")
    logger.info("[PRICES] Database connection closed")
    print("=== End of Price Fetch Cycle ===\n")
    logger.info("=== End of Price Fetch Cycle ===\n")
    
    # Final summary
    print(f"\nFinal Results:")
    print(f"Successfully fetched prices: {len(all_prices)}")
    print(f"Failed to fetch: {len(failed_tokens)}")
    logger.info(f"\nFinal Results:")
    logger.info(f"Successfully fetched prices: {len(all_prices)}")
    logger.info(f"Failed to fetch: {len(failed_tokens)}")

def price_fetcher():
    global fetch_in_progress
    print("=== Price fetcher thread started ===")
    logger.info("=== Price fetcher thread started ===")
    
    last_trigger_time = None
    while True:
        current_time = datetime.now(SGT)
        # Align current time to the beginning of the current minute (which is the floor of seconds and microseconds)
        trigger_time = current_time.replace(second=0, microsecond=0)
        
        # Check if the minute is exactly a 10-minute mark
        if trigger_time.minute % 10 == 0:
            # If within the first second of the trigger minute
            if (current_time - trigger_time).total_seconds() < 1:
                # Ensure we trigger only once for this 10-minute mark
                if last_trigger_time != trigger_time:
                    with fetch_lock:
                        if not fetch_in_progress:
                            fetch_in_progress = True
                    last_trigger_time = trigger_time
                    print(f"\n[Trigger] Time trigger hit: {trigger_time}")
                    logger.info(f"[Trigger] Time trigger hit: {trigger_time}")
                    print(f"[Trigger] Starting price fetch for timestamp: {trigger_time}")
                    logger.info(f"[Trigger] Starting price fetch for timestamp: {trigger_time}")
                    try:
                        fetch_crypto_prices(trigger_time)
                        logger.info(f"[Trigger] Price fetch for {trigger_time} completed successfully")
                    except Exception as e:
                        logger.error(f"[Trigger] Error during price fetch for {trigger_time}: {e}")
                    finally:
                        with fetch_lock:
                            fetch_in_progress = False
        time.sleep(0.2)

def safety_check_trigger():
    global fetch_in_progress
    print("[Safety] Safety check thread starting...")
    logger.info("[Safety] Safety check thread starting...")
    
    while True:
        # Wait until the beginning of the next minute
        now = datetime.now(SGT)
        next_minute = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
        sleep_seconds = (next_minute - now).total_seconds()
        
        print(f"[Safety] Current time: {now.strftime('%H:%M:%S')}, sleeping for {sleep_seconds:.1f} seconds until {next_minute.strftime('%H:%M:%S')}")
        logger.info(f"[Safety] Current time: {now.strftime('%H:%M:%S')}, sleeping for {sleep_seconds:.1f} seconds until {next_minute.strftime('%H:%M:%S')}")
        time.sleep(sleep_seconds)
        
        current_time = datetime.now(SGT)
        current_minute = current_time.minute % 10  # Get the ones digit of the minute
        
        print(f"[Safety] Woke up at {current_time.strftime('%H:%M:%S')}, minute digit is {current_minute}")
        logger.info(f"[Safety] Woke up at {current_time.strftime('%H:%M:%S')}, minute digit is {current_minute}")
        
        # Run safety check if we're at minute 2, 3, or 4 of any 10-minute block
        if current_minute in [2, 3, 4]:
            print(f"[Safety] Minute {current_minute} matches safety check window")
            logger.info(f"[Safety] Minute {current_minute} matches safety check window")
            # Calculate the previous 10-minute mark
            previous_trigger = current_time.replace(
                minute=((current_time.minute // 10) * 10),
                second=0,
                microsecond=0
            )
            
            print(f"[Safety] At {current_time.strftime('%H:%M')}, checking for price entry for trigger {previous_trigger.strftime('%H:%M')}.")
            logger.info(f"[Safety] At {current_time.strftime('%H:%M')}, checking for price entry for trigger {previous_trigger.strftime('%H:%M')}.")
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute('SELECT COUNT(*) FROM public.prices WHERE timestamp = %s', (previous_trigger,))
                count = cur.fetchone()[0]
                cur.close()
                conn.close()
            except Exception as e:
                print(f"[Safety] DB error during check at {current_time.strftime('%H:%M')}: {e}")
                logger.error(f"[Safety] DB error during check at {current_time.strftime('%H:%M')}: {e}")
                continue

            if count == 0:
                print(f"[Safety] No price entry for trigger {previous_trigger.strftime('%H:%M')} at {current_time.strftime('%H:%M')}. Triggering fetch.")
                logger.info(f"[Safety] No price entry for trigger {previous_trigger.strftime('%H:%M')} at {current_time.strftime('%H:%M')}. Triggering fetch.")
                with fetch_lock:
                    if not fetch_in_progress:
                        fetch_in_progress = True
                        try:
                            fetch_crypto_prices(previous_trigger)
                            print(f"[Safety] Price fetch for {previous_trigger.strftime('%H:%M')} completed successfully.")
                            logger.info(f"[Safety] Price fetch for {previous_trigger.strftime('%H:%M')} completed successfully.")
                        except Exception as e:
                            print(f"[Safety] Error during price fetch for {previous_trigger.strftime('%H:%M')}: {e}")
                            logger.error(f"[Safety] Error during price fetch for {previous_trigger.strftime('%H:%M')}: {e}")
                        finally:
                            fetch_in_progress = False
            else:
                print(f"[Safety] Price entry for trigger {previous_trigger.strftime('%H:%M')} exists at {current_time.strftime('%H:%M')}.")
                logger.info(f"[Safety] Price entry for trigger {previous_trigger.strftime('%H:%M')} exists at {current_time.strftime('%H:%M')}.")
        else:
            print(f"[Safety] Minute {current_minute} outside safety check window")
            logger.info(f"[Safety] Minute {current_minute} outside safety check window")

if __name__ == '__main__':
    print("\n=== Starting Crypto Price Tracker ===")
    
    # Start the price fetcher in a separate thread
    price_thread = threading.Thread(target=price_fetcher)
    price_thread.daemon = True
    price_thread.start()
    print("Price fetcher thread initialized")
    logger.info("Price fetcher thread initialized")
    
    # Start the safety check thread to recover from any missed triggers
    safety_thread = threading.Thread(target=safety_check_trigger)
    safety_thread.daemon = True
    safety_thread.start()
    print("Safety check thread initialized")
    logger.info("Safety check thread initialized")
    
    # No Flask app is required so we keep the main thread alive
    while True:
        time.sleep(10)
