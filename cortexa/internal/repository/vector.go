package repository

import (
	"context"
	"encoding/json"
	"sort"

	"github.com/cortexa/cortexa/internal/model"
	"github.com/google/uuid"
)

type VectorQuery struct {
	TenantID  string
	UserID    string
	QueryText string
	Embedding []float32
	TopK      int
}

type VectorRepository struct {
	db *DB
}

func NewVectorRepository(db *DB) *VectorRepository {
	return &VectorRepository{db: db}
}

func (r *VectorRepository) Search(ctx context.Context, q VectorQuery) ([]model.SemanticMessage, error) {
	embBytes, _ := json.Marshal(q.Embedding)
	embStr := string(embBytes)

	// For actual vector search we need to search messages or memory_records with vector embeddings.
	// We'll search messages as "SemanticMessage" for simplicity here.
	rows, err := r.db.Pool.Query(ctx, `
		SELECT id, content, 1 - (embedding <=> $3) AS cosine_sim, created_at
		FROM messages
		WHERE tenant_id = $1 AND user_id = $2 AND embedding IS NOT NULL
		ORDER BY embedding <=> $3
		LIMIT $4
	`, q.TenantID, q.UserID, embStr, q.TopK)

	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var chunks []model.SemanticMessage
	for rows.Next() {
		var chunk model.SemanticMessage
		if err := rows.Scan(&chunk.ID, &chunk.Content, &chunk.CosineSim, &chunk.CreatedAt); err != nil {
			return nil, err
		}
		chunk.Importance = 1.0 // Default importance
		chunks = append(chunks, chunk)
	}
	return chunks, nil
}

// rrfK is the ranking constant used in Reciprocal Rank Fusion.
// A value of 60 is the standard default from the original RRF paper.
const rrfK = 60

// SearchHybrid performs hybrid retrieval by combining pgvector ANN search with
// PostgreSQL full-text search (FTS) using Reciprocal Rank Fusion (RRF):
//
//	score = 1/(rrfK + rank_vector) + 1/(rrfK + rank_fts)
//
// This improves recall for short queries and proper nouns that vector search
// tends to miss. Both sub-queries run in parallel goroutines.
func (r *VectorRepository) SearchHybrid(ctx context.Context, q VectorQuery) ([]model.SemanticMessage, error) {
	type subResult struct {
		chunks []model.SemanticMessage
		err    error
	}

	vecCh := make(chan subResult, 1)
	ftsCh := make(chan subResult, 1)

	// --- Goroutine 1: ANN vector search ---
	go func() {
		embBytes, _ := json.Marshal(q.Embedding)
		embStr := string(embBytes)

		rows, err := r.db.Pool.Query(ctx, `
			SELECT id, content, 1 - (embedding <=> $3) AS cosine_sim, created_at
			FROM messages
			WHERE tenant_id = $1 AND user_id = $2 AND embedding IS NOT NULL
			ORDER BY embedding <=> $3
			LIMIT $4
		`, q.TenantID, q.UserID, embStr, q.TopK)
		if err != nil {
			vecCh <- subResult{err: err}
			return
		}
		defer rows.Close()

		var chunks []model.SemanticMessage
		for rows.Next() {
			var c model.SemanticMessage
			if err := rows.Scan(&c.ID, &c.Content, &c.CosineSim, &c.CreatedAt); err != nil {
				continue
			}
			c.Importance = 1.0
			chunks = append(chunks, c)
		}
		vecCh <- subResult{chunks: chunks}
	}()

	// --- Goroutine 2: Full-text search ---
	go func() {
		if q.QueryText == "" {
			ftsCh <- subResult{chunks: nil}
			return
		}
		rows, err := r.db.Pool.Query(ctx, `
			SELECT id, content,
			       ts_rank(to_tsvector('simple', content), plainto_tsquery('simple', $3)) AS fts_rank,
			       created_at
			FROM messages
			WHERE tenant_id = $1 AND user_id = $2
			  AND to_tsvector('simple', content) @@ plainto_tsquery('simple', $3)
			ORDER BY fts_rank DESC
			LIMIT $4
		`, q.TenantID, q.UserID, q.QueryText, q.TopK)
		if err != nil {
			ftsCh <- subResult{err: err}
			return
		}
		defer rows.Close()

		var chunks []model.SemanticMessage
		for rows.Next() {
			var c model.SemanticMessage
			var ftsRank float64
			if err := rows.Scan(&c.ID, &c.Content, &ftsRank, &c.CreatedAt); err != nil {
				continue
			}
			c.CosineSim = ftsRank
			c.Importance = 1.0
			chunks = append(chunks, c)
		}
		ftsCh <- subResult{chunks: chunks}
	}()

	vecRes := <-vecCh
	ftsRes := <-ftsCh

	// If both searches fail, propagate the vector error.
	if vecRes.err != nil && ftsRes.err != nil {
		return nil, vecRes.err
	}

	return rrfMerge(vecRes.chunks, ftsRes.chunks, q.TopK), nil
}

// rrfMerge combines two ranked result lists into a single list using Reciprocal
// Rank Fusion. Items that appear in both lists get a boosted score.
func rrfMerge(vecChunks, ftsChunks []model.SemanticMessage, topK int) []model.SemanticMessage {
	scores := make(map[uuid.UUID]float64)
	byID := make(map[uuid.UUID]model.SemanticMessage)

	for rank, c := range vecChunks {
		scores[c.ID] += 1.0 / float64(rrfK+rank+1)
		byID[c.ID] = c
	}
	for rank, c := range ftsChunks {
		scores[c.ID] += 1.0 / float64(rrfK+rank+1)
		if _, exists := byID[c.ID]; !exists {
			byID[c.ID] = c
		}
	}

	merged := make([]model.SemanticMessage, 0, len(scores))
	for id, chunk := range byID {
		chunk.Score = scores[id]
		merged = append(merged, chunk)
	}
	sort.Slice(merged, func(i, j int) bool {
		return merged[i].Score > merged[j].Score
	})
	if len(merged) > topK {
		merged = merged[:topK]
	}
	return merged
}
