package main

import (
	"context"
	"log"
	"time"

	"github.com/cortexa/cortexa/internal/config"
	"github.com/cortexa/cortexa/internal/llm"
	"github.com/cortexa/cortexa/internal/repository"
	"github.com/cortexa/cortexa/internal/worker"
	"github.com/redis/go-redis/v9"
)

func main() {
	cfg := config.Get()

	db, err := repository.GetDB(context.Background())
	if err != nil {
		log.Fatalf("Failed to connect to DB: %v", err)
	}

	rdb := redis.NewClient(&redis.Options{
		Addr:     cfg.RedisAddr,
		PoolSize: cfg.RedisPool,
	})

	llmClient := llm.NewClient()
	entityRepo := repository.NewEntityRepository(db)
	memRepo := repository.NewMemoryRepository(db)
	profileRepo := repository.NewProfileRepository(db)
	usageRepo := repository.NewLLMUsageRepository(db)
	expRepo := repository.NewExperienceRepository(db)

	embedder := worker.NewEmbedderWorker(cfg.DatabaseURL, rdb, llmClient)
	cognitiveWorker := worker.NewCognitiveWorker(rdb, llmClient, entityRepo, memRepo, profileRepo, usageRepo)
	experienceWorker := worker.NewExperienceWorker(rdb, llmClient, entityRepo, expRepo, profileRepo)

	decayWorker := worker.NewDecayWorker(
		memRepo,
		time.Duration(cfg.DecayIntervalHours)*time.Hour,
		0.05, // matches TimeDecayRate in service/retriever.go
		cfg.DecayAfterDays,
	)

	go func() {
		log.Printf("Starting Memory Decay Worker (interval=%dh, decay_after=%dd)...",
			cfg.DecayIntervalHours, cfg.DecayAfterDays)
		decayWorker.Run(context.Background())
	}()

	go func() {
		log.Println("Starting Cognitive Worker (Extractor + Event Detector)...")
		cognitiveWorker.Subscribe(context.Background())
	}()

	go func() {
		log.Println("Starting Experience Worker (Behavior Learner)...")
		experienceWorker.Subscribe(context.Background())
	}()

	log.Println("Starting Embedder Worker...")
	if err := embedder.Listen(context.Background()); err != nil {
		log.Fatalf("Embedder worker failed: %v", err)
	}
}
