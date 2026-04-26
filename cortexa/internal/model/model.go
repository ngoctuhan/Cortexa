package model

import (
	"encoding/json"
	"time"

	"github.com/google/uuid"
)

type Session struct {
	ID        uuid.UUID `json:"id"`
	TenantID  uuid.UUID `json:"tenant_id"`
	UserID    uuid.UUID `json:"user_id"`
	Title     string    `json:"title"`
	Meta      string    `json:"meta"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

type Message struct {
	ID         uuid.UUID `json:"id"`
	TenantID   uuid.UUID `json:"tenant_id"`
	SessionID  uuid.UUID `json:"session_id"`
	UserID     uuid.UUID `json:"user_id"`
	Role       string    `json:"role"`
	Content    string    `json:"content"`
	TokenCount int       `json:"token_count"`
	CreatedAt  time.Time `json:"created_at"`
}

type EntityFact struct {
	EntityName  string  `json:"entity_name"`
	EntityType  string  `json:"entity_type"`
	Attribute   string  `json:"attribute"`
	Value       string  `json:"value"`
	SourceQuote string  `json:"source_quote"`
	Confidence  float64 `json:"confidence"`
}

type ExtractedFact struct {
	EntityName  string `json:"entity_name"`
	EntityType  string `json:"entity_type"`
	Attribute   string `json:"attribute"`
	Value       string `json:"value"`
	SourceQuote string `json:"source_quote"`
}

type SemanticMessage struct {
	ID         uuid.UUID `json:"id"`
	Content    string    `json:"content"`
	CosineSim  float64   `json:"cosine_sim"`
	Score      float64   `json:"score"`
	Importance float64   `json:"importance"`
	CreatedAt  time.Time `json:"created_at"`
}

type MemoryRecord struct {
	ID             uuid.UUID       `json:"id"`
	Type           string          `json:"type"`
	Payload        json.RawMessage `json:"payload"`
	Importance     float64         `json:"importance"`
	AccessCount    int             `json:"access_count"`
	LastAccessedAt time.Time       `json:"last_accessed_at"`
	CreatedAt      time.Time       `json:"created_at"`
}

type UserProfile struct {
	CanonicalName string   `json:"canonical_name"`
	Aliases       []string `json:"aliases"`
}

type MessagePayload struct {
	MessageID uuid.UUID `json:"message_id"`
	UserID    uuid.UUID `json:"user_id"`
	TenantID  uuid.UUID `json:"tenant_id"`
	SessionID uuid.UUID `json:"session_id"`
}

// Experience represents a user-scoped learned behavior derived from real interactions.
// The AI extracts these from conversation windows where the user guides or corrects it.
type Experience struct {
	ID              uuid.UUID       `json:"id"`
	TenantID        uuid.UUID       `json:"tenant_id"`
	UserID          uuid.UUID       `json:"user_id"`
	Description     string          `json:"description"`
	Steps           json.RawMessage `json:"steps"`
	SourceSessionID *uuid.UUID      `json:"source_session_id,omitempty"`
	Confidence      float64         `json:"confidence"`
	UsageCount      int             `json:"usage_count"`
	SuccessCount    int             `json:"success_count"`
	IsActive        bool            `json:"is_active"`
	CreatedAt       time.Time       `json:"created_at"`
	UpdatedAt       time.Time       `json:"updated_at"`
}

// LLMUsage records token consumption for a single LLM Generate call.
type LLMUsage struct {
	ID          uuid.UUID `json:"id"`
	TenantID    uuid.UUID `json:"tenant_id"`
	UserID      uuid.UUID `json:"user_id"`
	SessionID   uuid.UUID `json:"session_id"`
	Feature     string    `json:"feature"`
	Model       string    `json:"model"`
	TotalTokens int       `json:"total_tokens"`
	CreatedAt   time.Time `json:"created_at"`
}
