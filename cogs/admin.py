import discord
from discord.ext import commands
import logging
import datetime
from main import is_admin
from database import get_connection, add_balance, subtract_balance
from ext.product_manager import ProductManager
from ext.balance_manager import BalanceManager
from ext.trx import TransactionCog

# Konfigurasi logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DATABASE = 'store.db'

class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.current_time = CURRENT_TIME
        self._last_command = {}  # Untuk mencegah duplikasi command
        self.product_manager = ProductManager(bot)
        self.balance_manager = BalanceManager(bot)
        self.transaction = TransactionCog(bot)

    def db_connect(self):
        """Membuat koneksi ke database"""
        return get_connection()

    async def check_duplicate_command(self, ctx, command_name, timeout=3):
        """Mencegah duplikasi command dalam waktu tertentu"""
        current_time = CURRENT_TIME.timestamp()
        user_last_command = self._last_command.get(ctx.author.id, {})
        
        if command_name in user_last_command:
            last_time = user_last_command[command_name]
            if current_time - last_time < timeout:
                await ctx.send("⚠️ Please wait a moment before using this command again.")
                return True

        user_last_command[command_name] = current_time
        self._last_command[ctx.author.id] = user_last_command
        return False

    @commands.command()
    @is_admin()
    async def addProduct(self, ctx, name: str, code: str, price: int, description: str = ""):
        """
        Menambahkan produk baru
        Usage: !addProduct <name> <code> <price> [description]
        """
        if await self.check_duplicate_command(ctx, 'addProduct'):
            return

        logging.info(f'addProduct command invoked by {ctx.author}')
        result = await self.product_manager.add_product(ctx, code, name, price, description)
        if isinstance(result, discord.Embed):
            await ctx.send(embed=result)
        else:
            await ctx.send(result)

    @commands.command()
    @is_admin()
    async def addStock(self, ctx, product_code: str, *, file_path: str = None):
        """
        Menambahkan stock dari file
        Usage: !addStock <product_code> [file_path]
        """
        if await self.check_duplicate_command(ctx, 'addStock'):
            return

        logging.info(f'addStock command invoked by {ctx.author}')
        result = await self.transaction.add_stock_from_file(ctx, product_code, file_path)
        if isinstance(result, discord.Embed):
            await ctx.send(embed=result)
        else:
            await ctx.send(result)

    @commands.command()
    @is_admin()
    async def addBal(self, ctx, growid: str, wl: int = 0, dl: int = 0, bgl: int = 0):
        """
        Menambah balance user
        Usage: !addBal <growid> <wl> [dl] [bgl]
        """
        if await self.check_duplicate_command(ctx, 'addBal'):
            return

        logging.info(f'addBal command invoked by {ctx.author}')
        result = await self.balance_manager.add_balance(ctx, growid, wl, dl, bgl)
        if isinstance(result, discord.Embed):
            await ctx.send(embed=result)
        else:
            await ctx.send(result)

    @commands.command()
    @is_admin()
    async def reduceBal(self, ctx, growid: str, wl: int = 0, dl: int = 0, bgl: int = 0):
        """
        Mengurangi balance user
        Usage: !reduceBal <growid> <wl> [dl] [bgl]
        """
        if await self.check_duplicate_command(ctx, 'reduceBal'):
            return

        logging.info(f'reduceBal command invoked by {ctx.author}')
        result = await self.balance_manager.remove_balance(ctx, growid, wl, dl, bgl)
        if isinstance(result, discord.Embed):
            await ctx.send(embed=result)
        else:
            await ctx.send(result)

    @commands.command()
    @is_admin()
    async def changePrice(self, ctx, code: str, new_price: int):
        """
        Mengubah harga produk
        Usage: !changePrice <code> <new_price>
        """
        if await self.check_duplicate_command(ctx, 'changePrice'):
            return

        logging.info(f'changePrice command invoked by {ctx.author}')
        result = await self.product_manager.edit_product(ctx, code, price=new_price)
        if isinstance(result, discord.Embed):
            await ctx.send(embed=result)
        else:
            await ctx.send(result)

    @commands.command()
    @is_admin()
    async def setDescription(self, ctx, code: str, *, description: str):
        """
        Mengubah deskripsi produk
        Usage: !setDescription <code> <description>
        """
        if await self.check_duplicate_command(ctx, 'setDescription'):
            return

        logging.info(f'setDescription command invoked by {ctx.author}')
        result = await self.product_manager.edit_product(ctx, code, description=description)
        if isinstance(result, discord.Embed):
            await ctx.send(embed=result)
        else:
            await ctx.send(result)

    @commands.command()
    @is_admin()
    async def setWorld(self, ctx, world: str, owner: str, bot_name: str):
        """
        Mengatur informasi world
        Usage: !setWorld <world> <owner> <bot_name>
        """
        if await self.check_duplicate_command(ctx, 'setWorld'):
            return

        logging.info(f'setWorld command invoked by {ctx.author}')
        try:
            conn = self.db_connect()
            if conn is None:
                await ctx.send("❌ Database connection failed.")
                return

            cursor = conn.cursor()
            
            # Update atau insert world info
            cursor.execute("""
                INSERT OR REPLACE INTO world_info (id, world, owner, bot, updated_at)
                VALUES (1, ?, ?, ?, ?)
            """, (world, owner, bot_name, self.current_time))
            
            conn.commit()
            
            embed = discord.Embed(
                title="✅ World Info Updated",
                color=discord.Color.green(),
                timestamp=self.current_time
            )
            embed.add_field(name="World", value=world, inline=True)
            embed.add_field(name="Owner", value=owner, inline=True)
            embed.add_field(name="Bot", value=bot_name, inline=True)
            embed.add_field(name="Updated At", value=self.current_time.strftime('%Y-%m-%d %H:%M:%S UTC'), inline=False)
            embed.set_footer(text=f"Updated by {ctx.author} | {CURRENT_USER}")
            
            await ctx.send(embed=embed)
            logger.info(f'World info updated to {world}/{owner}/{bot_name} by {ctx.author}')
            
        except Exception as e:
            logger.error(f'Error in setWorld: {e}')
            await ctx.send(f"❌ An error occurred: {e}")
            
        finally:
            if conn:
                conn.close()

    @commands.command()
    @is_admin()
    async def send(self, ctx, user: discord.User, code: str, count: int):
        """
        Mengirim produk ke user
        Usage: !send <@user> <product_code> <count>
        """
        if await self.check_duplicate_command(ctx, 'send'):
            return

        logging.info(f'send command invoked by {ctx.author}')
        result = await self.transaction.process_purchase(user, code, count)
        if isinstance(result, discord.Embed):
            await ctx.send(embed=result)
        else:
            await ctx.send(result)

    @commands.command()
    @is_admin()
    async def checkStock(self, ctx, product_code: str):
        """
        Memeriksa status stok produk
        Usage: !checkStock <product_code>
        """
        if await self.check_duplicate_command(ctx, 'checkStock'):
            return

        logging.info(f'checkStock command invoked by {ctx.author}')
        result = await self.product_manager.view_stock_details(ctx, product_code)
        if isinstance(result, discord.Embed):
            await ctx.send(embed=result)
        else:
            await ctx.send(result)

    @commands.command()
    @is_admin()
    async def clearChat(self, ctx, amount: int = None):
        """
        Membersihkan pesan dalam channel
        Usage: !clearChat [amount]
        """
        if await self.check_duplicate_command(ctx, 'clearChat'):
            return

        try:
            # Delete command message first
            await ctx.message.delete()

            if amount is None:
                messages = []
                async for message in ctx.channel.history(limit=None):
                    messages.append(message)
                
                if not messages:
                    error_msg = await ctx.send("❌ No messages to delete!")
                    await error_msg.delete(delay=3)
                    return

                while messages:
                    chunk = messages[:100]
                    messages = messages[100:]
                    await ctx.channel.delete_messages(chunk)
                
                confirm_msg = await ctx.send("✅ All messages have been cleared!")
                await confirm_msg.delete(delay=3)
            else:
                if amount < 1:
                    error_msg = await ctx.send("❌ Please specify a positive number!")
                    await error_msg.delete(delay=3)
                    return
                
                deleted = await ctx.channel.purge(limit=amount)
                confirm_msg = await ctx.send(f"✅ Deleted {len(deleted)} messages!")
                await confirm_msg.delete(delay=3)

            logger.info(
                f'Chat cleared in #{ctx.channel.name} by {ctx.author} ({CURRENT_USER}) '
                f'at {self.current_time.strftime("%Y-%m-%d %H:%M:%S UTC")}'
            )

        except discord.Forbidden:
            error_msg = await ctx.send("❌ I don't have permission to delete messages!")
            await error_msg.delete(delay=3)
        except discord.HTTPException as e:
            error_msg = await ctx.send(f"❌ An error occurred: {str(e)}")
            await error_msg.delete(delay=3)
            logger.error(f'Error in clearChat: {e}')
        except Exception as e:
            error_msg = await ctx.send("❌ An unexpected error occurred!")
            await error_msg.delete(delay=3)
            logger.error(f'Unexpected error in clearChat: {e}')

async def setup(bot):
    await bot.add_cog(AdminCommands(bot))