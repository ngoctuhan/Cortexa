package api

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/cortexa/cortexa/internal/config"
	"github.com/cortexa/cortexa/internal/model"
	"github.com/cortexa/cortexa/internal/repository"
	"github.com/cortexa/cortexa/internal/service"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

// withTenant enriches the request context with the tenant ID so that the
// pgxpool BeforeAcquire hook propagates it to app.tenant_id for RLS.
func withTenant(c *gin.Context, tenantID string) context.Context {
	return repository.WithTenantID(c.Request.Context(), tenantID)
}

const (
	// Maximum content length for messages to prevent DoS
	MaxContentLength = 100000 // 100KB
	// Maximum query length for context retrieval
	MaxQueryLength = 5000
	// Valid message roles
	ValidRoles = "user,assistant,system"
)

// RESTServer handles HTTP requests for the MCM API.
type RESTServer struct {
	router      *gin.Engine
	retriever   *service.ContextRetriever
	msgRepo     *repository.MessageRepository
	sessionRepo *repository.SessionRepository
	memRepo     *repository.MemoryRepository
	expRepo     *repository.ExperienceRepository
	cache       *repository.Cache
}

// NewRESTServer creates a new REST API server with the given dependencies.
func NewRESTServer(retriever *service.ContextRetriever, msgRepo *repository.MessageRepository, sessionRepo *repository.SessionRepository, memRepo *repository.MemoryRepository, expRepo *repository.ExperienceRepository, cache *repository.Cache) *RESTServer {
	r := gin.New()
	r.Use(gin.Recovery())
	r.Use(RequestIDMiddleware())
	r.Use(SlogMiddleware())
	r.Use(MetricsMiddleware())
	s := &RESTServer{
		router:      r,
		retriever:   retriever,
		msgRepo:     msgRepo,
		sessionRepo: sessionRepo,
		memRepo:     memRepo,
		expRepo:     expRepo,
		cache:       cache,
	}
	s.routes()
	return s
}

// routes sets up the API routes.
func (s *RESTServer) routes() {
	s.router.GET("/health", s.handleHealth)
	s.router.GET("/metrics", PrometheusHandler())

	v1 := s.router.Group("/v1")
	{
		v1.POST("/context", s.handleGetContext)
		v1.POST("/context/formatted", s.handleGetContextFormatted)
		v1.POST("/messages", s.handleAppendMessages)
		v1.POST("/feedback", s.handleFeedback)
		v1.GET("/sessions/:session_id/messages", s.handleGetSessionHistory)
		v1.POST("/sessions", s.handleCreateSession)
		v1.GET("/sessions", s.handleListSessions)
		v1.DELETE("/sessions/:session_id", s.handleDeleteSession)
		v1.GET("/experiences", s.handleListExperiences)
		v1.POST("/experiences/:experience_id/feedback", s.handleExperienceFeedback)
		v1.DELETE("/experiences/:experience_id", s.handleDeleteExperience)
	}
}

// handleHealth handles GET /health — used by container probes and load balancers.
func (s *RESTServer) handleHealth(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok"})
}

// handleAppendMessages handles POST /v1/messages requests.
func (s *RESTServer) handleAppendMessages(c *gin.Context) {
	var req struct {
		TenantID  string `json:"tenant_id" binding:"required"`
		UserID    string `json:"user_id" binding:"required"`
		SessionID string `json:"session_id" binding:"required"`
		Role      string `json:"role" binding:"required"`
		Content   string `json:"content" binding:"required"`
	}

	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request format"})
		return
	}

	// Validate role
	if req.Role != "user" && req.Role != "assistant" && req.Role != "system" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid role. Must be one of: " + ValidRoles})
		return
	}

	// Validate content length
	if len(req.Content) > MaxContentLength {
		c.JSON(http.StatusBadRequest, gin.H{"error": "content too large"})
		return
	}

	// Parse and validate UUIDs
	tenantID, err := uuid.Parse(req.TenantID)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid tenant_id format"})
		return
	}
	userID, err := uuid.Parse(req.UserID)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid user_id format"})
		return
	}
	sessionID, err := uuid.Parse(req.SessionID)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid session_id format"})
		return
	}

	// Inject tenant into context to activate Row-Level Security.
	ctx := withTenant(c, tenantID.String())

	msg := model.Message{
		ID:         uuid.New(),
		TenantID:   tenantID,
		SessionID:  sessionID,
		UserID:     userID,
		Role:       req.Role,
		Content:    req.Content,
		TokenCount: utf8.RuneCountInString(req.Content) / 4, // Unicode-aware token approximation
		CreatedAt:  time.Now(),
	}

	if err := s.msgRepo.InsertMessage(ctx, &msg); err != nil {
		log.Printf("InsertMessage error: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to store message"})
		return
	}

	// Push to embedder stream
	mp := model.MessagePayload{
		MessageID: msg.ID,
		UserID:    msg.UserID,
		TenantID:  msg.TenantID,
		SessionID: msg.SessionID,
	}
	if b, err := json.Marshal(mp); err == nil {
		_ = s.cache.XAddEmbedderTask(ctx, string(b))
	}

	// Update cache
	s.cache.AppendMessages(ctx, req.TenantID, req.SessionID, []model.Message{msg})

	// Check cognitive batch size limit
	cfg := config.Get()
	count, err := s.cache.IncrementCognitiveBatch(ctx, req.TenantID, req.SessionID)
	if err == nil && count >= int64(cfg.CognitiveBatch) {
		// Publish event to trigger batch processing
		s.cache.ResetCognitiveBatch(ctx, req.TenantID, req.SessionID)

		batchPayload := map[string]interface{}{
			"tenant_id":       req.TenantID,
			"user_id":         req.UserID,
			"session_id":      req.SessionID,
			"batch_size":      count,
			"last_message_id": msg.ID.String(),
		}
		if b, err := json.Marshal(batchPayload); err == nil {
			_ = s.cache.XAddCognitiveBatch(ctx, req.TenantID, string(b))
		}
	}

	c.JSON(http.StatusOK, gin.H{
		"status":  "success",
		"message": "messages appended",
		"id":      msg.ID.String(),
	})
}

// handleGetContext handles POST /v1/context requests.
func (s *RESTServer) handleGetContext(c *gin.Context) {
	var req struct {
		TenantID  string `json:"tenant_id" binding:"required"`
		UserID    string `json:"user_id" binding:"required"`
		SessionID string `json:"session_id" binding:"required"`
		Query     string `json:"query"`

		MemoryTypes []string           `json:"memory_types"`
		TimeRange   *service.TimeRange `json:"time_range"`
	}

	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request format"})
		return
	}

	// Validate query length
	if len(req.Query) > MaxQueryLength {
		c.JSON(http.StatusBadRequest, gin.H{"error": "query too large"})
		return
	}

	// Parse and validate UUIDs
	tenantID, err := uuid.Parse(req.TenantID)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid tenant_id format"})
		return
	}
	userID, err := uuid.Parse(req.UserID)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid user_id format"})
		return
	}
	sessionID, err := uuid.Parse(req.SessionID)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid session_id format"})
		return
	}

	// Inject tenant into context to activate Row-Level Security.
	ctx := withTenant(c, tenantID.String())

	start := time.Now()
	bundle, err := s.retriever.GetContext(ctx, service.GetContextRequest{
		TenantID:    tenantID.String(),
		UserID:      userID.String(),
		SessionID:   sessionID.String(),
		Query:       req.Query,
		MemoryTypes: req.MemoryTypes,
		TimeRange:   req.TimeRange,
	})

	if err != nil {
		if errors.Is(err, context.DeadlineExceeded) {
			c.JSON(http.StatusRequestTimeout, gin.H{"error": "request timeout"})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to retrieve context"})
		return
	}

	latency := time.Since(start).Milliseconds()

	// Initialize nil slices to avoid null in JSON
	if bundle.RecentMessages == nil {
		bundle.RecentMessages = make([]model.Message, 0)
	}
	if bundle.EntityFacts == nil {
		bundle.EntityFacts = make([]model.EntityFact, 0)
	}
	if bundle.SemanticMessages == nil {
		bundle.SemanticMessages = make([]model.SemanticMessage, 0)
	}
	if bundle.UpcomingEvents == nil {
		bundle.UpcomingEvents = make([]model.MemoryRecord, 0)
	}

	totalTokens := 0
	for _, m := range bundle.RecentMessages {
		totalTokens += m.TokenCount
	}
	for _, sm := range bundle.SemanticMessages {
		totalTokens += len(sm.Content) / 4
	}

	c.JSON(http.StatusOK, gin.H{
		"recent_messages":   bundle.RecentMessages,
		"entity_facts":      bundle.EntityFacts,
		"semantic_messages": bundle.SemanticMessages,
		"persona_context":   bundle.Persona,
		"upcoming_events":   bundle.UpcomingEvents,
		"total_tokens":      totalTokens,
		"latency_ms":        latency,
		"is_partial":        false,
	})
}

// handleGetSessionHistory handles GET /v1/sessions/:session_id/messages
// Supports cursor-based pagination via query params:
//
//	tenant_id  (required)
//	limit      (optional, default 50, max 100)
//	before_id  (optional, cursor — returns messages older than this message ID)
func (s *RESTServer) handleGetSessionHistory(c *gin.Context) {
	sessionID := c.Param("session_id")
	if _, err := uuid.Parse(sessionID); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid session_id format"})
		return
	}

	tenantID := c.Query("tenant_id")
	if _, err := uuid.Parse(tenantID); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "tenant_id is required and must be a valid UUID"})
		return
	}

	limit := 50
	if l := c.Query("limit"); l != "" {
		if v, err := strconv.Atoi(l); err == nil && v > 0 {
			limit = v
		}
	}

	beforeID := c.Query("before_id")
	if beforeID != "" {
		if _, err := uuid.Parse(beforeID); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid before_id format"})
			return
		}
	}

	// Inject tenant into context to activate Row-Level Security.
	ctx := withTenant(c, tenantID)

	msgs, err := s.msgRepo.GetSessionHistory(ctx, tenantID, sessionID, limit, beforeID)
	if err != nil {
		log.Printf("GetSessionHistory error: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to retrieve messages"})
		return
	}

	if msgs == nil {
		msgs = make([]model.Message, 0)
	}

	// next_cursor is the ID of the oldest message in this page;
	// pass it as before_id in the next request to load older messages.
	var nextCursor string
	if len(msgs) == limit {
		nextCursor = msgs[len(msgs)-1].ID.String()
	}

	totalTokens := 0
	for _, m := range msgs {
		totalTokens += m.TokenCount
	}

	c.JSON(http.StatusOK, gin.H{
		"messages":     msgs,
		"count":        len(msgs),
		"total_tokens": totalTokens,
		"next_cursor":  nextCursor,
		"has_more":     nextCursor != "",
	})
}

// handleCreateSession handles POST /v1/sessions.
func (s *RESTServer) handleCreateSession(c *gin.Context) {
	var req struct {
		TenantID string `json:"tenant_id" binding:"required"`
		UserID   string `json:"user_id" binding:"required"`
		Title    string `json:"title"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request format"})
		return
	}

	tenantID, err := uuid.Parse(req.TenantID)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid tenant_id format"})
		return
	}
	userID, err := uuid.Parse(req.UserID)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid user_id format"})
		return
	}

	ctx := withTenant(c, tenantID.String())
	session := model.Session{
		ID:       uuid.New(),
		TenantID: tenantID,
		UserID:   userID,
		Title:    req.Title,
		Meta:     "{}",
	}
	if err := s.sessionRepo.Create(ctx, &session); err != nil {
		log.Printf("handleCreateSession error: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create session"})
		return
	}

	// Async: Trigger Hybrid Flush for previous active sessions of this user.
	// Use a detached context with the tenant ID so RLS is enforced in the goroutine.
	flushCtx := repository.WithTenantID(context.Background(), tenantID.String())
	go s.flushPreviousUserSessions(flushCtx, req.TenantID, req.UserID, session.ID.String())

	c.JSON(http.StatusCreated, session)
}

// flushPreviousUserSessions checks recent sessions of a user and forces a cognitive batch flush
// if they have pending un-extracted messages.
func (s *RESTServer) flushPreviousUserSessions(ctx context.Context, tenantID, userID, excludeSessionID string) {
	// 1. Get recent sessions for the user (limit 5 to avoid overloading)
	sessions, err := s.sessionRepo.List(ctx, tenantID, userID, 5, 0)
	if err != nil {
		log.Printf("flushPreviousUserSessions: failed to list sessions: %v", err)
		return
	}

	for _, sess := range sessions {
		sessID := sess.ID.String()
		if sessID == excludeSessionID {
			continue
		}

		// 2. Check if this session has pending messages in the cache
		count, err := s.cache.GetCognitiveBatchCount(ctx, tenantID, sessID)
		if err != nil || count == 0 {
			continue
		}

		// 3. Get the latest message ID for this session to use as anchor
		msgs, err := s.msgRepo.GetSessionHistory(ctx, tenantID, sessID, 1, "")
		if err != nil || len(msgs) == 0 {
			continue
		}

		lastMsgID := msgs[0].ID.String()

		// 4. Reset the counter and publish to the stream
		s.cache.ResetCognitiveBatch(ctx, tenantID, sessID)

		batchPayload := map[string]interface{}{
			"tenant_id":       tenantID,
			"user_id":         userID,
			"session_id":      sessID,
			"batch_size":      int(count),
			"last_message_id": lastMsgID,
		}
		if b, err := json.Marshal(batchPayload); err == nil {
			_ = s.cache.XAddCognitiveBatch(ctx, tenantID, string(b))
			log.Printf("flushPreviousUserSessions: triggered force flush for session %s (count=%d)", sessID, count)
		}
	}
}

// handleListSessions handles GET /v1/sessions.
// Query params: tenant_id (required), user_id (required), limit (default 20), offset (default 0).
func (s *RESTServer) handleListSessions(c *gin.Context) {
	tenantID := c.Query("tenant_id")
	if _, err := uuid.Parse(tenantID); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "tenant_id is required and must be a valid UUID"})
		return
	}
	userID := c.Query("user_id")
	if _, err := uuid.Parse(userID); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "user_id is required and must be a valid UUID"})
		return
	}

	limit := 20
	if l := c.Query("limit"); l != "" {
		if v, err := strconv.Atoi(l); err == nil && v > 0 {
			limit = v
		}
	}
	offset := 0
	if o := c.Query("offset"); o != "" {
		if v, err := strconv.Atoi(o); err == nil && v >= 0 {
			offset = v
		}
	}

	ctx := withTenant(c, tenantID)
	sessions, err := s.sessionRepo.List(ctx, tenantID, userID, limit, offset)
	if err != nil {
		log.Printf("handleListSessions error: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to list sessions"})
		return
	}
	if sessions == nil {
		sessions = make([]model.Session, 0)
	}
	c.JSON(http.StatusOK, gin.H{"sessions": sessions, "count": len(sessions)})
}

// handleDeleteSession handles DELETE /v1/sessions/:session_id.
// Query param: tenant_id (required). Cascades to messages via FK.
func (s *RESTServer) handleDeleteSession(c *gin.Context) {
	sessionID := c.Param("session_id")
	if _, err := uuid.Parse(sessionID); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid session_id format"})
		return
	}
	tenantID := c.Query("tenant_id")
	if _, err := uuid.Parse(tenantID); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "tenant_id is required and must be a valid UUID"})
		return
	}

	ctx := withTenant(c, tenantID)
	deleted, err := s.sessionRepo.Delete(ctx, tenantID, sessionID)
	if err != nil {
		log.Printf("handleDeleteSession error: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to delete session"})
		return
	}
	if !deleted {
		c.JSON(http.StatusNotFound, gin.H{"error": "session not found"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "deleted"})
}

// Run starts the HTTP server on the given address.
func (s *RESTServer) Run(addr string) error {
	return s.router.Run(addr)
}

// handleFeedback handles POST /v1/feedback.
// Records a positive or negative signal for a memory record, updating its
// importance and access_count so the retriever reranker can reflect real usage.
func (s *RESTServer) handleFeedback(c *gin.Context) {
	var req struct {
		TenantID string `json:"tenant_id" binding:"required"`
		UserID   string `json:"user_id" binding:"required"`
		ItemID   string `json:"item_id" binding:"required"`
		Signal   string `json:"signal" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request format"})
		return
	}
	if req.Signal != "positive" && req.Signal != "negative" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "signal must be 'positive' or 'negative'"})
		return
	}
	tenantID, err := uuid.Parse(req.TenantID)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid tenant_id format"})
		return
	}
	userID, err := uuid.Parse(req.UserID)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid user_id format"})
		return
	}
	if _, err := uuid.Parse(req.ItemID); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid item_id format"})
		return
	}

	ctx := withTenant(c, tenantID.String())
	positive := req.Signal == "positive"
	if err := s.memRepo.RecordFeedback(ctx, tenantID.String(), userID.String(), req.ItemID, positive); err != nil {
		log.Printf("handleFeedback error: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to record feedback"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "feedback recorded"})
}

// handleGetContextFormatted handles POST /v1/context/formatted.
// It is identical to POST /v1/context but returns the context bundle as a
// plain-text string ready for injection into an LLM system prompt, rather than
// a structured JSON object.
func (s *RESTServer) handleGetContextFormatted(c *gin.Context) {
	var req struct {
		TenantID    string             `json:"tenant_id" binding:"required"`
		UserID      string             `json:"user_id" binding:"required"`
		SessionID   string             `json:"session_id" binding:"required"`
		Query       string             `json:"query"`
		MemoryTypes []string           `json:"memory_types"`
		TimeRange   *service.TimeRange `json:"time_range"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request format"})
		return
	}
	if len(req.Query) > MaxQueryLength {
		c.JSON(http.StatusBadRequest, gin.H{"error": "query too large"})
		return
	}
	tenantID, err := uuid.Parse(req.TenantID)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid tenant_id format"})
		return
	}
	userID, err := uuid.Parse(req.UserID)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid user_id format"})
		return
	}
	sessionID, err := uuid.Parse(req.SessionID)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid session_id format"})
		return
	}

	ctx := withTenant(c, tenantID.String())
	start := time.Now()
	bundle, err := s.retriever.GetContext(ctx, service.GetContextRequest{
		TenantID:    tenantID.String(),
		UserID:      userID.String(),
		SessionID:   sessionID.String(),
		Query:       req.Query,
		MemoryTypes: req.MemoryTypes,
		TimeRange:   req.TimeRange,
	})
	if err != nil {
		if errors.Is(err, context.DeadlineExceeded) {
			c.JSON(http.StatusRequestTimeout, gin.H{"error": "request timeout"})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to retrieve context"})
		return
	}
	latency := time.Since(start).Milliseconds()
	_ = sessionID // used for routing; bundle already scoped via GetContextRequest

	c.JSON(http.StatusOK, gin.H{
		"formatted":  formatBundle(bundle),
		"latency_ms": latency,
	})
}

// formatBundle converts a ContextBundle into a plain-text string suitable for
// direct injection into an LLM system prompt. Each section is separated by a
// blank line. Empty sections are omitted.
func formatBundle(bundle *service.ContextBundle) string {
	var sb strings.Builder

	if len(bundle.EntityFacts) > 0 {
		sb.WriteString("## Entity Facts\n")
		for _, f := range bundle.EntityFacts {
			fmt.Fprintf(&sb, "- %s (%s) \u2014 %s: %s\n", f.EntityName, f.EntityType, f.Attribute, f.Value)
		}
		sb.WriteString("\n")
	}

	if len(bundle.RecentMessages) > 0 {
		sb.WriteString("## Recent Messages\n")
		for _, m := range bundle.RecentMessages {
			fmt.Fprintf(&sb, "[%s]: %s\n", m.Role, m.Content)
		}
		sb.WriteString("\n")
	}

	if len(bundle.SemanticMessages) > 0 {
		sb.WriteString("## Semantic Matches\n")
		for _, sm := range bundle.SemanticMessages {
			fmt.Fprintf(&sb, "- %s\n", sm.Content)
		}
		sb.WriteString("\n")
	}

	if bundle.Persona != nil && len(bundle.Persona.Payload) > 0 {
		sb.WriteString("## Persona\n")
		sb.WriteString(string(bundle.Persona.Payload))
		sb.WriteString("\n\n")
	}

	if len(bundle.UpcomingEvents) > 0 {
		sb.WriteString("## Upcoming Events\n")
		for _, e := range bundle.UpcomingEvents {
			fmt.Fprintf(&sb, "- %s\n", string(e.Payload))
		}
		sb.WriteString("\n")
	}

	return strings.TrimSpace(sb.String())
}

// handleListExperiences handles GET /v1/experiences.
// Returns all active experiences for a given user.
func (s *RESTServer) handleListExperiences(c *gin.Context) {
	tenantIDStr := c.Query("tenant_id")
	userIDStr := c.Query("user_id")

	tenantID, err := uuid.Parse(tenantIDStr)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid tenant_id format"})
		return
	}
	userID, err := uuid.Parse(userIDStr)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid user_id format"})
		return
	}

	ctx := withTenant(c, tenantID.String())
	experiences, err := s.expRepo.ListByUser(ctx, tenantID.String(), userID.String())
	if err != nil {
		log.Printf("handleListExperiences error: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to list experiences"})
		return
	}
	if experiences == nil {
		experiences = make([]model.Experience, 0)
	}
	c.JSON(http.StatusOK, gin.H{"experiences": experiences})
}

// handleExperienceFeedback handles POST /v1/experiences/:experience_id/feedback.
// Accepts { "tenant_id", "user_id", "signal": "positive"|"negative" }.
func (s *RESTServer) handleExperienceFeedback(c *gin.Context) {
	experienceIDStr := c.Param("experience_id")
	if _, err := uuid.Parse(experienceIDStr); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid experience_id format"})
		return
	}

	var req struct {
		TenantID string `json:"tenant_id" binding:"required"`
		UserID   string `json:"user_id" binding:"required"`
		Signal   string `json:"signal" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request format"})
		return
	}
	if req.Signal != "positive" && req.Signal != "negative" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "signal must be 'positive' or 'negative'"})
		return
	}

	tenantID, err := uuid.Parse(req.TenantID)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid tenant_id format"})
		return
	}
	userID, err := uuid.Parse(req.UserID)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid user_id format"})
		return
	}

	ctx := withTenant(c, tenantID.String())
	positive := req.Signal == "positive"
	if err := s.expRepo.RecordFeedback(ctx, tenantID.String(), userID.String(), experienceIDStr, positive); err != nil {
		log.Printf("handleExperienceFeedback error: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to record feedback"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "feedback recorded"})
}

// handleDeleteExperience handles DELETE /v1/experiences/:experience_id.
// Soft-deletes (deactivates) an experience for a user.
func (s *RESTServer) handleDeleteExperience(c *gin.Context) {
	experienceIDStr := c.Param("experience_id")
	if _, err := uuid.Parse(experienceIDStr); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid experience_id format"})
		return
	}

	tenantIDStr := c.Query("tenant_id")
	userIDStr := c.Query("user_id")

	tenantID, err := uuid.Parse(tenantIDStr)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid tenant_id format"})
		return
	}
	userID, err := uuid.Parse(userIDStr)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid user_id format"})
		return
	}

	ctx := withTenant(c, tenantID.String())
	if err := s.expRepo.Deactivate(ctx, tenantID.String(), userID.String(), experienceIDStr); err != nil {
		log.Printf("handleDeleteExperience error: %v", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to delete experience"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "experience deactivated"})
}
