package repository

import (
	"context"
	"encoding/json"
	"log"

	"github.com/cortexa/cortexa/internal/config"
	"github.com/cortexa/cortexa/internal/model"
	"github.com/cortexa/cortexa/internal/security"
	"github.com/jackc/pgx/v5"
)

// EntityRepository handles entity-related database operations.
type EntityRepository struct {
	db *DB
}

// NewEntityRepository creates a new EntityRepository instance.
func NewEntityRepository(db *DB) *EntityRepository {
	return &EntityRepository{db: db}
}

// QueryCurrent retrieves all current (non-expired) entity facts for a user.
// It decrypts the encrypted values before returning them.
func (r *EntityRepository) QueryCurrent(ctx context.Context, tenantID, userID, sessionID string) ([]model.EntityFact, error) {
	// Query current entity facts (valid_until IS NULL), newest last so callers
	// can rely on list[-1] being the most recent fact for a given attribute.
	rows, err := r.db.Pool.Query(ctx, `
		SELECT entity_name, entity_type, attribute, value_encrypted, source_quote, confidence
		FROM entity_mentions
		WHERE tenant_id = $1 AND user_id = $2 AND valid_until IS NULL
		ORDER BY created_at ASC
	`, tenantID, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var facts []model.EntityFact
	cfg := config.Get()
	crypto, err := security.NewCrypto(cfg.MasterKey)
	if err != nil {
		return nil, err
	}

	for rows.Next() {
		var f model.EntityFact
		var enc []byte
		if err := rows.Scan(&f.EntityName, &f.EntityType, &f.Attribute, &enc, &f.SourceQuote, &f.Confidence); err != nil {
			continue
		}

		// Decrypt PII data
		decVal, err := crypto.DecryptValue(enc, tenantID)
		if err != nil {
			// Log error but continue with placeholder
			f.Value = "[encrypted]"
		} else {
			f.Value = decVal
		}

		facts = append(facts, f)
	}
	return facts, nil
}

// SearchByVector retrieves entity facts most semantically similar to the query embedding
// using HNSW approximate nearest neighbour search on entity_mentions.embedding.
//
// Falls back to confidence-sorted full dump when:
//   - No facts have been embedded yet (embedding IS NULL for all)
//   - The vector search returns 0 results
//
// Returns (facts, usedFallback, error).
func (r *EntityRepository) SearchByVector(ctx context.Context, tenantID, userID string, embedding []float32, topK int) ([]model.EntityFact, bool, error) {
	cfg := config.Get()
	crypto, err := security.NewCrypto(cfg.MasterKey)
	if err != nil {
		return nil, false, err
	}

	embBytes, _ := json.Marshal(embedding)

	rows, err := r.db.Pool.Query(ctx, `
		SELECT entity_name, entity_type, attribute, value_encrypted, source_quote, confidence
		FROM entity_mentions
		WHERE tenant_id = $1 AND user_id = $2 AND valid_until IS NULL AND embedding IS NOT NULL
		ORDER BY embedding <=> $3
		LIMIT $4
	`, tenantID, userID, string(embBytes), topK)
	if err != nil {
		return nil, false, err
	}
	defer rows.Close()

	facts, err := scanEntityFacts(rows, tenantID, crypto)
	if err != nil {
		return nil, false, err
	}
	if len(facts) > 0 {
		return facts, false, nil
	}

	// Fallback: no embeddings populated yet — return highest-confidence facts.
	facts, err = r.queryFactsFallback(ctx, tenantID, userID, crypto)
	return facts, true, err
}

// queryFactsFallback returns the top-N highest-confidence facts.
// Used when embeddings are not yet populated (cold start) or search returns 0.
func (r *EntityRepository) queryFactsFallback(ctx context.Context, tenantID, userID string, crypto *security.Crypto) ([]model.EntityFact, error) {
	rows, err := r.db.Pool.Query(ctx, `
		SELECT entity_name, entity_type, attribute, value_encrypted, source_quote, confidence
		FROM entity_mentions
		WHERE tenant_id = $1 AND user_id = $2 AND valid_until IS NULL
		ORDER BY confidence DESC, created_at DESC
		LIMIT 15
	`, tenantID, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanEntityFacts(rows, tenantID, crypto)
}

// UpdateFactEmbeddingsBatch batch-updates entity_mentions.embedding for a set of facts
// identified by (tenantID, userID, entityName, attribute) — the effective unique key
// for a current (valid_until IS NULL) fact.
func (r *EntityRepository) UpdateFactEmbeddingsBatch(ctx context.Context, tenantID, userID string, facts []model.ExtractedFact, embeddings [][]float32) error {
	if len(facts) == 0 {
		return nil
	}
	batch := &pgx.Batch{}
	for i, f := range facts {
		if i >= len(embeddings) || len(embeddings[i]) == 0 {
			continue
		}
		embBytes, _ := json.Marshal(embeddings[i])
		batch.Queue(`
			UPDATE entity_mentions
			SET embedding = $1
			WHERE tenant_id = $2 AND user_id = $3 AND entity_name = $4 AND attribute = $5 AND valid_until IS NULL
		`, string(embBytes), tenantID, userID, f.EntityName, f.Attribute)
	}
	br := r.db.Pool.SendBatch(ctx, batch)
	defer br.Close() //nolint:errcheck
	for i := 0; i < batch.Len(); i++ {
		if _, err := br.Exec(); err != nil {
			log.Printf("EntityRepository: UpdateFactEmbeddingsBatch item %d error: %v", i, err)
		}
	}
	return nil
}

// scanEntityFacts scans pgx rows into EntityFact slice, decrypting value_encrypted.
func scanEntityFacts(rows interface {
	Next() bool
	Scan(dest ...any) error
	Close()
}, tenantID string, crypto *security.Crypto) ([]model.EntityFact, error) {
	var facts []model.EntityFact
	for rows.Next() {
		var f model.EntityFact
		var enc []byte
		if err := rows.Scan(&f.EntityName, &f.EntityType, &f.Attribute, &enc, &f.SourceQuote, &f.Confidence); err != nil {
			continue
		}
		decVal, err := crypto.DecryptValue(enc, tenantID)
		if err != nil {
			f.Value = "[encrypted]"
		} else {
			f.Value = decVal
		}
		facts = append(facts, f)
	}
	return facts, nil
}

// GetRecentMessages retrieves the latest `limit` messages for a given user within a session.
// Useful for batch extraction.
func (r *EntityRepository) GetRecentMessages(ctx context.Context, tenantID, userID, sessionID string, limit int) ([]model.Message, error) {
	rows, err := r.db.Pool.Query(ctx, `
		SELECT id, tenant_id, session_id, user_id, role, content, token_count, created_at
		FROM messages
		WHERE tenant_id = $1 AND user_id = $2 AND session_id = $3
		ORDER BY created_at DESC
		LIMIT $4
	`, tenantID, userID, sessionID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var msgs []model.Message
	for rows.Next() {
		var m model.Message
		if err := rows.Scan(&m.ID, &m.TenantID, &m.SessionID, &m.UserID, &m.Role, &m.Content, &m.TokenCount, &m.CreatedAt); err != nil {
			return nil, err
		}
		msgs = append(msgs, m)
	}
	return msgs, nil
}

// GetRecentMessagesUntil retrieves up to `limit` messages with created_at <= the
// created_at of anchorMessageID. This prevents window-drift when batch events are
// processed long after rapid message insertions. Falls back to GetRecentMessages
// when anchorMessageID is empty or not found.
func (r *EntityRepository) GetRecentMessagesUntil(ctx context.Context, tenantID, userID, sessionID, anchorMessageID string, limit int) ([]model.Message, error) {
	if anchorMessageID == "" {
		return r.GetRecentMessages(ctx, tenantID, userID, sessionID, limit)
	}
	var anchorTime interface{}
	err := r.db.Pool.QueryRow(ctx, `
		SELECT created_at FROM messages WHERE id = $1 AND tenant_id = $2
	`, anchorMessageID, tenantID).Scan(&anchorTime)
	if err != nil {
		return r.GetRecentMessages(ctx, tenantID, userID, sessionID, limit)
	}
	rows, err := r.db.Pool.Query(ctx, `
		SELECT id, tenant_id, session_id, user_id, role, content, token_count, created_at
		FROM messages
		WHERE tenant_id = $1 AND user_id = $2 AND session_id = $3 AND created_at <= $4
		ORDER BY created_at DESC
		LIMIT $5
	`, tenantID, userID, sessionID, anchorTime, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var msgs []model.Message
	for rows.Next() {
		var m model.Message
		if err := rows.Scan(&m.ID, &m.TenantID, &m.SessionID, &m.UserID, &m.Role, &m.Content, &m.TokenCount, &m.CreatedAt); err != nil {
			return nil, err
		}
		msgs = append(msgs, m)
	}
	return msgs, nil
}

func (r *EntityRepository) GetMessage(ctx context.Context, messageID string) (*model.Message, error) {
	var m model.Message
	err := r.db.Pool.QueryRow(ctx, `
		SELECT id, tenant_id, session_id, user_id, role, content, token_count, created_at
		FROM messages WHERE id = $1
	`, messageID).Scan(&m.ID, &m.TenantID, &m.SessionID, &m.UserID, &m.Role, &m.Content, &m.TokenCount, &m.CreatedAt)
	if err != nil {
		return nil, err
	}
	return &m, nil
}

// upsertFactCTE is a single atomic statement covering all three cases:
// 1. Existing fact with same hash → no-op (deduplication)
// 2. Existing fact with different hash → invalidate old, insert new (supersede)
// 3. No existing fact → insert new
// Parameters: $1 tenantID, $2 userID, $3 entityName, $4 attribute, $5 valHash,
//
//	$6 sessionID, $7 messageID, $8 entityType, $9 encVal, $10 sourceQuote
const upsertFactCTE = `
WITH existing AS (
	SELECT id, value_hash
	FROM entity_mentions
	WHERE tenant_id=$1 AND user_id=$2 AND entity_name=$3 AND attribute=$4 AND valid_until IS NULL
	LIMIT 1
	FOR UPDATE
),
to_supersede AS (
	SELECT id FROM existing WHERE value_hash != $5
),
invalidated AS (
	UPDATE entity_mentions SET valid_until = NOW()
	WHERE id = (SELECT id FROM to_supersede)
)
INSERT INTO entity_mentions (
	tenant_id, user_id, session_id, message_id,
	entity_name, entity_type, attribute,
	value_encrypted, value_hash, source_quote, superseded_by
)
SELECT $1, $2, $6, $7, $3, $8, $4, $9, $5, $10,
       (SELECT id FROM to_supersede)
WHERE NOT EXISTS (SELECT 1 FROM existing WHERE value_hash = $5)
`

// UpsertFact inserts or updates an entity fact atomically via a single CTE,
// replacing the previous 3-step Read→Update→Insert Go pattern.
func (r *EntityRepository) UpsertFact(ctx context.Context, mp model.MessagePayload, f model.ExtractedFact, encVal []byte, valHash string) error {
	_, err := r.db.Pool.Exec(ctx, upsertFactCTE,
		mp.TenantID, mp.UserID, f.EntityName, f.Attribute, valHash,
		mp.SessionID, mp.MessageID, f.EntityType, encVal, f.SourceQuote,
	)
	return err
}

// UpsertFactBatch upserts multiple facts in a single pgx.Batch round-trip,
// reducing N DB round-trips down to one TCP exchange.
func (r *EntityRepository) UpsertFactBatch(ctx context.Context, mp model.MessagePayload, facts []model.ExtractedFact, encVals [][]byte, valHashes []string) error {
	batch := &pgx.Batch{}
	for i, f := range facts {
		batch.Queue(upsertFactCTE,
			mp.TenantID, mp.UserID, f.EntityName, f.Attribute, valHashes[i],
			mp.SessionID, mp.MessageID, f.EntityType, encVals[i], f.SourceQuote,
		)
	}
	br := r.db.Pool.SendBatch(ctx, batch)
	defer br.Close() //nolint:errcheck
	for range facts {
		if _, err := br.Exec(); err != nil {
			log.Printf("EntityRepository: upsert fact batch item error: %v", err)
		}
	}
	return nil
}

// InsertFact inserts a new entity fact without checking for duplicates.
func (r *EntityRepository) InsertFact(ctx context.Context, mp model.MessagePayload, f model.ExtractedFact, encVal []byte, valHash string) error {
	_, err := r.db.Pool.Exec(ctx, `
		INSERT INTO entity_mentions (tenant_id, user_id, session_id, message_id, entity_name, entity_type, attribute, value_encrypted, value_hash, source_quote)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
	`, mp.TenantID, mp.UserID, mp.SessionID, mp.MessageID, f.EntityName, f.EntityType, f.Attribute, encVal, valHash, f.SourceQuote)
	return err
}

// GetTopEntityNames retrieves the most frequently mentioned entity names for a user.
func (r *EntityRepository) GetTopEntityNames(ctx context.Context, tenantID, userID string, limit int) ([]string, error) {
	rows, err := r.db.Pool.Query(ctx, `
		SELECT entity_name
		FROM entity_mentions
		WHERE tenant_id = $1 AND user_id = $2
		GROUP BY entity_name
		ORDER BY COUNT(*) DESC
		LIMIT $3
	`, tenantID, userID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var names []string
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return nil, err
		}
		names = append(names, name)
	}
	return names, nil
}

// SearchSelfFacts retrieves all current entity facts where entity_type='self' for the given user.
// These represent the user's own identity (name, age, gender, job, etc.) and are always returned
// without any query-based filtering — they are pinned unconditionally into the context bundle.
func (r *EntityRepository) SearchSelfFacts(ctx context.Context, tenantID, userID string) ([]model.EntityFact, error) {
	cfg := config.Get()
	crypto, err := security.NewCrypto(cfg.MasterKey)
	if err != nil {
		return nil, err
	}

	rows, err := r.db.Pool.Query(ctx, `
		SELECT entity_name, entity_type, attribute, value_encrypted, source_quote, confidence
		FROM entity_mentions
		WHERE tenant_id = $1 AND user_id = $2 AND valid_until IS NULL AND entity_type = 'self'
		ORDER BY confidence DESC, created_at DESC
	`, tenantID, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	return scanEntityFacts(rows, tenantID, crypto)
}

// ResolveEntities uses FTS (plainto_tsquery) and trigram similarity to find entity names
// that are mentioned in the query. Only searches plaintext columns (entity_name) —
// no embedding required. Returns distinct entity names matched.
//
// Uses unaccent_immutable() (migration 007) so Postgres hits the GIN FTS index on
// entity_name instead of falling back to a sequential scan.
func (r *EntityRepository) ResolveEntities(ctx context.Context, tenantID, userID, query string) ([]string, error) {
	rows, err := r.db.Pool.Query(ctx, `
		SELECT DISTINCT entity_name
		FROM entity_mentions
		WHERE tenant_id = $1 AND user_id = $2 AND valid_until IS NULL AND entity_type != 'self'
		  AND (
		    to_tsvector('simple', unaccent_immutable(entity_name))
		      @@ plainto_tsquery('simple', unaccent_immutable($3))
		    OR
		    entity_name % $3
		  )
		ORDER BY entity_name
		LIMIT 10
	`, tenantID, userID, query)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var names []string
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return nil, err
		}
		names = append(names, name)
	}
	return names, nil
}

// QueryFactsByFTS fetches facts for the given entity names, ranked within each entity by
// ts_rank on (attribute || source_quote) against the query. Returns at most topKPerEntity
// facts per entity. Used as Phase 2 fallback when entity_mentions.embedding is not populated.
func (r *EntityRepository) QueryFactsByFTS(ctx context.Context, tenantID, userID, query string, entityNames []string, topKPerEntity int) ([]model.EntityFact, error) {
	if len(entityNames) == 0 {
		return nil, nil
	}

	cfg := config.Get()
	crypto, err := security.NewCrypto(cfg.MasterKey)
	if err != nil {
		return nil, err
	}

	rows, err := r.db.Pool.Query(ctx, `
		WITH ranked_facts AS (
		  SELECT
		    entity_name, entity_type, attribute, value_encrypted, source_quote, confidence,
		    ROW_NUMBER() OVER (
		      PARTITION BY entity_name
		      ORDER BY
		        ts_rank(
		          to_tsvector('simple', unaccent(attribute || ' ' || COALESCE(source_quote, ''))),
		          plainto_tsquery('simple', unaccent($3))
		        ) DESC,
		        confidence DESC,
		        created_at DESC
		    ) AS rn
		  FROM entity_mentions
		  WHERE tenant_id = $1 AND user_id = $2 AND valid_until IS NULL
		    AND entity_type != 'self'
		    AND entity_name = ANY($4)
		)
		SELECT entity_name, entity_type, attribute, value_encrypted, source_quote, confidence
		FROM ranked_facts
		WHERE rn <= $5
		ORDER BY entity_name, confidence DESC
	`, tenantID, userID, query, entityNames, topKPerEntity)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	return scanEntityFacts(rows, tenantID, crypto)
}

// QueryFactsByVector fetches facts for the given entity names, reranked within each entity by
// cosine distance to the query embedding. Returns at most topKPerEntity facts per entity.
// Only includes facts that have an embedding populated (by the cognitive worker).
// Falls back gracefully: if no facts have embeddings, callers should use QueryFactsByFTS.
func (r *EntityRepository) QueryFactsByVector(ctx context.Context, tenantID, userID string, embedding []float32, entityNames []string, topKPerEntity int) ([]model.EntityFact, error) {
	if len(entityNames) == 0 || len(embedding) == 0 {
		return nil, nil
	}

	cfg := config.Get()
	crypto, err := security.NewCrypto(cfg.MasterKey)
	if err != nil {
		return nil, err
	}

	embBytes, _ := json.Marshal(embedding)

	rows, err := r.db.Pool.Query(ctx, `
		WITH ranked_facts AS (
		  SELECT
		    entity_name, entity_type, attribute, value_encrypted, source_quote, confidence,
		    ROW_NUMBER() OVER (
		      PARTITION BY entity_name
		      ORDER BY embedding <=> $3, confidence DESC, created_at DESC
		    ) AS rn
		  FROM entity_mentions
		  WHERE tenant_id = $1 AND user_id = $2 AND valid_until IS NULL
		    AND entity_type != 'self'
		    AND entity_name = ANY($4)
		    AND embedding IS NOT NULL
		)
		SELECT entity_name, entity_type, attribute, value_encrypted, source_quote, confidence
		FROM ranked_facts
		WHERE rn <= $5
		ORDER BY entity_name, rn
	`, tenantID, userID, string(embBytes), entityNames, topKPerEntity)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	return scanEntityFacts(rows, tenantID, crypto)
}

// SearchAllFactsByVector is the query-aware fallback when Phase 1 FTS resolves no entity
// names. It runs cosine similarity over all third-party facts that have embeddings,
// returning the topK most relevant. Callers should fall back to FallbackFacts when this
// returns an empty slice (embeddings not yet populated by the worker).
func (r *EntityRepository) SearchAllFactsByVector(ctx context.Context, tenantID, userID string, embedding []float32, topK int) ([]model.EntityFact, error) {
	if len(embedding) == 0 {
		return nil, nil
	}

	cfg := config.Get()
	crypto, err := security.NewCrypto(cfg.MasterKey)
	if err != nil {
		return nil, err
	}

	embBytes, _ := json.Marshal(embedding)

	rows, err := r.db.Pool.Query(ctx, `
		SELECT entity_name, entity_type, attribute, value_encrypted, source_quote, confidence
		FROM entity_mentions
		WHERE tenant_id = $1 AND user_id = $2 AND valid_until IS NULL
		  AND entity_type != 'self'
		  AND embedding IS NOT NULL
		ORDER BY embedding <=> $3
		LIMIT $4
	`, tenantID, userID, string(embBytes), topK)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	return scanEntityFacts(rows, tenantID, crypto)
}

// FallbackFacts returns the highest-confidence third-party facts ordered by confidence.
// Used only as a last resort when both FTS entity resolution and vector search are
// unavailable (cold start: no embeddings populated yet, or embedding call failed).
func (r *EntityRepository) FallbackFacts(ctx context.Context, tenantID, userID string, limit int) ([]model.EntityFact, error) {
	cfg := config.Get()
	crypto, err := security.NewCrypto(cfg.MasterKey)
	if err != nil {
		return nil, err
	}

	rows, err := r.db.Pool.Query(ctx, `
		SELECT entity_name, entity_type, attribute, value_encrypted, source_quote, confidence
		FROM entity_mentions
		WHERE tenant_id = $1 AND user_id = $2 AND valid_until IS NULL AND entity_type != 'self'
		ORDER BY confidence DESC, created_at DESC
		LIMIT $3
	`, tenantID, userID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	return scanEntityFacts(rows, tenantID, crypto)
}
