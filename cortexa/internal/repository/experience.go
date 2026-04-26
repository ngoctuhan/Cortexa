package repository

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/cortexa/cortexa/internal/model"
	"github.com/google/uuid"
)

// ExperienceRepository handles database access for user-scoped learned experiences.
type ExperienceRepository struct {
	db *DB
}

// NewExperienceRepository creates a new ExperienceRepository.
func NewExperienceRepository(db *DB) *ExperienceRepository {
	return &ExperienceRepository{db: db}
}

// UpsertExperience inserts a new experience or merges with an existing one
// when the provided similar experience ID matches (cosine_sim > threshold).
// If similarID is nil, always insert a new record.
func (r *ExperienceRepository) UpsertExperience(
	ctx context.Context,
	tenantID, userID string,
	sessionID uuid.UUID,
	messageID uuid.UUID,
	description string,
	steps []string,
	embedding []float32,
	similarID *uuid.UUID,
) error {
	stepsJSON, err := json.Marshal(steps)
	if err != nil {
		return fmt.Errorf("marshal steps: %w", err)
	}

	embJSON, err := json.Marshal(embedding)
	if err != nil {
		return fmt.Errorf("marshal embedding: %w", err)
	}

	if similarID != nil {
		// Merge into existing: update description, steps, bump confidence, append source message.
		_, err = r.db.Pool.Exec(ctx, `
			UPDATE experiences
			SET
				description        = $3,
				steps              = $4,
				trigger_embedding  = $5,
				source_session_id  = $6,
				source_message_ids = array_append(source_message_ids, $7),
				confidence         = LEAST(1.0, confidence + 0.05),
				updated_at         = NOW()
			WHERE id = $1 AND tenant_id = $2
		`, similarID, tenantID, description, string(stepsJSON), string(embJSON),
			sessionID, messageID)
		return err
	}

	// Insert brand-new experience.
	_, err = r.db.Pool.Exec(ctx, `
		INSERT INTO experiences
			(tenant_id, user_id, description, steps, trigger_embedding,
			 source_session_id, source_message_ids, confidence)
		VALUES ($1, $2, $3, $4, $5, $6, ARRAY[$7::uuid], 0.5)
	`, tenantID, userID, description, string(stepsJSON), string(embJSON),
		sessionID, messageID)
	return err
}

// SearchSimilar finds the most similar active experience for a user by vector cosine similarity.
// Returns the best match if its similarity exceeds the threshold, otherwise returns nil.
func (r *ExperienceRepository) SearchSimilar(
	ctx context.Context,
	tenantID, userID string,
	embedding []float32,
	threshold float64,
) (*model.Experience, float64, error) {
	embJSON, err := json.Marshal(embedding)
	if err != nil {
		return nil, 0, fmt.Errorf("marshal embedding: %w", err)
	}

	row := r.db.Pool.QueryRow(ctx, `
		SELECT id, tenant_id, user_id, description, steps,
		       source_session_id, confidence, usage_count, success_count,
		       is_active, created_at, updated_at,
		       1 - (trigger_embedding <=> $3) AS cosine_sim
		FROM experiences
		WHERE tenant_id = $1 AND user_id = $2 AND is_active = true
		  AND trigger_embedding IS NOT NULL
		ORDER BY trigger_embedding <=> $3
		LIMIT 1
	`, tenantID, userID, string(embJSON))

	var exp model.Experience
	var steps []byte
	var sourceSessionID *uuid.UUID
	var sim float64

	err = row.Scan(
		&exp.ID, &exp.TenantID, &exp.UserID, &exp.Description, &steps,
		&sourceSessionID, &exp.Confidence, &exp.UsageCount, &exp.SuccessCount,
		&exp.IsActive, &exp.CreatedAt, &exp.UpdatedAt, &sim,
	)
	if err != nil {
		return nil, 0, nil // no result or scan error — treat as no match
	}
	exp.Steps = json.RawMessage(steps)
	exp.SourceSessionID = sourceSessionID

	if sim < threshold {
		return nil, sim, nil // below threshold → no match
	}
	return &exp, sim, nil
}

// SearchByVector retrieves top-K active experiences for a user ordered by cosine similarity.
// Used by ContextRetriever to inject relevant experiences into the context bundle.
func (r *ExperienceRepository) SearchByVector(
	ctx context.Context,
	tenantID, userID string,
	embedding []float32,
	topK int,
	minConfidence float64,
) ([]model.Experience, error) {
	embJSON, err := json.Marshal(embedding)
	if err != nil {
		return nil, fmt.Errorf("marshal embedding: %w", err)
	}

	rows, err := r.db.Pool.Query(ctx, `
		SELECT id, tenant_id, user_id, description, steps,
		       source_session_id, confidence, usage_count, success_count,
		       is_active, created_at, updated_at
		FROM experiences
		WHERE tenant_id = $1 AND user_id = $2
		  AND is_active = true
		  AND confidence >= $4
		  AND trigger_embedding IS NOT NULL
		ORDER BY trigger_embedding <=> $3
		LIMIT $5
	`, tenantID, userID, string(embJSON), minConfidence, topK)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var results []model.Experience
	for rows.Next() {
		var exp model.Experience
		var steps []byte
		var sourceSessionID *uuid.UUID
		if err := rows.Scan(
			&exp.ID, &exp.TenantID, &exp.UserID, &exp.Description, &steps,
			&sourceSessionID, &exp.Confidence, &exp.UsageCount, &exp.SuccessCount,
			&exp.IsActive, &exp.CreatedAt, &exp.UpdatedAt,
		); err != nil {
			continue
		}
		exp.Steps = json.RawMessage(steps)
		exp.SourceSessionID = sourceSessionID
		results = append(results, exp)
	}
	return results, nil
}

// ListByUser returns all active experiences for a user, ordered by confidence descending.
func (r *ExperienceRepository) ListByUser(ctx context.Context, tenantID, userID string) ([]model.Experience, error) {
	rows, err := r.db.Pool.Query(ctx, `
		SELECT id, tenant_id, user_id, description, steps,
		       source_session_id, confidence, usage_count, success_count,
		       is_active, created_at, updated_at
		FROM experiences
		WHERE tenant_id = $1 AND user_id = $2 AND is_active = true
		ORDER BY confidence DESC
	`, tenantID, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var results []model.Experience
	for rows.Next() {
		var exp model.Experience
		var steps []byte
		var sourceSessionID *uuid.UUID
		if err := rows.Scan(
			&exp.ID, &exp.TenantID, &exp.UserID, &exp.Description, &steps,
			&sourceSessionID, &exp.Confidence, &exp.UsageCount, &exp.SuccessCount,
			&exp.IsActive, &exp.CreatedAt, &exp.UpdatedAt,
		); err != nil {
			continue
		}
		exp.Steps = json.RawMessage(steps)
		exp.SourceSessionID = sourceSessionID
		results = append(results, exp)
	}
	return results, nil
}

// RecordUsage increments usage_count for an experience.
// Called by ContextRetriever when an experience is injected into context.
func (r *ExperienceRepository) RecordUsage(ctx context.Context, tenantID, experienceID string) error {
	_, err := r.db.Pool.Exec(ctx, `
		UPDATE experiences
		SET usage_count = usage_count + 1, updated_at = NOW()
		WHERE tenant_id = $1 AND id = $2
	`, tenantID, experienceID)
	return err
}

// RecordFeedback records a positive or negative signal from the host application.
//   - positive: increments success_count, recalculates confidence = success / (usage + 1)
//   - negative (3rd consecutive): deactivates the experience (is_active = false)
func (r *ExperienceRepository) RecordFeedback(ctx context.Context, tenantID, userID, experienceID string, positive bool) error {
	if positive {
		_, err := r.db.Pool.Exec(ctx, `
			UPDATE experiences
			SET
				success_count = success_count + 1,
				confidence    = LEAST(1.0, CAST(success_count + 1 AS FLOAT) / NULLIF(usage_count + 1, 0)),
				updated_at    = NOW()
			WHERE tenant_id = $1 AND user_id = $2 AND id = $3
		`, tenantID, userID, experienceID)
		return err
	}

	// Negative: reduce confidence. Deactivate if confidence drops below 0.1.
	_, err := r.db.Pool.Exec(ctx, `
		UPDATE experiences
		SET
			confidence = GREATEST(0.01, confidence - 0.15),
			is_active  = CASE WHEN confidence - 0.15 < 0.1 THEN false ELSE is_active END,
			updated_at = NOW()
		WHERE tenant_id = $1 AND user_id = $2 AND id = $3
	`, tenantID, userID, experienceID)
	return err
}

// Deactivate soft-deletes an experience (is_active = false).
func (r *ExperienceRepository) Deactivate(ctx context.Context, tenantID, userID, experienceID string) error {
	_, err := r.db.Pool.Exec(ctx, `
		UPDATE experiences
		SET is_active = false, updated_at = NOW()
		WHERE tenant_id = $1 AND user_id = $2 AND id = $3
	`, tenantID, userID, experienceID)
	return err
}
