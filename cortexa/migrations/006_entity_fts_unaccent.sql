-- Migration 006: Enable unaccent extension for diacritic-insensitive FTS on entity_mentions.
--
-- This supports the Entity-Aware Fact Retrieval feature (Phase 1):
--   plainto_tsquery('simple', unaccent($query))  ← query without diacritics
--   to_tsvector('simple', unaccent(entity_name || ' ' || attribute || ' ' || source_quote))
--
-- unaccent is a Postgres contrib module (no extra install needed on standard Postgres images).
-- It converts accented characters to their base form:
--   "bạn tôi Nam" → "ban toi Nam"   (user fast-typing without diacritics still matches)
--
-- Note: GIN index on the FTS expression is intentionally deferred to migration 007 (Phase 2).
-- Phase 1 relies on the sequential scan being fast enough for typical fact volumes (< 10k rows/user).

CREATE EXTENSION IF NOT EXISTS unaccent;
