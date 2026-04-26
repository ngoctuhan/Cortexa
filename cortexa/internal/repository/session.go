package repository

import (
	"context"

	"github.com/cortexa/cortexa/internal/model"
)

type SessionRepository struct {
	db *DB
}

func NewSessionRepository(db *DB) *SessionRepository {
	return &SessionRepository{db: db}
}

// Create inserts a new session and returns it.
func (r *SessionRepository) Create(ctx context.Context, s *model.Session) error {
	_, err := r.db.Pool.Exec(ctx, `
		INSERT INTO sessions (id, tenant_id, user_id, title, meta)
		VALUES ($1, $2, $3, $4, $5)
	`, s.ID, s.TenantID, s.UserID, s.Title, s.Meta)
	return err
}

// List returns paginated sessions for a user ordered by updated_at DESC.
func (r *SessionRepository) List(ctx context.Context, tenantID, userID string, limit, offset int) ([]model.Session, error) {
	if limit <= 0 || limit > 100 {
		limit = 20
	}
	rows, err := r.db.Pool.Query(ctx, `
		SELECT id, tenant_id, user_id, title, meta, created_at, updated_at
		FROM sessions
		WHERE tenant_id = $1 AND user_id = $2
		ORDER BY updated_at DESC
		LIMIT $3 OFFSET $4
	`, tenantID, userID, limit, offset)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var sessions []model.Session
	for rows.Next() {
		var s model.Session
		if err := rows.Scan(&s.ID, &s.TenantID, &s.UserID, &s.Title, &s.Meta, &s.CreatedAt, &s.UpdatedAt); err != nil {
			return nil, err
		}
		sessions = append(sessions, s)
	}
	return sessions, nil
}

// Delete removes a session (cascades to messages via FK).
func (r *SessionRepository) Delete(ctx context.Context, tenantID, sessionID string) (bool, error) {
	tag, err := r.db.Pool.Exec(ctx, `
		DELETE FROM sessions WHERE id = $1 AND tenant_id = $2
	`, sessionID, tenantID)
	if err != nil {
		return false, err
	}
	return tag.RowsAffected() > 0, nil
}
