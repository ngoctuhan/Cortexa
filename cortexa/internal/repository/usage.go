package repository

import (
	"context"

	"github.com/cortexa/cortexa/internal/model"
	"github.com/google/uuid"
)

// LLMUsageRepository persists LLM token consumption records.
type LLMUsageRepository struct {
	db *DB
}

func NewLLMUsageRepository(db *DB) *LLMUsageRepository {
	return &LLMUsageRepository{db: db}
}

// Record inserts one LLM usage event. Errors are non-fatal; callers may log and continue.
func (r *LLMUsageRepository) Record(ctx context.Context, u model.LLMUsage) error {
	_, err := r.db.Pool.Exec(ctx, `
		INSERT INTO llm_usage (id, tenant_id, user_id, session_id, feature, model, total_tokens, created_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
	`, uuid.New(), u.TenantID, u.UserID, u.SessionID, u.Feature, u.Model, u.TotalTokens, u.CreatedAt)
	return err
}
