import os
from dotenv import load_dotenv
import psycopg2
from datetime import datetime, timedelta
import pytz
from psycopg2.extras import execute_values, Json
import json
from decimal import Decimal
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
import signal
import sys
import time
import logging
import logging.handlers

# Load environment variables
load_dotenv()

# Configure timezone
SGT = pytz.timezone('Asia/Singapore')

# Configure logging for Papertrail
logger = logging.getLogger("strength_calculator")
logger.setLevel(logging.INFO)

# Papertrail handler
handler = logging.handlers.SysLogHandler(
    address=('logs6.papertrailapp.com', 48110)
)
formatter = logging.Formatter(
    '%(asctime)s strength.py: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
handler.setFormatter(formatter)
logger.addHandler(handler)

# Global scheduler for signal handling
scheduler = None

def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully"""
    print('\nReceived shutdown signal. Shutting down gracefully...')
    logger.info('Received shutdown signal. Shutting down gracefully...')
    if scheduler:
        scheduler.shutdown(wait=False)
    sys.exit(0)

def get_db_connection():
    """Create and return a connection to the PostgreSQL database"""
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

def get_calculation_timestamp():
    """Get the current calculation timestamp and the price timestamp (5 minutes earlier)"""
    now = datetime.now(SGT)
    
    # Round down to the previous 10-minute mark for both storage and price data
    storage_minutes = ((now.minute - 5) // 10) * 10  # Subtract 5 first to handle the offset
    
    # Create storage timestamp at the 10-minute mark
    storage_timestamp = now.replace(
        minute=storage_minutes,
        second=0,
        microsecond=0
    )
    
    # Price timestamp is the same as storage timestamp
    price_timestamp = storage_timestamp
    
    print(f"\nCalculation time: {now.strftime('%Y-%m-%d %H:%M:%S%z')}")
    logger.info(f"Calculation time: {now.strftime('%Y-%m-%d %H:%M:%S%z')}")
    print(f"Using price data from: {price_timestamp.strftime('%Y-%m-%d %H:%M:%S%z')}")
    logger.info(f"Using price data from: {price_timestamp.strftime('%Y-%m-%d %H:%M:%S%z')}")
    print(f"Storing results as of: {storage_timestamp.strftime('%Y-%m-%d %H:%M:%S%z')}")
    logger.info(f"Storing results as of: {storage_timestamp.strftime('%Y-%m-%d %H:%M:%S%z')}")
    
    return storage_timestamp, price_timestamp

def get_token_prices(conn, token_column, timestamp, lookback_periods=12):
    """Get historical prices for a token for the specified periods"""
    cur = conn.cursor()
    
    # Generate timestamps for the last 12 periods (2 hours)
    timestamps = [(timestamp - timedelta(minutes=i*10)) for i in range(lookback_periods)]
    timestamps.reverse()  # Oldest to newest
    
    # Query prices for these timestamps
    placeholders = ','.join(['%s'] * len(timestamps))
    query = f"""
        SELECT "{token_column}"
        FROM prices 
        WHERE timestamp IN ({placeholders})
        ORDER BY timestamp
    """
    
    cur.execute(query, timestamps)
    prices = [row[0] for row in cur.fetchall()]
    cur.close()
    
    return prices if len(prices) == lookback_periods else None

def get_all_token_prices(conn, date, price_timestamp):
    """Get prices for all tokens at once"""
    print("\nFetching prices for all tokens...")
    logger.info("Fetching prices for all tokens...")
    cur = conn.cursor()
    
    # Create price cache
    price_cache = {}
    
    # Get BTC prices first - always use BTC_1
    btc_prices = get_token_prices(conn, "BTC_1", price_timestamp)
    if not btc_prices:
        print("ERROR: Failed to get Bitcoin prices!")
        logger.error("Failed to get Bitcoin prices!")
        return {}  # Return empty cache if we can't get Bitcoin prices
    
    price_cache["BTC_1"] = btc_prices
    print("Successfully cached Bitcoin prices")
    logger.info("Successfully cached Bitcoin prices")
    
    # Get all tokens from Token List
    cur.execute("""
        SELECT DISTINCT symbol, cmc_id 
        FROM public."Token List"
    """)
    tokens = cur.fetchall()
    
    # Get prices for all tokens
    for symbol, cmc_id in tokens:
        column_name = f"{symbol}_{cmc_id}"
        prices = get_token_prices(conn, column_name, price_timestamp)
        if prices:
            price_cache[column_name] = prices
    
    cur.close()
    print(f"Cached prices for {len(price_cache)} tokens")
    logger.info(f"Cached prices for {len(price_cache)} tokens")
    return price_cache

def calculate_strength(token_prices, btc_prices):
    """Calculate strength ratio using 2-hour (12 points) of data"""
    if len(token_prices) < 12 or len(btc_prices) < 12:
        return None
        
    # Convert all prices to Decimal if they aren't already
    token_prices = [Decimal(str(p)) for p in token_prices]
    btc_prices = [Decimal(str(p)) for p in btc_prices]
    
    # Calculate returns (with zero protection)
    token_returns = []
    for prev, curr in zip(token_prices[:-1], token_prices[1:]):
        if prev == 0 or curr == 0:  # Skip pairs with zero prices
            return None
        token_returns.append((curr - prev) / prev)
        
    btc_returns = []
    for prev, curr in zip(btc_prices[:-1], btc_prices[1:]):
        if prev == 0 or curr == 0:  # Skip pairs with zero prices
            return None
        btc_returns.append((curr - prev) / prev)
    
    # Calculate period strengths
    period_strengths = []
    for token_ret, btc_ret in zip(token_returns, btc_returns):
        if abs(btc_ret) < Decimal('0.0001'):
            strength = Decimal('1.0')
        elif btc_ret > 0:
            strength = token_ret / btc_ret
        else:
            strength = Decimal('2.0') - abs(token_ret / btc_ret)
        period_strengths.append(min(max(strength, Decimal('0')), Decimal('2')))
    
    # Calculate EMA
    alpha = Decimal('2') / Decimal(str(12 + 1))
    ema = sum(period_strengths) / Decimal(str(len(period_strengths)))
    
    for strength in period_strengths:
        ema = (strength * alpha) + (ema * (Decimal('1') - alpha))
    
    return float(ema)  # Convert back to float for final result

def calculate_category_strength(conn, category, tokens, price_timestamp, price_cache):
    """Calculate strength for a category using specified tokens"""
    btc_prices = price_cache.get("BTC_1")
    if not btc_prices:
        print(f"ERROR: No Bitcoin prices in cache! Cannot calculate strengths.")
        logger.error(f"No Bitcoin prices in cache! Cannot calculate strengths.")
        return None, []
    
    # Calculate strength for each token
    token_strengths = []
    valid_tokens = []
    failed_tokens = []
    
    for token in tokens:
        column_name = f"{token['symbol']}_{token['cmc_id']}"
        prices = price_cache.get(column_name)
        
        if prices:
            strength = calculate_strength(prices, btc_prices)
            if strength is not None:
                token_strengths.append(strength)
                valid_tokens.append(token)
            else:
                failed_tokens.append(token['symbol'])
        else:
            failed_tokens.append(token['symbol'])
    
    if not token_strengths:
        print(f"No valid strength calculations for category: {category}")
        logger.warning(f"No valid strength calculations for category: {category}")
        if failed_tokens:
            print(f"Failed tokens: {', '.join(failed_tokens)}")
            logger.warning(f"Failed tokens: {', '.join(failed_tokens)}")
        return None, []
        
    avg_strength = sum(token_strengths) / len(token_strengths)
    print(f"Category {category}: Calculated strength {avg_strength:.4f} using {len(valid_tokens)} tokens")
    logger.info(f"Category {category}: Calculated strength {avg_strength:.4f} using {len(valid_tokens)} tokens")
    if failed_tokens:
        print(f"Failed tokens: {', '.join(failed_tokens)}")
        logger.warning(f"Failed tokens: {', '.join(failed_tokens)}")
    return avg_strength, valid_tokens

def get_categories_for_date(conn, date):
    """Get all categories for the given date"""
    print(f"\nFetching categories for date: {date}")
    logger.info(f"Fetching categories for date: {date}")
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT category 
        FROM public."DailyCategoryRanks"
        WHERE date = %s
    """, (date,))
    categories = [row[0] for row in cur.fetchall()]
    cur.close()
    print(f"Found {len(categories)} categories: {categories}")
    logger.info(f"Found {len(categories)} categories: {categories}")
    logger.debug(f"Categories: {categories}")
    return categories

def get_token_info(conn):
    """Get token information from Token List"""
    cur = conn.cursor()
    cur.execute("""
        SELECT symbol, cmc_id, name 
        FROM public."Token List"
    """)
    token_info = {f"{row[0]}_{row[1]}": {"symbol": row[0], "cmc_id": row[1], "name": row[2]} 
                  for row in cur.fetchall()}
    cur.close()
    logger.debug(f"Token info: {token_info}")
    return token_info

def get_category_tokens(conn, category, date, limit=None):
    """Get tokens for a category, optionally limited to top N by rank"""
    print(f"\nFetching {'top ' + str(limit) + ' ' if limit else ''}tokens for category: {category}")
    logger.info(f"Fetching {'top ' + str(limit) + ' ' if limit else ''}tokens for category: {category}")
    cur = conn.cursor()
    query = """
        SELECT t.symbol, t.cmc_id, t.name, d.rank
        FROM public."DailyCategoryRanks" d
        JOIN public."Token List" t ON d.token = t.symbol
        WHERE d.category = %s AND d.date = %s
        ORDER BY d.rank
    """
    if limit:
        query += f" LIMIT {limit}"
    
    cur.execute(query, (category, date))
    tokens = [{"symbol": row[0], "cmc_id": row[1], "name": row[2], "rank": row[3]} 
             for row in cur.fetchall()]
    cur.close()
    print(f"Found {len(tokens)} tokens")
    logger.info(f"Found {len(tokens)} tokens")
    logger.debug(f"Tokens: {tokens}")
    return tokens

def get_market_cap_tokens(conn, date, limit):
    """Get top N tokens by market cap"""
    print(f"\nFetching top {limit} tokens by market cap for date: {date}")
    logger.info(f"Fetching top {limit} tokens by market cap for date: {date}")
    cur = conn.cursor()
    cur.execute("""
        SELECT t.symbol, t.cmc_id, t.name
        FROM public."Token List" t
        JOIN public."DailyTokenRanks" d ON t.cmc_id = d.cmc_id
        WHERE d.date = %s
        ORDER BY d.market_cap_rank
        LIMIT %s
    """, (date, limit))
    tokens = [{"symbol": row[0], "cmc_id": row[1], "name": row[2]} 
             for row in cur.fetchall()]
    cur.close()
    print(f"Found {len(tokens)} tokens")
    logger.info(f"Found {len(tokens)} tokens")
    logger.debug(f"Tokens: {tokens}")
    return tokens

def store_category_strength(conn, strength_data):
    """Store all category strength results in a batch"""
    print("\nStoring all strength results...")
    logger.info("Storing all strength results...")
    cur = conn.cursor()
    
    # Prepare all the data for insertion
    values = []
    for timestamp, category, calc_type, strength, tokens in strength_data:
        token_info = json.dumps([{
            "symbol": t["symbol"],
            "name": t["name"],
            "cmc_id": t["cmc_id"]
        } for t in tokens])
        values.append((timestamp, category, calc_type, strength, token_info))
    
    # Batch insert all records
    cur.executemany("""
        INSERT INTO public."CategoryStrength" 
        ("TIMESTAMP", category, calculation_type, strength_ratio, token_info)
        VALUES (%s, %s, %s, %s, %s)
    """, values)
    
    conn.commit()
    cur.close()
    print(f"Successfully stored {len(values)} strength records")
    logger.info(f"Successfully stored {len(values)} strength records")
    logger.debug(f"Strength data: {strength_data}")

def process_category_calculations():
    """Main function to process all category strength calculations"""
    try:
        print("\n=== Starting Category Strength Calculations ===")
        logger.info("=== Starting Category Strength Calculations ===")
        print("Attempting database connection...")
        logger.info("Attempting database connection...")
        conn = get_db_connection()
        print("Database connection successful!")
        logger.info("Database connection successful!")
        
        calc_timestamp, price_timestamp = get_calculation_timestamp()
        current_date = calc_timestamp.date()
        print(f"\nCalculation timestamp: {calc_timestamp}")
        logger.info(f"Calculation timestamp: {calc_timestamp}")
        print(f"Price timestamp: {price_timestamp}")
        logger.info(f"Price timestamp: {price_timestamp}")
        print(f"Processing for date: {current_date}")
        logger.info(f"Processing for date: {current_date}")
        
        # Get all categories for current date
        categories = get_categories_for_date(conn, current_date)
        print(f"Found {len(categories)} categories to process")
        logger.info(f"Found {len(categories)} categories to process")
        
        # Cache all token prices
        price_cache = get_all_token_prices(conn, current_date, price_timestamp)
        
        # Different calculation methods
        category_methods = [
            ("top_5", 5),
            ("top_10", 10),
            ("top_15", 15),
            ("top_20", 20)
        ]
        
        market_cap_methods = [
            ("top_100_mc", 100),
            ("top_200_mc", 200)
        ]
        
        # Collect all strength calculations and failures
        strength_data = []
        failed_calculations = []
        
        # Process each category
        for category in categories:
            print(f"\n=== Processing Category: {category} ===")
            logger.info(f"=== Processing Category: {category} ===")
            
            # Category-based calculations
            for method_name, limit in category_methods:
                print(f"Method: {method_name}")
                logger.info(f"Method: {method_name}")
                tokens = get_category_tokens(conn, category, current_date, limit)
                if tokens:
                    strength, valid_tokens = calculate_category_strength(conn, category, tokens, price_timestamp, price_cache)
                    if strength is not None:
                        strength_data.append((calc_timestamp, category, method_name, strength, valid_tokens))
                    else:
                        failure_reason = f"Failed to calculate strength (insufficient valid prices) for {len(tokens)} tokens"
                        failed_calculations.append((calc_timestamp, category, method_name, failure_reason))
                        strength_data.append((calc_timestamp, category, method_name, None, []))
                else:
                    failure_reason = f"No tokens found for limit {limit}"
                    failed_calculations.append((calc_timestamp, category, method_name, failure_reason))
                    strength_data.append((calc_timestamp, category, method_name, None, []))
            
            # Market cap-based calculations
            for method_name, limit in market_cap_methods:
                print(f"Method: {method_name}")
                logger.info(f"Method: {method_name}")
                mc_tokens = get_market_cap_tokens(conn, current_date, limit)
                category_tokens = get_category_tokens(conn, category, current_date)
                category_symbols = {t["symbol"] for t in category_tokens}
                filtered_tokens = [t for t in mc_tokens if t["symbol"] in category_symbols]
                
                if filtered_tokens:
                    strength, valid_tokens = calculate_category_strength(conn, category, filtered_tokens, price_timestamp, price_cache)
                    if strength is not None:
                        strength_data.append((calc_timestamp, category, method_name, strength, valid_tokens))
                    else:
                        failure_reason = f"Failed to calculate strength (insufficient valid prices) for {len(filtered_tokens)} tokens"
                        failed_calculations.append((calc_timestamp, category, method_name, failure_reason))
                        strength_data.append((calc_timestamp, category, method_name, None, []))
                else:
                    failure_reason = f"No tokens found in top {limit} by market cap"
                    failed_calculations.append((calc_timestamp, category, method_name, failure_reason))
                    strength_data.append((calc_timestamp, category, method_name, None, []))
        
        # Store all results at once
        store_category_strength(conn, strength_data)
        
        # Print failure summary
        if failed_calculations:
            print("\n=== Failed Calculations Summary ===")
            logger.warning("=== Failed Calculations Summary ===")
            for timestamp, category, method, reason in failed_calculations:
                print(f"FAILED: {category} - {method} at {timestamp}")
                logger.warning(f"FAILED: {category} - {method} at {timestamp}")
                print(f"Reason: {reason}")
                logger.warning(f"Reason: {reason}")
        
        conn.close()
        print("\n=== Category Strength Calculations Completed Successfully ===")
        logger.info("=== Category Strength Calculations Completed Successfully ===")
        print(f"Total records stored: {len(strength_data)}")
        logger.info(f"Total records stored: {len(strength_data)}")
        print(f"Failed calculations: {len(failed_calculations)}")
        logger.info(f"Failed calculations: {len(failed_calculations)}")
        
    except Exception as e:
        print(f"\nError processing category strengths: {str(e)}")
        logger.error(f"Error processing category strengths: {str(e)}")
        raise

def job_listener(event):
    """Listen for job events and update next run time"""
    if event.code == EVENT_JOB_EXECUTED:
        next_run = scheduler.get_jobs()[0].next_run_time
        print(f"\nNext calculation at: {next_run.strftime('%m/%d/%Y %H:%M:%S%z')}")
        logger.info(f"Next calculation at: {next_run.strftime('%m/%d/%Y %H:%M:%S%z')}")

def main():
    """Main function that runs continuously using APScheduler"""
    global scheduler
    
    print("\n=== Starting Crypto Strength Calculator ===")
    logger.info("=== Starting Crypto Strength Calculator ===")
    print("Will calculate at: XX:05, XX:15, XX:25, XX:35, XX:45, XX:55")
    logger.info("Will calculate at: XX:05, XX:15, XX:25, XX:35, XX:45, XX:55")
    print("Using price data from previous 10-minute mark")
    logger.info("Using price data from previous 10-minute mark")
    print("Storing results as of previous 10-minute mark")
    logger.info("Storing results as of previous 10-minute mark")
    print("Press Ctrl+C to stop")
    logger.info("Press Ctrl+C to stop")
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create scheduler
    scheduler = BackgroundScheduler(timezone=SGT)
    
    # Add job listener to update next run time
    scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
    
    # Schedule the job to run at 5,15,25,35,45,55 minutes of every hour
    scheduler.add_job(
        process_category_calculations,
        CronTrigger(minute='5,15,25,35,45,55'),
        name='category_strength_calculator',
        max_instances=1  # Ensure only one instance runs at a time
    )
    
    # Start the scheduler
    scheduler.start()
    
    # Get next run time
    next_run = scheduler.get_jobs()[0].next_run_time
    print(f"\nWaiting until {next_run.strftime('%m/%d/%Y %H:%M:%S%z')}")
    logger.info(f"Waiting until {next_run.strftime('%m/%d/%Y %H:%M:%S%z')}")
    
    try:
        # Keep the main thread alive with a more responsive sleep
        while True:
            time.sleep(0.1)  # Sleep for 100ms instead of 1s for better responsiveness
    except (KeyboardInterrupt, SystemExit):
        print("\nShutting down gracefully...")
        logger.info("Shutting down gracefully...")
        scheduler.shutdown(wait=False)
    except Exception as e:
        print(f"\nFatal error: {str(e)}")
        logger.error(f"Fatal error: {str(e)}")
        scheduler.shutdown(wait=False)
        raise

if __name__ == "__main__":
    main()
