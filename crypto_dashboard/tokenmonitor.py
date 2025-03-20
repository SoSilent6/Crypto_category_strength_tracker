import os
from dotenv import load_dotenv
import asyncio
from telegram import Bot
import psycopg2
import pytz
from datetime import datetime, timedelta
import time
import requests
import matplotlib.pyplot as plt
import pandas as pd
from io import BytesIO
from matplotlib import patheffects as path_effects
import traceback

# Debug environment loading
print("Current working directory:", os.getcwd())
print("Files in directory:", os.listdir())

# Search for all .env files
def find_env_files(start_path):
    env_files = []
    for root, dirs, files in os.walk(start_path):
        if '.env' in files:
            env_path = os.path.join(root, '.env')
            env_files.append(env_path)
            print(f"\nFound .env file at: {env_path}")
            try:
                with open(env_path, 'r') as f:
                    content = f.read()
                print(f"Contents of {env_path}:")
                print(content)
            except Exception as e:
                print(f"Error reading file: {e}")
    return env_files

print("\nSearching for all .env files...")
all_env_files = find_env_files(os.getcwd())
print(f"\nFound {len(all_env_files)} .env files")

# Simple environment loading
print("Loading environment variables...")
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CMC_API_KEY = os.getenv('CMC_API_KEY')

# Add debug prints
print(f"Telegram Token loaded: {'Yes' if TELEGRAM_BOT_TOKEN else 'No'}")
print(f"CMC API Key loaded: {'Yes' if CMC_API_KEY else 'No'}")
if CMC_API_KEY:
    print(f"CMC API Key: {CMC_API_KEY[:8]}...")  # Only show first 8 chars for security

if not TELEGRAM_BOT_TOKEN:
    # Fallback to direct reading
    try:
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('TELEGRAM_BOT_TOKEN='):
                    TELEGRAM_BOT_TOKEN = line.split('=')[1].strip()
                    print(f"Token loaded from direct file read")
                    break
    except Exception as e:
        print(f"Error reading .env file directly: {e}")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Could not load TELEGRAM_BOT_TOKEN from .env file")

TELEGRAM_CHAT_ID = 7430984105

async def send_telegram_message(message: str):
    """Send message via Telegram bot"""
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='HTML')
        print(f"Message sent to Telegram successfully")
    except Exception as e:
        print(f"Error sending Telegram message: {e}")

def send_telegram_alert(message: str):
    """Helper function to run telegram send in async"""
    asyncio.run(send_telegram_message(message))

def get_db_connection():
    print("Attempting database connection...")
    try:
        conn = psycopg2.connect(
            "postgresql://crypto_database_465t_user:3Pn5YjUINXQWRTkMPx3OjiZCETYTlsSc@dpg-cuk9r98gph6c73bouo90-a.singapore-postgres.render.com/crypto_database_465t"
        )
        print("Database connection successful!")
        return conn
    except Exception as e:
        print(f"Database connection failed: {e}")
        raise

def get_token_data(cur, timestamp):
    """Get token data for a specific timestamp"""
    cur.execute("""
        SELECT market_cap_rank, symbol, market_cap, cmc_id 
        FROM public."Token Filter" 
        WHERE timestamp = %s 
        ORDER BY market_cap_rank
    """, (timestamp,))
    return {row[3]: {  # Using cmc_id as the key instead of symbol
        'rank': row[0],
        'symbol': row[1],  # Include symbol in the data
        'market_cap': row[2],
        'cmc_id': row[3]
    } for row in cur.fetchall()}

def fetch_historical_data(cmc_id, symbol):
    """Fetch historical price data from CMC with retry logic"""
    print(f"\n=== Fetching historical data for {symbol} (ID: {cmc_id}) ===")
    
    headers = {
        'X-CMC_PRO_API_KEY': CMC_API_KEY.strip(),
        'Accept': 'application/json'
    }
    
    def make_request_with_retry(url, params, max_retries=3, delay=5):
        """Helper function to make requests with retry logic"""
        for attempt in range(max_retries):
            try:
                print(f"Request attempt {attempt + 1}/{max_retries}")
                response = requests.get(url, headers=headers, params=params)
                
                # Print response details for debugging
                print(f"Response status code: {response.status_code}")
                response_json = response.json()
                if 'status' in response_json:
                    print(f"API Status: {response_json['status']}")
                
                response.raise_for_status()
                return response_json
            except requests.exceptions.RequestException as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    print(f"Waiting {delay} seconds before retrying...")
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
                else:
                    print("Max retries reached. Request failed.")
                    raise
    
    try:
        # Fetch current price first
        print("\nFetching current price...")
        current_price_url = 'https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest'
        current_price_params = {
            'id': cmc_id,
            'convert': 'USD'
        }
        
        current_price_data = make_request_with_retry(current_price_url, current_price_params)
        
        current_price = None
        current_timestamp = None
        if 'data' in current_price_data:
            current_price = current_price_data['data'][str(cmc_id)]['quote']['USD']['price']
            current_timestamp = current_price_data['data'][str(cmc_id)]['quote']['USD']['last_updated']
            print(f"Current price: ${current_price:.4f}")
        
        # Fetch 5-minute historical data
        print("\nFetching 5-minute data (last 72 intervals)...")
        five_min_params = {
            'id': cmc_id,
            'interval': '5m',
            'convert': 'USD',
            'count': 72
        }
        
        five_min_data = make_request_with_retry(
            'https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/historical',
            five_min_params
        )
        
        # Fetch 4-hour historical data
        print("\nFetching 4-hour data (last 100 intervals)...")
        four_hour_params = {
            'id': cmc_id,
            'interval': '4h',
            'convert': 'USD',
            'count': 100  # Changed to 100 intervals
        }
        
        four_hour_data = make_request_with_retry(
            'https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/historical',
            four_hour_params
        )
        
        # Add current price to the response data
        if current_price and current_timestamp:
            current_quote = {
                'timestamp': current_timestamp,
                'quote': {
                    'USD': {
                        'price': current_price
                    }
                }
            }
            
            if 'data' in five_min_data and 'quotes' in five_min_data['data']:
                five_min_data['data']['quotes'].append(current_quote)
            
            if 'data' in four_hour_data and 'quotes' in four_hour_data['data']:
                four_hour_data['data']['quotes'].append(current_quote)
        
        return {
            'five_min_data': five_min_data,
            'four_hour_data': four_hour_data
        }
        
    except Exception as e:
        print(f"Error fetching CMC data: {e}")
        traceback.print_exc()
        return None

def calculate_percentage_change(old_value, new_value):
    """Calculate percentage change between two values"""
    return ((new_value - old_value) / old_value) * 100

def format_market_cap_message(symbol, old_mcap, new_mcap, start_time, end_time, cmc_id):
    """Format a consistent market cap change message"""
    pct_change = calculate_percentage_change(old_mcap, new_mcap)
    time_diff = int((end_time - start_time).total_seconds() / 60)  # Convert to minutes
    
    direction = "up" if pct_change >= 0 else "down"
    color = "🟢" if pct_change >= 0 else "🔴"  # Green/red circle emoji
    
    # Format the colored percentage part
    colored_text = (
        f"{color} <b>{direction} by {abs(pct_change):.1f}%</b>"
    )
    
    return (
        f"Marketcap of {symbol} {colored_text} "
        f"from ${old_mcap:,.2f} to ${new_mcap:,.2f} "
        f"in the last {time_diff} minutes\n\n"
        f"CMC ID: {cmc_id}\n"
        f"Token Name: {symbol}"
    )

def check_rank_increases(current_data, historical_data, timestamps):
    findings = []
    current_timestamp = timestamps[0]
    token_changes = {}
    rank_only_changes = 0
    
    print("\n=== Checking Rank Increases ===")
    print(f"Current timestamp: {current_timestamp}")
    
    intervals_to_check = [
        (1, 50),   # 1 interval (10 mins): 50 rank improvement
        (3, 100),  # 3 intervals (30 mins): 100 rank improvement
        (6, 150)   # 6 intervals (60 mins): 150 rank improvement
    ]
    
    total_tokens = len([t for t in historical_data[0].values() if t['rank'] <= 1000])
    tokens_checked = 0
    
    # Clear the line before starting
    print(f"Checking {total_tokens} tokens...", end='\r', flush=True)
    
    for cmc_id, current in historical_data[0].items():
        if current['rank'] <= 1000:
            tokens_checked += 1
            print(f"Checking token {tokens_checked}/{total_tokens}...", end='\r', flush=True)
            
            found_significant_change = False
            met_rank_criteria = False
            
            if cmc_id not in token_changes:
                token_changes[cmc_id] = []
            
            for num_intervals, required_rank_change in intervals_to_check:
                if (len(historical_data) > num_intervals and 
                    cmc_id in historical_data[num_intervals]):
                    
                    historical = historical_data[num_intervals][cmc_id]
                    rank_change = historical['rank'] - current['rank']
                    
                    if rank_change >= required_rank_change:
                        met_rank_criteria = True
                        pct_change = calculate_percentage_change(
                            historical['market_cap'],
                            current['market_cap']
                        )
                        
                        if pct_change >= 10:
                            found_significant_change = True
                            time_diff = num_intervals * 10
                            
                            token_changes[cmc_id].append({
                                'symbol': current['symbol'],
                                'time_diff': time_diff,
                                'historical': historical,
                                'current': current,
                                'timestamp': timestamps[num_intervals],
                                'pct_change': pct_change,
                                'cmc_id': cmc_id,
                                'interval_start': timestamps[num_intervals],  # Store start of interval
                                'interval_end': current_timestamp  # Store end of interval
                            })
            
            if met_rank_criteria and not found_significant_change:
                rank_only_changes += 1
            
            if found_significant_change:
                print(" " * 50, end='\r')  # Clear the line
                print(f"\nFound significant change: {current['symbol']}")
                print(f"Current Rank: {current['rank']}")
                print(f"Current Market Cap: ${current['market_cap']:,.2f}")
    
    # Clean up token_changes to only keep tokens that actually had changes
    token_changes = {cmc_id: changes for cmc_id, changes in token_changes.items() if changes}
    
    print(" " * 50, end='\r')  # Clear the line
    print(f"\nChecked {total_tokens} tokens.")
    
    if token_changes or rank_only_changes > 0:
        print("Results:")
        print(f"- {rank_only_changes} tokens met rank criteria but not 10% market cap increase")
        print(f"- {len(token_changes)} tokens met both criteria and will be alerted")
    else:
        print("No significant changes found.")
    
    # Only return tokens that actually had changes
    findings = []
    for cmc_id, changes in token_changes.items():
        if changes:  # Only if we have actual changes
            findings.append(changes[0])  # Use the first change, which is the shortest interval
    
    return findings

def add_to_token_list(cur, conn, token_data):
    """Add a token to the Token List table and fetch charts if new"""
    try:
        # Check if token already exists by CMC ID or symbol
        cur.execute("""
            SELECT cmc_id, symbol FROM public."Token List"
            WHERE cmc_id = %s OR symbol = %s
        """, (token_data['cmc_id'], token_data['symbol']))
        
        existing_token = cur.fetchone()
        
        if existing_token:
            if existing_token[0] == token_data['cmc_id']:
                print(f"Token with CMC ID {token_data['cmc_id']} already exists")
            else:
                print(f"Token with symbol {token_data['symbol']} already exists (different CMC ID)")
            return
            
        # If we get here, token is new and symbol is unique
        cur.execute("""
            INSERT INTO public."Token List" (cmc_id, symbol)
            VALUES (%s, %s)
        """, (token_data['cmc_id'], token_data['symbol']))
        
        conn.commit()
        
        # Get historical data for market cap message
        cur.execute("""
            SELECT market_cap, timestamp 
            FROM public."Token Filter"
            WHERE cmc_id = %s
            ORDER BY timestamp DESC
            LIMIT 2
        """, (token_data['cmc_id'],))
        
        rows = cur.fetchall()
        if len(rows) >= 2:
            new_mcap, new_time = rows[0]
            old_mcap, old_time = rows[1]
            
            message = (
                f"{token_data['symbol']} has been added to your database.\n\n"
                + format_market_cap_message(
                    token_data['symbol'],
                    old_mcap,
                    new_mcap,
                    old_time,
                    new_time,
                    token_data['cmc_id']
                )
            )
            send_telegram_alert(message)
        
        # Fetch and send charts
        price_data = fetch_historical_data(token_data['cmc_id'], token_data['symbol'])
        if price_data:
            five_min_img, four_hour_img = create_price_charts(price_data, token_data['symbol'])
            if five_min_img or four_hour_img:
                send_telegram_charts_sync(five_min_img, four_hour_img, token_data['symbol'])
        
    except Exception as e:
        print(f"Error adding token to Token List: {e}")
        traceback.print_exc()

def check_sudden_appearance(current_data, historical_data, timestamps, conn):
    cur = conn.cursor()
    current_top_700 = {cmc_id: data for cmc_id, data in current_data.items() 
                      if data['rank'] <= 700}
    
    for cmc_id, data in current_top_700.items():
        sudden_appearance = True
        for prev_data in historical_data[1:7]:
            if cmc_id in prev_data and prev_data[cmc_id]['rank'] <= 1000:
                sudden_appearance = False
                break
                
        if sudden_appearance:
            try:
                # Temporarily disable adding tokens
                # cur.execute("""
                #     INSERT INTO public."Token List" (cmc_id, symbol)
                #     VALUES (%s, %s)
                #     ON CONFLICT DO NOTHING
                # """, (cmc_id, data['symbol']))
                # conn.commit()
                
                message = (
                    f"🚀 <b>SUDDEN APPEARANCE DETECTED</b>\n\n"
                    f"Token: {data['symbol']}\n"
                    f"Current Rank: #{data['rank']}\n"
                    f"Market Cap: ${data['market_cap']:,.2f}\n"
                    f"Timeframe: {timestamps[6]} -> {timestamps[0]}"
                )
                send_telegram_alert(message)
                print(f"\n{message}")
                
            except Exception as e:
                print(f"Error adding sudden appearance token to Token List: {e}")
            finally:
                cur.close()

def create_price_charts(historical_data, symbol):
    print("Creating charts...")
    try:
        # Set style and font
        plt.style.use('dark_background')
        plt.rcParams.update({
            'font.family': 'Segoe UI',
            'font.size': 14,
            'axes.titlesize': 20,
            'axes.labelsize': 18,
            'xtick.labelsize': 14,
            'ytick.labelsize': 14,
            'axes.linewidth': 2,
            'axes.grid': True,
            'grid.alpha': 0.2
        })
        
        five_min_img = None
        four_hour_img = None
        
        if 'five_min_data' in historical_data:
            five_min_data = historical_data['five_min_data']
            
            if 'data' in five_min_data and 'quotes' in five_min_data['data']:
                quotes = five_min_data['data']['quotes']
                
                if quotes:
                    try:
                        five_min_df = pd.DataFrame([{
                            'timestamp': quote['timestamp'],
                            'price': quote['quote']['USD']['price']
                        } for quote in quotes])
                        five_min_df['timestamp'] = pd.to_datetime(five_min_df['timestamp'])
                        
                        five_min_fig, ax1 = plt.subplots(figsize=(12, 7))
                        ax1.plot(five_min_df['timestamp'], five_min_df['price'], 
                                color='#00a8ff', linewidth=3)
                        ax1.grid(True, alpha=0.2, linewidth=1.2)
                        ax1.set_facecolor('#1a1a1a')
                        five_min_fig.patch.set_facecolor('#1a1a1a')
                        ax1.xaxis.set_major_locator(plt.LinearLocator(8))
                        ax1.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter('%H:%M'))
                        ax1.set_title(f'{symbol} Price\nLast 6 Hours (5m Intervals)', pad=20)
                        ax1.set_xlabel('Time', labelpad=15)
                        ax1.set_ylabel('Price (USD)', labelpad=15)
                        plt.xticks(rotation=45, ha='right')
                        five_min_fig.tight_layout(pad=2.0)
                        
                        five_min_img = BytesIO()
                        five_min_fig.savefig(five_min_img, format='png', bbox_inches='tight')
                        five_min_img.seek(0)
                        
                    except Exception as e:
                        print(f"Error in 5-minute chart creation: {e}")
        
        if 'four_hour_data' in historical_data:
            four_hour_data = historical_data['four_hour_data']
            
            if 'data' in four_hour_data and 'quotes' in four_hour_data['data']:
                quotes = four_hour_data['data']['quotes']
                
                if quotes:
                    try:
                        four_hour_df = pd.DataFrame([{
                            'timestamp': quote['timestamp'],
                            'price': quote['quote']['USD']['price']
                        } for quote in quotes])
                        four_hour_df['timestamp'] = pd.to_datetime(four_hour_df['timestamp'])
                        
                        four_hour_fig, ax2 = plt.subplots(figsize=(12, 7))
                        ax2.plot(four_hour_df['timestamp'], four_hour_df['price'], 
                                color='#00a8ff', linewidth=3)
                        ax2.grid(True, alpha=0.2, linewidth=1.2)
                        ax2.set_facecolor('#1a1a1a')
                        four_hour_fig.patch.set_facecolor('#1a1a1a')
                        ax2.xaxis.set_major_locator(plt.LinearLocator(8))
                        ax2.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter('%Y-%m-%d'))
                        ax2.set_title(f'{symbol} Price\nHistorical Chart', pad=20)
                        ax2.set_xlabel('Date', labelpad=15)
                        ax2.set_ylabel('Price (USD)', labelpad=15)
                        plt.xticks(rotation=45, ha='right')
                        four_hour_fig.tight_layout(pad=2.0)
                        
                        four_hour_img = BytesIO()
                        four_hour_fig.savefig(four_hour_img, format='png', bbox_inches='tight')
                        four_hour_img.seek(0)
                        
                    except Exception as e:
                        print(f"Error in 4-hour chart creation: {e}")
        
        return five_min_img, four_hour_img
    except Exception as e:
        print("✕ Failed")
        return None, None

def send_telegram_charts_sync(five_min_img, four_hour_img, symbol):
    print("Sending charts...")
    try:
        asyncio.run(send_telegram_charts(five_min_img, four_hour_img, symbol))
        print("✓ Done")
    except Exception as e:
        print("✕ Failed")

async def send_telegram_charts(five_min_img, four_hour_img, symbol):
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        if five_min_img:
            await bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=five_min_img)
        if four_hour_img:
            await bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=four_hour_img)
    except Exception as e:
        print("✕ Failed to send charts")

def process_token_messages(token_data, cur, conn, timestamps, historical_data):
    try:
        print(f"Processing {token_data['symbol']}")
        # First check if token exists
        # cur.execute("""
        #     SELECT cmc_id FROM public."Token List"
        #     WHERE cmc_id = %s
        # """, (token_data['cmc_id'],))
        
        # token_exists = cur.fetchone() is not None
        
        # Prepare message
        # if not token_exists:
        #     # Add new token
        #     cur.execute("""
        #         INSERT INTO public."Token List" (cmc_id, symbol)
        #         VALUES (%s, %s)
        #     """, (token_data['cmc_id'], token_data['symbol']))
        #     conn.commit()
            
        message = (
            f"{token_data['symbol']} has been added to your database.\n\n"
            + format_market_cap_message(
                token_data['symbol'],
                token_data['historical']['market_cap'],
                token_data['current']['market_cap'],
                token_data['interval_start'],
                token_data['interval_end'],
                token_data['cmc_id']
            )
        )
        
        # 1. Send alert message
        send_telegram_alert(message)
        
        # 2. Immediately fetch and send charts
        price_data = fetch_historical_data(token_data['cmc_id'], token_data['symbol'])
        if price_data:
            five_min_img, four_hour_img = create_price_charts(price_data, token_data['symbol'])
            if five_min_img and four_hour_img:
                send_telegram_charts_sync(five_min_img, four_hour_img, token_data['symbol'])
            
    except Exception as e:
        print("✕ Failed")

def process_test_token(cur, conn):
    try:
        print("Processing test token")
        cur.execute("""
            SELECT symbol FROM public."Token Filter"
            WHERE cmc_id = 35336
            ORDER BY timestamp DESC
            LIMIT 1
        """)
        token_symbol = cur.fetchone()[0]
        
        price_data = fetch_historical_data(35336, token_symbol)
        if price_data:
            five_min_img, four_hour_img = create_price_charts(price_data, token_symbol)
            if five_min_img and four_hour_img:
                send_telegram_charts_sync(five_min_img, four_hour_img, token_symbol)
    except Exception as e:
        print("✕ Failed")

def monitor_tokens():
    print("=== Monitor Started ===")
    
    # Get initial latest timestamp
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT timestamp FROM public.\"Token Filter\" ORDER BY timestamp DESC LIMIT 1")
    last_processed_timestamp = cur.fetchone()[0]
    print(f"Starting from timestamp: {last_processed_timestamp}")
    cur.close()
    conn.close()
    
    while True:
        try:
            print(f"\n[{datetime.now(pytz.UTC).strftime('%H:%M:%S')}] Checking...")
            conn = get_db_connection()
            cur = conn.cursor()
            
            # Get latest timestamp
            cur.execute("SELECT DISTINCT timestamp FROM public.\"Token Filter\" ORDER BY timestamp DESC LIMIT 1")
            current_timestamp = cur.fetchone()[0]
            
            # Process only if we have a newer timestamp
            if current_timestamp > last_processed_timestamp:
                print(f"New timestamp found: {current_timestamp}")
                
                # Get 7 timestamps for historical comparison
                cur.execute("SELECT DISTINCT timestamp FROM public.\"Token Filter\" ORDER BY timestamp DESC LIMIT 7")
                timestamps = [row[0] for row in cur.fetchall()]
                
                if len(timestamps) >= 7:
                    historical_data = [get_token_data(cur, ts) for ts in timestamps]
                    findings = check_rank_increases(historical_data[0], historical_data[1:], timestamps)
                    
                    if findings:
                        print(f"Found {len(findings)} changes")
                        for token in findings:
                            process_token_messages(token, cur, conn, timestamps, historical_data)
                    
                    process_test_token(cur, conn)
                    
                    # Update last processed timestamp after successful processing
                    last_processed_timestamp = current_timestamp
                    print(f"Updated last processed timestamp to: {last_processed_timestamp}")
            
            cur.close()
            conn.close()
            time.sleep(10)  # Check every 10 seconds
            
        except Exception as e:
            print(f"Error: {e}")
            if 'cur' in locals(): cur.close()
            if 'conn' in locals(): conn.close()
            time.sleep(10)

if __name__ == '__main__':
    try:
        monitor_tokens()
    except KeyboardInterrupt:
        print("Stopped")
    except Exception as e:
        print(f"Error: {e}")
