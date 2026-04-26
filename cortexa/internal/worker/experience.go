package worker

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/cortexa/cortexa/internal/config"
	"github.com/cortexa/cortexa/internal/llm"
	"github.com/cortexa/cortexa/internal/model"
	"github.com/cortexa/cortexa/internal/repository"
	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
)

const (
	experienceConsumerGroup = "exp-workers"
	experienceConsumerName  = "experience-worker"
	experienceWindowSize    = 20   // max messages to inspect per trigger
	experienceTier1Depth    = 8    // how many recent messages to scan for keywords (Tier 1)
	experienceSimilarityMin = 0.85 // cosine sim threshold: merge vs insert
	experienceReadTimeout   = 5 * time.Second
)

// tier1Keywords are cheap string signals indicating a learning moment.
// If none found in the last experienceTier1Depth messages, skip LLM call.
var tier1Keywords = []string{
	// Vietnamese
	"lần sau", "nhớ", "luôn luôn", "luôn ", "không phải", "thay vào đó",
	"đúng rồi", "chính xác", "gần rồi", "không đúng", "sai rồi",
	"cần phải", "nên ", "thay vì", "tốt hơn nếu", "từ nay",
	// English
	"next time", "always ", "remember", "instead", "that's right",
	"exactly", "not like that", "you should", "please always",
	"going forward", "from now on", "in the future", "don't do",
}

// ExperienceWorker subscribes to the same cognitive stream using a separate
// consumer group and extracts learned behaviors from conversation windows.
type ExperienceWorker struct {
	redis       *redis.Client
	llm         llm.Client
	entityRepo  *repository.EntityRepository
	expRepo     *repository.ExperienceRepository
	profileRepo *repository.ProfileRepository
	sem         chan struct{}
}

// NewExperienceWorker creates a new ExperienceWorker.
func NewExperienceWorker(
	r *redis.Client,
	l llm.Client,
	entityRepo *repository.EntityRepository,
	expRepo *repository.ExperienceRepository,
	profileRepo *repository.ProfileRepository,
) *ExperienceWorker {
	cfg := config.Get()
	return &ExperienceWorker{
		redis:       r,
		llm:         l,
		entityRepo:  entityRepo,
		expRepo:     expRepo,
		profileRepo: profileRepo,
		sem:         make(chan struct{}, cfg.CognitiveConcurrency),
	}
}

// Subscribe reads from the same tenant cognitive streams as CognitiveWorker
// but uses its own consumer group so both workers receive every message.
func (w *ExperienceWorker) Subscribe(ctx context.Context) {
	log.Println("ExperienceWorker: starting stream consumer")
	for {
		if ctx.Err() != nil {
			return
		}
		streams, err := w.discoverStreams(ctx)
		if err != nil || len(streams) == 0 {
			select {
			case <-ctx.Done():
				return
			case <-time.After(experienceReadTimeout):
			}
			continue
		}

		for _, stream := range streams {
			w.ensureConsumerGroup(ctx, stream)
		}

		streamArgs := make([]string, 0, len(streams)*2)
		for _, s := range streams {
			streamArgs = append(streamArgs, s)
		}
		for range streams {
			streamArgs = append(streamArgs, ">")
		}

		results, err := w.redis.XReadGroup(ctx, &redis.XReadGroupArgs{
			Group:    experienceConsumerGroup,
			Consumer: experienceConsumerName,
			Streams:  streamArgs,
			Count:    10,
			Block:    experienceReadTimeout,
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
					if err := w.processPayload(ctx, p); err != nil {
						log.Printf("ExperienceWorker: process error: %v", err)
					}
					_ = w.redis.XAck(ctx, s, experienceConsumerGroup, id).Err()
				}(stream, msgID, payload)
			}
		}
	}
}

// processPayload is the main entry point per batch event.
func (w *ExperienceWorker) processPayload(ctx context.Context, payload string) error {
	var batchInfo struct {
		TenantID      string `json:"tenant_id"`
		UserID        string `json:"user_id"`
		SessionID     string `json:"session_id"`
		LastMessageID string `json:"last_message_id"`
	}
	if err := json.Unmarshal([]byte(payload), &batchInfo); err != nil {
		return fmt.Errorf("parse payload: %w", err)
	}

	ctx = repository.WithTenantID(ctx, batchInfo.TenantID)

	// Fetch a wider window anchored to the triggering message to prevent
	// window-drift when batch events are processed after rapid bulk insertions.
	msgs, err := w.entityRepo.GetRecentMessagesUntil(
		ctx, batchInfo.TenantID, batchInfo.UserID, batchInfo.SessionID, batchInfo.LastMessageID, experienceWindowSize,
	)
	if err != nil || len(msgs) == 0 {
		return nil // nothing to process
	}

	// Reverse to chronological order (GetRecentMessages returns newest-first).
	chronological := make([]model.Message, len(msgs))
	for i, m := range msgs {
		chronological[len(msgs)-1-i] = m
	}

	// --- TIER 1: keyword scan on last experienceTier1Depth messages (zero LLM cost) ---
	scanDepth := experienceTier1Depth
	if len(chronological) < scanDepth {
		scanDepth = len(chronological)
	}
	recentSlice := chronological[len(chronological)-scanDepth:]

	if !hasTier1Signal(recentSlice) {
		return nil // no signal → skip entirely
	}

	// --- TIER 2: find correction boundary, build smart slice, call LLM ---
	smartSlice := findSmartSlice(chronological)
	window := buildWindowTranscript(smartSlice)

	prompt := w.buildPrompt(ctx, batchInfo.TenantID, batchInfo.UserID, window, len(smartSlice))

	resp, _, err := w.llm.Generate(ctx, llm.BuildLLMRequest(
		"You are an experience extractor. Return JSON only. No markdown.",
		prompt,
	))
	if err != nil {
		return fmt.Errorf("llm generate: %w", err)
	}

	resp = strings.TrimPrefix(resp, "```json")
	resp = strings.TrimPrefix(resp, "```")
	resp = strings.TrimSuffix(resp, "```")
	resp = strings.TrimSpace(resp)

	var result struct {
		HasSignal   bool     `json:"has_signal"`
		Description string   `json:"description"`
		Steps       []string `json:"steps"`
	}
	if err := json.Unmarshal([]byte(resp), &result); err != nil {
		log.Printf("ExperienceWorker: json parse error: %v | raw: %s", err, resp)
		return nil // soft fail — don't crash the worker
	}

	if !result.HasSignal || result.Description == "" || len(result.Steps) == 0 {
		return nil
	}

	// Embed the description for similarity search.
	embedding, err := w.llm.Embed(ctx, result.Description)
	if err != nil {
		return fmt.Errorf("embed description: %w", err)
	}

	sessionID, _ := uuid.Parse(batchInfo.SessionID)

	// Use the latest message ID in the smart slice as source reference.
	latestMsgID := chronological[len(chronological)-1].ID

	// Check if a similar experience already exists → merge or insert.
	similar, _, err := w.expRepo.SearchSimilar(
		ctx, batchInfo.TenantID, batchInfo.UserID, embedding, experienceSimilarityMin,
	)
	if err != nil {
		log.Printf("ExperienceWorker: similarity search error: %v", err)
	}

	var similarID *uuid.UUID
	if similar != nil {
		similarID = &similar.ID
	}

	if upsertErr := w.expRepo.UpsertExperience(
		ctx,
		batchInfo.TenantID, batchInfo.UserID,
		sessionID, latestMsgID,
		result.Description, result.Steps,
		embedding, similarID,
	); upsertErr != nil {
		return fmt.Errorf("upsert experience: %w", upsertErr)
	}

	if similarID != nil {
		log.Printf("ExperienceWorker: merged experience (id=%s) for user %s", similarID, batchInfo.UserID)
	} else {
		log.Printf("ExperienceWorker: new experience created for user %s: %q", batchInfo.UserID, result.Description)
	}
	return nil
}

// hasTier1Signal scans messages for any keyword that indicates a learning signal.
func hasTier1Signal(msgs []model.Message) bool {
	for _, m := range msgs {
		lower := strings.ToLower(m.Content)
		for _, kw := range tier1Keywords {
			if strings.Contains(lower, kw) {
				return true
			}
		}
	}
	return false
}

// findSmartSlice scans backward to find where the correction/instruction starts,
// returning a tight slice instead of the full window.
// It looks for the first message containing a tier1 keyword and returns from
// one message before that point to the end of the window.
func findSmartSlice(msgs []model.Message) []model.Message {
	boundaryIdx := 0
	for i := len(msgs) - 1; i >= 0; i-- {
		lower := strings.ToLower(msgs[i].Content)
		for _, kw := range tier1Keywords {
			if strings.Contains(lower, kw) {
				boundaryIdx = i
				break
			}
		}
	}
	// Include one message before the boundary for context.
	start := boundaryIdx - 1
	if start < 0 {
		start = 0
	}
	return msgs[start:]
}

// buildWindowTranscript formats a slice of messages into a plain-text transcript.
func buildWindowTranscript(msgs []model.Message) string {
	var sb strings.Builder
	for _, m := range msgs {
		role := strings.ToUpper(m.Role[:1]) + m.Role[1:]
		content := m.Content
		// Truncate very long messages to cap token usage.
		if utf8.RuneCountInString(content) > 300 {
			runes := []rune(content)
			content = string(runes[:300]) + "…"
		}
		sb.WriteString(fmt.Sprintf("[%s]: %s\n", role, content))
	}
	return sb.String()
}

// buildPrompt renders the experience_extractor.j2 template.
func (w *ExperienceWorker) buildPrompt(ctx context.Context, tenantID, userID, window string, msgCount int) string {
	userProfile, _ := w.profileRepo.Get(ctx, tenantID, userID)
	cfg := config.Get()
	return strings.NewReplacer(
		"{{CURRENT_TIME}}", time.Now().Format(time.RFC3339),
		"{{USER_NAME}}", userProfile.CanonicalName,
		"{{MESSAGE_COUNT}}", fmt.Sprintf("%d", msgCount),
		"{{CONVERSATION_WINDOW}}", window,
	).Replace(cfg.ExperiencePrompt)
}

func (w *ExperienceWorker) discoverStreams(ctx context.Context) ([]string, error) {
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

func (w *ExperienceWorker) ensureConsumerGroup(ctx context.Context, stream string) {
	err := w.redis.XGroupCreateMkStream(ctx, stream, experienceConsumerGroup, "0").Err()
	if err != nil && !strings.Contains(err.Error(), "BUSYGROUP") {
		log.Printf("ExperienceWorker: XGroupCreate error for %s: %v", stream, err)
	}
}
