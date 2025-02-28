import discord
from discord.ext import commands
import logging
from database import get_connection
from typing import List, Dict, Any
from datetime import datetime
import sqlite3

class ProductManager:
    def __init__(self, bot):
        self.bot = bot
        self._init_logger()
        
    def _init_logger(self):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

    async def get_all_products(self) -> List[Dict[str, Any]]:
        """Get all products from database"""
        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT code, name, price, stock, description
                FROM products
                ORDER BY price ASC
            """)
            
            products = []
            for row in cursor.fetchall():
                products.append({
                    'code': row[0],
                    'name': row[1],
                    'price': row[2],
                    'stock': row[3],
                    'description': row[4]
                })
            
            return products
            
        except Exception as e:
            self.logger.error(f"Error getting products: {e}")
            raise
            
        finally:
            if conn:
                conn.close()

    async def get_product(self, code: str) -> Dict[str, Any]:
        """Get a specific product by code"""
        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT code, name, price, stock, description
                FROM products
                WHERE code = ?
            """, (code,))
            
            row = cursor.fetchone()
            if row:
                return {
                    'code': row[0],
                    'name': row[1],
                    'price': row[2],
                    'stock': row[3],
                    'description': row[4]
                }
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting product {code}: {e}")
            raise
            
        finally:
            if conn:
                conn.close()

    async def update_stock(self, code: str, quantity: int) -> bool:
        """Update product stock"""
        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE products 
                SET stock = stock + ? 
                WHERE code = ?
            """, (quantity, code))
            
            conn.commit()
            self.logger.info(f"Stock updated for {code}")
            return True
            
        except Exception as e:
            if conn:
                conn.rollback()
            self.logger.error(f"Error updating stock for {code}: {e}")
            raise
            
        finally:
            if conn:
                conn.close()

    async def create_product(
        self, 
        code: str, 
        name: str, 
        price: int, 
        description: str = ""
    ) -> bool:
        """Create a new product"""
        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO products (
                    code, name, price, description, stock
                ) VALUES (?, ?, ?, ?, 0)
            """, (code, name, price, description))
            
            conn.commit()
            self.logger.info(f"Product {code} created")
            return True
            
        except Exception as e:
            if conn:
                conn.rollback()
            self.logger.error(f"Error creating product {code}: {e}")
            raise
            
        finally:
            if conn:
                conn.close()

    async def update_product(
        self, 
        code: str, 
        **kwargs
    ) -> bool:
        """Update product details"""
        valid_fields = ['name', 'price', 'description']
        update_fields = []
        values = []
        
        for field, value in kwargs.items():
            if field in valid_fields:
                update_fields.append(f"{field} = ?")
                values.append(value)
                
        if not update_fields:
            return False
            
        values.append(code)
        query = f"UPDATE products SET {', '.join(update_fields)} WHERE code = ?"
        
        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(query, values)
            conn.commit()
            self.logger.info(f"Product {code} updated")
            return True
            
        except Exception as e:
            if conn:
                conn.rollback()
            self.logger.error(f"Error updating product {code}: {e}")
            raise
            
        finally:
            if conn:
                conn.close()

    async def delete_product(self, code: str) -> bool:
        """Delete a product"""
        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                "DELETE FROM products WHERE code = ?", 
                (code,)
            )
            
            conn.commit()
            self.logger.info(f"Product {code} deleted")
            return True
            
        except Exception as e:
            if conn:
                conn.rollback()
            self.logger.error(f"Error deleting product {code}: {e}")
            raise
            
        finally:
            if conn:
                conn.close()

class ProductManagerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.product_manager = ProductManager(bot)

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info("ProductManager is ready")

async def setup(bot):
    await bot.add_cog(ProductManagerCog(bot))
    logging.info("ProductManagerCog loaded")