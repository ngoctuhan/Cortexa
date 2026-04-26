package config

import (
	"log"
	"os"
	"strconv"
	"sync"

	"github.com/joho/godotenv"
)

const (
	// Default configuration values
	DefaultServerPort           = ":8080"
	DefaultDBMaxConns           = 100
	DefaultRedisPool            = 100
	DefaultRedisAddr            = "localhost:6379"
	DefaultPromptPath           = "prompts/cognitive.j2"
	AltPromptPath               = "../cortexa/prompts/cognitive.j2"
	DefaultExperiencePromptPath = "prompts/experience_extractor.j2"
	AltExperiencePromptPath     = "../cortexa/prompts/experience_extractor.j2"
	DefaultDecayIntervalHrs     = 24 // Run decay job once per day
	DefaultDecayAfterDays       = 30 // Decay records not accessed in 30 days
	DefaultRecentMessagesLimit  = 20 // Number of recent messages returned in recent_messages

	// Configuration limits
	MaxDBMaxConns      = 1000
	MaxRedisPool       = 1000
	MaxRecentMsgsLimit = 200
)

type Config struct {
	DatabaseURL          string
	DBMaxConns           int32
	RedisAddr            string
	RedisPool            int
	ServerPort           string
	MasterKey            string
	CognitivePrompt      string
	CognitiveBatch       int
	CognitiveConcurrency int
	ExperiencePrompt     string
	DecayIntervalHours   int // How often to run the memory decay job (hours)
	DecayAfterDays       int // Decay records not accessed within this many days
	RecentMessagesLimit  int // Max messages returned in recent_messages per GetContext call
}

var (
	instance *Config
	once     sync.Once
)

// Get loads the application configuration once (Singleton pattern).
// It will attempt to load a .env file if present, then read from environment variables.
// Required environment variables: DATABASE_URL, MASTER_KEY
func Get() *Config {
	once.Do(func() {
		// Attempt to load .env file, ignore error if it doesn't exist
		_ = godotenv.Load()

		// Load and validate database configuration
		dbURL := os.Getenv("DATABASE_URL")
		if dbURL == "" {
			log.Fatalf("DATABASE_URL environment variable is required")
		}

		dbMaxConns := DefaultDBMaxConns
		if val := os.Getenv("DB_MAX_CONNS"); val != "" {
			if parsed, err := strconv.Atoi(val); err == nil && parsed > 0 && parsed <= MaxDBMaxConns {
				dbMaxConns = parsed
			}
		}

		// Load and validate Redis configuration
		redisAddr := os.Getenv("REDIS_ADDR")
		if redisAddr == "" {
			redisAddr = DefaultRedisAddr
		}

		redisPool := DefaultRedisPool
		if val := os.Getenv("REDIS_POOL_SIZE"); val != "" {
			if parsed, err := strconv.Atoi(val); err == nil && parsed > 0 && parsed <= MaxRedisPool {
				redisPool = parsed
			}
		}

		// Load and validate server port
		port := os.Getenv("PORT")
		if port == "" {
			port = DefaultServerPort
		}
		if len(port) > 0 && port[0] != ':' {
			port = ":" + port
		}

		// Load and validate master key (REQUIRED for security)
		masterKey := os.Getenv("MASTER_KEY")
		if masterKey == "" {
			log.Fatalf("MASTER_KEY environment variable is required. Generate a secure 64-byte hex key using: openssl rand -hex 32")
		}

		// Load cognitive prompt
		cognitivePrompt := os.Getenv("COGNITIVE_PROMPT_PATH")
		if cognitivePrompt == "" {
			// Try to find the prompt file in common locations
			if _, err := os.Stat(DefaultPromptPath); err == nil {
				cognitivePrompt = DefaultPromptPath
			} else if _, err := os.Stat(AltPromptPath); err == nil {
				cognitivePrompt = AltPromptPath
			} else {
				cognitivePrompt = DefaultPromptPath
			}
		}

		promptBytes, err := os.ReadFile(cognitivePrompt)
		if err != nil {
			log.Fatalf("Failed to load cognitive prompt from %s: %v", cognitivePrompt, err)
		}

		cognitiveBatch := 10 // Default batch size
		if val := os.Getenv("COGNITIVE_BATCH_SIZE"); val != "" {
			if parsed, err := strconv.Atoi(val); err == nil && parsed > 0 {
				cognitiveBatch = parsed
			}
		}

		cognitiveConcurrency := 5 // Default max concurrent LLM calls
		if val := os.Getenv("COGNITIVE_CONCURRENCY"); val != "" {
			if parsed, err := strconv.Atoi(val); err == nil && parsed > 0 {
				cognitiveConcurrency = parsed
			}
		}

		decayIntervalHours := DefaultDecayIntervalHrs
		if val := os.Getenv("DECAY_INTERVAL_HOURS"); val != "" {
			if parsed, err := strconv.Atoi(val); err == nil && parsed > 0 {
				decayIntervalHours = parsed
			}
		}

		decayAfterDays := DefaultDecayAfterDays
		if val := os.Getenv("DECAY_AFTER_DAYS"); val != "" {
			if parsed, err := strconv.Atoi(val); err == nil && parsed > 0 {
				decayAfterDays = parsed
			}
		}

		recentMessagesLimit := DefaultRecentMessagesLimit
		if val := os.Getenv("RECENT_MESSAGES_LIMIT"); val != "" {
			if parsed, err := strconv.Atoi(val); err == nil && parsed > 0 && parsed <= MaxRecentMsgsLimit {
				recentMessagesLimit = parsed
			}
		}

		// Load experience extractor prompt
		experiencePromptPath := os.Getenv("EXPERIENCE_PROMPT_PATH")
		if experiencePromptPath == "" {
			if _, err := os.Stat(DefaultExperiencePromptPath); err == nil {
				experiencePromptPath = DefaultExperiencePromptPath
			} else if _, err := os.Stat(AltExperiencePromptPath); err == nil {
				experiencePromptPath = AltExperiencePromptPath
			} else {
				experiencePromptPath = DefaultExperiencePromptPath
			}
		}
		experiencePromptBytes, err := os.ReadFile(experiencePromptPath)
		if err != nil {
			log.Fatalf("Failed to load experience prompt from %s: %v", experiencePromptPath, err)
		}

		instance = &Config{
			DatabaseURL:          dbURL,
			DBMaxConns:           int32(dbMaxConns),
			RedisAddr:            redisAddr,
			RedisPool:            redisPool,
			ServerPort:           port,
			MasterKey:            masterKey,
			CognitivePrompt:      string(promptBytes),
			CognitiveBatch:       cognitiveBatch,
			CognitiveConcurrency: cognitiveConcurrency,
			ExperiencePrompt:     string(experiencePromptBytes),
			DecayIntervalHours:   decayIntervalHours,
			DecayAfterDays:       decayAfterDays,
			RecentMessagesLimit:  recentMessagesLimit,
		}
	})

	return instance
}
