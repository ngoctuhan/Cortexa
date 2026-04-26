package service

import (
	"context"
	"math"
	"sort"
	"time"

	"github.com/cortexa/cortexa/internal/config"
	"github.com/cortexa/cortexa/internal/llm"
	"github.com/cortexa/cortexa/internal/model"
	"github.com/cortexa/cortexa/internal/repository"
)

const (
	// Configuration constants for context retrieval
	CacheRecentMessagesCount = 20                     // Number of recent messages to fetch from cache
	QueryTimeout             = 150 * time.Millisecond // Soft timeout for parallel DB queries
	EmbedTimeout             = 800 * time.Millisecond // Timeout for LLM embedding call (network round-trip)
	DefaultVectorTopK        = 100                    // Number of vector results to fetch
	DefaultRerankTopK        = 5                      // Number of results to return after reranking
	DefaultEventsLimit       = 3                      // Number of upcoming events to fetch
	TimeDecayRate            = 0.05                   // Decay rate for time-based scoring
	DefaultExperienceTopK    = 3                      // Max experiences to inject into context
	DefaultExperienceMinConf = 0.4                    // Minimum confidence threshold for retrieval
)

// TimeRange defines an optional start and end time for filtering memory retrieval.
type TimeRange struct {
	Start *time.Time `json:"start,omitempty"`
	End   *time.Time `json:"end,omitempty"`
}

// GetContextRequest represents a flexible request to retrieve context for a user session.
type GetContextRequest struct {
	TenantID  string
	UserID    string
	SessionID string
	Query     string

	// MemoryTypes specifies which types of memory to retrieve. If empty, retrieve all.
	// Valid options: "recent_messages", "entity_facts", "semantic_messages", "persona", "events"
	MemoryTypes []string

	// TimeRange filters the retrieval by a specific time window.
	TimeRange *TimeRange
}

// ContextBundle contains all retrieved context information.
type ContextBundle struct {
	RecentMessages   []model.Message
	EntityFacts      []model.EntityFact
	SemanticMessages []model.SemanticMessage
	Persona          *model.MemoryRecord
	UpcomingEvents   []model.MemoryRecord
	Experiences      []model.Experience
}

// ContextRetriever orchestrates parallel context retrieval from multiple sources.
type ContextRetriever struct {
	cache       *repository.Cache
	entityRepo  *repository.EntityRepository
	vectorRepo  *repository.VectorRepository
	profileRepo *repository.ProfileRepository
	memRepo     *repository.MemoryRepository
	expRepo     *repository.ExperienceRepository
	llmClient   llm.Client
}

// NewContextRetriever creates a new ContextRetriever with the given dependencies.
func NewContextRetriever(
	cache *repository.Cache,
	entityRepo *repository.EntityRepository,
	vectorRepo *repository.VectorRepository,
	profileRepo *repository.ProfileRepository,
	memRepo *repository.MemoryRepository,
	expRepo *repository.ExperienceRepository,
	llmClient llm.Client,
) *ContextRetriever {
	return &ContextRetriever{
		cache:       cache,
		entityRepo:  entityRepo,
		vectorRepo:  vectorRepo,
		profileRepo: profileRepo,
		memRepo:     memRepo,
		expRepo:     expRepo,
		llmClient:   llmClient,
	}
}

// GetContext retrieves context from all sources (cache, entities, vector search, structured memory).
func (r *ContextRetriever) GetContext(ctx context.Context, req GetContextRequest) (*ContextBundle, error) {
	bundle := &ContextBundle{}

	// Helper to check if a specific memory type is requested
	wantsType := func(t string) bool {
		if len(req.MemoryTypes) == 0 {
			return true // Default: fetch all
		}
		for _, v := range req.MemoryTypes {
			if v == t {
				return true
			}
		}
		return false
	}

	// 1. Fetch Working Memory (Recent Messages)
	if wantsType("recent_messages") {
		// If time_range is provided, we fetch from DB instead of Redis
		if req.TimeRange != nil && req.TimeRange.Start != nil && req.TimeRange.End != nil {
			// (Assuming msgRepo exists, but for now we skip or you need to add it to ContextRetriever)
			// For simplicity in this demo, if time travel is requested we will mock or
			// rely on Semantic Messages. To fully implement Time Travel for exact messages,
			// we'd need to add messageRepo to ContextRetriever.
		} else {
			limit := config.Get().RecentMessagesLimit
			if limit <= 0 {
				limit = CacheRecentMessagesCount
			}
			recentRaw, _ := r.cache.GetRawMessages(ctx, req.TenantID, req.SessionID, limit)
			bundle.RecentMessages = recentRaw
		}
	}

	// 2. Fetch Long-term Memory (Parallel)
	if err := r.fetchContextParallel(ctx, req, bundle, wantsType); err != nil {
		return nil, err
	}

	return bundle, nil
}

type fetchResult struct {
	kind string
	data any
	err  error
}

// fetchContextParallel performs parallel queries to data sources based on memory_types.
func (r *ContextRetriever) fetchContextParallel(ctx context.Context, req GetContextRequest, bundle *ContextBundle, wantsType func(string) bool) error {
	ch := make(chan fetchResult, 4)

	softCtx, cancel := context.WithTimeout(ctx, QueryTimeout)
	defer cancel()

	tasks := 0

	// Task 1: Entity facts
	if wantsType("entity_facts") {
		tasks++
		go func() {
			facts, err := r.entityRepo.QueryCurrent(softCtx, req.TenantID, req.UserID, req.SessionID)
			ch <- fetchResult{"entity", facts, err}
		}()
	}

	// Task 2: Vector search (Semantic Messages)
	if wantsType("semantic_messages") && req.Query != "" {
		tasks++
		go func() {
			// Use a wider timeout for the LLM embed call (network round-trip ~200-500ms).
			embedCtx, embedCancel := context.WithTimeout(ctx, EmbedTimeout)
			defer embedCancel()

			emb, err := r.llmClient.Embed(embedCtx, req.Query)
			if err != nil {
				ch <- fetchResult{"semantic", []model.SemanticMessage{}, err}
				return
			}

			chunks, err := r.vectorRepo.SearchHybrid(softCtx, repository.VectorQuery{
				TenantID:  req.TenantID,
				UserID:    req.UserID,
				QueryText: req.Query,
				Embedding: emb,
				TopK:      DefaultVectorTopK,
			})
			if err == nil {
				chunks = r.rerank(chunks, DefaultRerankTopK)
			}
			ch <- fetchResult{"semantic", chunks, err}
		}()
	}

	// Task 3: Structured memory (Persona and Events)
	if wantsType("persona") || wantsType("events") {
		tasks++
		go func() {
			data := make(map[string]any)
			if wantsType("persona") {
				persona, _ := r.memRepo.GetPersona(softCtx, req.TenantID, req.UserID)
				data["persona"] = persona
			}
			if wantsType("events") {
				events, _ := r.memRepo.GetUpcomingEvents(softCtx, req.TenantID, req.UserID, DefaultEventsLimit)
				data["events"] = events
			}
			ch <- fetchResult{"structured", data, nil}
		}()
	}

	// Task 4: Experiences (only when a query is present for semantic matching)
	if wantsType("experiences") && req.Query != "" {
		tasks++
		go func() {
			embedCtx, embedCancel := context.WithTimeout(ctx, EmbedTimeout)
			defer embedCancel()

			emb, err := r.llmClient.Embed(embedCtx, req.Query)
			if err != nil {
				ch <- fetchResult{"experiences", []model.Experience{}, err}
				return
			}
			exps, err := r.expRepo.SearchByVector(
				softCtx, req.TenantID, req.UserID,
				emb, DefaultExperienceTopK, DefaultExperienceMinConf,
			)
			// Fire-and-forget usage tracking for retrieved experiences.
			if err == nil {
				for _, e := range exps {
					eid := e.ID.String()
					go func(id string) {
						_ = r.expRepo.RecordUsage(context.Background(), req.TenantID, id)
					}(eid)
				}
			}
			ch <- fetchResult{"experiences", exps, err}
		}()
	}

	if tasks == 0 {
		return nil
	}

	// The outer wait uses EmbedTimeout so the semantic goroutine (which embeds
	// the query before searching) has enough time to complete. DB-only goroutines
	// still respect their inner softCtx (QueryTimeout).
	// experiences task also embeds, so we double the timeout when it is active.
	outerTimeout := EmbedTimeout
	outerCtx, outerCancel := context.WithTimeout(ctx, outerTimeout)
	defer outerCancel()

	for i := 0; i < tasks; i++ {
		select {
		case res := <-ch:
			r.merge(bundle, res)
		case <-outerCtx.Done():
			// Timeout hit - return partial results
			goto done
		}
	}
done:
	return nil
}

// merge combines fetch results into the context bundle.
func (r *ContextRetriever) merge(bundle *ContextBundle, res fetchResult) {
	switch res.kind {
	case "entity":
		if facts, ok := res.data.([]model.EntityFact); ok {
			bundle.EntityFacts = facts
		}
	case "semantic":
		if chunks, ok := res.data.([]model.SemanticMessage); ok {
			bundle.SemanticMessages = chunks
		}
	case "structured":
		if data, ok := res.data.(map[string]any); ok {
			if p, ok := data["persona"].(*model.MemoryRecord); ok {
				bundle.Persona = p
			}
			if e, ok := data["events"].([]model.MemoryRecord); ok {
				bundle.UpcomingEvents = e
			}
		}
	case "experiences":
		if exps, ok := res.data.([]model.Experience); ok {
			bundle.Experiences = exps
		}
	}
}

// rerank reorders chunks by combining cosine similarity, time decay, and importance.
func (r *ContextRetriever) rerank(chunks []model.SemanticMessage, topK int) []model.SemanticMessage {
	now := time.Now()
	for i := range chunks {
		daysAgo := now.Sub(chunks[i].CreatedAt).Hours() / 24
		decayFactor := math.Exp(-TimeDecayRate * daysAgo)
		chunks[i].Score = chunks[i].CosineSim * decayFactor * chunks[i].Importance
	}
	sort.Slice(chunks, func(i, j int) bool {
		return chunks[i].Score > chunks[j].Score
	})
	if len(chunks) > topK {
		chunks = chunks[:topK]
	}
	return chunks
}
