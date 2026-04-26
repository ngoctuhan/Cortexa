package repository

import (
	"context"
	"encoding/json"

	"github.com/cortexa/cortexa/internal/model"
)

type MemoryRepository struct {
	db *DB
}

func NewMemoryRepository(db *DB) *MemoryRepository {
	return &MemoryRepository{db: db}
}

func (r *MemoryRepository) GetPersona(ctx context.Context, tenantID, userID string) (*model.MemoryRecord, error) {
	row := r.db.Pool.QueryRow(ctx, `
		SELECT id, type, payload, importance, access_count, created_at
		FROM memory_records
		WHERE tenant_id = $1 AND user_id = $2 AND type = 'persona'
		ORDER BY created_at DESC
		LIMIT 1
	`, tenantID, userID)

	var m model.MemoryRecord
	var payload []byte
	if err := row.Scan(&m.ID, &m.Type, &payload, &m.Importance, &m.AccessCount, &m.CreatedAt); err != nil {
		return nil, nil
	}
	m.Payload = json.RawMessage(payload)
	return &m, nil
}

func (r *MemoryRepository) UpsertPersona(ctx context.Context, tenantID, userID, sessionID string, newTraits []string) error {
	existing, _ := r.GetPersona(ctx, tenantID, userID)

	traitsMap := make(map[string]bool)
	var currentTraits []string

	if existing != nil && len(existing.Payload) > 0 {
		_ = json.Unmarshal(existing.Payload, &currentTraits)
		for _, t := range currentTraits {
			traitsMap[t] = true
		}
	}

	updated := false
	for _, t := range newTraits {
		if !traitsMap[t] {
			currentTraits = append(currentTraits, t)
			traitsMap[t] = true
			updated = true
		}
	}

	if !updated {
		return nil
	}

	payloadBytes, _ := json.Marshal(currentTraits)
	payloadStr := string(payloadBytes)

	if existing != nil {
		_, err := r.db.Pool.Exec(ctx, `
			UPDATE memory_records 
			SET payload = $1, session_id = $2 
			WHERE id = $3
		`, payloadStr, sessionID, existing.ID)
		return err
	}

	_, err := r.db.Pool.Exec(ctx, `
		INSERT INTO memory_records (tenant_id, user_id, session_id, type, payload, importance)
		VALUES ($1, $2, $3, 'persona', $4, 1.0)
	`, tenantID, userID, sessionID, payloadStr)
	return err
}

func (r *MemoryRepository) GetUpcomingEvents(ctx context.Context, tenantID, userID string, limit int) ([]model.MemoryRecord, error) {
	rows, err := r.db.Pool.Query(ctx, `
		SELECT id, type, payload, importance, access_count, created_at
		FROM memory_records
		WHERE tenant_id = $1 AND user_id = $2 AND type = 'life_event'
		ORDER BY created_at DESC
		LIMIT $3
	`, tenantID, userID, limit)
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

func (r *MemoryRepository) UpsertEvent(ctx context.Context, tenantID, userID, sessionID, payload string) error {
	var existingID string
	err := r.db.Pool.QueryRow(ctx, `
		SELECT id FROM memory_records 
		WHERE tenant_id = $1 AND user_id = $2 AND type = 'life_event' AND payload::text = $3
		LIMIT 1
	`, tenantID, userID, payload).Scan(&existingID)

	if err == nil {
		// Exact match found -> Deduplicate (do nothing)
		return nil
	}

	// Insert new event
	_, err = r.db.Pool.Exec(ctx, `
		INSERT INTO memory_records (tenant_id, user_id, session_id, type, payload, importance)
		VALUES ($1, $2, $3, 'life_event', $4, 0.8)
	`, tenantID, userID, sessionID, payload)
	return err
}

func (r *MemoryRepository) InsertEvent(ctx context.Context, tenantID, userID, sessionID string, payload string) error {
	_, err := r.db.Pool.Exec(ctx, `
		INSERT INTO memory_records (tenant_id, user_id, session_id, type, payload, importance)
		VALUES ($1, $2, $3, 'life_event', $4, 0.8)
	`, tenantID, userID, sessionID, payload)
	return err
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
