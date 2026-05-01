package worker

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"regexp"
	"strings"
	"time"

	"github.com/cortexa/cortexa/internal/config"
	"github.com/cortexa/cortexa/internal/llm"
	"github.com/cortexa/cortexa/internal/model"
	"github.com/cortexa/cortexa/internal/repository"
	"github.com/cortexa/cortexa/internal/security"
	"github.com/redis/go-redis/v9"
)

// reJsonBlockCognitive extracts the outermost JSON object from an LLM response,
// tolerating markdown code fences around it.
var reJsonBlockCognitive = regexp.MustCompile(`(?s)\{.*\}`)

// errUnrecoverable wraps errors that should be sent straight to DLQ without retry.
type errUnrecoverable struct{ cause error }

func (e errUnrecoverable) Error() string { return e.cause.Error() }
func (e errUnrecoverable) Unwrap() error { return e.cause }

// isUnrecoverable returns true for error types where retrying will never help.
func isUnrecoverable(err error) bool {
	var u errUnrecoverable
	return errors.As(err, &u)
}

// shortID returns the first 8 characters of a UUID string for compact log tags.
// Sufficient to distinguish streams/tenants/users/sessions in log output.
func shortID(id string) string {
	if len(id) > 8 {
		return id[:8]
	}
	return id
}

type CognitiveWorker struct {
	redis       *redis.Client
	llm         llm.Client
	crypto      *security.Crypto // initialised once; safe for concurrent use
	cache       *repository.Cache
	entityRepo  *repository.EntityRepository
	memRepo     *repository.MemoryRepository
	profileRepo *repository.ProfileRepository
	usageRepo   *repository.LLMUsageRepository
	sem         chan struct{} // limits concurrent LLM calls
	scanCursor  uint64        // persistent cursor for fair round-robin stream discovery
}

func NewCognitiveWorker(
	r *redis.Client,
	l llm.Client,
	cache *repository.Cache,
	entityRepo *repository.EntityRepository,
	memRepo *repository.MemoryRepository,
	profileRepo *repository.ProfileRepository,
	usageRepo *repository.LLMUsageRepository,
) *CognitiveWorker {
	cfg := config.Get()
	crypto, err := security.NewCrypto(cfg.MasterKey)
	if err != nil {
		log.Fatalf("CognitiveWorker: failed to init crypto (check MASTER_KEY): %v", err)
	}
	return &CognitiveWorker{
		redis:       r,
		llm:         l,
		crypto:      crypto,
		cache:       cache,
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
	cognitiveMaxRetries    = 8
	cognitiveReadTimeout   = 5 * time.Second
	cognitiveStreamSuffix  = ":stream:cognitive"
	cognitiveDLQSuffix     = ":stream:cognitive:dlq"
	// cognitiveRetryIdleTime is how long a message must sit unacknowledged in the
	// Pending Entry List before XAUTOCLAIM reclaims it for retry. This gives the
	// previous attempt time to finish and provides natural backoff without a sleep.
	cognitiveRetryIdleTime = 20 * time.Second
)

// Subscribe reads cognitive batch events from every tenant stream via Redis Streams.
// It uses a consumer group to guarantee at-least-once delivery and moves permanently
// failing messages to a dead-letter queue after cognitiveMaxRetries attempts.
func (w *CognitiveWorker) Subscribe(ctx context.Context) {
	// We poll all known tenant streams. Tenant streams are discovered by scanning.
	// Each iteration reads up to 10 messages per stream.
	log.Println("CognitiveWorker: starting stream consumer")

	// Start a parallel loop that reclaims idle pending messages for retry.
	go w.reclaimPending(ctx)
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

				go func(s, id, p string) {
					w.sem <- struct{}{}
					defer func() { <-w.sem }()
					// Pass retries=0: this is the first delivery from the main loop.
					// Subsequent retries are handled by reclaimPending which uses
					// XPendingExt.RetryCount as the authoritative delivery counter.
					w.handleStreamMessage(ctx, s, id, p, 0)
				}(stream, msgID, payload)
			}
		}
	}
}

// handleStreamMessage processes one stream message, ACKs on success, retries or DLQs on failure.
// Unrecoverable errors (bad payload, JSON parse failure) go straight to DLQ without retrying.
// Transient errors (LLM timeout, DB down) do NOT re-enqueue — the message stays in the
// PEL and reclaimPending will reclaim it after cognitiveRetryIdleTime has elapsed, providing
// natural backoff without holding a semaphore slot while waiting.
func (w *CognitiveWorker) handleStreamMessage(ctx context.Context, stream, msgID, payload string, retries int) {
	tenantPrefix := strings.SplitN(stream, cognitiveStreamSuffix, 2)[0]
	log.Printf("CognitiveWorker [stream=%s] recv msg=%s attempt=%d", shortID(tenantPrefix), msgID, retries+1)

	err := w.processBatchPayload(ctx, payload)
	if err == nil {
		// Acknowledge successful processing.
		if ackErr := w.redis.XAck(ctx, stream, cognitiveConsumerGroup, msgID).Err(); ackErr != nil {
			log.Printf("CognitiveWorker [stream=%s] XACK failed msg=%s: %v", shortID(tenantPrefix), msgID, ackErr)
		}
		return
	}

	// Unrecoverable errors (malformed payload, unparseable LLM JSON, missing key)
	// will never succeed on retry → send directly to DLQ.
	if isUnrecoverable(err) || retries+1 >= cognitiveMaxRetries {
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
		_ = w.redis.XAck(ctx, stream, cognitiveConsumerGroup, msgID)
		log.Printf("CognitiveWorker [stream=%s] msg=%s → DLQ (unrecoverable=%v attempts=%d): %v",
			shortID(tenantPrefix), msgID, isUnrecoverable(err), retries+1, err)
		return
	}

	// Transient error: do NOT ACK and do NOT re-enqueue.
	// The message stays in the PEL; reclaimPending will pick it up after the
	// idle timeout expires, giving the system time to recover before retrying.
	log.Printf("CognitiveWorker [stream=%s] msg=%s transient error attempt=%d/%d: %v",
		shortID(tenantPrefix), msgID, retries+1, cognitiveMaxRetries, err)
}

// reclaimPending periodically uses XPendingExt + XClaim to re-deliver messages
// that have been sitting unacknowledged in the PEL for longer than
// cognitiveRetryIdleTime. XPendingExt gives the real delivery count (RetryCount)
// from the PEL, which is used as the authoritative retry counter instead of the
// "retries" field stored in the message Values (which is immutable after XADD).
func (w *CognitiveWorker) reclaimPending(ctx context.Context) {
	ticker := time.NewTicker(cognitiveRetryIdleTime / 2)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
		streams, err := w.discoverStreams(ctx)
		if err != nil || len(streams) == 0 {
			continue
		}
		for _, stream := range streams {
			// Use XPendingExt to find idle entries and get their true delivery count.
			pending, err := w.redis.XPendingExt(ctx, &redis.XPendingExtArgs{
				Stream: stream,
				Group:  cognitiveConsumerGroup,
				Idle:   cognitiveRetryIdleTime,
				Start:  "-",
				End:    "+",
				Count:  10,
			}).Result()
			if err != nil {
				continue
			}
			for _, p := range pending {
				// RetryCount is the number of times Redis has delivered this entry.
				// Subtract 1 to get "previous attempts" (consistent with retries param).
				tenantPart := strings.SplitN(stream, cognitiveStreamSuffix, 2)[0]
				retries := int(p.RetryCount) - 1
				log.Printf("CognitiveWorker [stream=%s] reclaim msg=%s (deliveries=%d)", shortID(tenantPart), p.ID, p.RetryCount)

				// Claim the message to get its payload.
				msgs, err := w.redis.XClaim(ctx, &redis.XClaimArgs{
					Stream:   stream,
					Group:    cognitiveConsumerGroup,
					Consumer: cognitiveConsumerName,
					MinIdle:  cognitiveRetryIdleTime,
					Messages: []string{p.ID},
				}).Result()
				if err != nil || len(msgs) == 0 {
					continue
				}
				payload, _ := msgs[0].Values["payload"].(string)
				w.sem <- struct{}{}
				go func(s, id, pl string, r int) {
					defer func() { <-w.sem }()
					w.handleStreamMessage(ctx, s, id, pl, r)
				}(stream, p.ID, payload, retries)
			}
		}
	}
}

// discoverStreams scans Redis for all tenant cognitive streams.
// cognitiveMaxStreamsPerTick is the maximum number of streams to read in a single
// XReadGroup call. Capping this prevents XREADGROUP from being overwhelmed when
// thousands of test/tenant streams accumulate in Redis.
// A persistent cursor ensures fair round-robin scheduling across all streams,
// preventing new streams from being starved by accumulated older ones.
const cognitiveMaxStreamsPerTick = 100

func (w *CognitiveWorker) discoverStreams(ctx context.Context) ([]string, error) {
	var streams []string
	cursor := w.scanCursor
	for {
		keys, nextCursor, err := w.redis.Scan(ctx, cursor, "*"+cognitiveStreamSuffix, 100).Result()
		if err != nil {
			return nil, err
		}
		streams = append(streams, keys...)
		cursor = nextCursor
		if cursor == 0 || len(streams) >= cognitiveMaxStreamsPerTick {
			break
		}
	}
	// Save cursor position for next call to ensure all streams get a turn.
	// When cursor wraps back to 0 we restart from the beginning.
	w.scanCursor = cursor
	if len(streams) > cognitiveMaxStreamsPerTick {
		streams = streams[:cognitiveMaxStreamsPerTick]
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

func (w *CognitiveWorker) processBatchPayload(ctx context.Context, payload string) error {
	var batchInfo struct {
		TenantID      string `json:"tenant_id"`
		UserID        string `json:"user_id"`
		SessionID     string `json:"session_id"`
		BatchSize     int    `json:"batch_size"`
		LastMessageID string `json:"last_message_id"`
	}
	if err := json.Unmarshal([]byte(payload), &batchInfo); err != nil {
		log.Printf("CognitiveWorker: parse batch payload err: %v", err)
		return errUnrecoverable{err} // malformed payload will never parse correctly
	}
	tag := fmt.Sprintf("[t:%s u:%s s:%s]", shortID(batchInfo.TenantID), shortID(batchInfo.UserID), shortID(batchInfo.SessionID))

	// Inject tenant into context to activate Row-Level Security.
	ctx = repository.WithTenantID(ctx, batchInfo.TenantID)

	// Try the Redis message cache first, anchored to the batch's last_message_id
	// to avoid window drift when newer messages arrive before the worker processes
	// this event. Falls back to a DB query on cache miss or anchor not found.
	msgs, err := w.cache.GetRawMessagesUntil(ctx, batchInfo.TenantID, batchInfo.SessionID, batchInfo.LastMessageID, batchInfo.BatchSize)
	if err != nil || len(msgs) == 0 {
		msgs, err = w.entityRepo.GetRecentMessagesUntil(ctx, batchInfo.TenantID, batchInfo.UserID, batchInfo.SessionID, batchInfo.LastMessageID, batchInfo.BatchSize)
	}
	if err != nil || len(msgs) == 0 {
		if err == nil {
			err = fmt.Errorf("no messages to process")
		}
		log.Printf("CognitiveWorker %s fetch messages: %v", tag, err)
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
		log.Printf("CognitiveWorker %s LLM error: %v", tag, err)
		return err
	}
	log.Printf("CognitiveWorker %s LLM done latency=%v tokens=%d", tag, latency, tokens)

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
		log.Printf("CognitiveWorker %s usage record error: %v", tag, recErr)
	}

	// Extract JSON object, tolerating any surrounding markdown fences.
	resp = extractCognitiveJSON(resp)

	var respObj struct {
		Facts          []model.ExtractedFact `json:"facts"`
		Events         []map[string]string   `json:"events"`
		PersonaUpdates []string              `json:"persona_updates"`
	}
	if err := json.Unmarshal([]byte(resp), &respObj); err != nil {
		log.Printf("CognitiveWorker %s LLM response parse error: %v", tag, err)
		return errUnrecoverable{err} // bad LLM output won't improve on retry
	}

	// --- 1. Process Facts (with Upsert/Deduplication) ---
	// Pre-filter duplicates from LLM response itself
	uniqueFacts := make(map[string]model.ExtractedFact)
	for _, f := range respObj.Facts {
		if err := security.ValidateExtractedFact(f); err != nil {
			continue
		}
		key := f.EntityName + "|" + f.Attribute
		uniqueFacts[key] = f
	}

	// Collect and encrypt all valid facts, then send in one pgx.Batch round-trip.
	batchFacts := make([]model.ExtractedFact, 0, len(uniqueFacts))
	batchEncVals := make([][]byte, 0, len(uniqueFacts))
	batchValHashes := make([]string, 0, len(uniqueFacts))
	for _, f := range uniqueFacts {
		encVal, err := w.crypto.EncryptValue(f.Value, mp.TenantID.String())
		if err != nil {
			log.Printf("CognitiveWorker %s encrypt fact %q: %v", tag, f.EntityName, err)
			continue
		}
		batchFacts = append(batchFacts, f)
		batchEncVals = append(batchEncVals, encVal)
		batchValHashes = append(batchValHashes, security.ValueHash(f.Value))
	}
	if len(batchFacts) > 0 {
		if err := w.entityRepo.UpsertFactBatch(ctx, mp, batchFacts, batchEncVals, batchValHashes); err != nil {
			log.Printf("CognitiveWorker %s upsert facts error: %v", tag, err)
		}
	}

	// --- 2. Process Events (with Upsert/Deduplication) ---
	// Also convert any birthday/anniversary facts to events (LLM sometimes
	// categorises them as facts even when instructed to use events).
	var eventPayloads []string
	for _, ev := range respObj.Events {
		if ev["event_name"] == "" {
			continue
		}
		payloadBytes, _ := json.Marshal(ev)
		eventPayloads = append(eventPayloads, string(payloadBytes))
	}
	for _, f := range uniqueFacts {
		if strings.EqualFold(f.Attribute, "birthday") || strings.EqualFold(f.Attribute, "anniversary") {
			eventName := "Sinh nhật " + f.EntityName
			if strings.EqualFold(f.EntityType, "self") || strings.EqualFold(f.EntityName, "user") {
				eventName = "Sinh nhật của tôi"
			}
			ev := map[string]string{"event_name": eventName, "date": f.Value}
			payloadBytes, _ := json.Marshal(ev)
			eventPayloads = append(eventPayloads, string(payloadBytes))
			log.Printf("CognitiveWorker %s birthday fact→event for %q", tag, f.EntityName)
		}
	}
	if len(eventPayloads) > 0 {
		if err := w.memRepo.UpsertEventBatch(ctx, mp.TenantID.String(), mp.UserID.String(), mp.SessionID.String(), eventPayloads); err != nil {
			log.Printf("CognitiveWorker %s upsert events error: %v", tag, err)
		}
	}

	// --- 3. Process Persona Updates ---
	if len(respObj.PersonaUpdates) > 0 {
		err := w.memRepo.UpsertPersona(ctx, mp.TenantID.String(), mp.UserID.String(), mp.SessionID.String(), respObj.PersonaUpdates)
		if err != nil {
			log.Printf("CognitiveWorker %s upsert persona error: %v", tag, err)
		}
	}

	log.Printf("CognitiveWorker %s done facts=%d events=%d persona=%d", tag, len(batchFacts), len(eventPayloads), len(respObj.PersonaUpdates))
	return nil
}

// extractCognitiveJSON returns the first JSON object found in s, stripping
// any surrounding markdown code fences.
func extractCognitiveJSON(s string) string {
	s = strings.TrimSpace(s)
	if loc := reJsonBlockCognitive.FindStringIndex(s); loc != nil {
		return s[loc[0]:loc[1]]
	}
	return s
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
