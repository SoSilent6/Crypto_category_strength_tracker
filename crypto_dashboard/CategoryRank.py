import os
from dotenv import load_dotenv
import psycopg2
from datetime import datetime, timedelta
import pytz
import time
import traceback
import logging
import logging.handlers
from psycopg2.extras import execute_values

# Load environment variables
load_dotenv()

# Set Singapore timezone
SGT = pytz.timezone('Asia/Singapore')

# Set up Papertrail logging
logger = logging.getLogger("categoryrank")
logger.setLevel(logging.INFO)

handler = logging.handlers.SysLogHandler(
    address=('logs6.papertrailapp.com', 48110)
)
formatter = logging.Formatter(
    '%(asctime)s CategoryRank.py: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
handler.setFormatter(formatter)
logger.addHandler(handler)

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
        error_msg = f"Database connection failed: {e}"
        print(error_msg)
        logger.error(error_msg)
        raise

def check_current_token_rank_status(current_date):
    """Check if currenttokenrankstatus table has an entry for today"""
    print(f"\nChecking current token rank status for {current_date}...")
    logger.info(f"Checking current token rank status for {current_date}...")
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM public."currenttokenrankstatus"
            WHERE date = %s
        """, (current_date,))
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        if count > 0:
            print(f"✓ Found current token rank status for {current_date}")
            logger.info(f"Found current token rank status for {current_date}")
            return True
        else:
            print(f"! No current token rank status found for {current_date}")
            logger.info(f"No current token rank status found for {current_date}")
            return False
    except Exception as e:
        print(f"Error checking current token rank status: {e}")
        logger.error(f"Error checking current token rank status: {e}")
        return False

def check_category_ranks(current_date):
    """Check if DailyCategoryRanks already has entries for today"""
    print(f"\nChecking if category rankings exist for {current_date}...")
    logger.info(f"Checking if category rankings exist for {current_date}...")
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT COUNT(*) FROM public."DailyCategoryRanks"
            WHERE date = %s
        """, (current_date,))
        
        count = cur.fetchone()[0]
        
        cur.close()
        conn.close()
        
        if count > 0:
            print(f"✓ Found existing category rankings for {current_date}")
            logger.info(f"Found existing category rankings for {current_date}")
        else:
            print(f"! No category rankings found for {current_date}")
            logger.info(f"No category rankings found for {current_date}")
        
        return count > 0
        
    except Exception as e:
        print(f"Error checking category ranks: {e}")
        logger.error(f"Error checking category ranks: {e}")
        return False

def process_categories():
    """Process all categories and update DailyCategoryRanks"""
    try:
        print("\n=== Starting Category Rankings Process ===")
        logger.info("=== Starting Category Rankings Process ===")
        
        current_time = datetime.now(SGT)
        current_date = current_time.date()
        
        print(f"Processing for date: {current_date}")
        logger.info(f"Processing for date: {current_date}")
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Get all unique categories from Token List
        print("\nGetting unique categories...")
        logger.info("Getting unique categories...")
        cur.execute("""
            SELECT DISTINCT unnest(category) as category
            FROM public."Token List"
            WHERE category IS NOT NULL
            ORDER BY category
        """)
        
        categories = [row[0] for row in cur.fetchall()]
        print(f"Found {len(categories)} unique categories")
        logger.info(f"Found {len(categories)} unique categories")
        
        # Collect all values across categories
        all_values = []
        
        # Process each category
        for category in categories:
            print(f"\nProcessing category: {category}")
            logger.info(f"Processing category: {category}")
            
            # Get tokens in this category and their ranks
            cur.execute("""
                SELECT t.symbol, d.market_cap_rank
                FROM public."Token List" t
                JOIN public."DailyTokenRanks" d ON t.cmc_id = d.cmc_id
                WHERE %s = ANY(t.category)
                AND d.date = %s
                ORDER BY d.market_cap_rank
            """, (category, current_date))
            
            tokens = cur.fetchall()
            print(f"Found {len(tokens)} tokens in {category}")
            logger.info(f"Found {len(tokens)} tokens in {category}")
            
            # Add to all_values instead of inserting
            all_values.extend([
                (current_date, category, token[0], token[1])
                for token in tokens
            ])
        
        # Single batch insert for all categories
        print(f"\nInserting {len(all_values)} total entries...")
        logger.info(f"Inserting {len(all_values)} total entries...")
        
        execute_values(
            cur,
            """
            INSERT INTO public."DailyCategoryRanks"
            (date, category, token, rank)
            VALUES %s
            """,
            all_values,
            page_size=1000
        )
        
        conn.commit()
        print(f"Successfully inserted {len(all_values)} entries")
        logger.info(f"Successfully inserted {len(all_values)} entries")
        print("\nAll categories processed successfully")
        logger.info("All categories processed successfully")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"Error processing categories: {e}")
        logger.error(f"Error processing categories: {e}")
        traceback.print_exc()
        if 'conn' in locals():
            conn.rollback()
            conn.close()

def main():
    print("=== Category Rank Monitor Started ===")
    logger.info("=== Category Rank Monitor Started ===")
    
    while True:
        try:
            current_time = datetime.now(SGT)
            current_date = current_time.date()
            
            # First check if we already have category ranks for today
            if check_category_ranks(current_date):
                # Calculate time until next day
                next_day = (current_time + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                wait_seconds = (next_day - current_time).total_seconds()
                
                print(f"Waiting until next day ({wait_seconds/3600:.1f} hours)")
                logger.info(f"Waiting until next day ({wait_seconds/3600:.1f} hours)")
                time.sleep(wait_seconds)
                continue
            
            # Check the currenttokenrankstatus table for today's date
            if check_current_token_rank_status(current_date):
                # Process categories using the top 2000 ranks from DailyTokenRanks
                process_categories()
                
                # Wait until next day
                next_day = (current_time + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                wait_seconds = (next_day - current_time).total_seconds()
                
                print(f"Waiting until next day ({wait_seconds/3600:.1f} hours)")
                logger.info(f"Waiting until next day ({wait_seconds/3600:.1f} hours)")
                time.sleep(wait_seconds)
            else:
                # Check again in 1 second
                time.sleep(1)
            
        except Exception as e:
            print(f"Error in main loop: {e}")
            logger.error(f"Error in main loop: {e}")
            time.sleep(60)  # Wait 1 minute before retry

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped by user")
        logger.info("Stopped by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        logger.error(f"Fatal error: {e}")
