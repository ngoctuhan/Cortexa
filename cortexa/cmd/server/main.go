package main

import (
	"context"
	"log"

	"github.com/cortexa/cortexa/internal/api"
	"github.com/cortexa/cortexa/internal/config"
	"github.com/cortexa/cortexa/internal/llm"
	"github.com/cortexa/cortexa/internal/repository"
	"github.com/cortexa/cortexa/internal/service"
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

	msgRepo := repository.NewMessageRepository(db)
	sessionRepo := repository.NewSessionRepository(db)
	cache := repository.NewCache(rdb, msgRepo)
	entityRepo := repository.NewEntityRepository(db)
	profileRepo := repository.NewProfileRepository(db)
	memRepo := repository.NewMemoryRepository(db)
	expRepo := repository.NewExperienceRepository(db)
	llmClient := llm.NewClient()

	retriever := service.NewContextRetriever(
		cache, entityRepo, profileRepo, memRepo, expRepo, llmClient,
	)

	server := api.NewRESTServer(retriever, msgRepo, sessionRepo, memRepo, expRepo, cache)

	log.Printf("Starting REST server on %s\n", cfg.ServerPort)
	if err := server.Run(cfg.ServerPort); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
