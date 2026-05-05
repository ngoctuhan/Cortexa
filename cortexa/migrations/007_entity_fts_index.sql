-- Migration 007: GIN FTS index on entity_name for entity-aware context retrieval (Phase 2).
--
-- Creates an immutable unaccent wrapper so the index can reference the (volatile)
-- unaccent() extension function. This is the standard Postgres workaround.
-- ResolveEntities in repository/entity.go uses unaccent_immutable() so Postgres
-- will use this index instead of falling back to a sequential scan.
--
-- Also adds a GIN FTS index on (attribute, source_quote) used by QueryFactsByFTS /
-- QueryFactsByVector for ts_rank scoring in Phase 2.

CREATE OR REPLACE FUNCTION public.unaccent_immutable(text)
  RETURNS text LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS
  $$ SELECT unaccent($1) $$;

-- Phase 1 index: entity name resolution via FTS (ResolveEntities).
CREATE INDEX entity_mentions_name_fts_idx
  ON entity_mentions
  USING gin (to_tsvector('simple', unaccent_immutable(entity_name)));

-- Phase 2 index: fact content FTS scoring (QueryFactsByFTS, QueryFactsByVector ts_rank).
CREATE INDEX entity_mentions_fact_fts_idx
  ON entity_mentions
  USING gin (
    to_tsvector('simple', unaccent_immutable(attribute || ' ' || COALESCE(source_quote, '')))
  );
