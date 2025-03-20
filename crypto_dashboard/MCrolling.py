import os
from dotenv import load_dotenv
import psycopg2
from datetime import datetime, timedelta
import pytz
import time
import requests
import traceback
from psycopg2.extras import execute_values
from tqdm import tqdm
import logging
import logging.handlers

# Load environment variables
load_dotenv()

# Set Singapore timezone globally
SGT = pytz.timezone('Asia/Singapore')

# Add Papertrail setup
logger = logging.getLogger("mcrolling")
logger.setLevel(logging.INFO)

handler = logging.handlers.SysLogHandler(
    address=('logs6.papertrailapp.com', 48110)
)
formatter = logging.Formatter(
    '%(asctime)s MCrolling.py: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
handler.setFormatter(formatter)
logger.addHandler(handler)

def get_db_connection():
    print("Attempting database connection...")
    logger.info("Attempting database connection...")
    try:
        conn = psycopg2.connect(
            "postgresql://crypto_database_465t_user:3Pn5YjUINXQWRTkMPx3OjiZCETYTlsSc@dpg-cuk9r98gph6c73bouo90-a.singapore-postgres.render.com/crypto_database_465t"
        )
        print("Database connection successful!")
        logger.info("Database connection successful!")
        return conn
    except Exception as e:
        print(f"Database connection failed: {e}")
        logger.error(f"Database connection failed: {e}")
        raise

def round_to_10min(dt):
    """Round up to next 10 minute mark"""
    # Ensure datetime is in SGT
    if dt.tzinfo != SGT:
        dt = dt.astimezone(SGT)
    
    minutes = dt.minute
    next_10min = ((minutes // 10) + 1) * 10
    rounded = dt.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=next_10min)
    if dt.minute % 10 == 0 and dt.second == 0 and dt.microsecond == 0:
        rounded = rounded + timedelta(minutes=10)
    return rounded

def insert_token_data(cur, conn, token_data, timestamp):
    try:
        print("\n=== Database Update Process ===")
        logger.info("\n=== Database Update Process ===")
        
        # Check timestamps
        cur.execute("""
            SELECT COUNT(DISTINCT timestamp) 
            FROM public."Token Filter";
        """)
        timestamp_count = cur.fetchone()[0]
        print(f"Current stored timestamps: {timestamp_count}")
        logger.info(f"Current stored timestamps: {timestamp_count}")
        
        # Delete oldest if needed
        if timestamp_count >= 12:
            cur.execute("""
                SELECT timestamp 
                FROM public."Token Filter"
                GROUP BY timestamp
                ORDER BY timestamp ASC
                LIMIT 1
            """)
            oldest_timestamp = cur.fetchone()[0]
            print(f"Removing data from earliest timestamp: {oldest_timestamp}")
            logger.info(f"Removing data from earliest timestamp: {oldest_timestamp}")
            
            cur.execute("""
                DELETE FROM public."Token Filter"
                WHERE timestamp = %s
            """, (oldest_timestamp,))
            print(f"Deleted {cur.rowcount} rows")
            logger.info(f"Deleted {cur.rowcount} rows")
        
        # Insert new data
        print(f"\nInserting new batch for timestamp: {timestamp}")
        logger.info(f"\nInserting new batch for timestamp: {timestamp}")
        values = [(
            token['cmc_rank'],
            token['symbol'],
            token['quote']['USD']['market_cap'],
            token['id'],
            timestamp
        ) for token in token_data]
        
        # Get row range for logging
        cur.execute("SELECT COUNT(*) FROM public.\"Token Filter\"")
        start_row = cur.fetchone()[0] + 1
        end_row = start_row + len(values) - 1
        
        execute_values(cur, """
            INSERT INTO public."Token Filter" 
            (market_cap_rank, symbol, market_cap, cmc_id, timestamp)
            VALUES %s
        """, values, page_size=100)
        
        print(f"Inserted {len(values)} tokens into rows {start_row} to {end_row}")
        logger.info(f"Inserted {len(values)} tokens into rows {start_row} to {end_row}")
        conn.commit()
        
    except Exception as e:
        print(f"Error inserting token data: {e}")
        conn.rollback()

def fetch_top_tokens():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        now = datetime.now(SGT)
        timestamp = round_to_10min(now) - timedelta(minutes=10)
        print(f"\nLast processed timestamp stored as: {timestamp}")
        logger.info(f"\nLast processed timestamp stored as: {timestamp}")
        
        print("\nFetching top 1000 tokens from CoinMarketCap...")
        logger.info("\nFetching top 1000 tokens from CoinMarketCap...")
        
        # Initialize for retries
        max_retries = 5
        failed_tokens = []
        all_token_data = []
        
        url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest'
        parameters = {
            'start': '1',
            'limit': '1000',
            'convert': 'USD'
        }
        headers = {
            'X-CMC_PRO_API_KEY': os.getenv('CMC_API_KEY')
        }
        
        # Main fetch and retry loop
        for attempt in range(max_retries):
            try:
                if attempt == 0:
                    # First attempt - try all tokens
                    print("\nInitial fetch attempt...")
                    logger.info("\nInitial fetch attempt...")
                    response = requests.get(url, headers=headers, params=parameters)
                    if response.status_code != 200:
                        raise Exception(f"API request failed: {response.text}")
                    
                    data = response.json()['data']
                    
                    # Check for incomplete data
                    complete_tokens = []
                    failed_tokens = []
                    for token in data:
                        if (token.get('symbol') and 
                            token.get('id') and 
                            token.get('quote', {}).get('USD', {}).get('market_cap')):
                            complete_tokens.append(token)
                        else:
                            failed_tokens.append(token)
                    
                    print(f"Received {len(data)} tokens total")
                    logger.info(f"Received {len(data)} tokens total")
                    print(f"Complete info: {len(complete_tokens)} tokens")
                    logger.info(f"Complete info: {len(complete_tokens)} tokens")
                    print(f"Incomplete info: {len(failed_tokens)} tokens")
                    logger.info(f"Incomplete info: {len(failed_tokens)} tokens")
                    
                    all_token_data.extend(complete_tokens)
                    
                    if not failed_tokens:
                        print("All tokens complete - no retry needed")
                        logger.info("All tokens complete - no retry needed")
                        break
                
                else:
                    # Retry attempts - process failed tokens in batches
                    print(f"\nRetry Attempt {attempt}/5")
                    logger.info(f"\nRetry Attempt {attempt}/5")
                    print(f"Attempting to fetch {len(failed_tokens)} failed tokens")
                    
                    # Split into batches of 100
                    batch_size = 100
                    batches = [failed_tokens[i:i+batch_size] for i in range(0, len(failed_tokens), batch_size)]
                    print(f"Split into {len(batches)} batches of {batch_size}")
                    
                    new_failed_tokens = []
                    new_complete_tokens = []
                    
                    for batch_num, batch in enumerate(batches, 1):
                        print(f"\nProcessing batch {batch_num}/{len(batches)}")
                        batch_ids = [str(token['id']) for token in batch]
                        
                        retry_params = {
                            'id': ','.join(batch_ids),
                            'convert': 'USD'
                        }
                        
                        response = requests.get(url, headers=headers, params=retry_params)
                        if response.status_code == 200:
                            batch_data = response.json()['data']
                            
                            for token in batch:
                                token_id = str(token['id'])
                                if token_id in batch_data:
                                    token_data = batch_data[token_id]
                                    if (token_data.get('symbol') and 
                                        token_data.get('id') and 
                                        token_data.get('quote', {}).get('USD', {}).get('market_cap')):
                                        new_complete_tokens.append(token_data)
                                    else:
                                        new_failed_tokens.append(token)
                                else:
                                    new_failed_tokens.append(token)
                        else:
                            new_failed_tokens.extend(batch)
                        
                        print(f"Batch {batch_num} results:")
                        print(f"- Complete data: {len(new_complete_tokens)} tokens")
                        print(f"- Still incomplete: {len(new_failed_tokens)} tokens")
                    
                    all_token_data.extend(new_complete_tokens)
                    failed_tokens = new_failed_tokens
                    
                    if not failed_tokens:
                        print("\nAll remaining tokens retrieved successfully")
                        logger.info("\nAll remaining tokens retrieved successfully")
                        break
                    
                    if attempt < max_retries - 1:
                        print(f"\nWaiting 5 seconds before next retry...")
                        logger.info(f"Waiting 5 seconds before next retry...")
                        time.sleep(5)
            
            except Exception as e:
                print(f"Error in attempt {attempt + 1}: {e}")
                logger.error(f"Error in attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    print("Waiting 5 seconds before retry...")
                    logger.info(f"Waiting 5 seconds before retry...")
                    time.sleep(5)
                continue
        
        if failed_tokens:
            print(f"\nWarning: {len(failed_tokens)} tokens still have incomplete data after all retries")
            logger.warning(f"\nWarning: {len(failed_tokens)} tokens still have incomplete data after all retries")
        
        print(f"\nFinal Results:")
        print(f"Successfully collected: {len(all_token_data)} tokens")
        logger.info(f"Successfully collected: {len(all_token_data)} tokens")
        print(f"Failed to collect: {len(failed_tokens)} tokens")
        logger.info(f"Failed to collect: {len(failed_tokens)} tokens")
        
        # Use all collected token data
        insert_token_data(cur, conn, all_token_data, timestamp)
        
        cur.close()
        conn.close()
        print("\nDatabase connection closed")
        logger.info("\nDatabase connection closed")
        
    except Exception as e:
        print(f"Error fetching top tokens: {e}")
        traceback.print_exc()
        logger.error(f"Error fetching top tokens: {e}")

def token_filter_thread():
    print("=== Market Cap Monitor Started ===")
    logger.info("=== Market Cap Monitor Started ===")
    print(f"Using timezone: {SGT}")
    logger.info(f"Using timezone: {SGT}")
    
    while True:
        try:
            # Get current time in SGT
            current_time = datetime.now(SGT)
            next_10min = round_to_10min(current_time)
            wait_seconds = (next_10min - current_time).total_seconds()
            
            while wait_seconds > 0:
                print(f"Looking for new timestamp... Waiting {wait_seconds:.1f} seconds")
                logger.info(f"Looking for new timestamp... Waiting {wait_seconds:.1f} seconds")
                time.sleep(10)
                current_time = datetime.now(SGT)
                wait_seconds = (next_10min - current_time).total_seconds()
            
            print(f"\nFound new timestamp of {next_10min}")
            logger.info(f"\nFound new timestamp of {next_10min}")
            fetch_top_tokens()
            
        except Exception as e:
            print(f"Error in market cap thread: {e}")
            logger.error(f"Error in market cap thread: {e}")
            time.sleep(60)

if __name__ == '__main__':
    try:
        token_filter_thread()
    except KeyboardInterrupt:
        print("\nStopped by user")
        logger.info("\nStopped by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        logger.error(f"Fatal error: {e}")
