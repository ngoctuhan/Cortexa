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
	"github.com/cortexa/cortexa/internal/security"
	"github.com/redis/go-redis/v9"
)

type CognitiveWorker struct {
	redis       *redis.Client
	llm         llm.Client
	entityRepo  *repository.EntityRepository
	memRepo     *repository.MemoryRepository
	profileRepo *repository.ProfileRepository
	usageRepo   *repository.LLMUsageRepository
	sem         chan struct{} // limits concurrent LLM calls
}

func NewCognitiveWorker(
	r *redis.Client,
	l llm.Client,
	entityRepo *repository.EntityRepository,
	memRepo *repository.MemoryRepository,
	profileRepo *repository.ProfileRepository,
	usageRepo *repository.LLMUsageRepository,
) *CognitiveWorker {
	cfg := config.Get()
	return &CognitiveWorker{
		redis:       r,
		llm:         l,
		entityRepo:  entityRepo,
		memRepo:     memRepo,
		profileRepo: profileRepo,
		usageRepo:   usageRepo,
		sem:         make(chan struct{}, cfg.CognitiveConcurrency),
	}
}

const (
	cognitiveConsumerGroup = "workers"
	cognitiveConsumerName  = "cognitive-worker"
	cognitiveMaxRetries    = 3
	cognitiveReadTimeout   = 5 * time.Second
	cognitiveStreamSuffix  = ":stream:cognitive"
	cognitiveDLQSuffix     = ":stream:cognitive:dlq"
)

// Subscribe reads cognitive batch events from every tenant stream via Redis Streams.
// It uses a consumer group to guarantee at-least-once delivery and moves permanently
// failing messages to a dead-letter queue after cognitiveMaxRetries attempts.
func (w *CognitiveWorker) Subscribe(ctx context.Context) {
	// We poll all known tenant streams. Tenant streams are discovered by scanning.
	// Each iteration reads up to 10 messages per stream.
	log.Println("CognitiveWorker: starting stream consumer")
	for {
		if ctx.Err() != nil {
			return
		}
		streams, err := w.discoverStreams(ctx)
		if err != nil || len(streams) == 0 {
			// Nothing to process yet — back off briefly.
			select {
			case <-ctx.Done():
				return
			case <-time.After(cognitiveReadTimeout):
			}
			continue
		}

		// Ensure consumer groups exist for each stream.
		for _, stream := range streams {
			w.ensureConsumerGroup(ctx, stream)
		}

		// Build XREADGROUP args: read new messages (">") from all streams.
		streamArgs := make([]string, 0, len(streams)*2)
		for _, s := range streams {
			streamArgs = append(streamArgs, s)
		}
		for range streams {
			streamArgs = append(streamArgs, ">")
		}

		results, err := w.redis.XReadGroup(ctx, &redis.XReadGroupArgs{
			Group:    cognitiveConsumerGroup,
			Consumer: cognitiveConsumerName,
			Streams:  streamArgs,
			Count:    10,
			Block:    cognitiveReadTimeout,
		}).Result()
		if err != nil && err != redis.Nil {
			if ctx.Err() != nil {
				return
			}
			continue
		}

		for _, result := range results {
			stream := result.Stream
			for _, msg := range result.Messages {
				msgID := msg.ID
				payload, _ := msg.Values["payload"].(string)
				retries := 0
				if r, ok := msg.Values["retries"].(string); ok {
					fmt.Sscanf(r, "%d", &retries)
				}

				go func(s, id, p string, r int) {
					w.sem <- struct{}{}
					defer func() { <-w.sem }()
					w.handleStreamMessage(ctx, s, id, p, r)
				}(stream, msgID, payload, retries)
			}
		}
	}
}

// handleStreamMessage processes one stream message, ACKs on success, retries or DLQs on failure.
func (w *CognitiveWorker) handleStreamMessage(ctx context.Context, stream, msgID, payload string, retries int) {
	err := w.processBatchPayload(ctx, payload)
	if err == nil {
		// Acknowledge successful processing.
		if ackErr := w.redis.XAck(ctx, stream, cognitiveConsumerGroup, msgID).Err(); ackErr != nil {
			log.Printf("CognitiveWorker: XACK failed for %s: %v", msgID, ackErr)
		}
		return
	}

	log.Printf("CognitiveWorker: processBatch error (attempt %d/%d): %v", retries+1, cognitiveMaxRetries, err)
	if retries+1 >= cognitiveMaxRetries {
		// Move to DLQ.
		tenantPrefix := strings.SplitN(stream, cognitiveStreamSuffix, 2)[0]
		dlq := tenantPrefix + cognitiveDLQSuffix
		_ = w.redis.XAdd(ctx, &redis.XAddArgs{
			Stream: dlq,
			MaxLen: 1000,
			Approx: true,
			Values: map[string]interface{}{
				"payload": payload,
				"retries": fmt.Sprintf("%d", retries+1),
				"error":   err.Error(),
			},
		}).Err()
		// ACK original to remove from pending list.
		_ = w.redis.XAck(ctx, stream, cognitiveConsumerGroup, msgID)
		log.Printf("CognitiveWorker: message %s moved to DLQ after %d retries", msgID, retries+1)
		return
	}

	// Re-enqueue with incremented retry count.
	_ = w.redis.XAdd(ctx, &redis.XAddArgs{
		Stream: stream,
		MaxLen: 10000,
		Approx: true,
		Values: map[string]interface{}{
			"payload": payload,
			"retries": fmt.Sprintf("%d", retries+1),
		},
	}).Err()
	_ = w.redis.XAck(ctx, stream, cognitiveConsumerGroup, msgID)
}

// discoverStreams scans Redis for all tenant cognitive streams.
func (w *CognitiveWorker) discoverStreams(ctx context.Context) ([]string, error) {
	var streams []string
	var cursor uint64
	for {
		keys, nextCursor, err := w.redis.Scan(ctx, cursor, "*"+cognitiveStreamSuffix, 100).Result()
		if err != nil {
			return nil, err
		}
		streams = append(streams, keys...)
		cursor = nextCursor
		if cursor == 0 {
			break
		}
	}
	return streams, nil
}

// ensureConsumerGroup creates the consumer group if it does not exist.
func (w *CognitiveWorker) ensureConsumerGroup(ctx context.Context, stream string) {
	err := w.redis.XGroupCreateMkStream(ctx, stream, cognitiveConsumerGroup, "0").Err()
	if err != nil && !strings.Contains(err.Error(), "BUSYGROUP") {
		log.Printf("CognitiveWorker: XGroupCreate error for %s: %v", stream, err)
	}
}

func (w *CognitiveWorker) processBatch(ctx context.Context, payload string) {
	if err := w.processBatchPayload(ctx, payload); err != nil {
		log.Printf("CognitiveWorker: processBatch error: %v", err)
	}
}

func (w *CognitiveWorker) processBatchPayload(ctx context.Context, payload string) error {
	var batchInfo struct {
		TenantID      string `json:"tenant_id"`
		UserID        string `json:"user_id"`
		SessionID     string `json:"session_id"`
		BatchSize     int    `json:"batch_size"`
		LastMessageID string `json:"last_message_id"`
	}
	if err := json.Unmarshal([]byte(payload), &batchInfo); err != nil {
		log.Printf("CognitiveWorker: parse batch payload err: %v\n", err)
		return err
	}

	// Inject tenant into context to activate Row-Level Security.
	ctx = repository.WithTenantID(ctx, batchInfo.TenantID)

	// Fetch the last N messages anchored to the message that triggered this batch,
	// preventing window-drift when events are processed after rapid bulk insertions.
	msgs, err := w.entityRepo.GetRecentMessagesUntil(ctx, batchInfo.TenantID, batchInfo.UserID, batchInfo.SessionID, batchInfo.LastMessageID, batchInfo.BatchSize)
	if err != nil || len(msgs) == 0 {
		if err == nil {
			err = fmt.Errorf("no messages to process")
		}
		log.Printf("CognitiveWorker: fetch messages err or empty: %v\n", err)
		return err
	}

	// Combine messages into a single transcript
	var transcriptBuilder strings.Builder
	for i := len(msgs) - 1; i >= 0; i-- {
		// Reverse loop to get chronological order (oldest to newest in the batch)
		transcriptBuilder.WriteString(fmt.Sprintf("[%s]: %s\n", msgs[i].Role, msgs[i].Content))
	}
	transcript := transcriptBuilder.String()

	// Use the latest message ID for reference in facts
	latestMsgID := msgs[0].ID

	mp := model.MessagePayload{
		MessageID: latestMsgID,
		UserID:    msgs[0].UserID,
		TenantID:  msgs[0].TenantID,
		SessionID: msgs[0].SessionID,
	}

	prompt, _ := w.buildBatchPrompt(ctx, mp.TenantID.String(), mp.UserID.String(), transcript)
	llmReq := llm.BuildLLMRequest("You are a cognitive data extractor", prompt)

	start := time.Now()
	resp, tokens, err := w.llm.Generate(ctx, llmReq)
	latency := time.Since(start)

	if err != nil {
		log.Printf("CognitiveWorker: llm error: %v\n", err)
		return err
	}
	log.Printf("CognitiveWorker: Batch Extraction (size %d) completed in %v, consumed %d tokens\n", batchInfo.BatchSize, latency, tokens)

	// Persist token usage for cost tracking
	usage := model.LLMUsage{
		TenantID:    mp.TenantID,
		UserID:      mp.UserID,
		SessionID:   mp.SessionID,
		Feature:     "cognitive_extraction",
		Model:       w.llm.ModelName(),
		TotalTokens: tokens,
		CreatedAt:   time.Now(),
	}
	if recErr := w.usageRepo.Record(ctx, usage); recErr != nil {
		log.Printf("CognitiveWorker: record usage error: %v\n", recErr)
	}

	// Strip markdown blocks if any
	resp = strings.TrimPrefix(resp, "```json")
	resp = strings.TrimPrefix(resp, "```")
	resp = strings.TrimSuffix(resp, "```")
	resp = strings.TrimSpace(resp)

	var respObj struct {
		Facts          []model.ExtractedFact `json:"facts"`
		Events         []map[string]string   `json:"events"`
		PersonaUpdates []string              `json:"persona_updates"`
	}
	if err := json.Unmarshal([]byte(resp), &respObj); err != nil {
		log.Printf("CognitiveWorker: json parse error on llm resp: %v\n", err)
		return err
	}

	// --- 1. Process Facts (with Upsert/Deduplication) ---
	cfg := config.Get()
	crypto, err := security.NewCrypto(cfg.MasterKey)
	if err != nil {
		log.Printf("CognitiveWorker: failed to init crypto (check MASTER_KEY): %v\n", err)
		return err
	}
	// Pre-filter duplicates from LLM response itself
	uniqueFacts := make(map[string]model.ExtractedFact)
	for _, f := range respObj.Facts {
		if err := security.ValidateExtractedFact(f); err != nil {
			continue
		}
		key := f.EntityName + "|" + f.Attribute
		uniqueFacts[key] = f
	}

	for _, f := range uniqueFacts {
		encVal, _ := crypto.EncryptValue(f.Value, mp.TenantID.String())
		valHash := security.ValueHash(f.Value)

		err := w.entityRepo.UpsertFact(ctx, mp, f, encVal, valHash)
		if err != nil {
			log.Printf("CognitiveWorker: db upsert fact error: %v\n", err)
		} else {
			log.Printf("CognitiveWorker: Extracted/Upserted fact %s - %s\n", f.EntityName, f.Attribute)
		}
	}

	// --- 2. Process Events (with Upsert/Deduplication) ---
	for _, ev := range respObj.Events {
		if ev["event_name"] == "" {
			continue
		}

		payloadBytes, _ := json.Marshal(ev)
		err := w.memRepo.UpsertEvent(ctx, mp.TenantID.String(), mp.UserID.String(), mp.SessionID.String(), string(payloadBytes))
		if err != nil {
			log.Printf("CognitiveWorker: db upsert event error: %v\n", err)
		} else {
			log.Printf("CognitiveWorker: Extracted/Upserted event '%s'\n", ev["event_name"])
		}
	}

	// --- 3. Process Persona Updates ---
	if len(respObj.PersonaUpdates) > 0 {
		err := w.memRepo.UpsertPersona(ctx, mp.TenantID.String(), mp.UserID.String(), mp.SessionID.String(), respObj.PersonaUpdates)
		if err != nil {
			log.Printf("CognitiveWorker: db upsert persona error: %v\n", err)
		} else {
			log.Printf("CognitiveWorker: Extracted/Upserted persona traits: %d\n", len(respObj.PersonaUpdates))
		}
	}
	return nil
}

func (w *CognitiveWorker) buildBatchPrompt(ctx context.Context, tenantID, userID, transcript string) (string, error) {
	knownEntities, _ := w.entityRepo.GetTopEntityNames(ctx, tenantID, userID, 20)
	userProfile, _ := w.profileRepo.Get(ctx, tenantID, userID)

	cfg := config.Get()
	return strings.NewReplacer(
		"{{CURRENT_TIME}}", time.Now().Format(time.RFC3339),
		"{{USER_NAME}}", userProfile.CanonicalName,
		"{{USER_ALIASES}}", strings.Join(userProfile.Aliases, ", "),
		"{{KNOWN_CONTACTS}}", strings.Join(knownEntities, ", "),
		"{{MESSAGE}}", transcript,
	).Replace(cfg.CognitivePrompt), nil
}
