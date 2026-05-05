package worker

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strings"
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

	// ensureGroup creates the consumer group if it doesn't exist (or if the
	// stream was recreated after a Redis restart, which drops all groups).
	ensureGroup := func() {
		if err := w.redis.XGroupCreateMkStream(ctx, stream, group, "0").Err(); err != nil {
			if err.Error() != "BUSYGROUP Consumer Group name already exists" {
				log.Printf("Embedder: failed to create consumer group: %v", err)
			}
		}
	}
	ensureGroup()

	// Reclaim idle pending messages every 30s so failed batches are retried.
	go func() {
		ticker := time.NewTicker(30 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
			}
			pending, err := w.redis.XPendingExt(ctx, &redis.XPendingExtArgs{
				Stream: stream,
				Group:  group,
				Idle:   25 * time.Second,
				Start:  "-",
				End:    "+",
				Count:  EmbedBatchMaxSize,
			}).Result()
			if err != nil {
				continue
			}
			if len(pending) == 0 {
				continue
			}
			ids := make([]string, len(pending))
			for i, p := range pending {
				ids[i] = p.ID
			}
			msgs, err := w.redis.XClaim(ctx, &redis.XClaimArgs{
				Stream:   stream,
				Group:    group,
				Consumer: consumer,
				MinIdle:  25 * time.Second,
				Messages: ids,
			}).Result()
			if err != nil || len(msgs) == 0 {
				continue
			}
			var retryPayloads []model.MessagePayload
			var retryIDs []string
			for _, msg := range msgs {
				payloadStr, ok := msg.Values["payload"].(string)
				if !ok {
					continue
				}
				var p model.MessagePayload
				if err := json.Unmarshal([]byte(payloadStr), &p); err == nil {
					retryPayloads = append(retryPayloads, p)
					retryIDs = append(retryIDs, msg.ID)
				}
			}
			if len(retryPayloads) == 0 {
				continue
			}
			log.Printf("Embedder: reclaiming %d idle pending messages", len(retryPayloads))
			w.sem <- struct{}{}
			go func(p []model.MessagePayload, rids []string) {
				defer func() { <-w.sem }()
				if err := w.processBatch(ctx, p, pool); err != nil {
					log.Printf("Embedder: reclaim batch failed: %v", err)
					return
				}
				if err := w.redis.XAck(ctx, stream, group, rids...).Err(); err != nil {
					log.Printf("Embedder: XAck error for reclaimed batch: %v", err)
				}
			}(retryPayloads, retryIDs)
		}
	}()

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
			// NOGROUP means the stream or consumer group was wiped (e.g. Redis
			// restart). Recreate the group and resume from the current tail so
			// we don't re-process the entire history on every restart.
			if strings.Contains(err.Error(), "NOGROUP") {
				log.Printf("Embedder: consumer group missing, recreating from current tail")
				if cErr := w.redis.XGroupCreateMkStream(ctx, stream, group, "$").Err(); cErr != nil {
					if cErr.Error() != "BUSYGROUP Consumer Group name already exists" {
						log.Printf("Embedder: recreate group error: %v", cErr)
					}
				}
				continue
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
				if err := w.processBatch(ctx, p, pool); err != nil {
					// Leave messages in PEL — they will be retried on the next poll cycle.
					log.Printf("Embedder: batch failed (will retry): %v", err)
					return
				}
				// ACK only after successful embedding.
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
func (w *EmbedderWorker) processBatch(ctx context.Context, payloads []model.MessagePayload, pool *pgxpool.Pool) error {
	byTenant := make(map[string][]model.MessagePayload)
	for _, p := range payloads {
		tid := p.TenantID.String()
		byTenant[tid] = append(byTenant[tid], p)
	}
	for tenantID, group := range byTenant {
		if err := w.processTenantBatch(ctx, tenantID, group, pool); err != nil {
			return err
		}
	}
	return nil
}

// processTenantBatch fetches message contents, calls EmbedBatch in one API call,
// then bulk-updates the DB and publishes events to Redis.
func (w *EmbedderWorker) processTenantBatch(ctx context.Context, tenantID string, payloads []model.MessagePayload, pool *pgxpool.Pool) error {
	// Inject tenant into context to activate Row-Level Security.
	ctx = repository.WithTenantID(ctx, tenantID)

	// 1. Fetch all message contents in a single query.
	ids := make([]string, len(payloads))
	for i, p := range payloads {
		ids[i] = p.MessageID.String()
	}
	rows, err := pool.Query(ctx, `SELECT id::text, content FROM messages WHERE id::text = ANY($1::text[])`, ids)
	if err != nil {
		log.Printf("Embedder [t:%s] batch query error: %v", shortID(tenantID), err)
		return err
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
		return nil
	}

	// 2. Call EmbedBatch — one LLM API call for the entire batch.
	texts := make([]string, len(records))
	for i, r := range records {
		texts[i] = r.content
	}
	embeddings, err := w.llm.EmbedBatch(ctx, texts)
	if err != nil {
		log.Printf("Embedder [t:%s] embed error: %v", shortID(tenantID), err)
		return err
	}
	if len(embeddings) != len(records) {
		log.Printf("Embedder [t:%s] embedding count mismatch: got %d expected %d", shortID(tenantID), len(embeddings), len(records))
		return fmt.Errorf("embedding count mismatch")
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
	log.Printf("Embedder [t:%s] processed %d/%d messages", shortID(tenantID), len(records), len(payloads))
	return nil
}
