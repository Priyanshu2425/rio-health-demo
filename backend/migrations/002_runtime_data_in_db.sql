-- The running app reads only the database. Files in data/ and the parser's sample
-- images are ETL inputs, loaded here once; nothing reads them at request time.

-- Brand popularity for search tie-breaks (lower = better known). Filled by the
-- catalog ETL; null for SKUs with no rank.
ALTER TABLE skus ADD COLUMN popularity_rank integer;

-- Demo prescriptions for the "Try a sample" fallback, with their cached parse.
CREATE TABLE samples (
    sample_id   text PRIMARY KEY,
    label       text NOT NULL,
    position    integer NOT NULL,          -- display order
    image       bytea NOT NULL,
    image_mime  text NOT NULL,
    parsed_rx   jsonb NOT NULL             -- ParsedRx
);
