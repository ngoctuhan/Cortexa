package repository

import (
	"context"
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
