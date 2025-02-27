import discord
from discord.ext import commands
import logging
from database import get_connection
from datetime import datetime

logger = logging.getLogger(__name__)

class ProductManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def add_product(self, ctx, code: str, name: str, price: int, description: str = ""):
        """Menambah produk baru"""
        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Cek apakah kode produk sudah ada
            cursor.execute("SELECT code FROM products WHERE code = ?", (code,))
            if cursor.fetchone():
                return f"❌ Produk dengan kode {code} sudah ada!"

            # Tambah produk baru
            cursor.execute("""
                INSERT INTO products (code, name, price, description, stock)
                VALUES (?, ?, ?, ?, 0)
            """, (code, name, price, description))

            conn.commit()

            embed = discord.Embed(
                title="✅ Produk Berhasil Ditambahkan",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Kode", value=code, inline=True)
            embed.add_field(name="Nama", value=name, inline=True)
            embed.add_field(name="Harga", value=f"{price:,} WL", inline=True)
            if description:
                embed.add_field(name="Deskripsi", value=description, inline=False)
            embed.set_footer(text=f"Ditambahkan oleh {ctx.author}")

            return embed

        except Exception as e:
            logger.error(f"Error menambah produk: {e}")
            if conn:
                conn.rollback()
            return f"❌ Terjadi kesalahan: {str(e)}"

        finally:
            if conn:
                conn.close()

    async def edit_product(self, ctx, code: str, name: str = None, price: int = None, description: str = None):
        """Edit informasi produk"""
        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Cek apakah produk ada
            cursor.execute("SELECT * FROM products WHERE code = ?", (code,))
            product = cursor.fetchone()
            if not product:
                return f"❌ Produk dengan kode {code} tidak ditemukan!"

            # Update fields yang diubah
            updates = []
            values = []
            if name is not None:
                updates.append("name = ?")
                values.append(name)
            if price is not None:
                updates.append("price = ?")
                values.append(price)
            if description is not None:
                updates.append("description = ?")
                values.append(description)

            if not updates:
                return "❌ Tidak ada data yang diubah!"

            # Execute update
            values.append(code)
            cursor.execute(f"""
                UPDATE products 
                SET {', '.join(updates)}
                WHERE code = ?
            """, values)

            conn.commit()

            embed = discord.Embed(
                title="✅ Produk Berhasil Diubah",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Kode", value=code, inline=True)
            if name:
                embed.add_field(name="Nama Baru", value=name, inline=True)
            if price:
                embed.add_field(name="Harga Baru", value=f"{price:,} WL", inline=True)
            if description:
                embed.add_field(name="Deskripsi Baru", value=description, inline=False)
            embed.set_footer(text=f"Diubah oleh {ctx.author}")

            return embed

        except Exception as e:
            logger.error(f"Error mengubah produk: {e}")
            if conn:
                conn.rollback()
            return f"❌ Terjadi kesalahan: {str(e)}"

        finally:
            if conn:
                conn.close()

    async def delete_product(self, ctx, code: str):
        """Hapus produk"""
        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Cek apakah produk ada
            cursor.execute("SELECT name, stock FROM products WHERE code = ?", (code,))
            product = cursor.fetchone()
            if not product:
                return f"❌ Produk dengan kode {code} tidak ditemukan!"

            name, stock = product
            if stock > 0:
                return f"❌ Tidak dapat menghapus produk yang masih memiliki stok ({stock} item)!"

            # Hapus produk
            cursor.execute("DELETE FROM products WHERE code = ?", (code,))
            conn.commit()

            embed = discord.Embed(
                title="✅ Produk Berhasil Dihapus",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Kode", value=code, inline=True)
            embed.add_field(name="Nama", value=name, inline=True)
            embed.set_footer(text=f"Dihapus oleh {ctx.author}")

            return embed

        except Exception as e:
            logger.error(f"Error menghapus produk: {e}")
            if conn:
                conn.rollback()
            return f"❌ Terjadi kesalahan: {str(e)}"

        finally:
            if conn:
                conn.close()

    async def list_products(self, ctx):
        """Tampilkan daftar produk"""
        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT code, name, price, stock, description 
                FROM products 
                ORDER BY name
            """)
            products = cursor.fetchall()

            if not products:
                return "❌ Belum ada produk yang terdaftar!"

            embed = discord.Embed(
                title="📋 Daftar Produk",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )

            for code, name, price, stock, description in products:
                value = f"Harga: {price:,} WL\nStok: {stock} item"
                if description:
                    value += f"\n{description}"
                embed.add_field(
                    name=f"{name} ({code})",
                    value=value,
                    inline=False
                )

            return embed

        except Exception as e:
            logger.error(f"Error menampilkan produk: {e}")
            return f"❌ Terjadi kesalahan: {str(e)}"

        finally:
            if conn:
                conn.close()

    async def view_stock_details(self, ctx, code: str):
        """Lihat detail stok produk"""
        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Get product info
            cursor.execute("""
                SELECT name, price, stock, description 
                FROM products 
                WHERE code = ?
            """, (code,))
            product = cursor.fetchone()

            if not product:
                return f"❌ Produk dengan kode {code} tidak ditemukan!"

            name, price, stock, description = product

            # Get stock details
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN used = 0 THEN 1 ELSE 0 END) as available,
                    SUM(CASE WHEN used = 1 THEN 1 ELSE 0 END) as sold
                FROM product_stock 
                WHERE product_code = ?
            """, (code,))
            stock_info = cursor.fetchone()

            embed = discord.Embed(
                title=f"📊 Detail Stok: {name}",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Kode", value=code, inline=True)
            embed.add_field(name="Harga", value=f"{price:,} WL", inline=True)
            embed.add_field(name="Stok Tersedia", value=str(stock), inline=True)
            
            if stock_info:
                total, available, sold = stock_info
                embed.add_field(name="Total Item", value=str(total), inline=True)
                embed.add_field(name="Item Tersedia", value=str(available), inline=True)
                embed.add_field(name="Item Terjual", value=str(sold), inline=True)

            if description:
                embed.add_field(name="Deskripsi", value=description, inline=False)

            return embed

        except Exception as e:
            logger.error(f"Error melihat detail stok: {e}")
            return f"❌ Terjadi kesalahan: {str(e)}"

        finally:
            if conn:
                conn.close()

async def setup(bot):
    await bot.add_cog(ProductManager(bot))