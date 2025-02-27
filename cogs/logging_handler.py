import discord
from discord.ext import commands
import logging
import os

LOG_FILE = 'transactions.log'

class LoggingHandler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('discord')
        self.logger.setLevel(logging.INFO)
        handler = logging.FileHandler(filename=LOG_FILE, encoding='utf-8', mode='w')
        handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
        self.logger.addHandler(handler)

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        log_message = f"User: {ctx.author} (ID: {ctx.author.id}), Command: {ctx.command}, Channel: {ctx.channel}"
        self.logger.info(log_message)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        log_message = f"User: {ctx.author} (ID: {ctx.author.id}), Command: {ctx.command}, Error: {error}, Channel: {ctx.channel}"
        self.logger.error(log_message)

async def setup(bot):
    await bot.add_cog(LoggingHandler(bot))