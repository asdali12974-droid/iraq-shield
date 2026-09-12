-- Provisioned once, on first database initialization, by the Postgres image.
-- These extensions are the foundation the later phases build on:
--   postgis      -> GEOINT (geometry, spatial indexes)          [Phase P3]
--   vector       -> embeddings / RAG retrieval (pgvector)        [Phase P6/P9]
--   timescaledb  -> time-series event density (hypertables)      [Phase P4]
-- P0's own schema does not use them yet; they are enabled here so the database
-- is ready and application migrations never have to manage extensions.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS timescaledb;
