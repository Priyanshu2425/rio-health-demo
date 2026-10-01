-- Emails entered at the demo's email wall. One row per address (stored lowercased);
-- a returning visitor updates last_seen and visits. Never verified, never emailed.
CREATE TABLE visitors (
    email       text PRIMARY KEY,
    first_seen  timestamptz NOT NULL DEFAULT now(),
    last_seen   timestamptz NOT NULL DEFAULT now(),
    visits      integer NOT NULL DEFAULT 1
);
