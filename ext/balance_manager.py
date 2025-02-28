import discord
from discord.ext import commands
import logging
from database import get_connection
from datetime import datetime
from .constants import Balance, TransactionError, CURRENCY_RATES

class BalanceManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._init_logger()
        
    def _init_logger(self):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        
    async def get_user_balance(self, growid: str) -> Balance:
        """Get user's balance from database"""
        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT balance_wl, balance_dl, balance_bgl FROM users WHERE growid = ?",
                (growid,)
            )
            result = cursor.fetchone()
            if result:
                return Balance(*result)
            return Balance(0, 0, 0)
            
        except Exception as e:
            self.logger.error(f"Error getting balance: {e}")
            raise TransactionError(f"Failed to get balance: {str(e)}")
            
        finally:
            if conn:
                conn.close()

    async def update_balance(
        self, 
        growid: str, 
        wl: int = 0, 
        dl: int = 0, 
        bgl: int = 0,
        transaction_type: str = "MANUAL",
        details: str = ""
    ) -> Balance:
        """Update user's balance and log transaction"""
        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            # Get current balance
            current = await self.get_user_balance(growid)
            
            # Calculate new balance
            new_balance = Balance(
                current.wl + wl,
                current.dl + dl,
                current.bgl + bgl
            )
            
            # Validate balance isn't negative
            if new_balance.total_wls < 0:
                raise TransactionError("Balance cannot be negative")
                
            # Update balance
            cursor.execute("""
                UPDATE users 
                SET balance_wl = ?, 
                    balance_dl = ?, 
                    balance_bgl = ? 
                WHERE growid = ?
            """, (new_balance.wl, new_balance.dl, new_balance.bgl, growid))
            
            # Log transaction
            cursor.execute("""
                INSERT INTO transaction_log 
                (growid, amount, type, details, old_balance, new_balance, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                growid,
                wl + (dl * CURRENCY_RATES['DL']) + (bgl * CURRENCY_RATES['BGL']),
                transaction_type,
                details,
                current.format(),
                new_balance.format()
            ))
            
            conn.commit()
            return new_balance
            
        except Exception as e:
            if conn:
                conn.rollback()
            self.logger.error(f"Error updating balance: {e}")
            raise TransactionError(f"Failed to update balance: {str(e)}")
            
        finally:
            if conn:
                conn.close()

async def setup(bot):
    await bot.add_cog(BalanceManager(bot))