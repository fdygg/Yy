-- Add new indices
CREATE INDEX IF NOT EXISTS idx_product_stock_used ON product_stock(used);
CREATE INDEX IF NOT EXISTS idx_product_stock_product_code ON product_stock(product_code);
CREATE INDEX IF NOT EXISTS idx_user_growid_user_id ON user_growid(user_id);

-- Add buyer_growid column
ALTER TABLE product_stock ADD COLUMN IF NOT EXISTS buyer_growid TEXT REFERENCES users(growid);

-- Add timestamp indices for better query performance
CREATE INDEX IF NOT EXISTS idx_transaction_log_timestamp ON transaction_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_product_stock_used_at ON product_stock(used_at);