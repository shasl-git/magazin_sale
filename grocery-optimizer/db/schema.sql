-- Магазины / точки в Барнауле
CREATE TABLE IF NOT EXISTS stores (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,              -- magnit | pyaterochka | samokat
  title TEXT,                      -- «Магнит на …»
  city TEXT DEFAULT 'Барнаул',
  external_store_id TEXT NOT NULL, -- storeCode / sapCode / zone id
  delivery_cost_default REAL DEFAULT 0,
  notes TEXT
);

-- Что пользователь имеет в виду («молоко», «чокопай»)
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY,
  name_user TEXT NOT NULL UNIQUE
);

-- Привязка «молоко» → конкретный SKU в магазине (после кнопки «это оно»)
CREATE TABLE IF NOT EXISTS aliases (
  id INTEGER PRIMARY KEY,
  product_id INTEGER REFERENCES products(id),
  store_id INTEGER REFERENCES stores(id),
  external_sku TEXT NOT NULL,
  title TEXT,
  unit TEXT,           -- мл, г, шт
  qty REAL,            -- 1000, 1200, 6
  UNIQUE(product_id, store_id, external_sku)
);

-- Снимок цены
CREATE TABLE IF NOT EXISTS offers (
  id INTEGER PRIMARY KEY,
  product_id INTEGER REFERENCES products(id),
  store_id INTEGER REFERENCES stores(id),
  external_sku TEXT,
  title TEXT,
  price REAL NOT NULL,
  old_price REAL,
  unit TEXT,
  qty REAL,
  price_per_base REAL, -- цена за мл / за 100 г
  url TEXT,
  in_stock INTEGER DEFAULT 1,
  catalog_mode TEXT NOT NULL DEFAULT '', -- dostavka:2 или 1:1 (полка)
  scraped_at TEXT NOT NULL
);

-- Акции магазина
-- type: item_discount | cart_threshold | n_plus_m | free_delivery
CREATE TABLE IF NOT EXISTS promos (
  id INTEGER PRIMARY KEY,
  store_id INTEGER REFERENCES stores(id),
  type TEXT NOT NULL,
  title TEXT,
  threshold REAL,      -- порог «от N ₽»
  discount_value REAL, -- 500 ₽ или 0.20 для −20%
  discount_kind TEXT,  -- percent | amount
  ends_at TEXT,
  rules_json TEXT
);

-- История экономии
CREATE TABLE IF NOT EXISTS savings_log (
  id INTEGER PRIMARY KEY,
  bought_at TEXT NOT NULL,
  store_ids TEXT,              -- json список
  baseline_total REAL NOT NULL,
  calculated_total REAL NOT NULL,
  paid_total REAL,
  saved REAL NOT NULL,
  breakdown_json TEXT
);
