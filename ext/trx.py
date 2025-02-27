import discord
from discord.ext import commands
import logging
from database import get_connection
import datetime
import aiofiles
import os

# Di awal file, setelah imports
def init_logger():
    """Initialize logger for this module"""
    logger = logging.getLogger(__name__)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger

logger = init_logger()
logger = logging.getLogger(__name__)

def format_datetime():
    """Get current datetime in UTC"""
    return datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

def get_total_wls(balance_wl, balance_dl, balance_bgl):
    """Calculate total WLs from all currencies"""
    return balance_wl + (balance_dl * 100) + (balance_bgl * 10000)

def format_balance(balance_wl, balance_dl, balance_bgl):
    """Format balance for display"""
    return (
        f"• {balance_wl:,} WL\n"
        f"• {balance_dl:,} DL (= {balance_dl * 100:,} WL)\n"
        f"• {balance_bgl:,} BGL (= {balance_bgl * 10000:,} WL)\n"
        f"Total: {get_total_wls(balance_wl, balance_dl, balance_bgl):,} WL"
    )

class TransactionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def initialize_database(self):
        """Initialize database tables"""
        conn = get_connection()
        cursor = conn.cursor()
        
        # Create users table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                growid TEXT PRIMARY KEY,
                balance_wl INTEGER DEFAULT 0,
                balance_dl INTEGER DEFAULT 0,
                balance_bgl INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create transaction_log table if not exists
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

        conn.commit()
        conn.close()

    async def get_user_balance(self, growid: str):
        """Get user's balance, create account if not exists"""
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT balance_wl, balance_dl, balance_bgl FROM users WHERE growid = ?", (growid,))
        balance = cursor.fetchone()
        
        if not balance:
            cursor.execute("""
                INSERT INTO users (growid, balance_wl, balance_dl, balance_bgl)
                VALUES (?, 0, 0, 0)
            """, (growid,))
            conn.commit()
            balance = (0, 0, 0)
        
        conn.close()
        return balance

    async def update_balance(self, growid: str, wl: int, dl: int, bgl: int, transaction_type: str, details: str = ""):
        """Update user balance and log transaction"""
        conn = get_connection()
        cursor = conn.cursor()
        
        try:
            # Get old balance
            cursor.execute("SELECT balance_wl, balance_dl, balance_bgl FROM users WHERE growid = ?", (growid,))
            old_balance = cursor.fetchone()
            if not old_balance:
                old_balance = (0, 0, 0)
            
            # Calculate new balance
            new_wl = old_balance[0] + wl
            new_dl = old_balance[1] + dl
            new_bgl = old_balance[2] + bgl
            
            # Update balance
            cursor.execute("""
                UPDATE users 
                SET balance_wl = ?, balance_dl = ?, balance_bgl = ?
                WHERE growid = ?
            """, (new_wl, new_dl, new_bgl, growid))
            
            # Log transaction
            cursor.execute("""
                INSERT INTO transaction_log (
                    growid, amount, type, details, old_balance, new_balance, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                growid,
                get_total_wls(wl, dl, bgl),
                transaction_type,
                details,
                format_balance(*old_balance),
                format_balance(new_wl, new_dl, new_bgl)
            ))
            
            conn.commit()
            return new_wl, new_dl, new_bgl

        except Exception as e:
            logger.error(f"Error updating balance: {e}")
            conn.rollback()
            raise e
        
        finally:
            conn.close()

    async def add_stock_from_file(self, ctx, product_code: str, file_path: str = None):
        """Add stock from file"""
        conn = None
        try:
            current_time = format_datetime()
            logger.info(f"Adding stock at {current_time}")
            
            if not file_path and not ctx.message.attachments:
                return "❌ No file provided!"

            # Handle file attachment
            if not file_path and ctx.message.attachments:
                attachment = ctx.message.attachments[0]
                file_path = attachment.filename
                await attachment.save(file_path)

            # Read file content
            try:
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as file:
                    content = await file.read()
                    lines = [line.strip() for line in content.split('\n') if line.strip()]
            except Exception as e:
                logger.error(f"Error reading file: {e}")
                return f"❌ Error reading file: {str(e)}"

            if not lines:
                return "❌ File is empty!"

            conn = get_connection()
            cursor = conn.cursor()

            # Verify product exists
            cursor.execute("SELECT code FROM products WHERE code = ?", (product_code,))
            if not cursor.fetchone():
                return f"❌ Product with code {product_code} does not exist!"

            # Create product_stock table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS product_stock (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_code TEXT NOT NULL,
                    content TEXT NOT NULL,
                    used INTEGER DEFAULT 0,
                    used_by TEXT DEFAULT NULL,
                    used_at TIMESTAMP DEFAULT NULL,
                    added_by TEXT NOT NULL,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    source_file TEXT,
                    FOREIGN KEY (product_code) REFERENCES products(code)
                )
            """)

            # Add stock items
            added_count = 0
            for line in lines:
                cursor.execute("""
                    INSERT INTO product_stock (
                        product_code, content, added_by, source_file
                    ) VALUES (?, ?, ?, ?)
                """, (product_code, line, str(ctx.author), file_path))
                added_count += 1

            # Update product stock count
            cursor.execute("""
                UPDATE products 
                SET stock = stock + ? 
                WHERE code = ?
            """, (added_count, product_code))

            conn.commit()

            # Create embed response
            embed = discord.Embed(
                title="✅ Stock Added Successfully",
                color=discord.Color.green(),
                timestamp=datetime.datetime.utcnow()
            )
            embed.add_field(name="Product Code", value=product_code, inline=True)
            embed.add_field(name="Items Added", value=str(added_count), inline=True)
            embed.add_field(name="Source File", value=file_path, inline=True)
            embed.set_footer(text=f"Added by {ctx.author}")

            # Clean up file if it was an attachment
            if ctx.message.attachments and os.path.exists(file_path):
                os.remove(file_path)

            return embed

        except Exception as e:
            logger.error(f"Error adding stock: {e}")
            if conn:
                conn.rollback()
            return f"❌ An error occurred: {str(e)}"

        finally:
            if conn:
                conn.close()

    async def process_purchase(self, user, product_code: str, quantity: int):
        """Process purchase of products"""
        conn = None
        try:
            current_time = format_datetime()
            logger.info(f"Processing purchase at {current_time}")
            
            conn = get_connection()
            cursor = conn.cursor()

            # Get user's GrowID
            cursor.execute("SELECT growid FROM user_growid WHERE user_id = ?", (user.id,))
            user_data = cursor.fetchone()

            if not user_data:
                return "❌ Please set your GrowID first using the 'Set GrowID' button!"

            growid = user_data[0]
            logger.info(f"Processing purchase for GrowID: {growid}")

            # Get product information
            cursor.execute("""
                SELECT name, price, stock, description 
                FROM products 
                WHERE code = ?
            """, (product_code,))
            product = cursor.fetchone()

            if not product:
                return f"❌ Product with code `{product_code}` not found!"

            name, price, stock, description = product
            logger.info(f"Product info - Name: {name}, Price: {price}, Stock: {stock}")

            if stock < quantity:
                return f"❌ Not enough stock! Only {stock} items available."

            required_wls = price * quantity

            # Get user's balance
            balance_wl, balance_dl, balance_bgl = await self.get_user_balance(growid)
            total_wls = get_total_wls(balance_wl, balance_dl, balance_bgl)

            logger.info(f"User balance - Total: {total_wls} WL")
            logger.info(f"Required WLs: {required_wls}")

            if total_wls < required_wls:
                return (
                    f"❌ Insufficient balance!\n"
                    f"Price: {required_wls:,} WLs\n"
                    f"Your balance:\n{format_balance(balance_wl, balance_dl, balance_bgl)}"
                )

            # Calculate balance changes
            remaining = required_wls
            new_bgl = balance_bgl
            new_dl = balance_dl
            new_wl = balance_wl

            # Convert from BGL if needed
            while remaining > (new_wl + new_dl * 100) and new_bgl > 0:
                new_bgl -= 1
                new_dl += 100

            # Convert from DL if needed
            while remaining > new_wl and new_dl > 0:
                new_dl -= 1
                new_wl += 100

            # Deduct WLs
            if new_wl >= remaining:
                new_wl -= remaining
            else:
                return "❌ Balance conversion error!"

            # Get items from stock
            cursor.execute("""
                SELECT id, content 
                FROM product_stock 
                WHERE product_code = ? AND used = 0 
                LIMIT ?
            """, (product_code, quantity))
            
            items = cursor.fetchall()
            
            if len(items) < quantity:
                return f"❌ Not enough stock available. Only {len(items)} items left."

            try:
                # Update user's balance
                await self.update_balance(
                    growid,
                    new_wl - balance_wl,
                    new_dl - balance_dl,
                    new_bgl - balance_bgl,
                    'PURCHASE',
                    f"Purchased {quantity}x {name} ({product_code})"
                )

                # Mark items as used
                for item_id, _ in items:
                    cursor.execute("""
                        UPDATE product_stock 
                        SET used = 1, 
                            used_by = ?, 
                            used_at = ? 
                        WHERE id = ?
                    """, (str(user), current_time, item_id))

                # Update product stock
                cursor.execute("""
                    UPDATE products 
                    SET stock = stock - ? 
                    WHERE code = ?
                """, (quantity, product_code))

                conn.commit()

                # Prepare DM content
                content_message = (
                    f"🛍️ Purchase Details:\n"
                    f"Product: {name}\n"
                    f"Quantity: {quantity}\n"
                    f"Total Price: {required_wls:,} WLs\n"
                    f"Time: {current_time}\n\n"
                    f"Your Items:\n"
                )
                for i, (_, content) in enumerate(items, 1):
                    content_message += f"{i}. {content}\n"

                # Send items to user
                try:
                    if len(content_message) > 1900:
                        parts = [content_message[i:i+1900] for i in range(0, len(content_message), 1900)]
                        for part in parts:
                            await user.send(part)
                    else:
                        await user.send(content_message)

                    return (
                        f"✅ Purchase Successful!\n"
                        f"• Product: {name}\n"
                        f"• Quantity: {quantity}\n"
                        f"• Price Paid: {required_wls:,} WLs\n"
                        f"• New Balance:\n{format_balance(new_wl, new_dl, new_bgl)}\n"
                        f"Check your DMs for the items!"
                    )

                except discord.Forbidden:
                    return (
                        f"✅ Purchase Successful!\n"
                        f"• Product: {name}\n"
                        f"• Quantity: {quantity}\n"
                        f"• Price Paid: {required_wls:,} WLs\n"
                        f"• New Balance:\n{format_balance(new_wl, new_dl, new_bgl)}\n"
                        f"❗ Couldn't send items via DM. Please enable DMs!"
                    )

            except Exception as e:
                conn.rollback()
                logger.error(f"Error processing purchase: {e}")
                return f"❌ Error processing purchase: {str(e)}"

        except Exception as e:
            logger.error(f"Error in process_purchase: {e}")
            return f"❌ An error occurred: {str(e)}"

        finally:
            if conn:
                conn.close()

    @commands.Cog.listener()
    async def on_ready(self):
        """Initialize database when bot is ready"""
        await self.initialize_database()
        logger.info("Transaction system initialized")

async def setup(bot):
    cog = TransactionCog(bot)
    await bot.add_cog(cog)