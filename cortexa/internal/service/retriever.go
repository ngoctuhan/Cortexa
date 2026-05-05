package service

import (
	"context"
	"log"
	"time"
	"unicode/utf8"

	"github.com/cortexa/cortexa/internal/config"
	"github.com/cortexa/cortexa/internal/llm"
	"github.com/cortexa/cortexa/internal/model"
	"github.com/cortexa/cortexa/internal/repository"
)

const (
	// Configuration constants for context retrieval
	CacheRecentMessagesCount = 20              // Number of recent messages to fetch from cache
	QueryTimeout             = 2 * time.Second // Soft timeout for parallel DB queries (incl. HNSW vector search)
	EmbedTimeout             = 5 * time.Second // Timeout for LLM embedding call (network round-trip)
	DefaultEventsLimit       = 5               // Number of upcoming events to fetch
	TimeDecayRate            = 0.05            // Decay rate for time-based scoring
	DefaultExperienceTopK    = 3               // Max experiences to inject into context
	DefaultExperienceMinConf = 0.4             // Minimum confidence threshold for retrieval
	DefaultEntityFactsTopK   = 20              // Number of top-K similar facts to return
	DefaultMemoryTopKPerType = 5               // Top-K results per memory type (persona, life_event, etc.)
	DefaultTopKPerEntity     = 5               // Max facts returned per matched entity
	DefaultFallbackFactsTopK = 15              // Facts returned on total FTS miss (no entity matched)
	EntityFactMinConfidence  = 0.25            // Minimum confidence to include a fact in context

	// entityFactsCharBudget is the default character budget for entity facts.
	// Approximation: 4000 chars ≈ 1000 tokens ≈ 25% of a typical 4k context window.
	entityFactsCharBudget = 4000
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
	// Valid options: "recent_messages", "entity_facts", "persona", "events"
	MemoryTypes []string

	// TimeRange filters the retrieval by a specific time window.
	TimeRange *TimeRange
}

// ContextBundle contains all retrieved context information.
type ContextBundle struct {
	SelfFacts      []model.EntityFact // user's own identity facts (entity_type='self'), always pinned
	RecentMessages []model.Message
	EntityFacts    []model.EntityFact   // third-party entity facts only (entity_type != 'self')
	Persona        []model.MemoryRecord // one record per persona trait
	UpcomingEvents []model.MemoryRecord
	Experiences    []model.Experience
}

// ContextRetriever orchestrates parallel context retrieval from multiple sources.
type ContextRetriever struct {
	cache       *repository.Cache
	entityRepo  *repository.EntityRepository
	profileRepo *repository.ProfileRepository
	memRepo     *repository.MemoryRepository
	expRepo     *repository.ExperienceRepository
	llmClient   llm.Client
}

// NewContextRetriever creates a new ContextRetriever with the given dependencies.
func NewContextRetriever(
	cache *repository.Cache,
	entityRepo *repository.EntityRepository,
	profileRepo *repository.ProfileRepository,
	memRepo *repository.MemoryRepository,
	expRepo *repository.ExperienceRepository,
	llmClient llm.Client,
) *ContextRetriever {
	return &ContextRetriever{
		cache:       cache,
		entityRepo:  entityRepo,
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
	ch := make(chan fetchResult, 5)

	tasks := 0

	// Prepare embedding once — shared across experiences, persona, and entity_facts
	// (Phase 2: vector reranking per matched entity).
	// Note: events (life_event) records are never embedded, so they are excluded from needsEmbed.
	var emb []float32
	var embErr error
	embDone := make(chan struct{})
	needsEmbed := req.Query != "" && (wantsType("experiences") || wantsType("persona") || wantsType("entity_facts"))
	if needsEmbed {
		go func() {
			defer close(embDone)
			embedCtx, embedCancel := context.WithTimeout(ctx, EmbedTimeout)
			defer embedCancel()
			emb, embErr = r.llmClient.Embed(embedCtx, req.Query)
		}()
	} else {
		close(embDone)
	}

	// Task: Self-facts — always run unconditionally, no embDone wait.
	// Fetches entity_type='self' facts (user's own identity: name, age, gender, job...).
	// These are pinned into bundle.SelfFacts and never mixed with third-party entity_facts.
	tasks++
	go func() {
		dbCtx, dbCancel := context.WithTimeout(ctx, QueryTimeout)
		defer dbCancel()
		facts, err := r.entityRepo.SearchSelfFacts(dbCtx, req.TenantID, req.UserID)
		if err == nil {
			facts = deduplicateByAttribute(facts)
			facts = filterByConfidence(facts, EntityFactMinConfidence)
		}
		ch <- fetchResult{"self_facts", facts, err}
	}()

	// Task: Entity facts — three-phase retrieval.
	//   Phase 1 : ResolveEntities — FTS+trigram on entity_name (runs concurrently with embedding).
	//   Phase 2a: QueryFactsByVector — cosine distance per matched entity (requires embDone).
	//   Phase 2b: QueryFactsByFTS — ts_rank fallback when embeddings unavailable or empty.
	//   Fallback : FallbackFacts — confidence DESC when no entity name resolved.
	if wantsType("entity_facts") {
		tasks++
		go func() {
			var facts []model.EntityFact
			var err error

			if req.Query != "" {
				// Phase 1: FTS+trigram — runs immediately, concurrently with embedding.
				p1Ctx, p1Cancel := context.WithTimeout(ctx, QueryTimeout)
				entityNames, resolveErr := r.entityRepo.ResolveEntities(p1Ctx, req.TenantID, req.UserID, req.Query)
				p1Cancel()
				if resolveErr != nil {
					log.Printf("[entity_retrieval] ResolveEntities error: %v", resolveErr)
				}

				if len(entityNames) > 0 {
					// Wait for shared embedding (may already be ready if Phase 1 was slow).
					<-embDone

					p2Ctx, p2Cancel := context.WithTimeout(ctx, QueryTimeout)

					// Phase 2a: vector rerank — only when embedding succeeded and facts have embeddings.
					if embErr == nil && len(emb) > 0 {
						facts, err = r.entityRepo.QueryFactsByVector(p2Ctx, req.TenantID, req.UserID, emb, entityNames, DefaultTopKPerEntity)
						if err != nil {
							log.Printf("[entity_retrieval] QueryFactsByVector error: %v", err)
							err = nil // allow FTS fallback
						}
					}

					// Phase 2b: FTS fallback — embedding failed or no facts have embeddings yet.
					if len(facts) == 0 {
						facts, err = r.entityRepo.QueryFactsByFTS(p2Ctx, req.TenantID, req.UserID, req.Query, entityNames, DefaultTopKPerEntity)
						if err != nil {
							log.Printf("[entity_retrieval] QueryFactsByFTS error: %v", err)
						}
					}

					p2Cancel()
				}
			}

			// Fallback: no entity name resolved from Phase 1.
			// Step 1 — semantic search over all embedded facts (query-aware).
			// Step 2 — confidence sort only when embeddings unavailable (cold start).
			if len(facts) == 0 {
				if req.Query != "" {
					log.Printf("[entity_retrieval] FTS miss, trying vector fallback userID=%s query=%q", req.UserID, req.Query)
					<-embDone // wait for shared embedding
					if embErr == nil && len(emb) > 0 {
						vfCtx, vfCancel := context.WithTimeout(ctx, QueryTimeout)
						var vfErr error
						facts, vfErr = r.entityRepo.SearchAllFactsByVector(vfCtx, req.TenantID, req.UserID, emb, DefaultFallbackFactsTopK)
						vfCancel()
						if vfErr != nil {
							log.Printf("[entity_retrieval] vector fallback error: %v", vfErr)
							err = nil // allow confidence fallback
						}
					}
				}
				// Cold-start or no query: confidence sort as last resort.
				if len(facts) == 0 {
					log.Printf("[entity_retrieval] using confidence fallback userID=%s", req.UserID)
					fbCtx, fbCancel := context.WithTimeout(ctx, QueryTimeout)
					var fbErr error
					facts, fbErr = r.entityRepo.FallbackFacts(fbCtx, req.TenantID, req.UserID, DefaultFallbackFactsTopK)
					fbCancel()
					if fbErr != nil {
						err = fbErr
					}
				}
			}

			if err == nil {
				facts = deduplicateByAttribute(facts)
				facts = filterByConfidence(facts, EntityFactMinConfidence)
				facts = truncateFactsToBudget(facts, entityFactsCharBudget)
			}
			ch <- fetchResult{"entity", facts, err}
		}()
	}

	// Task: Structured memory (Persona and Events).
	// Persona: vector rerank when embedding available, fallback to latest persona record.
	// Events: life_event records carry no embeddings — always use FTS on event_name
	//         plus date-proximity ordering so query-relevant events surface first.
	if wantsType("persona") || wantsType("events") {
		tasks++
		go func() {
			data := make(map[string]any)

			// Persona: try vector rerank (top 5 traits), fallback to recency-sorted records.
			if wantsType("persona") {
				personaSet := false
				if req.Query != "" {
					<-embDone
					if embErr == nil && len(emb) > 0 {
						dbCtx, dbCancel := context.WithTimeout(ctx, QueryTimeout)
						byType, err := r.memRepo.SearchByVectorPerType(dbCtx, req.TenantID, req.UserID, emb, []string{"persona"}, 5)
						dbCancel()
						if err == nil {
							if records, ok := byType["persona"]; ok && len(records) > 0 {
								data["persona"] = records
								personaSet = true
							}
						} else {
							log.Printf("[memory_retrieval] persona vector search error: %v", err)
						}
					}
				}
				if !personaSet {
					fbCtx, fbCancel := context.WithTimeout(ctx, QueryTimeout)
					persona, _ := r.memRepo.GetPersona(fbCtx, req.TenantID, req.UserID, 5)
					fbCancel()
					data["persona"] = persona
				}
			}

			// Events: FTS on event_name + date-proximity sort (no embeddings on life_events).
			if wantsType("events") {
				evCtx, evCancel := context.WithTimeout(ctx, QueryTimeout)
				events, _ := r.memRepo.GetUpcomingEvents(evCtx, req.TenantID, req.UserID, req.Query, DefaultEventsLimit)
				evCancel()
				data["events"] = events
			}

			ch <- fetchResult{"structured", data, nil}
		}()
	}

	// Task: Experiences (only when a query is present for semantic matching)
	if wantsType("experiences") && req.Query != "" {
		tasks++
		go func() {
			<-embDone // Wait for embedding
			if embErr != nil {
				ch <- fetchResult{"experiences", []model.Experience{}, embErr}
				return
			}
			expDbCtx, expDbCancel := context.WithTimeout(ctx, QueryTimeout)
			defer expDbCancel()
			exps, err := r.expRepo.SearchByVector(
				expDbCtx, req.TenantID, req.UserID,
				emb, DefaultExperienceTopK, DefaultExperienceMinConf,
			)
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

	outerTimeout := EmbedTimeout + QueryTimeout
	if wantsType("experiences") {
		outerTimeout *= 2
	}
	outerCtx, outerCancel := context.WithTimeout(ctx, outerTimeout)
	defer outerCancel()

	for i := 0; i < tasks; i++ {
		select {
		case res := <-ch:
			r.merge(bundle, res)
		case <-outerCtx.Done():
			goto done
		}
	}
done:
	return nil
}

// merge combines fetch results into the context bundle.
func (r *ContextRetriever) merge(bundle *ContextBundle, res fetchResult) {
	switch res.kind {
	case "self_facts":
		if facts, ok := res.data.([]model.EntityFact); ok {
			bundle.SelfFacts = facts
		}
	case "entity":
		if facts, ok := res.data.([]model.EntityFact); ok {
			bundle.EntityFacts = facts
		}
	case "structured":
		if data, ok := res.data.(map[string]any); ok {
			if p, ok := data["persona"].([]model.MemoryRecord); ok {
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

// factCharCount returns the total character size of a fact's plaintext fields.
// Uses rune count (not byte count) so Vietnamese multi-byte chars count as 1.
func factCharCount(f model.EntityFact) int {
	return utf8.RuneCountInString(f.EntityName) +
		utf8.RuneCountInString(f.Attribute) +
		utf8.RuneCountInString(f.Value) +
		utf8.RuneCountInString(f.SourceQuote)
}

// truncateFactsToBudget returns the longest prefix of facts whose cumulative
// character count fits within budget.
func truncateFactsToBudget(facts []model.EntityFact, budget int) []model.EntityFact {
	if budget <= 0 || len(facts) == 0 {
		return []model.EntityFact{}
	}

	total := 0
	for i, f := range facts {
		total += factCharCount(f)
		if total > budget {
			if i == 0 {
				// Always return at least one fact — prevents empty context.
				return facts[:1]
			}
			return facts[:i]
		}
	}
	// All facts fit within budget.
	return facts
}

// deduplicateByAttribute keeps the highest-confidence fact per (entity_name, attribute) pair.
// On confidence tie, the first occurrence (assumed highest-confidence from SQL ORDER BY) wins.
func deduplicateByAttribute(facts []model.EntityFact) []model.EntityFact {
	seen := make(map[string]struct{}, len(facts))
	out := facts[:0]
	for _, f := range facts {
		key := f.EntityName + "\x00" + f.Attribute
		if _, exists := seen[key]; exists {
			continue
		}
		seen[key] = struct{}{}
		out = append(out, f)
	}
	return out
}

// filterByConfidence removes facts whose confidence is below minConf.
func filterByConfidence(facts []model.EntityFact, minConf float64) []model.EntityFact {
	out := facts[:0]
	for _, f := range facts {
		if f.Confidence >= minConf {
			out = append(out, f)
		}
	}
	return out
}
