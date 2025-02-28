import discord
from discord.ext import commands, tasks
from discord.ui import Button, Modal, TextInput, View
import logging
from datetime import datetime
import asyncio
from database import get_connection
from ext.product_manager import ProductManager
from ext.balance_manager import BalanceManager
from ext.trx import TransactionCog
from ext.constants import Balance, CURRENCY_RATES, MAX_ITEMS_PER_MESSAGE
import json
from typing import Optional, Dict, Any

# Load config
with open('config.json') as config_file:
    config = json.load(config_file)

LIVE_STOCK_CHANNEL_ID = int(config['id_live_stock'])
COOLDOWN_SECONDS = 3
UPDATE_INTERVAL = 55  # Seconds between updates

def format_datetime() -> str:
    """Get current datetime in UTC"""
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

class BuyModal(Modal):
    def __init__(self, bot):
        super().__init__(title="Buy Product")
        self.bot = bot
        self.transaction = TransactionCog(bot)
        
        self.product_code = TextInput(
            label="Product Code",
            placeholder="Enter product code",
            required=True,
            min_length=1,
            max_length=10,
            custom_id="product_code"
        )
        
        self.quantity = TextInput(
            label="Quantity", 
            placeholder="Enter quantity",
            required=True,
            min_length=1,
            max_length=3,
            custom_id="quantity"
        )
        
        self.add_item(self.product_code)
        self.add_item(self.quantity)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            quantity = int(self.quantity.value)
            if quantity <= 0:
                await interaction.response.send_message(
                    "❌ Quantity must be positive.", 
                    ephemeral=True
                )
                return
                
            result = await self.transaction.process_purchase(
                interaction.user, 
                self.product_code.value.upper(), 
                quantity
            )
            
            if isinstance(result, discord.Embed):
                await interaction.response.send_message(
                    embed=result, 
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    result, 
                    ephemeral=True
                )
            
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid quantity.", 
                ephemeral=True
            )
        except Exception as e:
            logging.error(f"Error in BuyModal: {e}")
            await interaction.response.send_message(
                f"❌ An error occurred: {str(e)}", 
                ephemeral=True
            )

class SetGrowIDModal(Modal):
    def __init__(self, bot):
        super().__init__(title="Set GrowID")
        self.bot = bot
        
        self.growid = TextInput(
            label="GrowID",
            placeholder="Enter your GrowID",
            required=True,
            min_length=3,
            max_length=20,
            custom_id="growid"
        )
        
        self.add_item(self.growid)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            growid = self.growid.value.strip()
            
            if not growid.isalnum():
                await interaction.response.send_message(
                    "❌ GrowID must contain only letters and numbers.", 
                    ephemeral=True
                )
                return
            
            conn = None
            try:
                conn = get_connection()
                cursor = conn.cursor()
                
                # Check if GrowID already registered to another user
                cursor.execute(
                    "SELECT user_id FROM user_growid WHERE growid = ? AND user_id != ?",
                    (growid, interaction.user.id)
                )
                if cursor.fetchone():
                    await interaction.response.send_message(
                        "❌ This GrowID is already registered to another user.",
                        ephemeral=True
                    )
                    return
                
                cursor.execute(
                    "INSERT OR REPLACE INTO user_growid (user_id, growid) VALUES (?, ?)",
                    (interaction.user.id, growid)
                )
                cursor.execute(
                    "INSERT OR IGNORE INTO users (growid) VALUES (?)",
                    (growid,)
                )
                conn.commit()
                
                embed = discord.Embed(
                    title="✅ GrowID Set Successfully",
                    description=f"Your GrowID has been set to: `{growid}`",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.set_footer(text=f"Set by: {interaction.user}")
                
                await interaction.response.send_message(
                    embed=embed, 
                    ephemeral=True
                )
                logging.info(f"GrowID set for {interaction.user}: {growid}")
                
            except Exception as e:
                if conn:
                    conn.rollback()
                raise e
            
            finally:
                if conn:
                    conn.close()
            
        except Exception as e:
            logging.error(f'Error in SetGrowIDModal: {e}')
            await interaction.response.send_message(
                f"❌ An error occurred: {str(e)}", 
                ephemeral=True
            )

class PersistentView(View):
    def __init__(self):
        super().__init__(timeout=None)

class StockView(PersistentView):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self._last_use: Dict[int, float] = {}
        self._cache_timeout = 300  # 5 minutes cache timeout
        self._cache: Dict[str, Any] = {}
        self.balance_manager = BalanceManager(bot)
        self.transaction = TransactionCog(bot)
        
        # Initialize buttons
        self._init_buttons()

    def _init_buttons(self):
        """Initialize all buttons with their properties"""
        buttons_config = [
            {
                "name": "balance",
                "label": "Check Balance",
                "style": discord.ButtonStyle.secondary,
                "emoji": "💰",
                "callback": self.button_balance_callback
            },
            {
                "name": "buy",
                "label": "Buy",
                "style": discord.ButtonStyle.primary,
                "emoji": "🛒",
                "callback": self.button_buy_callback
            },
            {
                "name": "set_growid",
                "label": "Set GrowID",
                "style": discord.ButtonStyle.success,
                "emoji": "📝",
                "callback": self.button_set_growid_callback
            },
            {
                "name": "check_growid",
                "label": "Check GrowID",
                "style": discord.ButtonStyle.secondary,
                "emoji": "🔍",
                "callback": self.button_check_growid_callback
            },
            {
                "name": "world",
                "label": "World Info",
                "style": discord.ButtonStyle.secondary,
                "emoji": "🌍",
                "callback": self.button_world_callback
            }
        ]

        for btn_config in buttons_config:
            button = Button(
                label=btn_config["label"],
                style=btn_config["style"],
                emoji=btn_config["emoji"],
                custom_id=f"button_{btn_config['name']}"
            )
            button.callback = btn_config["callback"]
            self.add_item(button)

    async def check_cooldown(self, interaction: discord.Interaction) -> bool:
        """Check if user is on cooldown"""
        current_time = datetime.utcnow().timestamp()
        last_use = self._last_use.get(interaction.user.id, 0)
        
        if current_time - last_use < COOLDOWN_SECONDS:
            await interaction.response.send_message(
                "⚠️ Please wait a few seconds before using buttons again.", 
                ephemeral=True
            )
            return False
        
        self._last_use[interaction.user.id] = current_time
        return True

    async def get_user_growid(self, user_id: int) -> Optional[str]:
        """Get user's GrowID from cache or database"""
        cache_key = f"growid_{user_id}"
        
        # Check cache
        if cache_key in self._cache:
            cache_time, growid = self._cache[cache_key]
            if datetime.utcnow().timestamp() - cache_time < self._cache_timeout:
                return growid
        
        # Get from database
        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT growid FROM user_growid WHERE user_id = ?", 
                (user_id,)
            )
            result = cursor.fetchone()
            
            if result:
                growid = result[0]
                # Update cache
                self._cache[cache_key] = (datetime.utcnow().timestamp(), growid)
                return growid
            return None
            
        finally:
            if conn:
                conn.close()

    async def button_balance_callback(self, interaction: discord.Interaction):
        if not await self.check_cooldown(interaction):
            return

        try:
            growid = await self.get_user_growid(interaction.user.id)
            
            if growid:
                balance = await self.balance_manager.get_user_balance(growid)
                if balance:
                    embed = discord.Embed(
                        title="💰 Your Balance",
                        color=discord.Color.green(),
                        timestamp=datetime.utcnow()
                    )
                    embed.add_field(name="GrowID", value=growid, inline=False)
                    embed.add_field(
                        name="Balance", 
                        value=balance.format(), 
                        inline=False
                    )
                    embed.set_footer(text=f"Checked by: {interaction.user}")
                    
                    await interaction.response.send_message(
                        embed=embed, 
                        ephemeral=True
                    )
                    logging.info(f"Balance checked for {growid}")
                else:
                    await interaction.response.send_message(
                        "❌ No balance found for your account.", 
                        ephemeral=True
                    )
            else:
                await interaction.response.send_message(
                    "❌ No GrowID found for your account.", 
                    ephemeral=True
                )

        except Exception as e:
            logging.error(f"Error checking balance: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while checking balance.", 
                ephemeral=True
            )

    async def button_buy_callback(self, interaction: discord.Interaction):
        if not await self.check_cooldown(interaction):
            return
            
        try:
            growid = await self.get_user_growid(interaction.user.id)
            
            if not growid:
                await interaction.response.send_message(
                    "❌ Please set your GrowID first!", 
                    ephemeral=True
                )
                return
                
            modal = BuyModal(self.bot)
            await interaction.response.send_modal(modal)
            logging.info(f"Buy modal opened by {interaction.user}")
            
        except Exception as e:
            logging.error(f"Error in buy callback: {e}")
            await interaction.response.send_message(
                "❌ An error occurred.", 
                ephemeral=True
            )

    async def button_set_growid_callback(self, interaction: discord.Interaction):
        if not await self.check_cooldown(interaction):
            return
        try:
            modal = SetGrowIDModal(self.bot)
            await interaction.response.send_modal(modal)
            logging.info(f"Set GrowID modal opened by {interaction.user}")
        except Exception as e:
            logging.error(f"Error in set GrowID callback: {e}")
            await interaction.response.send_message(
                "❌ An error occurred.", 
                ephemeral=True
            )

    async def button_check_growid_callback(self, interaction: discord.Interaction):
        if not await self.check_cooldown(interaction):
            return

        try:
            growid = await self.get_user_growid(interaction.user.id)
            
            if growid:
                embed = discord.Embed(
                    title="🔍 GrowID Information",
                    description=f"Your registered GrowID: `{growid}`",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                embed.set_footer(text=f"Checked by: {interaction.user}")
                await interaction.response.send_message(
                    embed=embed, 
                    ephemeral=True
                )
                logging.info(f"GrowID checked for {interaction.user}")
            else:
                await interaction.response.send_message(
                    "❌ No GrowID registered for your account.", 
                    ephemeral=True
                )
                
        except Exception as e:
            logging.error(f"Error checking GrowID: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while checking GrowID.", 
                ephemeral=True
            )

    async def button_world_callback(self, interaction: discord.Interaction):
        if not await self.check_cooldown(interaction):
            return

        try:
            cache_key = "world_info"
            current_time = datetime.utcnow().timestamp()
            
            # Check cache
            if cache_key in self._cache:
                cache_time, world_info = self._cache[cache_key]
                if current_time - cache_time < self._cache_timeout:
                    embed = self._create_world_info_embed(world_info)
                    await interaction.response.send_message(
                        embed=embed, 
                        ephemeral=True
                    )
                    return
            
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT world, owner, bot FROM world_info WHERE id = 1"
            )
            world_info = cursor.fetchone()
            conn.close()
            
            if world_info:
                # Update cache
                self._cache[cache_key] = (current_time, world_info)
                embed = self._create_world_info_embed(world_info)
                await interaction.response.send_message(
                    embed=embed, 
                    ephemeral=True
                )
                logging.info(f"World info checked by {interaction.user}")
            else:
                await interaction.response.send_message(
                    "❌ No world information available.", 
                    ephemeral=True
                )
                
        except Exception as e:
            logging.error(f"Error checking world info: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while checking world info.", 
                ephemeral=True
            )

    def _create_world_info_embed(self, world_info):
        """Create embed for world info"""
        world, owner, bot_name = world_info
        embed = discord.Embed(
            title="🌍 World Information",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="World", value=f"`{world}`", inline=True)
        embed.add_field(name="Owner", value=f"`{owner}`", inline=True)
        embed.add_field(name="Bot", value=f"`{bot_name}`", inline=True)
        return embed

class LiveStock(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.message_id = None
        self.update_lock = asyncio.Lock()
        self.last_update = 0
        self.stock_view = StockView(bot)
        self.product_manager = ProductManager(bot)
        self.balance_manager = BalanceManager(bot)
        self.transaction = TransactionCog(bot)
        self._cache = {}
        self._cache_timeout = 300  # 5 minutes
        self.live_stock.start()

    def db_connect(self):
        return get_connection()

    def cog_unload(self):
        self.live_stock.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(self.stock_view)
        logging.info("LiveStock cog is ready")

    async def _get_cached_products(self):
        """Get products from cache or database"""
        current_time = datetime.utcnow().timestamp()
        
        if 'products' in self._cache:
            cache_time, products = self._cache['products']
            if current_time - cache_time < self._cache_timeout:
                return products
                
        products = await self.product_manager.get_all_products()
        self._cache['products'] = (current_time, products)
        return products

    async def _get_cached_world_info(self):
        """Get world info from cache or database"""
        current_time = datetime.utcnow().timestamp()
        
        if 'world_info' in self._cache:
            cache_time, world_info = self._cache['world_info']
            if current_time - cache_time < self._cache_timeout:
                return world_info
                
        conn = self.db_connect()
        cursor = conn.cursor()
        cursor.execute("SELECT world, owner, bot FROM world_info WHERE id = 1")
        world_info = cursor.fetchone()
        conn.close()
        
        if world_info:
            self._cache['world_info'] = (current_time, world_info)
        return world_info

    def _create_stock_embed(self, products, world_info) -> discord.Embed:
        """Create embed for stock display"""
        embed = discord.Embed(
            title="🏪 Store Stock Status",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )

        if world_info:
            world, owner, bot_name = world_info
            embed.add_field(
                name="🌍 World Information",
                value=(
                    f"World: `{world}`\n"
                    f"Owner: `{owner}`\n"
                    f"Bot: `{bot_name}`"
                ),
                inline=False
            )

        if products:
            for product in products:
                code = product['code']
                name = product['name']
                price = product['price']
                stock = product['stock']
                description = product.get('description', '')
                
                # Format product field
                value = (
                    f"💎 Code: `{code}`\n"
                    f"📦 Stock: `{stock}`\n"
                    f"💰 Price: `{price:,} WL`\n"
                )
                if description:
                    value += f"📝 Info: {description}\n"
                
                embed.add_field(
                    name=f"🔸 {name} 🔸",
                    value=value,
                    inline=False
                )
        else:
            embed.description = "No products available."

        embed.set_footer(text=f"Last Update: {format_datetime()} UTC")
        return embed

    @tasks.loop(minutes=1)
    async def live_stock(self):
        if not self.update_lock.locked():
            async with self.update_lock:
                try:
                    current_time = datetime.utcnow().timestamp()
                    if current_time - self.last_update < UPDATE_INTERVAL:
                        return
                    self.last_update = current_time
                    
                    channel = self.bot.get_channel(LIVE_STOCK_CHANNEL_ID)
                    if not channel:
                        logging.error('Live stock channel not found')
                        return

                    try:
                        # Get cached data
                        products = await self._get_cached_products()
                        world_info = await self._get_cached_world_info()
                        
                        # Create embed
                        embed = self._create_stock_embed(products, world_info)

                        # Update or send message
                        if self.message_id:
                            try:
                                message = await channel.fetch_message(self.message_id)
                                await message.edit(embed=embed, view=self.stock_view)
                                logging.info(f"Stock message updated at {format_datetime()}")
                            except discord.NotFound:
                                message = await channel.send(embed=embed, view=self.stock_view)
                                self.message_id = message.id
                                logging.info(f"New stock message created at {format_datetime()}")
                        else:
                            message = await channel.send(embed=embed, view=self.stock_view)
                            self.message_id = message.id
                            logging.info(f"Initial stock message created at {format_datetime()}")

                    except Exception as e:
                        logging.error(f"Error updating stock message: {e}")
                        if self.message_id:
                            try:
                                message = await channel.fetch_message(self.message_id)
                                await message.edit(
                                    content="❌ Error updating stock information. Please try again later."
                                )
                            except:
                                pass
                        self.message_id = None

                except Exception as e:
                    logging.error(f"Error in live_stock task: {e}")

    @live_stock.before_loop
    async def before_live_stock(self):
        """Wait for bot to be ready before starting the loop"""
        await self.bot.wait_until_ready()
        logging.info("Live stock loop is ready to start")

    @live_stock.error
    async def live_stock_error(self, error):
        """Handle errors in the live_stock task"""
        logging.error(f"Error in live_stock task: {error}")
        
async def setup(bot):
    await bot.add_cog(LiveStock(bot))