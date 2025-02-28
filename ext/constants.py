from dataclasses import dataclass
from decimal import Decimal
from typing import Dict

# Currency constants
CURRENCY_RATES: Dict[str, int] = {
    'BGL': 10000,
    'DL': 100,
    'WL': 1
}

# Transaction limits
MAX_ITEMS_PER_TRANSACTION = 100
MAX_ITEMS_PER_MESSAGE = 20

# Cache settings
CACHE_TTL = 300  # 5 minutes
MAX_CACHE_SIZE = 1000

@dataclass
class Balance:
    wl: int
    dl: int 
    bgl: int
    
    @property
    def total_wls(self) -> int:
        return self.wl + (self.dl * CURRENCY_RATES['DL']) + (self.bgl * CURRENCY_RATES['BGL'])
    
    def format(self) -> str:
        return (
            f"• {self.wl:,} WL\n"
            f"• {self.dl:,} DL (= {self.dl * CURRENCY_RATES['DL']:,} WL)\n"
            f"• {self.bgl:,} BGL (= {self.bgl * CURRENCY_RATES['BGL']:,} WL)\n"
            f"Total: {self.total_wls:,} WL"
        )

class TransactionError(Exception):
    """Custom exception for transaction errors"""
    pass