import sqlite3
import logging
from datetime import datetime
import os

logger = logging.getLogger(__name__)

DATABASE_PATH = 'shop.db'

def get_connection():
    """Get SQLite database connection"""
    return sqlite3.connect(DATABASE_PATH)

def get_balance(growid: str):
    """Get user balance from database"""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT balance_wl, balance_dl, balance_bgl 
            FROM users 
            WHERE growid = ?
        """, (growid,))
        balance = cursor.fetchone()
        return balance if balance else (0, 0, 0)
    except Exception as e:
        logger.error(f"Error getting balance: {e}")
        return (0, 0, 0)
    finally:
        conn.close()

def setup_database():
    """Initialize database tables"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Create users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                growid TEXT PRIMARY KEY,
                balance_wl INTEGER DEFAULT 0,
                balance_dl INTEGER DEFAULT 0,
                balance_bgl INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create user_growid table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_growid (
                user_id INTEGER PRIMARY KEY,
                growid TEXT UNIQUE NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create products table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                price INTEGER NOT NULL,
                stock INTEGER DEFAULT 0,
                description TEXT
            )
        """)

        # Create stock table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'available',
                added_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                added_by TEXT NOT NULL,
                used_date DATETIME,
                used_by TEXT,
                buyer_growid TEXT,
                source_file TEXT
            )
        """)

        # Create transaction_log table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transaction_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                growid TEXT NOT NULL,
                amount INTEGER NOT NULL,
                type TEXT NOT NULL,
                details TEXT,
                old_balance TEXT,
                new_balance TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (growid) REFERENCES users(growid)
            )
        """)

        # Create world_info table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS world_info (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                world TEXT NOT NULL,
                owner TEXT NOT NULL,
                bot TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        logger.info("Database initialized successfully")

    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

def format_datetime(dt=None):
    """Format datetime in YYYY-MM-DD HH:MM:SS format"""
    if dt is None:
        dt = datetime.utcnow()
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def ensure_database():
    """Ensure database is set up"""
    if not os.path.exists(DATABASE_PATH):
        setup_database()