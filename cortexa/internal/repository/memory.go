package repository

import (
	"context"
	"encoding/json"
	"log"
	"strings"

	"github.com/cortexa/cortexa/internal/model"
	"github.com/jackc/pgx/v5"
)

type MemoryRepository struct {
	db *DB
}

func NewMemoryRepository(db *DB) *MemoryRepository {
	return &MemoryRepository{db: db}
}

// GetPersona returns up to limit persona trait records for a user, ordered by
// importance then recency. Returns an empty slice (not an error) when none exist.
func (r *MemoryRepository) GetPersona(ctx context.Context, tenantID, userID string, limit int) ([]model.MemoryRecord, error) {
	rows, err := r.db.Pool.Query(ctx, `
		SELECT id, type, payload, importance, access_count, created_at
		FROM memory_records
		WHERE tenant_id = $1 AND user_id = $2 AND type = 'persona'
		ORDER BY importance DESC, created_at DESC
		LIMIT $3
	`, tenantID, userID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var records []model.MemoryRecord
	for rows.Next() {
		var m model.MemoryRecord
		var payload []byte
		if err := rows.Scan(&m.ID, &m.Type, &payload, &m.Importance, &m.AccessCount, &m.CreatedAt); err != nil {
			continue
		}
		m.Payload = json.RawMessage(payload)
		records = append(records, m)
	}
	return records, rows.Err()
}

// UpsertPersona inserts each trait as its own memory_records row (type='persona',
// payload={"trait":"..."}) skipping exact duplicates via NOT EXISTS.
// Returns the IDs of newly inserted records so the caller can embed them.
func (r *MemoryRepository) UpsertPersona(ctx context.Context, tenantID, userID, sessionID string, newTraits []string) ([]string, error) {
	var insertedIDs []string
	for _, trait := range newTraits {
		trait = strings.TrimSpace(trait)
		if trait == "" {
			continue
		}
		payloadBytes, _ := json.Marshal(map[string]string{"trait": trait})
		var id string
		err := r.db.Pool.QueryRow(ctx, `
			INSERT INTO memory_records (tenant_id, user_id, session_id, type, payload, importance)
			SELECT $1, $2, $3, 'persona', $4::jsonb, 1.0
			WHERE NOT EXISTS (
				SELECT 1 FROM memory_records
				WHERE tenant_id=$1 AND user_id=$2 AND type='persona'
				  AND payload->>'trait' = $5
			)
			RETURNING id
		`, tenantID, userID, sessionID, string(payloadBytes), trait).Scan(&id)
		if err != nil {
			if err.Error() != "no rows in result set" {
				log.Printf("UpsertPersona: insert trait error: %v", err)
			}
			continue // duplicate or error — skip
		}
		insertedIDs = append(insertedIDs, id)
	}
	return insertedIDs, nil
}

// UpdatePersonaEmbeddingsBatch sets the embedding for a list of persona records
// identified by ID. ids and embeddings must be the same length.
func (r *MemoryRepository) UpdatePersonaEmbeddingsBatch(ctx context.Context, tenantID string, ids []string, embeddings [][]float32) error {
	batch := &pgx.Batch{}
	for i, id := range ids {
		if i >= len(embeddings) {
			break
		}
		embBytes, _ := json.Marshal(embeddings[i])
		batch.Queue(
			`UPDATE memory_records SET embedding = $1::vector WHERE id = $2 AND tenant_id = $3`,
			string(embBytes), id, tenantID,
		)
	}
	if batch.Len() == 0 {
		return nil
	}
	br := r.db.Pool.SendBatch(ctx, batch)
	defer br.Close()
	for i := 0; i < batch.Len(); i++ {
		if _, err := br.Exec(); err != nil {
			log.Printf("UpdatePersonaEmbeddingsBatch item %d error: %v", i, err)
		}
	}
	return nil
}

// GetUpcomingEvents returns upcoming life_event records ordered by query relevance
// (FTS on event_name when query is non-empty) then by date proximity to now.
// Only events within a 7-day lookback + future window are returned.
func (r *MemoryRepository) GetUpcomingEvents(ctx context.Context, tenantID, userID, query string, limit int) ([]model.MemoryRecord, error) {
	rows, err := r.db.Pool.Query(ctx, `
		SELECT id, type, payload, importance, access_count, created_at
		FROM memory_records
		WHERE tenant_id = $1 AND user_id = $2 AND type = 'life_event'
		  AND (
		    NULLIF(payload->>'date', 'unspecified') IS NULL
		    OR NULLIF(payload->>'date', 'unspecified')::timestamptz >= NOW() - INTERVAL '7 days'
		  )
		ORDER BY
		  CASE WHEN $3 != ''
		    THEN ts_rank(
		      to_tsvector('simple', unaccent_immutable(COALESCE(payload->>'event_name', ''))),
		      plainto_tsquery('simple', unaccent_immutable($3))
		    )
		    ELSE 0.0
		  END DESC,
		  ABS(EXTRACT(EPOCH FROM (
		    COALESCE(NULLIF(payload->>'date', 'unspecified')::timestamptz, created_at) - NOW()
		  ))) ASC
		LIMIT $4
	`, tenantID, userID, query, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var events []model.MemoryRecord
	for rows.Next() {
		var m model.MemoryRecord
		var payload []byte
		if err := rows.Scan(&m.ID, &m.Type, &payload, &m.Importance, &m.AccessCount, &m.CreatedAt); err != nil {
			continue
		}
		m.Payload = json.RawMessage(payload)
		events = append(events, m)
	}
	return events, nil
}

// UpsertEvent inserts a life_event record, skipping duplicates using a
// single INSERT WHERE NOT EXISTS statement (replaces the previous SELECT + INSERT).
func (r *MemoryRepository) UpsertEvent(ctx context.Context, tenantID, userID, sessionID, payload string) error {
	_, err := r.db.Pool.Exec(ctx, `
		INSERT INTO memory_records (tenant_id, user_id, session_id, type, payload, importance)
		SELECT $1, $2, $3, 'life_event', $4::jsonb, 0.8
		WHERE NOT EXISTS (
			SELECT 1 FROM memory_records
			WHERE tenant_id=$1 AND user_id=$2 AND type='life_event' AND payload = $4::jsonb
		)
	`, tenantID, userID, sessionID, payload)
	return err
}

// UpsertEventBatch upserts multiple life_event records in a single pgx.Batch round-trip.
func (r *MemoryRepository) UpsertEventBatch(ctx context.Context, tenantID, userID, sessionID string, payloads []string) error {
	batch := &pgx.Batch{}
	for _, p := range payloads {
		batch.Queue(`
			INSERT INTO memory_records (tenant_id, user_id, session_id, type, payload, importance)
			SELECT $1, $2, $3, 'life_event', $4::jsonb, 0.8
			WHERE NOT EXISTS (
				SELECT 1 FROM memory_records
				WHERE tenant_id=$1 AND user_id=$2 AND type='life_event' AND payload = $4::jsonb
			)
		`, tenantID, userID, sessionID, p)
	}
	br := r.db.Pool.SendBatch(ctx, batch)
	defer br.Close() //nolint:errcheck
	for range payloads {
		if _, err := br.Exec(); err != nil {
			log.Printf("MemoryRepository: upsert event batch item error: %v", err)
		}
	}
	return nil
}

func (r *MemoryRepository) InsertEvent(ctx context.Context, tenantID, userID, sessionID string, payload string) error {
	_, err := r.db.Pool.Exec(ctx, `
		INSERT INTO memory_records (tenant_id, user_id, session_id, type, payload, importance)
		VALUES ($1, $2, $3, 'life_event', $4, 0.8)
	`, tenantID, userID, sessionID, payload)
	return err
}

// SearchByVectorPerType searches memory_records by cosine similarity, returning
// up to topKPerType results for each requested type using a single HNSW query
// with a window function to partition results by type.
//
// Falls back to importance-sorted records per type when no embeddings are populated (cold start).
func (r *MemoryRepository) SearchByVectorPerType(
	ctx context.Context,
	tenantID, userID string,
	embedding []float32,
	types []string,
	topKPerType int,
) (map[string][]model.MemoryRecord, error) {
	embBytes, _ := json.Marshal(embedding)

	rows, err := r.db.Pool.Query(ctx, `
		WITH ranked AS (
			SELECT id, type, payload, importance, access_count, created_at,
			       ROW_NUMBER() OVER (PARTITION BY type ORDER BY embedding <=> $3::vector) AS rn
			FROM memory_records
			WHERE tenant_id = $1 AND user_id = $2
			  AND type = ANY($4::text[])
			  AND embedding IS NOT NULL
		)
		SELECT id, type, payload, importance, access_count, created_at
		FROM ranked
		WHERE rn <= $5
		ORDER BY type, rn
	`, tenantID, userID, string(embBytes), types, topKPerType)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := make(map[string][]model.MemoryRecord)
	for rows.Next() {
		var m model.MemoryRecord
		var payload []byte
		if err := rows.Scan(&m.ID, &m.Type, &payload, &m.Importance, &m.AccessCount, &m.CreatedAt); err != nil {
			continue
		}
		m.Payload = json.RawMessage(payload)
		result[m.Type] = append(result[m.Type], m)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	// Cold start: if none of the requested types had embeddings yet, fall back per type.
	if len(result) == 0 {
		for _, t := range types {
			fallback, ferr := r.memoryFallback(ctx, tenantID, userID, t, topKPerType)
			if ferr == nil && len(fallback) > 0 {
				result[t] = fallback
			}
		}
	}
	return result, nil
}

// memoryFallback returns records for a single type ordered by importance DESC — used
// when embeddings are not yet populated (cold start) for that type.
func (r *MemoryRepository) memoryFallback(ctx context.Context, tenantID, userID, memType string, limit int) ([]model.MemoryRecord, error) {
	rows, err := r.db.Pool.Query(ctx, `
		SELECT id, type, payload, importance, access_count, created_at
		FROM memory_records
		WHERE tenant_id = $1 AND user_id = $2 AND type = $3
		ORDER BY importance DESC, created_at DESC
		LIMIT $4
	`, tenantID, userID, memType, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []model.MemoryRecord
	for rows.Next() {
		var m model.MemoryRecord
		var payload []byte
		if err := rows.Scan(&m.ID, &m.Type, &payload, &m.Importance, &m.AccessCount, &m.CreatedAt); err != nil {
			continue
		}
		m.Payload = json.RawMessage(payload)
		out = append(out, m)
	}
	return out, rows.Err()
}

// RecordFeedback updates importance and access_count of a memory_record based on
// a positive or negative signal from the host application.
// A positive signal boosts importance by 0.1 (max 1.0); negative reduces by 0.1 (min 0.01).
func (r *MemoryRepository) RecordFeedback(ctx context.Context, tenantID, userID, itemID string, positive bool) error {
	var delta float64
	if positive {
		delta = 0.1
	} else {
		delta = -0.1
	}
	_, err := r.db.Pool.Exec(ctx, `
		UPDATE memory_records
		SET
			access_count     = access_count + 1,
			last_accessed_at = NOW(),
			importance       = LEAST(1.0, GREATEST(0.01, importance + $4))
		WHERE tenant_id = $1 AND user_id = $2 AND id = $3
	`, tenantID, userID, itemID, delta)
	return err
}

// DecayImportance reduces the importance of stale memory records that have not been
// accessed within olderThanDays days. The decay formula is:
//
//	importance = GREATEST(0.01, importance * (1 - rate))
//
// This is a cross-tenant maintenance operation and intentionally bypasses RLS
// using SET LOCAL row_security = off inside a transaction. It MUST only be
// called from privileged background workers.
func (r *MemoryRepository) DecayImportance(ctx context.Context, rate float64, olderThanDays int) (int64, error) {
	tx, err := r.db.Pool.Begin(ctx)
	if err != nil {
		return 0, err
	}
	defer tx.Rollback(ctx) //nolint:errcheck

	// Bypass RLS for this cross-tenant maintenance transaction.
	if _, err := tx.Exec(ctx, "SET LOCAL row_security = off"); err != nil {
		return 0, err
	}

	tag, err := tx.Exec(ctx, `
		UPDATE memory_records
		SET importance = GREATEST(0.01, importance * (1 - $1))
		WHERE
			type IN ('life_event', 'user_character', 'persona', 'persona_context')
			AND (
				last_accessed_at IS NULL
				OR last_accessed_at < NOW() - ($2 * INTERVAL '1 day')
			)
	`, rate, olderThanDays)
	if err != nil {
		return 0, err
	}

	if err := tx.Commit(ctx); err != nil {
		return 0, err
	}
	return tag.RowsAffected(), nil
}
