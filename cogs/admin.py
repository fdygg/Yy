import discord
from discord.ext import commands
import logging
from datetime import datetime
from typing import Optional, List
from decimal import Decimal

from database import get_connection
from ext.constants import Balance, TransactionError, CURRENCY_RATES  # Perbaikan import
from ext.balance_manager import BalanceManager  # Perbaikan import

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._init_logger()
        self.balance_manager = BalanceManager(bot)
        logger = logging.getLogger(__name__)
        logger.info(f"AdminCog initialized at {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")

    def _init_logger(self):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    async def _check_admin(self, ctx: commands.Context) -> bool:
        """Check if user has admin permissions"""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ You don't have permission to use this command!")
            return False
        return True

    @commands.group(name="admin")
    @commands.has_permissions(administrator=True)
    async def admin(self, ctx):
        """Admin commands group"""
        if ctx.invoked_subcommand is None:
            await ctx.send("❌ Invalid admin command. Use `!help admin` for available commands.")

    @admin.command(name="addproduct")
    async def add_product(
        self, 
        ctx, 
        code: str, 
        name: str, 
        price: int, 
        *, 
        description: str = "No description"
    ):
        """Add a new product"""
        try:
            if not await self._check_admin(ctx):
                return

            conn = get_connection()
            cursor = conn.cursor()

            # Check if product exists
            cursor.execute(
                "SELECT code FROM products WHERE code = ?", 
                (code,)
            )
            if cursor.fetchone():
                await ctx.send(f"❌ Product with code {code} already exists!")
                return

            # Add product
            cursor.execute("""
                INSERT INTO products (
                    code, name, price, description, stock, active
                ) VALUES (?, ?, ?, ?, 0, 1)
            """, (code, name, price, description))

            conn.commit()

            embed = discord.Embed(
                title="✅ Product Added",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Code", value=code, inline=True)
            embed.add_field(name="Name", value=name, inline=True)
            embed.add_field(name="Price", value=f"{price:,} WLs", inline=True)
            embed.add_field(name="Description", value=description, inline=False)
            embed.set_footer(text=f"Added by {ctx.author}")

            await ctx.send(embed=embed)

        except Exception as e:
            self.logger.error(f"Error adding product: {e}")
            await ctx.send(f"❌ Error: {str(e)}")
        finally:
            if conn:
                conn.close()
                
    @admin.command(name="editproduct")
    async def edit_product(
        self, 
        ctx, 
        code: str, 
        field: str, 
        *, 
        value: str
    ):
        """Edit a product's details"""
        try:
            if not await self._check_admin(ctx):
                return

            valid_fields = ['name', 'price', 'description', 'active']
            if field.lower() not in valid_fields:
                await ctx.send(
                    f"❌ Invalid field. Valid fields: {', '.join(valid_fields)}"
                )
                return

            conn = get_connection()
            cursor = conn.cursor()

            # Check if product exists
            cursor.execute(
                "SELECT * FROM products WHERE code = ?", 
                (code,)
            )
            product = cursor.fetchone()
            if not product:
                await ctx.send(f"❌ Product {code} not found!")
                return

            # Update product
            if field.lower() == 'price':
                try:
                    value = int(value)
                except ValueError:
                    await ctx.send("❌ Price must be a number!")
                    return
            elif field.lower() == 'active':
                value = int(value.lower() in ['true', '1', 'yes'])

            cursor.execute(
                f"UPDATE products SET {field.lower()} = ? WHERE code = ?",
                (value, code)
            )
            conn.commit()

            embed = discord.Embed(
                title="✅ Product Updated",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Code", value=code, inline=True)
            embed.add_field(name="Field", value=field, inline=True)
            embed.add_field(name="New Value", value=str(value), inline=True)
            embed.set_footer(text=f"Updated by {ctx.author}")

            await ctx.send(embed=embed)

        except Exception as e:
            self.logger.error(f"Error editing product: {e}")
            await ctx.send(f"❌ Error: {str(e)}")
        finally:
            if conn:
                conn.close()

    @admin.command(name="deleteproduct")
    async def delete_product(self, ctx, code: str):
        """Delete a product"""
        try:
            if not await self._check_admin(ctx):
                return

            conn = get_connection()
            cursor = conn.cursor()

            # Check if product exists
            cursor.execute(
                "SELECT name FROM products WHERE code = ?", 
                (code,)
            )
            product = cursor.fetchone()
            if not product:
                await ctx.send(f"❌ Product {code} not found!")
                return

            # Check for confirmation
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

            # Delete product
            cursor.execute(
                "DELETE FROM products WHERE code = ?", 
                (code,)
            )
            conn.commit()

            embed = discord.Embed(
                title="✅ Product Deleted",
                description=f"Product {code} ({product[0]}) has been deleted.",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text=f"Deleted by {ctx.author}")

            await ctx.send(embed=embed)

        except Exception as e:
            self.logger.error(f"Error deleting product: {e}")
            await ctx.send(f"❌ Error: {str(e)}")
        finally:
            if conn:
                conn.close()

    @admin.command(name="addbalance")
    async def add_balance(
        self, 
        ctx, 
        growid: str, 
        amount: int, 
        currency: str
    ):
        """Add balance to a user"""
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
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
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

        except TransactionError as e:
            await ctx.send(f"❌ {str(e)}")
        except Exception as e:
            self.logger.error(f"Error adding balance: {e}")
            await ctx.send(f"❌ Error: {str(e)}")

    @admin.command(name="removebalance")
    async def remove_balance(
        self, 
        ctx, 
        growid: str, 
        amount: int, 
        currency: str
    ):
        """Remove balance from a user"""
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
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
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

        except TransactionError as e:
            await ctx.send(f"❌ {str(e)}")
        except Exception as e:
            self.logger.error(f"Error removing balance: {e}")
            await ctx.send(f"❌ Error: {str(e)}")

    @admin.command(name="checkbalance")
    async def check_balance(self, ctx, growid: str):
        """Check a user's balance"""
        try:
            if not await self._check_admin(ctx):
                return

            balance = await self.balance_manager.get_user_balance(growid)
            embed = discord.Embed(
                title=f"Balance for {growid}",
                description=balance.format(),
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            await ctx.send(embed=embed)

        except TransactionError as e:
            await ctx.send(f"❌ {str(e)}")
        except Exception as e:
            self.logger.error(f"Error checking balance: {e}")
            await ctx.send(f"❌ Error: {str(e)}")

    @admin.command(name="transactions")
    async def view_transactions(
        self, 
        ctx, 
        growid: str, 
        limit: int = 10
    ):
        """View recent transactions for a user"""
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
                await ctx.send(f"❌ No transactions found for {growid}")
                return

            embed = discord.Embed(
                title=f"Recent Transactions for {growid}",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )

            for tx_type, amount, details, timestamp in transactions:
                embed.add_field(
                    name=f"{tx_type} - {timestamp}",
                    value=f"Amount: {amount:,} WLs\nDetails: {details}",
                    inline=False
                )

            await ctx.send(embed=embed)

        except Exception as e:
            self.logger.error(f"Error viewing transactions: {e}")
            await ctx.send(f"❌ Error: {str(e)}")
        finally:
            if conn:
                conn.close()

    @admin.command(name="stock")
    async def view_stock(self, ctx, product_code: str = None):
        """View product stock"""
        try:
            if not await self._check_admin(ctx):
                return

            conn = get_connection()
            cursor = conn.cursor()

            if product_code:
                # View specific product stock
                cursor.execute("""
                    SELECT p.name, p.price, p.stock, p.description, p.active
                    FROM products p
                    WHERE p.code = ?
                """, (product_code,))
                
                product = cursor.fetchone()
                if not product:
                    await ctx.send(f"❌ Product {product_code} not found!")
                    return

                name, price, stock, desc, active = product
                
                embed = discord.Embed(
                    title=f"Stock Details - {product_code}",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Name", value=name, inline=True)
                embed.add_field(name="Price", value=f"{price:,} WLs", inline=True)
                embed.add_field(name="Stock", value=stock, inline=True)
                embed.add_field(name="Description", value=desc, inline=False)
                embed.add_field(name="Status", value="Active" if active else "Inactive", inline=True)

            else:
                # View all products stock
                cursor.execute("""
                    SELECT code, name, price, stock, active
                    FROM products
                    ORDER BY price ASC
                """)
                
                products = cursor.fetchall()
                if not products:
                    await ctx.send("❌ No products found!")
                    return

                embed = discord.Embed(
                    title="Current Stock Status",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )

                for code, name, price, stock, active in products:
                    status = "🟢" if active else "🔴"
                    embed.add_field(
                        name=f"{status} {name} ({code})",
                        value=f"Price: {price:,} WLs\nStock: {stock}",
                        inline=True
                    )
            # Lanjutan dari view_stock command
            await ctx.send(embed=embed)

        except Exception as e:
            self.logger.error(f"Error viewing stock: {e}")
            await ctx.send(f"❌ Error: {str(e)}")
        finally:
            if conn:
                conn.close()

    @admin.command(name="stockhistory")
    async def view_stock_history(
        self, 
        ctx, 
        product_code: str, 
        limit: int = 10
    ):
        """View stock addition history"""
        try:
            if not await self._check_admin(ctx):
                return

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT ps.content, ps.added_by, ps.added_at, ps.used, 
                       ps.used_by, ps.used_at, ps.buyer_growid
                FROM product_stock ps
                WHERE ps.product_code = ?
                ORDER BY ps.added_at DESC
                LIMIT ?
            """, (product_code, limit))

            items = cursor.fetchall()
            if not items:
                await ctx.send(f"❌ No stock history found for {product_code}")
                return

            embed = discord.Embed(
                title=f"Stock History - {product_code}",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )

            for content, added_by, added_at, used, used_by, used_at, buyer in items:
                status = "🔴 Sold" if used else "🟢 Available"
                value = (
                    f"Added by: {added_by}\n"
                    f"Added at: {added_at}\n"
                    f"Status: {status}\n"
                )
                if used:
                    value += (
                        f"Buyer: {buyer}\n"
                        f"Used by: {used_by}\n"
                        f"Used at: {used_at}"
                    )

                embed.add_field(
                    name=f"Item {content[:20]}...",
                    value=value,
                    inline=False
                )

            await ctx.send(embed=embed)

        except Exception as e:
            self.logger.error(f"Error viewing stock history: {e}")
            await ctx.send(f"❌ Error: {str(e)}")
        finally:
            if conn:
                conn.close()

    @admin.command(name="stats")
    async def view_stats(self, ctx, days: int = 7):
        """View system statistics"""
        try:
            if not await self._check_admin(ctx):
                return

            conn = get_connection()
            cursor = conn.cursor()

            # Get transaction stats
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_tx,
                    SUM(CASE WHEN type = 'PURCHASE' THEN 1 ELSE 0 END) as purchases,
                    SUM(CASE WHEN type = 'DONATION' THEN 1 ELSE 0 END) as donations,
                    SUM(amount) as total_amount
                FROM transaction_log
                WHERE timestamp >= datetime('now', ?)
            """, (f'-{days} days',))

            tx_stats = cursor.fetchone()

            # Get product stats
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_products,
                    SUM(stock) as total_stock,
                    SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) as active_products
                FROM products
            """)

            prod_stats = cursor.fetchone()

            # Get user stats
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_users,
                    SUM(balance_wl + balance_dl * 100 + balance_bgl * 10000) as total_balance
                FROM users
            """)

            user_stats = cursor.fetchone()

            embed = discord.Embed(
                title=f"System Statistics (Last {days} days)",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )

            # Transaction Stats
            embed.add_field(
                name="Transaction Statistics",
                value=(
                    f"Total Transactions: {tx_stats[0]:,}\n"
                    f"Purchases: {tx_stats[1]:,}\n"
                    f"Donations: {tx_stats[2]:,}\n"
                    f"Total Volume: {tx_stats[3]:,} WLs"
                ),
                inline=False
            )

            # Product Stats
            embed.add_field(
                name="Product Statistics",
                value=(
                    f"Total Products: {prod_stats[0]:,}\n"
                    f"Active Products: {prod_stats[2]:,}\n"
                    f"Total Stock: {prod_stats[1]:,}"
                ),
                inline=False
            )

            # User Stats
            embed.add_field(
                name="User Statistics",
                value=(
                    f"Total Users: {user_stats[0]:,}\n"
                    f"Total Balance: {user_stats[1]:,} WLs"
                ),
                inline=False
            )

            await ctx.send(embed=embed)

        except Exception as e:
            self.logger.error(f"Error viewing stats: {e}")
            await ctx.send(f"❌ Error: {str(e)}")
        finally:
            if conn:
                conn.close()

    @admin.command(name="resetuser")
    async def reset_user(self, ctx, growid: str):
        """Reset a user's balance (Admin only)"""
        try:
            if not await self._check_admin(ctx):
                return

            # Request confirmation
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

            # Reset balance
            conn = get_connection()
            cursor = conn.cursor()

            # Get current balance for logging
            old_balance = await self.balance_manager.get_user_balance(growid)

            # Reset balance to 0
            cursor.execute("""
                UPDATE users 
                SET balance_wl = 0, balance_dl = 0, balance_bgl = 0 
                WHERE growid = ?
            """, (growid,))

            # Log the reset
            cursor.execute("""
                INSERT INTO transaction_log 
                (growid, amount, type, details, old_balance, new_balance)
                VALUES (?, ?, 'ADMIN_RESET', ?, ?, ?)
            """, (
                growid,
                -old_balance.total_wls,
                f"Balance reset by admin {ctx.author}",
                old_balance.format(),
                Balance(0, 0, 0).format()
            ))

            conn.commit()

            embed = discord.Embed(
                title="✅ User Reset",
                description=f"Balance for {growid} has been reset to 0",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(
                name="Old Balance",
                value=old_balance.format(),
                inline=False
            )
            embed.set_footer(text=f"Reset by {ctx.author}")

            await ctx.send(embed=embed)

        except Exception as e:
            self.logger.error(f"Error resetting user: {e}")
            await ctx.send(f"❌ Error: {str(e)}")
        finally:
            if conn:
                conn.close()

async def setup(bot):
    await bot.add_cog(AdminCog(bot))