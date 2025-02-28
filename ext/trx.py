import discord
from discord.ext import commands
import logging
from datetime import datetime
import aiofiles
import os
from typing import List, Tuple, Optional
from decimal import Decimal

from database import get_connection
from .constants import (
    Balance, 
    TransactionError, 
    CURRENCY_RATES,
    MAX_ITEMS_PER_TRANSACTION,
    MAX_ITEMS_PER_MESSAGE
)

class TransactionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._init_logger()
        self._cache = {}
        print(f"Current Date and Time (UTC - YYYY-MM-DD HH:MM:SS formatted): {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
        
    def _init_logger(self):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    async def _get_cached_balance(self, growid: str) -> Optional[Balance]:
        if growid in self._cache:
            return self._cache[growid]
        balance = await self._get_balance_from_db(growid)
        if balance:
            self._cache[growid] = balance
        return balance

    async def _get_balance_from_db(self, growid: str) -> Optional[Balance]:
        async with self._db_transaction() as cursor:
            cursor.execute(
                "SELECT balance_wl, balance_dl, balance_bgl FROM users WHERE growid = ?", 
                (growid,)
            )
            result = cursor.fetchone()
            return Balance(*result) if result else None

    async def _update_cached_balance(self, growid: str, balance: Balance):
        self._cache[growid] = balance

    async def _db_transaction(self):
        conn = None
        try:
            conn = get_connection()
            yield conn.cursor()
            conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            self.logger.error(f"Database error: {e}")
            raise TransactionError(f"Database error: {str(e)}")
        finally:
            if conn:
                conn.close()

    async def process_purchase(
        self, 
        user: discord.User, 
        product_code: str, 
        quantity: int
    ) -> str:
        try:
            # Validate input
            if quantity <= 0:
                raise TransactionError("Quantity must be positive")
            if quantity > MAX_ITEMS_PER_TRANSACTION:
                raise TransactionError(
                    f"Maximum {MAX_ITEMS_PER_TRANSACTION} items per transaction"
                )

            async with self._db_transaction() as cursor:
                # Get user's GrowID
                cursor.execute(
                    "SELECT growid FROM user_growid WHERE user_id = ?", 
                    (user.id,)
                )
                user_data = cursor.fetchone()
                if not user_data:
                    raise TransactionError("Please set your GrowID first!")
                
                growid = user_data[0]
                
                # Get product with lock
                cursor.execute("""
                    SELECT name, price, stock, description 
                    FROM products 
                    WHERE code = ?
                    FOR UPDATE
                """, (product_code,))
                product = cursor.fetchone()
                
                if not product:
                    raise TransactionError(f"Product {product_code} not found")
                    
                name, price, stock, description = product
                
                if stock < quantity:
                    raise TransactionError(f"Insufficient stock ({stock} available)")
                
                required_wls = Decimal(price) * quantity
                
                # Get and verify balance
                balance = await self._get_cached_balance(growid)
                if not balance:
                    raise TransactionError("Account not found")
                    
                if balance.total_wls < required_wls:
                    raise TransactionError(
                        f"Insufficient balance\n"
                        f"Required: {required_wls:,} WLs\n"
                        f"Your balance:\n{balance.format()}"
                    )

                # Get items with lock
                cursor.execute("""
                    SELECT id, content 
                    FROM stock 
                    WHERE status = 'available'
                    LIMIT ?
                    FOR UPDATE
                """, (quantity,))
                
                items = cursor.fetchall()
                if len(items) < quantity:
                    raise TransactionError("Stock changed during transaction")
                
                # Process payment
                new_balance = await self._process_payment(
                    cursor, growid, balance, required_wls, name, product_code
                )
                
                # Update stock status
                current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                for item_id, _ in items:
                    cursor.execute("""
                        UPDATE stock 
                        SET status = 'used',
                            used_date = ?,
                            used_by = ?,
                            buyer_growid = ?
                        WHERE id = ?
                    """, (current_time, str(user.id), growid, item_id))
                
                # Update product stock count
                cursor.execute("""
                    UPDATE products 
                    SET stock = stock - ? 
                    WHERE code = ?
                """, (quantity, product_code))
                
                # Send items to user
                await self._send_items_to_user(
                    user, name, quantity, required_wls, new_balance, items
                )
                
                # Update cache
                await self._update_cached_balance(growid, new_balance)
                
                return (
                    f"✅ Purchase Successful!\n"
                    f"• Product: {name}\n"
                    f"• Quantity: {quantity}\n" 
                    f"• Price Paid: {required_wls:,} WLs\n"
                    f"• New Balance:\n{new_balance.format()}\n"
                    f"Check your DMs for the items!"
                )
                
        except TransactionError as e:
            self.logger.warning(f"Transaction failed: {e}")
            return f"❌ {str(e)}"
            
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
            return "❌ An unexpected error occurred"

    async def _process_payment(
        self,
        cursor,
        growid: str,
        balance: Balance,
        amount: Decimal,
        product_name: str,
        product_code: str
    ) -> Balance:
        remaining = amount
        new_balance = Balance(
            balance.wl,
            balance.dl,
            balance.bgl
        )
        
        # Convert from BGL if needed
        while (
            remaining > (new_balance.wl + new_balance.dl * CURRENCY_RATES['DL']) and 
            new_balance.bgl > 0
        ):
            new_balance.bgl -= 1
            new_balance.dl += 100
            
        # Convert from DL if needed    
        while remaining > new_balance.wl and new_balance.dl > 0:
            new_balance.dl -= 1
            new_balance.wl += 100
            
        if new_balance.wl < remaining:
            raise TransactionError("Balance conversion error")
            
        new_balance.wl -= int(remaining)
        
        # Update database
        cursor.execute("""
            UPDATE users 
            SET balance_wl = ?, balance_dl = ?, balance_bgl = ?
            WHERE growid = ?
        """, (new_balance.wl, new_balance.dl, new_balance.bgl, growid))
        
        # Log transaction
        cursor.execute("""
            INSERT INTO transaction_log 
            (growid, amount, type, details, old_balance, new_balance, timestamp)
            VALUES (?, ?, 'PURCHASE', ?, ?, ?, datetime('now'))
        """, (
            growid,
            int(amount),
            f"Purchased {product_name} ({product_code})",
            balance.format(),
            new_balance.format()
        ))
        
        return new_balance

    async def _send_items_to_user(
        self,
        user: discord.User,
        product_name: str,
        quantity: int,
        price: Decimal,
        balance: Balance,
        items: List[Tuple]
    ):
        try:
            messages = []
            current_msg = [
                f"🛍️ Purchase Details:\n"
                f"Product: {product_name}\n"
                f"Quantity: {quantity}\n"
                f"Total Price: {price:,} WLs\n"
                f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"Your Items:\n"
            ]
            
            for i, (_, content) in enumerate(items, 1):
                item_line = f"{i}. {content}\n"
                if len('\n'.join(current_msg)) + len(item_line) > 1900:
                    messages.append('\n'.join(current_msg))
                    current_msg = [item_line]
                else:
                    current_msg.append(item_line)
                    
            if current_msg:
                messages.append('\n'.join(current_msg))
            
            for msg in messages:
                await user.send(msg)
                
        except discord.Forbidden:
            self.logger.warning(f"Could not send DM to user {user.id}")
            raise TransactionError(
                "Couldn't send items via DM. Please enable DMs and try again!"
            )

    async def add_stock_from_file(
        self, 
        ctx: commands.Context, 
        file_path: str = None
    ) -> discord.Embed:
        """Add stock from file"""
        try:
            current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            self.logger.info(f"Adding stock at {current_time}")
            
            if not file_path and not ctx.message.attachments:
                raise TransactionError("No file provided!")

            if not file_path and ctx.message.attachments:
                attachment = ctx.message.attachments[0]
                file_path = attachment.filename
                await attachment.save(file_path)

            try:
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as file:
                    content = await file.read()
                    lines = [line.strip() for line in content.split('\n') if line.strip()]
            except Exception as e:
                raise TransactionError(f"Error reading file: {str(e)}")

            if not lines:
                raise TransactionError("File is empty!")

            async with self._db_transaction() as cursor:
                # Add stock items
                added_count = 0
                failed_items = []
                
                for line in lines:
                    try:
                        cursor.execute("""
                            INSERT INTO stock (
                                content, status, added_date, added_by, source_file
                            ) VALUES (?, 'available', ?, ?, ?)
                        """, (line, current_time, str(ctx.author), file_path))
                        added_count += 1
                    except Exception as e:
                        failed_items.append(f"{line}: {str(e)}")

            embed = discord.Embed(
                title="✅ Stock Added Successfully",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Items Added", value=str(added_count), inline=True)
            embed.add_field(name="Failed Items", value=str(len(failed_items)), inline=True)
            embed.add_field(name="Source File", value=file_path, inline=True)
            
            if failed_items:
                # Split failed items into chunks if too long
                chunks = [failed_items[i:i + 10] for i in range(0, len(failed_items), 10)]
                for i, chunk in enumerate(chunks):
                    embed.add_field(
                        name=f"Failed Items (Part {i+1})",
                        value="\n".join(chunk),
                        inline=False
                    )
                    
            embed.set_footer(text=f"Added by {ctx.author}")

            # Clean up file if it was an attachment
            if ctx.message.attachments and os.path.exists(file_path):
                os.remove(file_path)

            return embed

        except TransactionError as e:
            self.logger.warning(f"Error adding stock: {e}")
            raise

        except Exception as e:
            self.logger.error(f"Unexpected error adding stock: {e}")
            raise TransactionError(f"An unexpected error occurred: {str(e)}")

    @commands.Cog.listener()
    async def on_ready(self):
        """Initialize when bot is ready"""
        self.logger.info("Transaction system initialized")

async def setup(bot):
    await bot.add_cog(TransactionCog(bot))