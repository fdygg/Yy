import discord
from discord.ext import commands
import logging
import datetime
from database import get_connection

class BalanceManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def db_connect(self):
        return get_connection()

    async def get_user_balance(self, growid: str):
        """Get user balance from database"""
        try:
            conn = self.db_connect()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT balance_wl, balance_dl, balance_bgl 
                FROM users 
                WHERE growid = ?
            """, (growid,))
            balance = cursor.fetchone()
            conn.close()
            return balance if balance else (0, 0, 0)
        except Exception as e:
            logging.error(f"Error getting balance: {e}")
            return None

    async def add_balance(self, growid: str, wl: int = 0, dl: int = 0, bgl: int = 0):
        """Add balance to user account"""
        try:
            conn = self.db_connect()
            cursor = conn.cursor()
            
            # Get current balance
            cursor.execute("""
                SELECT balance_wl, balance_dl, balance_bgl 
                FROM users 
                WHERE growid = ?
            """, (growid,))
            current = cursor.fetchone()
            
            current_time = datetime.datetime.utcnow()
            
            if current:
                new_wl = current[0] + wl
                new_dl = current[1] + dl
                new_bgl = current[2] + bgl
                
                cursor.execute("""
                    UPDATE users 
                    SET balance_wl = ?, 
                        balance_dl = ?, 
                        balance_bgl = ?,
                        updated_at = ? 
                    WHERE growid = ?
                """, (new_wl, new_dl, new_bgl, current_time, growid))
            else:
                cursor.execute("""
                    INSERT INTO users (
                        growid, balance_wl, balance_dl, balance_bgl, 
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (growid, wl, dl, bgl, current_time, current_time))

            # Add transaction log
            cursor.execute("""
                INSERT INTO balance_transactions (
                    growid, type, amount_wl, amount_dl, amount_bgl, 
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (growid, 'ADD', wl, dl, bgl, current_time))
            
            conn.commit()
            conn.close()
            
            return True
        except Exception as e:
            logging.error(f"Error adding balance: {e}")
            return False

    async def remove_balance(self, growid: str, wl: int = 0, dl: int = 0, bgl: int = 0):
        """Remove balance from user account"""
        try:
            conn = self.db_connect()
            cursor = conn.cursor()
            
            # Get current balance
            cursor.execute("""
                SELECT balance_wl, balance_dl, balance_bgl 
                FROM users 
                WHERE growid = ?
            """, (growid,))
            current = cursor.fetchone()
            
            if not current:
                return False
                
            new_wl = current[0] - wl
            new_dl = current[1] - dl
            new_bgl = current[2] - bgl
            
            # Check if balance would go negative
            if new_wl < 0 or new_dl < 0 or new_bgl < 0:
                return False
            
            current_time = datetime.datetime.utcnow()
            
            cursor.execute("""
                UPDATE users 
                SET balance_wl = ?, 
                    balance_dl = ?, 
                    balance_bgl = ?,
                    updated_at = ? 
                WHERE growid = ?
            """, (new_wl, new_dl, new_bgl, current_time, growid))
            
            # Add transaction log
            cursor.execute("""
                INSERT INTO balance_transactions (
                    growid, type, amount_wl, amount_dl, amount_bgl, 
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (growid, 'REMOVE', wl, dl, bgl, current_time))
            
            conn.commit()
            conn.close()
            
            return True
        except Exception as e:
            logging.error(f"Error removing balance: {e}")
            return False

    async def transfer_balance(self, from_growid: str, to_growid: str, wl: int = 0, dl: int = 0, bgl: int = 0):
        """Transfer balance between users"""
        try:
            # Remove from sender
            if not await self.remove_balance(from_growid, wl, dl, bgl):
                return False
                
            # Add to receiver
            if not await self.add_balance(to_growid, wl, dl, bgl):
                # Rollback if adding fails
                await self.add_balance(from_growid, wl, dl, bgl)
                return False
                
            return True
        except Exception as e:
            logging.error(f"Error transferring balance: {e}")
            return False

    def add_balance_sync(self, growid: str, wl: int = 0, dl: int = 0, bgl: int = 0):
        """Synchronous version of add_balance for use in other cogs"""
        try:
            conn = self.db_connect()
            cursor = conn.cursor()
            
            # Get current balance
            cursor.execute("""
                SELECT balance_wl, balance_dl, balance_bgl 
                FROM users 
                WHERE growid = ?
            """, (growid,))
            current = cursor.fetchone()
            
            current_time = datetime.datetime.utcnow()
            
            if current:
                new_wl = current[0] + wl
                new_dl = current[1] + dl
                new_bgl = current[2] + bgl
                
                cursor.execute("""
                    UPDATE users 
                    SET balance_wl = ?, 
                        balance_dl = ?, 
                        balance_bgl = ?,
                        updated_at = ? 
                    WHERE growid = ?
                """, (new_wl, new_dl, new_bgl, current_time, growid))
            else:
                cursor.execute("""
                    INSERT INTO users (
                        growid, balance_wl, balance_dl, balance_bgl, 
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (growid, wl, dl, bgl, current_time, current_time))

            # Add transaction log
            cursor.execute("""
                INSERT INTO balance_transactions (
                    growid, type, amount_wl, amount_dl, amount_bgl, 
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (growid, 'ADD', wl, dl, bgl, current_time))
            
            conn.commit()
            conn.close()
            
            return True
        except Exception as e:
            logging.error(f"Error adding balance: {e}")
            return False

async def setup(bot):
    await bot.add_cog(BalanceManager(bot))