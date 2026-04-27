package worker

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"time"

	"github.com/cortexa/cortexa/internal/config"
	"github.com/cortexa/cortexa/internal/llm"
	"github.com/cortexa/cortexa/internal/model"
	"github.com/cortexa/cortexa/internal/repository"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

const (
	// EmbedBatchMaxSize is the maximum number of messages collected before
	// flushing to the LLM batch embed API regardless of the time window.
	EmbedBatchMaxSize = 32
	// EmbedBatchWindow is the maximum time to wait before flushing a partial batch.
	EmbedBatchWindow = 200 * time.Millisecond
)

type EmbedderWorker struct {
	redis *redis.Client
	llm   llm.Client
	sem   chan struct{} // limits concurrent batch embed calls
}

func NewEmbedderWorker(r *redis.Client, l llm.Client) *EmbedderWorker {
	cfg := config.Get()
	return &EmbedderWorker{
		redis: r,
		llm:   l,
		sem:   make(chan struct{}, cfg.CognitiveConcurrency),
	}
}

func (w *EmbedderWorker) Listen(ctx context.Context) error {
	db, err := repository.GetDB(ctx)
	if err != nil {
		return err
	}
	pool := db.Pool

	stream := "global:stream:embedder"
	group := "embedder_group"
	consumer := fmt.Sprintf("embedder_worker_%d", time.Now().UnixNano())

	// Create consumer group
	err = w.redis.XGroupCreateMkStream(ctx, stream, group, "0").Err()
	if err != nil && err.Error() != "BUSYGROUP Consumer Group name already exists" {
		log.Printf("Embedder: failed to create consumer group: %v", err)
	}

	for {
		select {
		case <-ctx.Done():
			return nil
		default:
		}

		// Block for EmbedBatchWindow to fetch up to EmbedBatchMaxSize messages
		streams, err := w.redis.XReadGroup(ctx, &redis.XReadGroupArgs{
			Group:    group,
			Consumer: consumer,
			Streams:  []string{stream, ">"},
			Count:    EmbedBatchMaxSize,
			Block:    EmbedBatchWindow,
		}).Result()

		if err != nil {
			if err == redis.Nil {
				// Timeout, no new messages
				continue
			}
			if ctx.Err() != nil {
				return nil
			}
			log.Printf("Embedder: XReadGroup error: %v", err)
			time.Sleep(1 * time.Second)
			continue
		}

		if len(streams) == 0 || len(streams[0].Messages) == 0 {
			continue
		}

		var payloads []model.MessagePayload
		var msgIDs []string

		for _, msg := range streams[0].Messages {
			payloadStr, ok := msg.Values["payload"].(string)
			if !ok {
				if err := w.redis.XAck(ctx, stream, group, msg.ID).Err(); err != nil {
					log.Printf("Embedder: XAck error for malformed message %s: %v", msg.ID, err)
				}
				continue
			}
			var payload model.MessagePayload
			if err := json.Unmarshal([]byte(payloadStr), &payload); err == nil {
				payloads = append(payloads, payload)
				msgIDs = append(msgIDs, msg.ID)
			} else {
				if err := w.redis.XAck(ctx, stream, group, msg.ID).Err(); err != nil {
					log.Printf("Embedder: XAck error for unparseable message %s: %v", msg.ID, err)
				}
			}
		}

		if len(payloads) > 0 {
			// Acquire semaphore slot
			w.sem <- struct{}{}
			go func(p []model.MessagePayload, ids []string) {
				defer func() { <-w.sem }()
				w.processBatch(ctx, p, pool)
				// Ack messages after processing
				if len(ids) > 0 {
					if err := w.redis.XAck(ctx, stream, group, ids...).Err(); err != nil {
						log.Printf("Embedder: XAck error for batch: %v", err)
					}
				}
			}(payloads, msgIDs)
		}
	}
}

// processBatch groups payloads by tenant and calls processTenantBatch for each group.
func (w *EmbedderWorker) processBatch(ctx context.Context, payloads []model.MessagePayload, pool *pgxpool.Pool) {
	byTenant := make(map[string][]model.MessagePayload)
	for _, p := range payloads {
		tid := p.TenantID.String()
		byTenant[tid] = append(byTenant[tid], p)
	}
	for tenantID, group := range byTenant {
		w.processTenantBatch(ctx, tenantID, group, pool)
	}
}

// processTenantBatch fetches message contents, calls EmbedBatch in one API call,
// then bulk-updates the DB and publishes events to Redis.
func (w *EmbedderWorker) processTenantBatch(ctx context.Context, tenantID string, payloads []model.MessagePayload, pool *pgxpool.Pool) {
	// Inject tenant into context to activate Row-Level Security.
	ctx = repository.WithTenantID(ctx, tenantID)

	// 1. Fetch all message contents in a single query.
	ids := make([]string, len(payloads))
	for i, p := range payloads {
		ids[i] = p.MessageID.String()
	}
	rows, err := pool.Query(ctx, `SELECT id::text, content FROM messages WHERE id::text = ANY($1::text[])`, ids)
	if err != nil {
		log.Printf("Embedder: batch query error (tenant %s): %v", tenantID, err)
		return
	}
	type msgRecord struct{ id, content string }
	var records []msgRecord
	for rows.Next() {
		var r msgRecord
		if err := rows.Scan(&r.id, &r.content); err == nil {
			records = append(records, r)
		}
	}
	rows.Close()

	if len(records) == 0 {
		return
	}

	// 2. Call EmbedBatch — one LLM API call for the entire batch.
	texts := make([]string, len(records))
	for i, r := range records {
		texts[i] = r.content
	}
	embeddings, err := w.llm.EmbedBatch(ctx, texts)
	if err != nil {
		log.Printf("Embedder: batch embed error (tenant %s): %v", tenantID, err)
		return
	}
	if len(embeddings) != len(records) {
		log.Printf("Embedder: embedding count mismatch: got %d, expected %d", len(embeddings), len(records))
		return
	}

	// 3. Update DB for each message using pgx.Batch to prevent N+1 queries.
	batch := &pgx.Batch{}
	for i, r := range records {
		embBytes, _ := json.Marshal(embeddings[i])
		batch.Queue(`UPDATE messages SET embedding = $1 WHERE id::text = $2`, string(embBytes), r.id)
	}

	br := pool.SendBatch(ctx, batch)
	for i := 0; i < len(records); i++ {
		if _, err := br.Exec(); err != nil {
			log.Printf("Embedder: db update error for batch item %d: %v", i, err)
		}
	}
	br.Close()

	// 4. Publish to Redis for downstream consumers.
	for _, p := range payloads {
		payloadBytes, _ := json.Marshal(p)
		w.redis.Publish(ctx, fmt.Sprintf("%s:events:messages", p.TenantID), payloadBytes)
	}
	log.Printf("Embedder: batch processed %d/%d messages for tenant %s", len(records), len(payloads), tenantID)
}
