-- Rio schema. Frozen on main like app/contracts.py: change it only on a contracts branch.
-- Runs with search_path = app_rio_health, public. pg_trgm is installed database-wide by
-- the Neon admin (see docs/briefs/00-you-setup.md), so its operators resolve via public.

-- Catalog -------------------------------------------------------------------

CREATE TABLE skus (
    sku_id          text PRIMARY KEY,
    brand_name      text NOT NULL,
    manufacturer    text NOT NULL,
    form            text NOT NULL,
    pack_size       integer NOT NULL CHECK (pack_size >= 1),
    pack_label      text NOT NULL,
    mrp_inr         numeric(10, 2) NOT NULL CHECK (mrp_inr >= 0),
    composition     jsonb NOT NULL,          -- list[Salt]
    composition_key text NOT NULL,           -- equal keys = substitutable
    rx_only         boolean NOT NULL,
    schedule        text CHECK (schedule IN ('H', 'H1', 'X'))
);

CREATE INDEX skus_brand_trgm ON skus USING gin (lower(brand_name) gin_trgm_ops);
CREATE INDEX skus_composition_trgm ON skus USING gin (composition_key gin_trgm_ops);
CREATE INDEX skus_composition_key ON skus (composition_key, form, mrp_inr);

-- Orders --------------------------------------------------------------------
-- Items live in jsonb (list[CartItem]): one order is read and written whole.

CREATE TABLE orders (
    order_id         text PRIMARY KEY,
    created_at       timestamptz NOT NULL DEFAULT now(),
    source           text NOT NULL CHECK (source IN ('prescription', 'sample', 'text')),
    status           text NOT NULL,
    image            bytea,
    image_mime       text,
    parsed_rx        jsonb,
    items            jsonb NOT NULL,
    total_inr        numeric(10, 2) NOT NULL,
    requires_review  boolean NOT NULL,
    pharmacist_note  text,
    reviewed_at      timestamptz
);

CREATE INDEX orders_queue ON orders (created_at) WHERE status = 'pending_review';

-- Forecast ------------------------------------------------------------------

CREATE TABLE synthetic_orders (
    ts      timestamptz NOT NULL,            -- start of the hour
    area    text NOT NULL,
    sku_id  text NOT NULL REFERENCES skus,
    qty     integer NOT NULL CHECK (qty >= 0),
    PRIMARY KEY (area, sku_id, ts)
);

CREATE TABLE inventory (
    area             text NOT NULL,
    sku_id           text NOT NULL REFERENCES skus,
    on_hand          integer NOT NULL CHECK (on_hand >= 0),
    lead_time_hours  integer NOT NULL CHECK (lead_time_hours > 0),
    PRIMARY KEY (area, sku_id)
);

CREATE TABLE forecast_runs (
    run_id        bigserial PRIMARY KEY,
    generated_at  timestamptz NOT NULL DEFAULT now(),
    summary       jsonb NOT NULL                -- ForecastSummary
);

CREATE TABLE forecast_series (
    run_id  bigint NOT NULL REFERENCES forecast_runs ON DELETE CASCADE,
    area    text NOT NULL,
    sku_id  text NOT NULL,
    series  jsonb NOT NULL,                    -- SkuForecast
    PRIMARY KEY (run_id, area, sku_id)
);
