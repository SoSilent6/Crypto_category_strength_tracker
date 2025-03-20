import os
from dotenv import load_dotenv
import requests
import psycopg2
from datetime import datetime, timedelta
import pytz
import time
import traceback
from psycopg2.extras import execute_values
import logging
import logging.handlers

# Load environment variables from .env file
load_dotenv()
CMC_API_KEY = os.getenv('CMC_API_KEY')  # Get CoinMarketCap API key from .env

# Add Papertrail setup
logger = logging.getLogger("calculations")
logger.setLevel(logging.INFO)

handler = logging.handlers.SysLogHandler(
    address=('logs6.papertrailapp.com', 48110)
)
formatter = logging.Formatter(
    '%(asctime)s calculations.py: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
handler.setFormatter(formatter)
logger.addHandler(handler)

def get_db_connection():
    """Create and return a connection to the PostgreSQL database"""
    try:
        # Connect to the render.com hosted PostgreSQL database
        conn = psycopg2.connect(
            "postgresql://crypto_database_465t_user:3Pn5YjUINXQWRTkMPx3OjiZCETYTlsSc@dpg-cuk9r98gph6c73bouo90-a.singapore-postgres.render.com/crypto_database_465t"
        )
        return conn
    except Exception as e:
        print(f"Database connection failed: {e}")
        raise  # Re-raise the exception after logging

def fetch_cmc_batch(start, limit):
    """Fetch a batch of tokens from CoinMarketCap API
    
    Args:
        start (int): Starting position in rankings (e.g., 1, 501, 1001)
        limit (int): How many tokens to fetch (e.g., 500)
    
    Returns:
        dict: JSON response from CMC containing token data
    """
    url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest'
    parameters = {
        'start': str(start),      # Starting position (converted to string)
        'limit': str(limit),      # How many tokens to fetch
        'convert': 'USD'          # Get prices in USD
    }
    headers = {
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': CMC_API_KEY,  # API authentication
    }
    
    response = requests.get(url, headers=headers, params=parameters)
    return response.json()

def check_existing_rankings(cur, date):
    """Check if we already have rankings stored for a specific date
    
    Args:
        cur: Database cursor
        date: Date to check for existing rankings
    
    Returns:
        bool: True if rankings exist for date, False otherwise
    """
    cur.execute("""
        SELECT COUNT(*) FROM public."DailyTokenRanks"
        WHERE date = %s
    """, (date,))
    count = cur.fetchone()[0]
    return count > 0  # Return True if any rankings exist for this date

def update_daily_ranks():
    """Update daily market cap rankings for top 2000 tokens in the database"""
    try:
        sg_tz = pytz.timezone('Asia/Singapore')
        current_time = datetime.now(sg_tz)
        current_date = current_time.date()
        
        print("\n=== Daily Rankings Update Started ===")
        logger.info("\n=== Daily Rankings Update Started ===")
        print(f"Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # First check if we already have today's rankings
        conn = get_db_connection()
        cur = conn.cursor()
        
        if check_existing_rankings(cur, current_date):
            print(f"✓ Rankings for {current_date} already exist in database")
            logger.info(f"✓ Rankings for {current_date} already exist in database")
            print("→ Skipping update until next scheduled time")
            logger.info("→ Skipping update until next scheduled time")
            cur.close()
            conn.close()
            return
            
        print(f"! No rankings found for {current_date}")
        logger.info(f"! No rankings found for {current_date}")
        print("→ Starting data collection process...")
        
        # Initialize retry variables
        max_retries = 5
        failed_tokens = []
        all_token_data = []
        
        # Main fetch and retry loop
        for attempt in range(max_retries):
            try:
                if attempt == 0:
                    # First attempt - all 2000 tokens
                    data = fetch_cmc_batch(1, 2000)
                    
                    # Process tokens
                    complete_tokens = []
                    for token in data['data']:
                        if (token.get('id') and 
                            token.get('symbol') and 
                            token.get('quote', {}).get('USD', {}).get('market_cap')):
                            complete_tokens.append(token)
                        else:
                            failed_tokens.append(token)
                    
                    print(f"\nReceived {len(data['data'])} tokens total")
                    logger.info(f"\nReceived {len(data['data'])} tokens total")
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
                    # Retry attempts
                    print(f"\nRetry Attempt {attempt}/5")
                    logger.info(f"\nRetry Attempt {attempt}/5")
                    print(f"Attempting to fetch {len(failed_tokens)} failed tokens")
                    logger.info(f"Attempting to fetch {len(failed_tokens)} failed tokens")
                    
                    # Split into batches of 100
                    batch_size = 100
                    batches = [failed_tokens[i:i+batch_size] for i in range(0, len(failed_tokens), batch_size)]
                    print(f"Split into {len(batches)} batches of {batch_size}")
                    logger.info(f"Split into {len(batches)} batches of {batch_size}")
                    
                    new_failed_tokens = []
                    new_complete_tokens = []
                    
                    for batch_num, batch in enumerate(batches, 1):
                        print(f"\nProcessing batch {batch_num}/{len(batches)}")
                        logger.info(f"\nProcessing batch {batch_num}/{len(batches)}")
                        batch_ids = [str(token['id']) for token in batch]
                        
                        retry_params = {
                            'id': ','.join(batch_ids),
                            'convert': 'USD'
                        }
                        
                        retry_response = requests.get(
                            'https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest',
                            headers={'X-CMC_PRO_API_KEY': CMC_API_KEY},
                            params=retry_params
                        )
                        
                        if retry_response.status_code == 200:
                            batch_data = retry_response.json()['data']
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
                        print(f"- Retrieved: {len(new_complete_tokens)} tokens")
                        print(f"- Still incomplete: {len(new_failed_tokens)} tokens")
                        logger.info(f"Batch {batch_num} results:")
                        logger.info(f"- Retrieved: {len(new_complete_tokens)} tokens")
                        logger.info(f"- Still incomplete: {len(new_failed_tokens)} tokens")
                    
                    all_token_data.extend(new_complete_tokens)
                    failed_tokens = new_failed_tokens
                    
                    if not failed_tokens:
                        print("\nAll remaining tokens retrieved successfully")
                        logger.info("\nAll remaining tokens retrieved successfully")
                        break
                    
                    if attempt < max_retries - 1:
                        print(f"\nWaiting 20 seconds before next retry...")
                        logger.info(f"\nWaiting 20 seconds before next retry...")
                        time.sleep(20)
            
            except Exception as e:
                print(f"Error in attempt {attempt + 1}: {e}")
                logger.error(f"Error in attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    print("Waiting 20 seconds before retry...")
                    logger.info("Waiting 20 seconds before retry...")
                    time.sleep(20)
                continue
        
        print(f"\nFinal Results:")
        print(f"Successfully collected: {len(all_token_data)} tokens")
        logger.info(f"Successfully collected: {len(all_token_data)} tokens")
        print(f"Failed to collect: {len(failed_tokens)} tokens")
        logger.info(f"Failed to collect: {len(failed_tokens)} tokens")
        
        # Insert what we have
        print(f"\nInserting {len(all_token_data)} tokens into database...")
        logger.info(f"\nInserting {len(all_token_data)} tokens into database...")
        
        try:
            values = [(
                r['id'],
                r['cmc_rank'],
                r['symbol'],
                r['quote']['USD']['market_cap'],
                current_date
            ) for r in all_token_data]
            
            start_time = time.time()
            execute_values(
                cur,
                """
                INSERT INTO public."DailyTokenRanks" 
                (cmc_id, market_cap_rank, symbol, market_cap, date)
                VALUES %s
                """,
                values,
                page_size=500
            )
            end_time = time.time()
            
            print(f"✓ Successfully inserted {len(all_token_data)} tokens in {end_time - start_time:.2f} seconds")
            logger.info(f"✓ Successfully inserted {len(all_token_data)} tokens in {end_time - start_time:.2f} seconds")
            conn.commit()

            # --- New Code: Insert new row in currenttokenrankstatus table ---
            print(f"Creating a new row in currenttokenrankstatus with date: {current_date}")
            logger.info(f"Creating a new row in currenttokenrankstatus with date: {current_date}")
            cur.execute(
                'INSERT INTO public."currenttokenrankstatus" (date) VALUES (%s)',
                (current_date,)
            )
            conn.commit()
            # --- End New Code ---

        except Exception as e:
            print(f"✕ Error during insertion: {e}")
            logger.error(f"✕ Error during insertion: {e}")
            conn.rollback()
            raise
        
        finally:
            cur.close()
            conn.close()
        
        print(f"Time: {datetime.now(sg_tz).strftime('%H:%M:%S')}")
        logger.info(f"Time: {datetime.now(sg_tz).strftime('%H:%M:%S')}")
        print("=== Daily Token Rankings Update Complete ===\n")
        logger.info("=== Daily Token Rankings Update Complete ===\n")
        
    except Exception as e:
        print(f"✕ Error updating daily ranks: {e}")
        logger.error(f"✕ Error updating daily ranks: {e}")
        traceback.print_exc()
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

def schedule_rank_updates():
    """Run an infinite loop to schedule daily ranking updates at midnight SGT"""
    try:
        while True:
            try:
                # Get current time in Singapore timezone
                sg_tz = pytz.timezone('Asia/Singapore')
                now = datetime.now(sg_tz)
                
                # Calculate next midnight in Singapore time
                next_update = (now + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                
                # Calculate seconds until next update
                wait_seconds = (next_update - now).total_seconds()
                
                print(f"\nNext rank update scheduled for: {next_update}")
                print(f"Waiting {wait_seconds/3600:.2f} hours")
                logger.info(f"\nNext rank update scheduled for: {next_update}")
                logger.info(f"Waiting {wait_seconds/3600:.2f} hours")
                
                # Sleep until next update time
                time.sleep(wait_seconds)
                update_daily_ranks()
                
            except Exception as e:
                print(f"Error in scheduler: {e}")
                logger.error(f"Error in scheduler: {e}")
                time.sleep(300)  # On error, wait 5 minutes and try again
                
    except KeyboardInterrupt:
        print("\n=== Program terminated by user ===")
        print("Shutting down gracefully...")
        logger.info("\n=== Program terminated by user ===")
        logger.info("Shutting down gracefully...")

if __name__ == "__main__":
    # When script starts: Update rankings if needed
    update_daily_ranks()
    
    # Then start the scheduler for future updates
    schedule_rank_updates()
