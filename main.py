import discord
from discord.ext import commands
import os
import json
import logging
import asyncio
from database import setup_database, get_connection
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Load config
try:
    with open('config.json', 'r') as config_file:
        config = json.load(config_file)

    # Bot configuration
    TOKEN = config['token']
    GUILD_ID = config['guild_id']
    ADMIN_ID = int(config['admin_id'])
    LIVE_STOCK_CHANNEL_ID = int(config['id_live_stock'])
    LOG_PURCHASE_CHANNEL_ID = int(config['id_log_purch'])
    DONATION_LOG_CHANNEL_ID = int(config['id_donation_log'])

except FileNotFoundError:
    logger.error("config.json file not found!")
    raise
except json.JSONDecodeError:
    logger.error("config.json is not valid JSON!")
    raise
except KeyError as e:
    logger.error(f"Missing required configuration key: {e}")
    raise

# Setup intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.messages = True

bot = commands.Bot(command_prefix='!', intents=intents)

def is_admin():
    """Check if user is admin"""
    async def predicate(ctx):
        is_admin = ctx.author.id == ADMIN_ID
        logger.info(f'Admin check for {ctx.author} (ID: {ctx.author.id}): {is_admin}')
        return is_admin
    return commands.check(predicate)

@bot.event
async def on_ready():
    """Event when bot is ready"""
    logger.info(f'Bot {bot.user.name} is online!')
    logger.info(f'Guild ID: {GUILD_ID}')
    logger.info(f'Admin ID: {ADMIN_ID}')
    
    # Set custom status
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="Growtopia Shop"
        )
    )

@bot.event
async def on_message(message):
    """Event when a message is received"""
    if message.author == bot.user:
        return
        
    logger.info(f'Message from {message.author}: {message.content}')
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    """Global error handler"""
    if isinstance(error, commands.errors.CheckFailure):
        await ctx.send("❌ You don't have permission to use this command!")
    elif isinstance(error, commands.errors.CommandNotFound):
        pass
    else:
        logger.error(f'Error in {ctx.command}: {error}')
        await ctx.send(f"❌ An error occurred: {str(error)}")

async def load_extensions():
    """Load all extensions"""
    # Load from ext folder
    if os.path.exists('./ext'):
        for filename in os.listdir('./ext'):
            if filename.endswith('.py'):
                try:
                    await bot.load_extension(f'ext.{filename[:-3]}')
                    logger.info(f'Loaded ext: {filename}')
                except Exception as e:
                    logger.error(f'Failed to load {filename}: {e}')

async def main():
    """Main function to run the bot"""
    try:
        # Initialize database
        setup_database()
        
        # Load extensions
        await load_extensions()
        
        # Start bot
        await bot.start(TOKEN)
    except Exception as e:
        logger.error(f'Fatal error: {e}')
        raise

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info('Bot stopped by user')
    except Exception as e:
        logger.error(f'Fatal error occurred: {e}')