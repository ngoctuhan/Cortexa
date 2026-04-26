package repository

import (
	"context"
	"encoding/json"

	"github.com/cortexa/cortexa/internal/model"
)

type MessageRepository struct {
	db *DB
}

func NewMessageRepository(db *DB) *MessageRepository {
	return &MessageRepository{db: db}
}

func (r *MessageRepository) InsertMessage(ctx context.Context, msg *model.Message) error {
	// First ensure session exists
	_, err := r.db.Pool.Exec(ctx, `
		INSERT INTO sessions (id, tenant_id, user_id)
		VALUES ($1, $2, $3)
		ON CONFLICT (id) DO NOTHING
	`, msg.SessionID, msg.TenantID, msg.UserID)
	if err != nil {
		return err
	}

	_, err = r.db.Pool.Exec(ctx, `
		INSERT INTO messages (id, tenant_id, session_id, user_id, role, content, token_count)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
	`, msg.ID, msg.TenantID, msg.SessionID, msg.UserID, msg.Role, msg.Content, msg.TokenCount)
	return err
}

func (r *MessageRepository) UpdateEmbedding(ctx context.Context, messageID string, embedding []float32) error {
	embStr := formatVector(embedding)
	_, err := r.db.Pool.Exec(ctx, `
		UPDATE messages SET embedding = $1 WHERE id = $2
	`, embStr, messageID)
	return err
}

func formatVector(v []float32) string {
	b, _ := json.Marshal(v)
	return string(b)
}

func (r *MessageRepository) GetRecent(ctx context.Context, tenantID, userID string, limit int) ([]model.Message, error) {
	rows, err := r.db.Pool.Query(ctx, `
		SELECT id, tenant_id, session_id, user_id, role, content, token_count, created_at
		FROM messages
		WHERE tenant_id = $1 AND user_id = $2
		ORDER BY created_at DESC
		LIMIT $3
	`, tenantID, userID, limit)
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

// GetSessionHistory returns paginated messages for a session, newest first.
// Pass beforeID to get messages older than that message (cursor-based pagination).
// Pass limit to control page size (max 100).
func (r *MessageRepository) GetSessionHistory(ctx context.Context, tenantID, sessionID string, limit int, beforeID string) ([]model.Message, error) {
	if limit <= 0 || limit > 100 {
		limit = 50
	}

	var query string
	var args []interface{}

	if beforeID == "" {
		query = `
                        SELECT id, tenant_id, session_id, user_id, role, content, token_count, created_at
                        FROM messages
                        WHERE tenant_id = $1 AND session_id = $2
                        ORDER BY created_at DESC
                        LIMIT $3`
		args = []interface{}{tenantID, sessionID, limit}
	} else {
		query = `
                        SELECT id, tenant_id, session_id, user_id, role, content, token_count, created_at
                        FROM messages
                        WHERE tenant_id = $1 AND session_id = $2
                          AND created_at < (SELECT created_at FROM messages WHERE id = $3 AND tenant_id = $1)
                        ORDER BY created_at DESC
                        LIMIT $4`
		args = []interface{}{tenantID, sessionID, beforeID, limit}
	}

	rows, err := r.db.Pool.Query(ctx, query, args...)
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
