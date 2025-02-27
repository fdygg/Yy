import sqlite3
import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from discord.ext import commands
from ext.balance_manager import add_balance
from database import get_connection

# Baca konfigurasi dari config.json
with open('config.json') as config_file:
    config = json.load(config_file)

DATABASE = 'store.db'
PORT = 8081  # Ganti port jika diperlukan untuk menghindari bentrok
DONATION_LOG_CHANNEL_ID = config['id_donation_log']

class DonateHandler(BaseHTTPRequestHandler):
    def db_connect(self):
        return get_connection()

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        logging.info(f"Received donation data: {post_data}")

        try:
            data = json.loads(post_data)
            growid = data.get('GrowID')
            deposit = data.get('Deposit')

            if not growid or not deposit:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Invalid data")
                return

            wl = 0
            dl = 0
            bgl = 0

            # Extract WL, DL, and BGL from the deposit string
            deposits = deposit.split(',')
            for d in deposits:
                d = d.strip()
                if 'World Lock' in d:
                    wl += int(d.split()[0])
                elif 'Diamond Lock' in d:
                    dl += int(d.split()[0])
                elif 'Blue Gem Lock' in d:
                    bgl += int(d.split()[0])

            total_wl = wl + (dl * 100) + (bgl * 10000)
            add_balance(growid, wl=total_wl)

            self.send_response(200)
            self.end_headers()
            self.wfile.write(f"Donation received. Added {total_wl} WL to {growid}'s balance.".encode())

            logging.info(f"Added {total_wl} WL to {growid}'s balance.")

        except Exception as e:
            logging.error(f"Error processing donation: {e}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Internal server error")

def run(server_class=HTTPServer, handler_class=DonateHandler, port=PORT):
    logging.basicConfig(level=logging.INFO)
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    logging.info(f'Starting server on port {port}...')
    httpd.serve_forever()

class DonateCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.server = None

    @commands.Cog.listener()
    async def on_ready(self):
        if self.server is None:
            try:
                self.server = HTTPServer(('0.0.0.0', PORT), DonateHandler)
                logging.info(f'Starting donation server on port {PORT}')
                self.bot.loop.run_in_executor(None, self.server.serve_forever)
            except OSError as e:
                logging.error(f"Error starting HTTP server: {e}")

    @commands.Cog.listener()
    async def on_disconnect(self):
        if self.server:
            self.server.shutdown()
            self.server = None

async def setup(bot):
    await bot.add_cog(DonateCog(bot))

if __name__ == "__main__":
    run()