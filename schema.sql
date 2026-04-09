CREATE TABLE IF NOT EXISTS watchlist (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    coin_id TEXT NOT NULL,
    coin_name TEXT NOT NULL,
    added_at TIMESTAMP DEFAULT NOW()
);