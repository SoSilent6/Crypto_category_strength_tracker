import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import pytz
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get database connection string from environment variable
DB_CONNECTION = os.environ.get('DATABASE_URL')

if not DB_CONNECTION:
    raise Exception("DATABASE_URL environment variable is not set")

def get_db_connection():
    """Create a database connection"""
    try:
        conn = psycopg2.connect(DB_CONNECTION)
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return None

def get_strength_data(categories, calculation_type, hours=24, since_time=None):
    """
    Fetch strength data for specified categories and calculation type
    
    Args:
        categories (list): List of category names to fetch data for
        calculation_type (str): One of: top_5, top_10, top_15, top_20, top_100_mc, top_200_mc
        hours (int, optional): How many hours of historical data to fetch. If None, fetches all history
        since_time (datetime, optional): If provided, fetches data since this timestamp
    
    Returns:
        dict: Dictionary with categories as keys and lists of (timestamp, strength) tuples as values
    """
    try:
        conn = get_db_connection()
        if not conn:
            return None
        
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Build the base query
        query = """
            SELECT "TIMESTAMP", category, strength_ratio 
            FROM public."CategoryStrength"
            WHERE category = ANY(%s)
            AND calculation_type = %s
        """
        
        params = [categories, calculation_type]
        
        # Add time filtering based on parameters
        if since_time is not None:
            # Fetch data since the last update
            query += ' AND "TIMESTAMP" > %s'
            params.append(since_time)
        elif hours is not None:
            # Fetch last N hours of data
            end_time = datetime.now(pytz.UTC)
            start_time = end_time - timedelta(hours=hours)
            query += ' AND "TIMESTAMP" BETWEEN %s AND %s'
            params.extend([start_time, end_time])
        # If both are None, fetch all historical data
        
        query += ' ORDER BY "TIMESTAMP" ASC'
        
        print(f"Executing query with params: {params}")
        cur.execute(query, params)
        rows = cur.fetchall()
        
        # Organize data by category
        result = {category: [] for category in categories}
        for row in rows:
            result[row['category']].append({
                'timestamp': row['TIMESTAMP'].isoformat(),
                'strength': float(row['strength_ratio']) if row['strength_ratio'] is not None else None
            })
            
        cur.close()
        conn.close()
        return result
        
    except Exception as e:
        print(f"Error fetching strength data: {e}")
        if conn:
            conn.close()
        return None

def get_1h_strength_data(categories, calculation_type, hours=24, since_time=None):
    """
    Fetch strength data for specified categories and calculation type at 1-hour intervals
    
    Args:
        categories (list): List of category names to fetch data for
        calculation_type (str): One of: top_5, top_10, top_15, top_20, top_100_mc, top_200_mc
        hours (int, optional): How many hours of historical data to fetch. If None, fetches all history
        since_time (datetime, optional): If provided, fetches data since this timestamp
    
    Returns:
        dict: Dictionary with categories as keys and lists of (timestamp, strength) tuples as values
    """
    try:
        conn = get_db_connection()
        if not conn:
            return None
        
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Build the base query with 1-hour interval filter
        query = """
            SELECT "TIMESTAMP", category, strength_ratio 
            FROM public."CategoryStrength"
            WHERE category = ANY(%s)
            AND calculation_type = %s
            AND EXTRACT(MINUTE FROM "TIMESTAMP") = 0  -- Only get data points at the start of each hour
        """
        
        params = [categories, calculation_type]
        
        # Add time filtering based on parameters
        if since_time is not None:
            query += ' AND "TIMESTAMP" > %s'
            params.append(since_time)
        elif hours is not None:
            end_time = datetime.now(pytz.UTC)
            start_time = end_time - timedelta(hours=hours)
            query += ' AND "TIMESTAMP" BETWEEN %s AND %s'
            params.extend([start_time, end_time])
        
        query += ' ORDER BY "TIMESTAMP" ASC'
        
        print(f"Executing 1h query with params: {params}")
        cur.execute(query, params)
        rows = cur.fetchall()
        
        # Organize data by category
        result = {category: [] for category in categories}
        for row in rows:
            result[row['category']].append({
                'timestamp': row['TIMESTAMP'].isoformat(),
                'strength': float(row['strength_ratio']) if row['strength_ratio'] is not None else None
            })
            
        cur.close()
        conn.close()
        return result
        
    except Exception as e:
        print(f"Error fetching 1h strength data: {e}")
        if conn:
            conn.close()
        return None

def get_latest_timestamp(debug=False):
    """Get the most recent timestamp in the database"""
    try:
        conn = get_db_connection()
        if not conn:
            print("Failed to get database connection")
            return None
            
        cur = conn.cursor()
        
        # First verify the column exists and its type
        cur.execute("""
            SELECT column_name, data_type, datetime_precision
            FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = 'CategoryStrength'
            AND column_name = 'TIMESTAMP'
        """)
        column_info = cur.fetchone()
        if not column_info:
            print("ERROR: TIMESTAMP column not found in CategoryStrength table!")
            return None
        if debug:
            print(f"Found TIMESTAMP column: type={column_info[1]}, precision={column_info[2]}")
        
        # Get the latest timestamp
        query = 'SELECT MAX("TIMESTAMP") FROM public."CategoryStrength"'
        if debug:
            print(f"Executing query: {query}")
        cur.execute(query)
        latest = cur.fetchone()[0]
        
        if latest is None:
            print("WARNING: No timestamps found in database!")
        elif debug:
            print(f"Latest SQL timestamp (naive): {latest}")
            
        cur.close()
        conn.close()
        return latest
        
    except Exception as e:
        print(f"Error fetching latest timestamp: {e}")
        if 'conn' in locals() and conn:
            conn.close()
        return None

def get_category_tokens(date, category, calculation_type):
    """
    Get token information for a specific date, category, and calculation type
    
    Args:
        date (str): Date in YYYY-MM-DD format
        category (str): Category name
        calculation_type (str): One of: top_5, top_10, top_15, top_20, top_100_mc, top_200_mc
    
    Returns:
        dict: Dictionary containing:
            - success (bool): Whether the query was successful
            - data (list): List of token dictionaries with name, symbol, and ranks
            - error (str): Error message if any
    """
    try:
        conn = get_db_connection()
        if not conn:
            return {"success": False, "error": "Database connection failed", "data": None}
        
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # First get token info from CategoryStrength
        query = """
            WITH token_cmc_ids AS (
                SELECT symbol, name, cmc_id 
                FROM public."Token List"
            ),
            filtered_tokens AS (
                SELECT cs."TIMESTAMP", cs.category, cs.calculation_type,
                    jsonb_agg(t.token) as token_info
                FROM public."CategoryStrength" cs,
                    jsonb_array_elements(cs.token_info) AS t(token)
                LEFT JOIN token_cmc_ids tci 
                    ON tci.symbol = (t.token->>'symbol')::text 
                    AND tci.name = (t.token->>'name')::text
                WHERE DATE(cs."TIMESTAMP") = DATE(%s)
                AND cs.category = %s
                AND cs.calculation_type = %s
                AND (tci.cmc_id IS NULL OR tci.cmc_id != 1)
                GROUP BY cs."TIMESTAMP", cs.category, cs.calculation_type
            )
            SELECT token_info
            FROM filtered_tokens
            LIMIT 1
        """
        
        cur.execute(query, (date, category, calculation_type))
        result = cur.fetchone()
        
        if not result:
            return {
                "success": False,
                "error": "No data found for the specified criteria",
                "data": None
            }
        
        # Parse the token_info JSON string
        tokens = result['token_info']
        
        # For each token, get its CMC ID and ranks
        for token in tokens:
            # Get CMC ID from Token List
            cur.execute("""
                SELECT cmc_id 
                FROM public."Token List" 
                WHERE symbol = %s AND name = %s
            """, (token['symbol'], token['name']))
            
            cmc_result = cur.fetchone()
            if cmc_result:
                cmc_id = cmc_result['cmc_id']
                
                # Get ranks from DailyTokenRanks
                cur.execute("""
                    SELECT market_cap_rank, market_cap
                    FROM public."DailyTokenRanks"
                    WHERE date = %s AND cmc_id = %s
                """, (date, cmc_id))
                
                rank_result = cur.fetchone()
                if rank_result:
                    token['overall_rank'] = rank_result['market_cap_rank']
                    token['market_cap'] = float(rank_result['market_cap'])
                    token['cmc_id'] = cmc_id
                    
                    # Get current strength and historical strengths for 4h and 24h changes
                    cur.execute("""
                        WITH current_strength AS (
                            SELECT strength
                            FROM public."tokenstrength"
                            WHERE cmc_id = %s
                            ORDER BY timestamp DESC
                            LIMIT 1
                        ),
                        four_hours_ago AS (
                            SELECT strength
                            FROM public."tokenstrength"
                            WHERE cmc_id = %s
                            AND timestamp <= (NOW() - INTERVAL '4 hours')
                            ORDER BY timestamp DESC
                            LIMIT 1
                        ),
                        twenty_four_hours_ago AS (
                            SELECT strength
                            FROM public."tokenstrength"
                            WHERE cmc_id = %s
                            AND timestamp <= (NOW() - INTERVAL '24 hours')
                            ORDER BY timestamp DESC
                            LIMIT 1
                        )
                        SELECT 
                            c.strength as current_strength,
                            CASE 
                                WHEN f.strength IS NOT NULL THEN c.strength - f.strength
                                ELSE NULL
                            END as strength_change_4h,
                            CASE 
                                WHEN t.strength IS NOT NULL THEN c.strength - t.strength
                                ELSE NULL
                            END as strength_change_24h
                        FROM current_strength c
                        LEFT JOIN four_hours_ago f ON true
                        LEFT JOIN twenty_four_hours_ago t ON true
                    """, (cmc_id, cmc_id, cmc_id))
                    
                    strength_result = cur.fetchone()
                    if strength_result:
                        token['current_strength'] = strength_result['current_strength']
                        token['strength_change_4h'] = strength_result['strength_change_4h']
                        token['strength_change_24h'] = strength_result['strength_change_24h']
                    else:
                        token['current_strength'] = None
                        token['strength_change_4h'] = None
                        token['strength_change_24h'] = None
                else:
                    token['overall_rank'] = '-'
                    token['market_cap'] = None
                    token['cmc_id'] = None
                    token['current_strength'] = None
                    token['strength_change_4h'] = None
                    token['strength_change_24h'] = None
            else:
                token['overall_rank'] = '-'
                token['market_cap'] = None
                token['cmc_id'] = None
                token['current_strength'] = None
                token['strength_change_4h'] = None
                token['strength_change_24h'] = None
        
        # Calculate category ranks based on market_cap, excluding BTC (CMC ID = 1)
        valid_tokens = [t for t in tokens if t['market_cap'] is not None and t.get('cmc_id') != 1]
        valid_tokens.sort(key=lambda x: x['market_cap'], reverse=True)
        
        # Create rank mapping
        rank_map = {token['symbol']: idx + 1 for idx, token in enumerate(valid_tokens)}
        
        # Assign category ranks
        for token in tokens:
            token['category_rank'] = rank_map.get(token['symbol'], '-')
        
        cur.close()
        conn.close()
        
        return {
            "success": True,
            "data": tokens,
            "error": None
        }
        
    except Exception as e:
        print(f"Error fetching category tokens: {e}")
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()
        return {
            "success": False,
            "error": str(e),
            "data": None
        }

def get_all_tokens():
    """
    Get complete list of tokens with their categories from Token List
    
    Returns:
        dict: Dictionary containing:
            - success (bool): Whether the query was successful
            - data (list): List of token dictionaries with symbol, name, and categories
            - error (str): Error message if any
    """
    try:
        conn = get_db_connection()
        if not conn:
            return {
                "success": False,
                "error": "Database connection failed",
                "data": None
            }
        
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        query = """
            SELECT symbol, name, 
                   ARRAY_TO_STRING(category, ', ') as category
            FROM public."Token List"
            ORDER BY symbol
        """
        
        cur.execute(query)
        tokens = cur.fetchall()
        
        cur.close()
        conn.close()
        
        return {
            "success": True,
            "data": tokens,
            "error": None
        }
        
    except Exception as e:
        print(f"Error getting all tokens: {e}")
        return {
            "success": False,
            "error": str(e),
            "data": None
        }

def get_tokens_by_category(category):
    """
    Get all tokens that belong to a specific category
    
    Args:
        category (str): Category name to search for
        
    Returns:
        dict: Dictionary containing:
            - success (bool): Whether the query was successful
            - data (list): List of token dictionaries with symbol, name, and categories
            - error (str): Error message if any
    """
    try:
        conn = get_db_connection()
        if not conn:
            return {
                'success': False,
                'data': [],
                'error': 'Failed to connect to database'
            }
            
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Query tokens where the category array contains our target category
        query = """
            SELECT symbol, name, category 
            FROM public."Token List"
            WHERE %s = ANY(category)
            ORDER BY symbol ASC
        """
        
        cur.execute(query, (category,))
        rows = cur.fetchall()
        
        # Process results
        tokens = []
        for row in rows:
            # Get all categories except the current one
            other_categories = [cat for cat in row['category'] if cat != category]
            tokens.append({
                'symbol': row['symbol'],
                'name': row['name'],
                'other_categories': other_categories
            })
            
        cur.close()
        conn.close()
        
        return {
            'success': True,
            'data': tokens,
            'error': None
        }
        
    except Exception as e:
        print(f"Error fetching tokens by category: {e}")
        if conn:
            conn.close()
        return {
            'success': False,
            'data': [],
            'error': str(e)
        }

def get_all_strength_data(categories, calculation_types, since_time=None):
    """
    Fetch strength data for multiple calculation types in a single query
    
    Args:
        categories (list): List of category names to fetch data for
        calculation_types (list): List of calculation types (top_5, top_10, etc.)
        since_time (datetime, optional): If provided, fetches only data since this timestamp
                                       If None, fetches all historical data
    
    Returns:
        dict: Nested dictionary with calculation_type and categories as keys
    """
    try:
        conn = get_db_connection()
        if not conn:
            return None
        
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Build the base query with calculation_type filter
        query = """
            SELECT "TIMESTAMP", category, calculation_type, strength_ratio 
            FROM public."CategoryStrength"
            WHERE category = ANY(%s)
            AND calculation_type = ANY(%s)
        """
        
        params = [categories, calculation_types]
        
        # Only add timestamp filter if since_time is provided
        if since_time is not None:
            query += ' AND "TIMESTAMP" > %s'
            params.append(since_time)
            print(f"Fetching data since: {since_time}")
        else:
            print("Fetching all historical data")
        
        query += ' ORDER BY "TIMESTAMP" ASC'
        
        print(f"Executing consolidated query with params: {params}")
        cur.execute(query, params)
        rows = cur.fetchall()
        
        # Initialize result structure
        result = {calc_type: {category: [] for category in categories} 
                 for calc_type in calculation_types}
        
        # Organize data by calculation_type and category
        for row in rows:
            calc_type = row['calculation_type']
            category = row['category']
            result[calc_type][category].append({
                'timestamp': row['TIMESTAMP'].isoformat(),
                'strength': float(row['strength_ratio']) if row['strength_ratio'] is not None else None
            })
            
        cur.close()
        conn.close()
        return result
        
    except Exception as e:
        print(f"Error fetching consolidated strength data: {e}")
        if conn:
            conn.close()
        return None

def get_all_1h_strength_data(categories, calculation_types, since_time=None):
    """
    Fetch hourly strength data for multiple calculation types in a single query
    
    Args:
        categories (list): List of category names to fetch data for
        calculation_types (list): List of calculation types (top_5, top_10, etc.)
        since_time (datetime, optional): If provided, fetches only data since this timestamp
                                       If None, fetches all historical data
    
    Returns:
        dict: Nested dictionary with calculation_type and categories as keys
    """
    try:
        conn = get_db_connection()
        if not conn:
            return None
        
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Build the base query with calculation_type filter and hourly data
        query = """
            SELECT "TIMESTAMP", category, calculation_type, strength_ratio 
            FROM public."CategoryStrength"
            WHERE category = ANY(%s)
            AND calculation_type = ANY(%s)
            AND EXTRACT(MINUTE FROM "TIMESTAMP") = 0  -- Only get data points at the start of each hour
        """
        
        params = [categories, calculation_types]
        
        # Only add timestamp filter if since_time is provided
        if since_time is not None:
            query += ' AND "TIMESTAMP" > %s'
            params.append(since_time)
            print(f"Fetching hourly data since: {since_time}")
        else:
            print("Fetching all historical hourly data")
        
        query += ' ORDER BY "TIMESTAMP" ASC'
        
        print(f"Executing consolidated 1h query with params: {params}")
        cur.execute(query, params)
        rows = cur.fetchall()
        
        # Initialize result structure
        result = {calc_type: {category: [] for category in categories} 
                 for calc_type in calculation_types}
        
        # Organize data by calculation_type and category
        for row in rows:
            calc_type = row['calculation_type']
            category = row['category']
            result[calc_type][category].append({
                'timestamp': row['TIMESTAMP'].isoformat(),
                'strength': float(row['strength_ratio']) if row['strength_ratio'] is not None else None
            })
            
        cur.close()
        conn.close()
        return result
        
    except Exception as e:
        print(f"Error fetching consolidated 1h strength data: {e}")
        if conn:
            conn.close()
        return None