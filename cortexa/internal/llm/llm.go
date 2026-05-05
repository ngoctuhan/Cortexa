package llm

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
)

type LLMMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type LLMRequest struct {
	Messages []LLMMessage `json:"messages"`
}

type Client interface {
	Generate(ctx context.Context, req LLMRequest) (string, int, error)
	Embed(ctx context.Context, text string) ([]float32, error)
	EmbedBatch(ctx context.Context, texts []string) ([][]float32, error)
	ModelName() string
}

// --- Gemini Client ---
type GeminiClient struct {
	apiKey string
	client *http.Client
}

func NewGeminiClient(apiKey string) *GeminiClient {
	return &GeminiClient{
		apiKey: apiKey,
		client: &http.Client{},
	}
}

func (c *GeminiClient) Generate(ctx context.Context, req LLMRequest) (string, int, error) {
	// Map to Gemini format
	var geminiContents []map[string]any
	var systemInstruction *map[string]any

	for _, msg := range req.Messages {
		if msg.Role == "system" {
			systemInstruction = &map[string]any{
				"parts": []map[string]any{{"text": msg.Content}},
			}
		} else {
			role := "user"
			if msg.Role == "assistant" {
				role = "model"
			}
			geminiContents = append(geminiContents, map[string]any{
				"role":  role,
				"parts": []map[string]any{{"text": msg.Content}},
			})
		}
	}

	payload := map[string]any{
		"contents": geminiContents,
		"generationConfig": map[string]any{
			"responseMimeType": "application/json",
		},
	}
	if systemInstruction != nil {
		payload["systemInstruction"] = systemInstruction
	}

	b, _ := json.Marshal(payload)
	url := fmt.Sprintf("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key=%s", c.apiKey)

	httpReq, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(b))
	if err != nil {
		return "", 0, err
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := c.client.Do(httpReq)
	if err != nil {
		return "", 0, err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		return "", 0, fmt.Errorf("gemini generate error: %s", string(body))
	}

	var result struct {
		Candidates []struct {
			Content struct {
				Parts []struct {
					Text string `json:"text"`
				} `json:"parts"`
			} `json:"content"`
		} `json:"candidates"`
		UsageMetadata struct {
			TotalTokenCount int `json:"totalTokenCount"`
		} `json:"usageMetadata"`
	}
	json.Unmarshal(body, &result)

	tokens := result.UsageMetadata.TotalTokenCount

	if len(result.Candidates) > 0 && len(result.Candidates[0].Content.Parts) > 0 {
		return result.Candidates[0].Content.Parts[0].Text, tokens, nil
	}
	return "[]", tokens, nil
}

func (c *GeminiClient) ModelName() string { return "gemini-2.5-flash-lite" }

func (c *GeminiClient) Embed(ctx context.Context, text string) ([]float32, error) {
	payload := map[string]any{
		"model": "models/text-embedding-004",
		"content": map[string]any{
			"parts": []map[string]any{{"text": text}},
		},
	}
	b, _ := json.Marshal(payload)
	url := fmt.Sprintf("https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key=%s", c.apiKey)

	httpReq, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(b))
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := c.client.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("gemini embed error: %s", string(body))
	}

	var result struct {
		Embedding struct {
			Values []float32 `json:"values"`
		} `json:"embedding"`
	}
	json.Unmarshal(body, &result)

	// pgvector uses 1536, gemini text-embedding-004 returns 768 by default.
	// We can pad to 1536 with zeros so it fits the DB schema without altering the schema now.
	emb := result.Embedding.Values
	if len(emb) < 1536 {
		padded := make([]float32, 1536)
		copy(padded, emb)
		emb = padded
	}
	return emb, nil
}

func (c *GeminiClient) EmbedBatch(ctx context.Context, texts []string) ([][]float32, error) {
	type batchRequest struct {
		Model   string         `json:"model"`
		Content map[string]any `json:"content"`
	}
	requests := make([]batchRequest, len(texts))
	for i, text := range texts {
		requests[i] = batchRequest{
			Model:   "models/text-embedding-004",
			Content: map[string]any{"parts": []map[string]any{{"text": text}}},
		}
	}
	payload := map[string]any{"requests": requests}
	b, _ := json.Marshal(payload)
	url := fmt.Sprintf("https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:batchEmbedContents?key=%s", c.apiKey)

	httpReq, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(b))
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := c.client.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("gemini batch embed error: %s", string(body))
	}

	var result struct {
		Embeddings []struct {
			Values []float32 `json:"values"`
		} `json:"embeddings"`
	}
	json.Unmarshal(body, &result)

	out := make([][]float32, len(result.Embeddings))
	for i, emb := range result.Embeddings {
		e := emb.Values
		if len(e) < 1536 {
			padded := make([]float32, 1536)
			copy(padded, e)
			e = padded
		}
		out[i] = e
	}
	return out, nil
}

// --- OpenAI Client ---
type OpenAIClient struct {
	apiKey string
	client *http.Client
}

func NewOpenAIClient(apiKey string) *OpenAIClient {
	return &OpenAIClient{
		apiKey: apiKey,
		client: &http.Client{},
	}
}

func (c *OpenAIClient) Generate(ctx context.Context, req LLMRequest) (string, int, error) {
	payload := map[string]any{
		"model":           "gpt-4o-mini",
		"messages":        req.Messages,
		"response_format": map[string]string{"type": "json_object"},
	}
	b, _ := json.Marshal(payload)
	httpReq, err := http.NewRequestWithContext(ctx, "POST", "https://api.openai.com/v1/chat/completions", bytes.NewReader(b))
	if err != nil {
		return "", 0, err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Authorization", "Bearer "+c.apiKey)

	resp, err := c.client.Do(httpReq)
	if err != nil {
		return "", 0, err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		return "", 0, fmt.Errorf("openai generate error: %s", string(body))
	}

	var result struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
		Usage struct {
			TotalTokens int `json:"total_tokens"`
		} `json:"usage"`
	}
	json.Unmarshal(body, &result)

	tokens := result.Usage.TotalTokens

	if len(result.Choices) > 0 {
		return result.Choices[0].Message.Content, tokens, nil
	}
	return "[]", tokens, nil
}

func (c *OpenAIClient) ModelName() string { return "gpt-4o-mini" }

func (c *OpenAIClient) EmbedBatch(ctx context.Context, texts []string) ([][]float32, error) {
	payload := map[string]any{
		"model": "text-embedding-3-small",
		"input": texts,
	}
	b, _ := json.Marshal(payload)
	httpReq, err := http.NewRequestWithContext(ctx, "POST", "https://api.openai.com/v1/embeddings", bytes.NewReader(b))
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Authorization", "Bearer "+c.apiKey)

	resp, err := c.client.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("openai batch embed error: %s", string(body))
	}

	var result struct {
		Data []struct {
			Index     int       `json:"index"`
			Embedding []float32 `json:"embedding"`
		} `json:"data"`
	}
	json.Unmarshal(body, &result)

	out := make([][]float32, len(texts))
	for _, d := range result.Data {
		if d.Index < len(out) {
			out[d.Index] = d.Embedding
		}
	}
	return out, nil
}

func (c *OpenAIClient) Embed(ctx context.Context, text string) ([]float32, error) {
	payload := map[string]any{
		"model": "text-embedding-3-small",
		"input": text,
	}
	b, _ := json.Marshal(payload)
	httpReq, err := http.NewRequestWithContext(ctx, "POST", "https://api.openai.com/v1/embeddings", bytes.NewReader(b))
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Authorization", "Bearer "+c.apiKey)

	resp, err := c.client.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("openai embed error: %s", string(body))
	}

	var result struct {
		Data []struct {
			Embedding []float32 `json:"embedding"`
		} `json:"data"`
	}
	json.Unmarshal(body, &result)

	if len(result.Data) > 0 {
		return result.Data[0].Embedding, nil
	}
	return make([]float32, 1536), nil
}

func BuildLLMRequest(systemPrompt, userContent string) LLMRequest {
	return LLMRequest{
		Messages: []LLMMessage{
			{Role: "system", Content: systemPrompt},
			{Role: "user", Content: userContent},
		},
	}
}

// --- Azure OpenAI Client ---

const azureOpenAIDefaultAPIVersion = "2024-02-01"

type AzureOpenAIClient struct {
	endpoint        string
	apiKey          string
	chatDeployment  string
	embedDeployment string
	apiVersion      string
	client          *http.Client
}

func NewAzureOpenAIClient(endpoint, apiKey, chatDeployment, embedDeployment, apiVersion string) *AzureOpenAIClient {
	if apiVersion == "" {
		apiVersion = azureOpenAIDefaultAPIVersion
	}
	return &AzureOpenAIClient{
		endpoint:        strings.TrimRight(endpoint, "/"),
		apiKey:          apiKey,
		chatDeployment:  chatDeployment,
		embedDeployment: embedDeployment,
		apiVersion:      apiVersion,
		client:          &http.Client{},
	}
}

func (c *AzureOpenAIClient) Generate(ctx context.Context, req LLMRequest) (string, int, error) {
	payload := map[string]any{
		"messages":        req.Messages,
		"response_format": map[string]string{"type": "json_object"},
	}
	b, _ := json.Marshal(payload)
	url := fmt.Sprintf("%s/openai/deployments/%s/chat/completions?api-version=%s",
		c.endpoint, c.chatDeployment, c.apiVersion)

	httpReq, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(b))
	if err != nil {
		return "", 0, err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("api-key", c.apiKey)

	resp, err := c.client.Do(httpReq)
	if err != nil {
		return "", 0, err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		return "", 0, fmt.Errorf("azure openai generate error: %s", string(body))
	}

	var result struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
		Usage struct {
			TotalTokens int `json:"total_tokens"`
		} `json:"usage"`
	}
	json.Unmarshal(body, &result)

	tokens := result.Usage.TotalTokens
	if len(result.Choices) > 0 {
		return result.Choices[0].Message.Content, tokens, nil
	}
	return "[]", tokens, nil
}

func (c *AzureOpenAIClient) ModelName() string { return c.chatDeployment }

func (c *AzureOpenAIClient) EmbedBatch(ctx context.Context, texts []string) ([][]float32, error) {
	payload := map[string]any{
		"input": texts,
	}
	b, _ := json.Marshal(payload)
	url := fmt.Sprintf("%s/openai/deployments/%s/embeddings?api-version=%s",
		c.endpoint, c.embedDeployment, c.apiVersion)

	httpReq, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(b))
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("api-key", c.apiKey)

	resp, err := c.client.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("azure openai batch embed error: %s", string(body))
	}

	var result struct {
		Data []struct {
			Index     int       `json:"index"`
			Embedding []float32 `json:"embedding"`
		} `json:"data"`
	}
	json.Unmarshal(body, &result)

	out := make([][]float32, len(texts))
	for _, d := range result.Data {
		if d.Index < len(out) {
			out[d.Index] = d.Embedding
		}
	}
	return out, nil
}

func (c *AzureOpenAIClient) Embed(ctx context.Context, text string) ([]float32, error) {
	payload := map[string]any{
		"input": text,
	}
	b, _ := json.Marshal(payload)
	url := fmt.Sprintf("%s/openai/deployments/%s/embeddings?api-version=%s",
		c.endpoint, c.embedDeployment, c.apiVersion)

	httpReq, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(b))
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("api-key", c.apiKey)

	resp, err := c.client.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("azure openai embed error: %s", string(body))
	}

	var result struct {
		Data []struct {
			Embedding []float32 `json:"embedding"`
		} `json:"data"`
	}
	json.Unmarshal(body, &result)

	if len(result.Data) > 0 {
		return result.Data[0].Embedding, nil
	}
	return make([]float32, 1536), nil
}

// newAzureClient constructs an AzureOpenAIClient from environment variables,
// fatally logging if any required variable is absent.
func newAzureClient() Client {
	endpoint := os.Getenv("AZURE_OPENAI_ENDPOINT")
	key := os.Getenv("AZURE_OPENAI_KEY")
	chatDep := os.Getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")
	embedDep := os.Getenv("AZURE_OPENAI_EMBED_DEPLOYMENT")
	if endpoint == "" || key == "" || chatDep == "" || embedDep == "" {
		log.Fatal("azure provider selected but one or more required env vars are missing: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY, AZURE_OPENAI_CHAT_DEPLOYMENT, AZURE_OPENAI_EMBED_DEPLOYMENT")
	}
	return NewAzureOpenAIClient(endpoint, key, chatDep, embedDep, os.Getenv("AZURE_OPENAI_API_VERSION"))
}

// MockClient is a no-op LLM client that returns a minimal valid cognitive/experience
// JSON response immediately without any network call. Use LLM_PROVIDER=mock for local
// testing of batch/reclaim logic.
type MockClient struct{}

const mockCognitiveResponse = `{"facts":[],"events":[],"persona_updates":[]}`
const mockExperienceResponse = `{"experiences":[]}`

func (m *MockClient) Generate(_ context.Context, req LLMRequest) (string, int, error) {
	// Pick the right stub based on what the prompt looks like.
	for _, msg := range req.Messages {
		if strings.Contains(msg.Content, "experience") || strings.Contains(msg.Content, "behavior") {
			return mockExperienceResponse, 10, nil
		}
	}
	return mockCognitiveResponse, 10, nil
}

func (m *MockClient) Embed(_ context.Context, _ string) ([]float32, error) {
	return make([]float32, 1536), nil
}

func (m *MockClient) EmbedBatch(_ context.Context, texts []string) ([][]float32, error) {
	result := make([][]float32, len(texts))
	for i := range result {
		result[i] = make([]float32, 1536)
	}
	return result, nil
}

func (m *MockClient) ModelName() string { return "mock" }

// NewClient constructs the active LLM client.
//
// Provider selection order:
//  1. If LLM_PROVIDER is set (mock | gemini | openai | azure), use that provider
//     explicitly and fatal if the required credentials are absent.
//  2. Otherwise fall back to auto-detect: azure → openai → gemini.
func NewClient() Client {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("LLM_PROVIDER"))) {
	case "mock":
		log.Println("LLM: using MockClient — no real API calls will be made")
		return &MockClient{}
	case "azure":
		return newAzureClient()
	case "openai":
		key := os.Getenv("OPENAI_API_KEY")
		if key == "" {
			log.Fatal("LLM_PROVIDER=openai but OPENAI_API_KEY is not set")
		}
		return NewOpenAIClient(key)
	case "gemini":
		key := os.Getenv("GEMINI_API_KEY")
		if key == "" {
			log.Fatal("LLM_PROVIDER=gemini but GEMINI_API_KEY is not set")
		}
		return NewGeminiClient(key)
	case "":
		// Auto-detect by priority: azure > openai > gemini
		if os.Getenv("AZURE_OPENAI_ENDPOINT") != "" {
			return newAzureClient()
		}
		if key := os.Getenv("OPENAI_API_KEY"); key != "" {
			return NewOpenAIClient(key)
		}
		if key := os.Getenv("GEMINI_API_KEY"); key != "" {
			return NewGeminiClient(key)
		}
		log.Fatal("no LLM API key configured: set LLM_PROVIDER and credentials, or set AZURE_OPENAI_ENDPOINT / OPENAI_API_KEY / GEMINI_API_KEY")
		return nil
	default:
		log.Fatalf("LLM_PROVIDER=%q is invalid; valid values are: mock, gemini, openai, azure", os.Getenv("LLM_PROVIDER"))
		return nil
	}
}
