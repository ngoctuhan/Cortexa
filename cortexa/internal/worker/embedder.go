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
	dsn   string
	redis *redis.Client
	llm   llm.Client
	sem   chan struct{} // limits concurrent batch embed calls
}

func NewEmbedderWorker(dsn string, r *redis.Client, l llm.Client) *EmbedderWorker {
	cfg := config.Get()
	return &EmbedderWorker{
		dsn:   dsn,
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

	conn, err := db.Pool.Acquire(ctx)
	if err != nil {
		return err
	}
	defer conn.Release()

	_, err = conn.Exec(ctx, "LISTEN new_message")
	if err != nil {
		return err
	}

	// payloadCh buffers incoming notifications so the PG listener loop is never
	// blocked by slow embed processing.
	payloadCh := make(chan model.MessagePayload, 256)
	go w.batchProcessor(ctx, payloadCh, db.Pool)

	for {
		notification, err := conn.Conn().WaitForNotification(ctx)
		if err != nil {
			if ctx.Err() != nil {
				close(payloadCh)
				return nil
			}
			time.Sleep(time.Second)
			continue
		}

		var payload model.MessagePayload
		if err := json.Unmarshal([]byte(notification.Payload), &payload); err == nil {
			select {
			case payloadCh <- payload:
			default:
				// Channel full — log and drop; message embedding will be skipped.
				log.Printf("Embedder: payload channel full, dropping message %s", payload.MessageID)
			}
		}
	}
}

// batchProcessor collects payloads from payloadCh and flushes them as a batch
// either when EmbedBatchMaxSize is reached or EmbedBatchWindow elapses.
func (w *EmbedderWorker) batchProcessor(ctx context.Context, payloadCh <-chan model.MessagePayload, pool *pgxpool.Pool) {
	ticker := time.NewTicker(EmbedBatchWindow)
	defer ticker.Stop()

	var batch []model.MessagePayload

	flush := func() {
		if len(batch) == 0 {
			return
		}
		toProcess := batch
		batch = nil
		// Acquire semaphore slot — blocks if CognitiveConcurrency is reached.
		w.sem <- struct{}{}
		go func() {
			defer func() { <-w.sem }()
			w.processBatch(ctx, toProcess, pool)
		}()
	}

	for {
		select {
		case <-ctx.Done():
			flush()
			return
		case p, ok := <-payloadCh:
			if !ok {
				flush()
				return
			}
			batch = append(batch, p)
			if len(batch) >= EmbedBatchMaxSize {
				flush()
			}
		case <-ticker.C:
			flush()
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

	// 3. Update DB for each message.
	for i, r := range records {
		embBytes, _ := json.Marshal(embeddings[i])
		if _, err := pool.Exec(ctx, `UPDATE messages SET embedding = $1 WHERE id::text = $2`, string(embBytes), r.id); err != nil {
			log.Printf("Embedder: db update error for %s: %v", r.id, err)
		}
	}

	// 4. Publish to Redis for downstream consumers.
	for _, p := range payloads {
		payloadBytes, _ := json.Marshal(p)
		w.redis.Publish(ctx, fmt.Sprintf("%s:events:messages", p.TenantID), payloadBytes)
	}
	log.Printf("Embedder: batch processed %d/%d messages for tenant %s", len(records), len(payloads), tenantID)
}
