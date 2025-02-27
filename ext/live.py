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
import json

# Load config
with open('config.json') as config_file:
    config = json.load(config_file)

LIVE_STOCK_CHANNEL_ID = int(config['id_live_stock'])
COOLDOWN_SECONDS = 3

def format_datetime():
    """Get current datetime in UTC"""
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

class BuyModal(Modal):
    def __init__(self, bot):
        super().__init__(title="Buy Product")
        self.bot = bot
        self.transaction = self.bot.get_cog('TransactionCog')
        
        self.product_code = TextInput(
            label="Product Code",
            placeholder="Enter product code",
            required=True,
            min_length=1,
            max_length=10
        )
        
        self.quantity = TextInput(
            label="Quantity", 
            placeholder="Enter quantity",
            required=True,
            min_length=1,
            max_length=3
        )
        
        self.add_item(self.product_code)
        self.add_item(self.quantity)
    
    async def on_submit(self, interaction):
        try:
            quantity = int(self.quantity.value)
            if quantity <= 0:
                await interaction.response.send_message("❌ Quantity must be positive.", ephemeral=True)
                return
                
            if not self.transaction:
                await interaction.response.send_message("❌ Transaction system not available!", ephemeral=True)
                return

            result = await self.transaction.process_purchase(
                interaction.user, 
                self.product_code.value, 
                quantity
            )
            await interaction.response.send_message(result, ephemeral=True)
            
        except ValueError:
            await interaction.response.send_message("❌ Invalid quantity.", ephemeral=True)
        except Exception as e:
            logging.error(f"Error in BuyModal: {e}")
            await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=True)

class SetGrowIDModal(Modal):
    def __init__(self, bot):
        super().__init__(title="Set GrowID")
        self.bot = bot
        
        self.growid = TextInput(
            label="GrowID",
            placeholder="Enter your GrowID",
            required=True,
            min_length=3,
            max_length=20
        )
        
        self.add_item(self.growid)
    
    async def on_submit(self, interaction):
        try:
            growid = self.growid.value.strip()
            
            if not growid.isalnum():
                await interaction.response.send_message(
                    "❌ GrowID must contain only letters and numbers.", 
                    ephemeral=True
                )
                return
            
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO user_growid (user_id, growid) VALUES (?, ?)",
                (interaction.user.id, growid)
            )
            cursor.execute(
                "INSERT OR IGNORE INTO users (growid) VALUES (?)",
                (growid,)
            )
            conn.commit()
            conn.close()
            
            embed = discord.Embed(
                title="✅ GrowID Set Successfully",
                description=f"Your GrowID has been set to: `{growid}`",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text=f"Set by: {interaction.user}")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logging.info(f"GrowID set for {interaction.user}: {growid}")
            
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
        self._last_use = {}
        self.balance_manager = self.bot.get_cog('BalanceManager')
        
        # Add buttons
        self.button_balance = Button(
            label="Check Balance", 
            style=discord.ButtonStyle.secondary, 
            emoji="💰",
            custom_id="check_balance"
        )
        self.button_buy = Button(
            label="Buy", 
            style=discord.ButtonStyle.primary, 
            emoji="🛒",
            custom_id="buy"
        )
        self.button_set_growid = Button(
            label="Set GrowID", 
            style=discord.ButtonStyle.success, 
            emoji="📝",
            custom_id="set_growid"
        )
        self.button_check_growid = Button(
            label="Check GrowID", 
            style=discord.ButtonStyle.secondary, 
            emoji="🔍",
            custom_id="check_growid"
        )
        self.button_world = Button(
            label="World Info", 
            style=discord.ButtonStyle.secondary, 
            emoji="🌍",
            custom_id="world_info"
        )

        # Set callbacks
        self.button_balance.callback = self.button_balance_callback
        self.button_buy.callback = self.button_buy_callback
        self.button_set_growid.callback = self.button_set_growid_callback
        self.button_check_growid.callback = self.button_check_growid_callback
        self.button_world.callback = self.button_world_callback

        # Add buttons to view
        self.add_item(self.button_balance)
        self.add_item(self.button_buy)
        self.add_item(self.button_set_growid)
        self.add_item(self.button_check_growid)
        self.add_item(self.button_world)

    async def check_cooldown(self, interaction: discord.Interaction) -> bool:
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

    async def button_balance_callback(self, interaction: discord.Interaction):
        if not await self.check_cooldown(interaction):
            return

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT growid FROM user_growid WHERE user_id = ?", (interaction.user.id,))
        growid = cursor.fetchone()
        conn.close()
        
        if growid:
            if self.balance_manager:
                balance = await self.balance_manager.get_user_balance(growid[0])
                if balance:
                    balance_wl, balance_dl, balance_bgl = balance
                    total_wls = balance_wl + (balance_dl * 100) + (balance_bgl * 10000)
                    
                    embed = discord.Embed(
                        title="💰 Your Balance",
                        color=discord.Color.green(),
                        timestamp=datetime.utcnow()
                    )
                    embed.add_field(name="GrowID", value=growid[0], inline=False)
                    embed.add_field(name="World Locks", value=f"{balance_wl:,} WL", inline=True)
                    embed.add_field(name="Diamond Locks", value=f"{balance_dl:,} DL", inline=True)
                    embed.add_field(name="Blue Gem Locks", value=f"{balance_bgl:,} BGL", inline=True)
                    embed.add_field(name="Total in WLs", value=f"{total_wls:,} WL", inline=False)
                    embed.set_footer(text=f"Checked by: {interaction.user}")
                    
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    logging.info(f"Balance checked for {growid[0]} by {interaction.user}")
                else:
                    await interaction.response.send_message("❌ No balance found for your account.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Balance system not available!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ No GrowID found for your account.", ephemeral=True)

    async def button_buy_callback(self, interaction: discord.Interaction):
        if not await self.check_cooldown(interaction):
            return
            
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT growid FROM user_growid WHERE user_id = ?", (interaction.user.id,))
        growid = cursor.fetchone()
        conn.close()
        
        if not growid:
            await interaction.response.send_message("❌ Please set your GrowID first!", ephemeral=True)
            return
            
        modal = BuyModal(self.bot)
        await interaction.response.send_modal(modal)
        logging.info(f"Buy modal opened by {interaction.user}")

    async def button_set_growid_callback(self, interaction: discord.Interaction):
        if not await self.check_cooldown(interaction):
            return
        modal = SetGrowIDModal(self.bot)
        await interaction.response.send_modal(modal)
        logging.info(f"Set GrowID modal opened by {interaction.user}")

    async def button_check_growid_callback(self, interaction: discord.Interaction):
        if not await self.check_cooldown(interaction):
            return

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT growid FROM user_growid WHERE user_id = ?", (interaction.user.id,))
        growid = cursor.fetchone()
        conn.close()
        
        if growid:
            embed = discord.Embed(
                title="🔍 GrowID Information",
                description=f"Your registered GrowID: `{growid[0]}`",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text=f"Checked by: {interaction.user}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logging.info(f"GrowID checked for {interaction.user}")
        else:
            await interaction.response.send_message("❌ No GrowID registered for your account.", ephemeral=True)

    async def button_world_callback(self, interaction: discord.Interaction):
        if not await self.check_cooldown(interaction):
            return

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT world, owner, bot FROM world_info WHERE id = 1")
        world_info = cursor.fetchone()
        conn.close()
        
        if world_info:
            world, owner, bot_name = world_info
            embed = discord.Embed(
                title="🌍 World Information",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="World", value=f"`{world}`", inline=True)
            embed.add_field(name="Owner", value=f"`{owner}`", inline=True)
            embed.add_field(name="Bot", value=f"`{bot_name}`", inline=True)
            embed.set_footer(text=f"Checked by: {interaction.user}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logging.info(f"World info checked by {interaction.user}")
        else:
            await interaction.response.send_message("❌ No world information available.", ephemeral=True)

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
        self.live_stock.start()

    def db_connect(self):
        return get_connection()

    def cog_unload(self):
        self.live_stock.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(self.stock_view)

    @tasks.loop(minutes=1)
    async def live_stock(self):
        if not self.update_lock.locked():
            async with self.update_lock:
                current_time = datetime.utcnow().timestamp()
                if current_time - self.last_update < 55:
                    return
                self.last_update = current_time
                
                channel = self.bot.get_channel(LIVE_STOCK_CHANNEL_ID)
                if not channel:
                    logging.error('Live stock channel not found')
                    return

                # Get products directly from database
                conn = self.db_connect()
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT 
                        p.name, 
                        p.code, 
                        COUNT(CASE WHEN ps.used = 0 THEN 1 END) as available_stock,
                        p.price,
                        p.description
                    FROM products p
                    LEFT JOIN product_stock ps ON p.code = ps.product_code
                    GROUP BY p.code
                    ORDER BY p.name
                """)
                products = cursor.fetchall()

                # Get world info
                cursor.execute("SELECT world, owner, bot FROM world_info WHERE id = 1")
                world_info = cursor.fetchone()
                conn.close()

                embed = discord.Embed(
                    title="🏪 Store Stock Status",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )

                if world_info:
                    world, owner, bot_name = world_info
                    embed.add_field(
                        name="🌍 World Information",
                        value=f"World: `{world}`\nOwner: `{owner}`\nBot: `{bot_name}`",
                        inline=False
                    )

                if products:
                    for name, code, stock, price, description in products:
                        value = (
                            f"💎 Code: `{code}`\n"
                            f"📦 Stock: `{stock}`\n"
                            f"💰 Price: `{price} WL`\n"
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

                try:
                    if self.message_id:
                        try:
                            message = await channel.fetch_message(self.message_id)
                            await message.edit(embed=embed, view=self.stock_view)
                            logging.info("Stock message updated")
                        except discord.NotFound:
                            message = await channel.send(embed=embed, view=self.stock_view)
                            self.message_id = message.id
                            logging.info("New stock message created")
                    else:
                        message = await channel.send(embed=embed, view=self.stock_view)
                        self.message_id = message.id
                        logging.info("Initial stock message created")
                except Exception as e:
                    logging.error(f"Error updating stock message: {e}")
                    self.message_id = None

    @live_stock.before_loop
    async def before_live_stock(self):
        await self.bot.wait_until_ready()
        logging.info("Live stock loop started")

async def setup(bot):
    await bot.add_cog(LiveStock(bot))