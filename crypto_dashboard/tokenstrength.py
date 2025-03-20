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
logger = logging.getLogger("token_strength_calculator")
logger.setLevel(logging.INFO)

# Papertrail handler
handler = logging.handlers.SysLogHandler(
    address=('logs6.papertrailapp.com', 48110)
)
formatter = logging.Formatter(
    '%(asctime)s tokenstrength.py: %(message)s',
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

def get_all_tokens(conn):
    """Get all tokens from Token List except Bitcoin (cmc_id=1)"""
    print("\nFetching all tokens from Token List...")
    logger.info("Fetching all tokens from Token List...")
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT cmc_id, symbol, name 
            FROM public."Token List"
            WHERE cmc_id != 1
            ORDER BY cmc_id
        """)
        tokens = cur.fetchall()
        print(f"Found {len(tokens)} tokens to process")
        logger.info(f"Found {len(tokens)} tokens to process")
        return tokens
    except Exception as e:
        print(f"Error fetching tokens: {e}")
        logger.error(f"Error fetching tokens: {e}")
        raise
    finally:
        cur.close()

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

def store_token_strengths(conn, strength_data):
    """Store token strength results in the tokenstrength table"""
    if not strength_data:
        print("No strength data to store")
        logger.warning("No strength data to store")
        return
        
    print("\nStoring token strength results...")
    logger.info("Storing token strength results...")
    cur = conn.cursor()
    
    try:
        # Prepare data for batch insert
        values = [
            (data['timestamp'], data['cmc_id'], data['symbol'], data['name'], data['strength'])
            for data in strength_data
        ]
        
        # Batch insert using execute_values
        execute_values(
            cur,
            'INSERT INTO tokenstrength (timestamp, cmc_id, symbol, name, strength) VALUES %s',
            values
        )
        
        conn.commit()
        print(f"Successfully stored {len(values)} token strength records")
        logger.info(f"Successfully stored {len(values)} token strength records")
        logger.debug(f"Strength data: {strength_data}")
        
    except Exception as e:
        conn.rollback()
        print(f"Error storing token strengths: {e}")
        logger.error(f"Error storing token strengths: {e}")
        raise
    finally:
        cur.close()

def process_token_strength_calculations():
    """Main function to process all token strength calculations"""
    print("\n=== Starting Token Strength Calculations ===")
    logger.info("=== Starting Token Strength Calculations ===")
    
    try:
        # Get database connection
        print("Attempting database connection...")
        logger.info("Attempting database connection...")
        conn = get_db_connection()
        print("Database connection successful!")
        logger.info("Database connection successful!")
        
        # Get calculation timestamps
        calc_timestamp, price_timestamp = get_calculation_timestamp()
        current_date = calc_timestamp.date()
        print(f"\nCalculation timestamp: {calc_timestamp}")
        logger.info(f"Calculation timestamp: {calc_timestamp}")
        print(f"Price timestamp: {price_timestamp}")
        logger.info(f"Price timestamp: {price_timestamp}")
        print(f"Processing for date: {current_date}")
        logger.info(f"Processing for date: {current_date}")
        
        # Get Bitcoin prices (reference)
        btc_prices = get_token_prices(conn, "BTC_1", price_timestamp)
        if not btc_prices:
            print("ERROR: Failed to get Bitcoin prices!")
            logger.error("Failed to get Bitcoin prices!")
            return
            
        print("Successfully retrieved Bitcoin prices")
        logger.info("Successfully retrieved Bitcoin prices")
        
        # Get all tokens except Bitcoin
        tokens = get_all_tokens(conn)
        if not tokens:
            print("ERROR: No tokens found to process!")
            logger.error("No tokens found to process!")
            return
            
        print(f"Processing strength calculations for {len(tokens)} tokens")
        logger.info(f"Processing strength calculations for {len(tokens)} tokens")
        
        # Calculate strength for each token
        strength_data = []
        failed_tokens = []
        
        for cmc_id, symbol, name in tokens:
            try:
                column_name = f"{symbol}_{cmc_id}"
                token_prices = get_token_prices(conn, column_name, price_timestamp)
                
                if token_prices:
                    strength = calculate_strength(token_prices, btc_prices)
                    if strength is not None:
                        strength_data.append({
                            'timestamp': calc_timestamp,
                            'cmc_id': cmc_id,
                            'symbol': symbol,
                            'name': name,
                            'strength': strength
                        })
                    else:
                        failed_tokens.append((symbol, "Invalid strength calculation"))
                        # Store NULL for failed calculations
                        strength_data.append({
                            'timestamp': calc_timestamp,
                            'cmc_id': cmc_id,
                            'symbol': symbol,
                            'name': name,
                            'strength': None
                        })
                else:
                    failed_tokens.append((symbol, "Insufficient price data"))
                    # Store NULL for failed calculations
                    strength_data.append({
                        'timestamp': calc_timestamp,
                        'cmc_id': cmc_id,
                        'symbol': symbol,
                        'name': name,
                        'strength': None
                    })
            except Exception as e:
                failed_tokens.append((symbol, str(e)))
                print(f"Error processing token {symbol}: {e}")
                logger.error(f"Error processing token {symbol}: {e}")
                # Store NULL for failed calculations
                strength_data.append({
                    'timestamp': calc_timestamp,
                    'cmc_id': cmc_id,
                    'symbol': symbol,
                    'name': name,
                    'strength': None
                })
        
        # Store results
        if strength_data:
            store_token_strengths(conn, strength_data)
        
        # Print failure summary
        if failed_tokens:
            print("\n=== Failed Calculations Summary ===")
            logger.warning("=== Failed Calculations Summary ===")
            for symbol, reason in failed_tokens:
                print(f"FAILED: {symbol} - Reason: {reason}")
                logger.warning(f"FAILED: {symbol} - Reason: {reason}")
        
        print("\n=== Token Strength Calculations Completed Successfully ===")
        logger.info("=== Token Strength Calculations Completed Successfully ===")
        print(f"Total records stored: {len(strength_data)}")
        logger.info(f"Total records stored: {len(strength_data)}")
        print(f"Failed calculations: {len(failed_tokens)}")
        logger.info(f"Failed calculations: {len(failed_tokens)}")
        
    except Exception as e:
        print(f"\nError processing token strengths: {str(e)}")
        logger.error(f"Error processing token strengths: {str(e)}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()

def job_listener(event):
    """Listen for job events and update next run time"""
    if event.code == EVENT_JOB_EXECUTED:
        next_run = scheduler.get_jobs()[0].next_run_time
        print(f"\nNext calculation at: {next_run.strftime('%m/%d/%Y %H:%M:%S%z')}")
        logger.info(f"Next calculation at: {next_run.strftime('%m/%d/%Y %H:%M:%S%z')}")

def main():
    """Main function that runs continuously using APScheduler"""
    global scheduler
    
    print("\n=== Starting Token Strength Calculator ===")
    logger.info("=== Starting Token Strength Calculator ===")
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
        process_token_strength_calculations,
        CronTrigger(minute='5,15,25,35,45,55'),
        name='token_strength_calculator',
        max_instances=1  # Ensure only one instance runs at a time
    )
    
    # Start the scheduler
    scheduler.start()
    
    # Run initial calculation
    process_token_strength_calculations()
    
    # Keep the main thread alive
    while True:
        time.sleep(60)

if __name__ == "__main__":
    main()