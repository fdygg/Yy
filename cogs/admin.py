import discord
from discord.ext import commands
import logging
from datetime import datetime
import json
from asyncio import TimeoutError
import sqlite3
from database import get_connection
from ext.constants import Balance, TransactionError, CURRENCY_RATES
from ext.balance_manager import BalanceManager

class AdminCog(commands.Cog, name="Admin"):
    def __init__(self, bot):
        self.bot = bot
        self._init_logger()
        self.balance_manager = BalanceManager(bot)
        
        print(f"Current Date and Time (UTC - YYYY-MM-DD HH:MM:SS formatted): {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Load admin ID from config.json
        try:
            with open('config.json') as f:
                config = json.load(f)
                self.admin_id = int(config['admin_id'])
                self.logger.info(f"Admin ID loaded: {self.admin_id}")
        except Exception as e:
            self.logger.error(f"Failed to load admin_id: {e}")
            raise

    def _init_logger(self):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    async def _check_admin(self, ctx):
        """Check if user has admin permissions"""
        is_admin = ctx.author.id == self.admin_id
        if not is_admin:
            await ctx.send("❌ You are not authorized to use admin commands!")
            self.logger.warning(f"Unauthorized access attempt by {ctx.author} (ID: {ctx.author.id})")
        else:
            self.logger.info(f"Admin command used by {ctx.author} (ID: {ctx.author.id})")
        return is_admin

    @commands.command(name="adminhelp")
    async def admin_help(self, ctx):
        """Show admin commands"""
        if not await self._check_admin(ctx):
            return
            
        embed = discord.Embed(
            title="Admin Commands",
            description="Available admin commands:",
            color=discord.Color.blue()
        )
        
        # Products Commands
        products_commands = [
            "`!addproduct <code> <n> <price> <description>` - Add a new product",
            "`!bulkstock [attach stock.txt]",
            "`!editproduct <code> <field> <value>` - Edit product details",
            "`!deleteproduct <code>` - Delete a product",
            "`!stock [code]` - View product stock",
            "`!stockhistory <code> [limit]` - View stock history"
        ]
        embed.add_field(
            name="Products",
            value="\n".join(products_commands),
            inline=False
        )
        
        # Balance Commands
        balance_commands = [
            "`!addbalance <growid> <amount> <currency>` - Add balance to user",
            "`!removebalance <growid> <amount> <currency>` - Remove balance from user",
            "`!checkbalance <growid>` - Check user balance",
            "`!resetuser <growid>` - Reset user balance"
        ]
        embed.add_field(
            name="Balance Management",
            value="\n".join(balance_commands),
            inline=False
        )
        
        await ctx.send(embed=embed)

    @commands.command(name="addproduct")
    async def add_product(self, ctx, code: str, name: str, price: int, *, description: str = "No description"):
        """Add a new product"""
        if not await self._check_admin(ctx):
            return
            
        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Check if product exists
            cursor.execute("SELECT code FROM products WHERE code = ?", (code,))
            if cursor.fetchone():
                await ctx.send(f"❌ Product with code {code} already exists!")
                return

            # Add product
            cursor.execute("""
                INSERT INTO products (code, name, price, description, stock)
                VALUES (?, ?, ?, ?, 0)
            """, (code, name, price, description))

            conn.commit()

            embed = discord.Embed(
                title="✅ Product Added",
                color=discord.Color.green()
            )
            embed.add_field(name="Code", value=code, inline=True)
            embed.add_field(name="Name", value=name, inline=True)
            embed.add_field(name="Price", value=f"{price:,} WLs", inline=True)
            embed.add_field(name="Description", value=description, inline=False)

            await ctx.send(embed=embed)
            self.logger.info(f"Product {code} added by {ctx.author}")

        except Exception as e:
            self.logger.error(f"Error adding product: {e}")
            await ctx.send(f"❌ Error: {str(e)}")
        finally:
            if conn:
                conn.close()

    @commands.command(name="editproduct")
    async def edit_product(self, ctx, code: str, field: str, *, value: str):
        """
        Edit a product's details
        
        Parameters:
        - code: Product code to edit
        - field: Field to edit (name/price/description)
        - value: New value for the field
        """
        try:
            if not await self._check_admin(ctx):
                return

            valid_fields = ['name', 'price', 'description']
            if field.lower() not in valid_fields:
                await ctx.send(
                    f"❌ Invalid field. Valid fields: {', '.join(valid_fields)}"
                )
                return

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute(
                "SELECT * FROM products WHERE code = ?", 
                (code,)
            )
            product = cursor.fetchone()
            if not product:
                await ctx.send(f"❌ Product {code} not found!")
                return

            if field.lower() == 'price':
                try:
                    value = int(value)
                except ValueError:
                    await ctx.send("❌ Price must be a number!")
                    return

            cursor.execute(
                f"UPDATE products SET {field.lower()} = ? WHERE code = ?",
                (value, code)
            )
            conn.commit()

            embed = discord.Embed(
                title="✅ Product Updated",
                color=discord.Color.green()
            )
            embed.add_field(name="Code", value=code, inline=True)
            embed.add_field(name="Field", value=field, inline=True)
            embed.add_field(name="New Value", value=str(value), inline=True)
            embed.set_footer(text=f"Updated by {ctx.author}")

            await ctx.send(embed=embed)
            self.logger.info(f"Product {code} updated")

        except Exception as e:
            self.logger.error(f"Error editing product: {e}")
            await ctx.send(f"❌ Error: {str(e)}")
        finally:
            if conn:
                conn.close()

    @commands.command(name="bulkstock")
    async def bulk_add_stock(self, ctx):
        """
        Add stock from attached .txt file
        File name can be anything (example: stock.txt, items.txt, accounts.txt, etc)
        Each new line will be counted as 1 stock
        """
        try:
            if not await self._check_admin(ctx):
                return

            if not ctx.message.attachments:
                embed = discord.Embed(
                    title="❌ Missing File",
                    description="Please attach a .txt file\n\n"
                              "Example usage:\n"
                              "1. Type `!bulkstock`\n"
                              "2. Attach any .txt file (stock.txt, items.txt, etc)\n"
                              "3. Send the message",
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed)
                return

            attachment = ctx.message.attachments[0]
            if not attachment.filename.lower().endswith('.txt'):
                embed = discord.Embed(
                    title="❌ Invalid File Format",
                    description="Only .txt files are allowed\n\n"
                              f"Your file: `{attachment.filename}`\n"
                              "Rename your file to end with .txt",
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed)
                return

            # Download and read file content
            content = await attachment.read()
            try:
                file_content = content.decode('utf-8').strip().split('\n')
            except UnicodeDecodeError:
                await ctx.send("❌ File must be in text format!")
                return

            if not file_content or not any(line.strip() for line in file_content):
                await ctx.send("❌ File is empty!")
                return

            conn = get_connection()
            cursor = conn.cursor()

            success_count = 0
            failed_items = []
            duplicate_count = 0

            # Get current timestamp
            current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

            # Process each line
            for line_number, line in enumerate(file_content, 1):
                try:
                    # Skip empty lines
                    if not line.strip():
                        continue

                    # Try to insert, catch duplicates
                    try:
                        cursor.execute("""
                            INSERT INTO stock (content, status, added_date, added_by, line_number)
                            VALUES (?, 'available', ?, ?, ?)
                        """, (line.strip(), current_time, str(ctx.author), line_number))
                        success_count += 1
                    except sqlite3.IntegrityError:
                        duplicate_count += 1
                        failed_items.append(f"Line {line_number}: Duplicate entry")
                    except Exception as e:
                        failed_items.append(f"Line {line_number}: {str(e)}")

                except Exception as e:
                    failed_items.append(f"Line {line_number}: {str(e)}")

            conn.commit()

            # Create response embed
            embed = discord.Embed(
                title="📦 Stock Update Results",
                description=f"File: `{attachment.filename}`",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="Summary",
                value=f"✅ Successfully added: {success_count}\n"
                      f"⚠️ Duplicates found: {duplicate_count}\n"
                      f"❌ Failed entries: {len(failed_items)}",
                inline=False
            )

            if failed_items:
                # Split failed items into chunks if too long
                chunks = [failed_items[i:i + 10] for i in range(0, len(failed_items), 10)]
                for i, chunk in enumerate(chunks):
                    embed.add_field(
                        name=f"Failed Items (Part {i+1})",
                        value="\n".join(chunk),
                        inline=False
                    )

            embed.set_footer(text=f"Processed by {ctx.author} • {current_time}")
            await ctx.send(embed=embed)
            
            self.logger.info(f"Stock update completed for {attachment.filename}: {success_count} successful, {duplicate_count} duplicates, {len(failed_items)} failed")

        except Exception as e:
            self.logger.error(f"Error in stock update: {e}")
            await ctx.send(f"❌ Error: {str(e)}")
        finally:
            if conn:
                conn.close()

    @commands.command(name="deleteproduct")
    async def delete_product(self, ctx, code: str):
        """
        Delete a product from the shop
        
        Parameters:
        - code: Product code to delete
        """
        try:
            if not await self._check_admin(ctx):
                return

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute(
                "SELECT name FROM products WHERE code = ?", 
                (code,)
            )
            product = cursor.fetchone()
            if not product:
                await ctx.send(f"❌ Product {code} not found!")
                return

            confirm_msg = await ctx.send(
                f"⚠️ Are you sure you want to delete {code} ({product[0]})?\n"
                f"This action cannot be undone!"
            )
            await confirm_msg.add_reaction('✅')
            await confirm_msg.add_reaction('❌')

            def check(reaction, user):
                return user == ctx.author and str(reaction.emoji) in ['✅', '❌']

            try:
                reaction, user = await self.bot.wait_for(
                    'reaction_add', 
                    timeout=30.0, 
                    check=check
                )
            except TimeoutError:
                await ctx.send("❌ Operation timed out!")
                return

            if str(reaction.emoji) == '❌':
                await ctx.send("❌ Operation cancelled!")
                return

            cursor.execute(
                "DELETE FROM products WHERE code = ?", 
                (code,)
            )
            conn.commit()

            embed = discord.Embed(
                title="✅ Product Deleted",
                description=f"Product {code} ({product[0]}) has been deleted.",
                color=discord.Color.red()
            )
            embed.set_footer(text=f"Deleted by {ctx.author}")

            await ctx.send(embed=embed)
            self.logger.info(f"Product {code} deleted")

        except Exception as e:
            self.logger.error(f"Error deleting product: {e}")
            await ctx.send(f"❌ Error: {str(e)}")
        finally:
            if conn:
                conn.close()

    @commands.command(name="addbalance")
    async def add_balance(self, ctx, growid: str, amount: int, currency: str):
        """
        Add balance to a user's account
        
        Parameters:
        - growid: User's Growtopia ID
        - amount: Amount to add
        - currency: Currency type (WL/DL/BGL)
        """
        try:
            if not await self._check_admin(ctx):
                return

            currency = currency.upper()
            if currency not in CURRENCY_RATES:
                await ctx.send(
                    f"❌ Invalid currency. Use: {', '.join(CURRENCY_RATES.keys())}"
                )
                return

            kwargs = {currency.lower(): amount}
            new_balance = await self.balance_manager.update_balance(
                growid,
                transaction_type="ADMIN_ADD",
                details=f"Added by admin {ctx.author}",
                **kwargs
            )

            embed = discord.Embed(
                title="✅ Balance Added",
                color=discord.Color.green()
            )
            embed.add_field(name="GrowID", value=growid, inline=True)
            embed.add_field(
                name="Added", 
                value=f"{amount:,} {currency}", 
                inline=True
            )
            embed.add_field(
                name="New Balance", 
                value=new_balance.format(), 
                inline=False
            )
            embed.set_footer(text=f"Added by {ctx.author}")

            await ctx.send(embed=embed)
            self.logger.info(f"Balance added for user {growid}")

        except TransactionError as e:
            await ctx.send(f"❌ {str(e)}")
        except Exception as e:
            self.logger.error(f"Error adding balance: {e}")
            await ctx.send(f"❌ Error: {str(e)}")

    @commands.command(name="removebalance")
    async def remove_balance(self, ctx, growid: str, amount: int, currency: str):
        """
        Remove balance from a user's account
        
        Parameters:
        - growid: User's Growtopia ID
        - amount: Amount to remove
        - currency: Currency type (WL/DL/BGL)
        """
        try:
            if not await self._check_admin(ctx):
                return

            currency = currency.upper()
            if currency not in CURRENCY_RATES:
                await ctx.send(
                    f"❌ Invalid currency. Use: {', '.join(CURRENCY_RATES.keys())}"
                )
                return

            kwargs = {currency.lower(): -amount}
            new_balance = await self.balance_manager.update_balance(
                growid,
                transaction_type="ADMIN_REMOVE",
                details=f"Removed by admin {ctx.author}",
                **kwargs
            )

            embed = discord.Embed(
                title="✅ Balance Removed",
                color=discord.Color.red()
            )
            embed.add_field(name="GrowID", value=growid, inline=True)
            embed.add_field(
                name="Removed", 
                value=f"{amount:,} {currency}", 
                inline=True
            )
            embed.add_field(
                name="New Balance", 
                value=new_balance.format(), 
                inline=False
            )
            embed.set_footer(text=f"Removed by {ctx.author}")

            await ctx.send(embed=embed)
            self.logger.info(f"Balance removed from user {growid}")

        except TransactionError as e:
            await ctx.send(f"❌ {str(e)}")
        except Exception as e:
            self.logger.error(f"Error removing balance: {e}")
            await ctx.send(f"❌ Error: {str(e)}")

    @commands.command(name="checkbalance")
    async def check_balance(self, ctx, growid: str):
        """
        Check a user's current balance
        
        Parameters:
        - growid: User's Growtopia ID
        """
        try:
            if not await self._check_admin(ctx):
                return

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT balance_wl, balance_dl, balance_bgl 
                FROM users 
                WHERE growid = ?
            """, (growid,))
            
            result = cursor.fetchone()
            if not result:
                await ctx.send(f"❌ User {growid} not found!")
                return

            balance = Balance(*result)
            embed = discord.Embed(
                title=f"Balance Check - {growid}",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="Balance", 
                value=balance.format(), 
                inline=False
            )
            embed.set_footer(text=f"Checked by {ctx.author}")

            await ctx.send(embed=embed)
            self.logger.info(f"Balance checked for user {growid}")

        except Exception as e:
            self.logger.error(f"Error checking balance: {e}")
            await ctx.send(f"❌ Error: {str(e)}")
        finally:
            if conn:
                conn.close()

    @commands.command(name="resetuser")
    async def reset_user(self, ctx, growid: str):
        """
        Reset a user's balance to zero
        
        Parameters:
        - growid: User's Growtopia ID to reset
        """
        try:
            if not await self._check_admin(ctx):
                return

            confirm_msg = await ctx.send(
                f"⚠️ Are you sure you want to reset {growid}'s balance?\n"
                f"This action cannot be undone!"
            )
            await confirm_msg.add_reaction('✅')
            await confirm_msg.add_reaction('❌')

            def check(reaction, user):
                return user == ctx.author and str(reaction.emoji) in ['✅', '❌']

            try:
                reaction, user = await self.bot.wait_for(
                    'reaction_add', 
                    timeout=30.0, 
                    check=check
                )
            except TimeoutError:
                await ctx.send("❌ Operation timed out!")
                return

            if str(reaction.emoji) == '❌':
                await ctx.send("❌ Operation cancelled!")
                return

            conn = get_connection()
            cursor = conn.cursor()

            # Check if user exists
            cursor.execute(
                "SELECT growid FROM users WHERE growid = ?", 
                (growid,)
            )
            if not cursor.fetchone():
                await ctx.send(f"❌ User {growid} not found!")
                return

            # Reset balance
            cursor.execute("""
                UPDATE users 
                SET balance_wl = 0, balance_dl = 0, balance_bgl = 0 
                WHERE growid = ?
            """, (growid,))
            
            # Add transaction log
            cursor.execute("""
                INSERT INTO transaction_log (
                    growid, type, amount, details
                ) VALUES (?, 'RESET', 0, ?)
            """, (growid, f"Balance reset by admin {ctx.author}"))

            conn.commit()

            embed = discord.Embed(
                title="✅ User Reset",
                description=f"User {growid}'s balance has been reset to 0.",
                color=discord.Color.red()
            )
            embed.set_footer(text=f"Reset by {ctx.author}")

            await ctx.send(embed=embed)
            self.logger.info(f"Balance reset for user {growid}")

        except Exception as e:
            self.logger.error(f"Error resetting user: {e}")
            await ctx.send(f"❌ Error: {str(e)}")
        finally:
            if conn:
                conn.close()

    @commands.command(name="transactions")
    async def view_transactions(self, ctx, growid: str, limit: int = 10):
        """
        View a user's transaction history
        
        Parameters:
        - growid: User's Growtopia ID
        - limit: Number of transactions to show (default: 10)
        """
        try:
            if not await self._check_admin(ctx):
                return

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT type, amount, details, timestamp
                FROM transaction_log
                WHERE growid = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (growid, limit))

            transactions = cursor.fetchall()
            if not transactions:
                await ctx.send(f"❌ No transactions found for {growid}!")
                return

            embed = discord.Embed(
                title=f"Transaction History - {growid}",
                color=discord.Color.blue()
            )

            for tx_type, amount, details, timestamp in transactions:
                embed.add_field(
                    name=f"{tx_type} - {timestamp}",
                    value=f"Amount: {amount:,} WLs\nDetails: {details}",
                    inline=False
                )

            await ctx.send(embed=embed)
            self.logger.info(f"Transactions viewed for user {growid}")

        except Exception as e:
            self.logger.error(f"Error viewing transactions: {e}")
            await ctx.send(f"❌ Error: {str(e)}")
        finally:
            if conn:
                conn.close()

async def setup(bot):
    await bot.add_cog(AdminCog(bot))