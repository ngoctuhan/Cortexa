package worker

import (
	"context"
	"encoding/json"
	"log"
	"strings"
	"time"

	"github.com/cortexa/cortexa/internal/repository"
)

// FlusherWorker periodically scans for inactive sessions and flushes pending messages
// to the cognitive extraction stream.
type FlusherWorker struct {
	cache   *repository.Cache
	msgRepo *repository.MessageRepository
	stopCh  chan struct{}
}

// NewFlusherWorker creates a new FlusherWorker.
func NewFlusherWorker(cache *repository.Cache, msgRepo *repository.MessageRepository) *FlusherWorker {
	return &FlusherWorker{
		cache:   cache,
		msgRepo: msgRepo,
		stopCh:  make(chan struct{}),
	}
}

// Start begins the periodic flush loop.
func (w *FlusherWorker) Start(interval, olderThan time.Duration) {
	ticker := time.NewTicker(interval)
	log.Printf("FlusherWorker: started (interval=%v, olderThan=%v)\n", interval, olderThan)
	for {
		select {
		case <-ticker.C:
			w.runFlushCycle(olderThan)
		case <-w.stopCh:
			ticker.Stop()
			log.Println("FlusherWorker: stopped")
			return
		}
	}
}

// Stop stops the worker.
func (w *FlusherWorker) Stop() {
	close(w.stopCh)
}

func (w *FlusherWorker) runFlushCycle(olderThan time.Duration) {
	ctx := context.Background()
	
	// Distributed Lock: Prevent multiple Pods from running the flush cycle concurrently
	lockKey := "lock:flusher_worker"
	// TTL is slightly less than the typical 1-minute interval
	locked, err := w.cache.TryLock(ctx, lockKey, 50*time.Second)
	if err != nil {
		log.Printf("FlusherWorker: error acquiring lock: %v\n", err)
		return
	}
	if !locked {
		// Another Pod holds the lock, skip this cycle safely
		return
	}

	// Process up to 100 inactive sessions per cycle to avoid overloading
	inactiveMembers, err := w.cache.GetInactiveSessions(ctx, olderThan, 100)
	if err != nil {
		log.Printf("FlusherWorker: error getting inactive sessions: %v\n", err)
		return
	}

	if len(inactiveMembers) == 0 {
		return
	}

	for _, member := range inactiveMembers {
		parts := strings.Split(member, ":")
		if len(parts) != 2 {
			continue // Malformed member
		}
		tenantID, sessionID := parts[0], parts[1]

		count, err := w.cache.GetCognitiveBatchCount(ctx, tenantID, sessionID)
		if err != nil {
			log.Printf("FlusherWorker: error getting batch count for session %s: %v\n", sessionID, err)
			continue
		}

		// If no pending messages, just remove from tracking and continue
		if count == 0 {
			_ = w.cache.RemoveSessionActivity(ctx, tenantID, sessionID)
			continue
		}

		// Flush the session
		w.flushSession(ctx, tenantID, sessionID, count)
	}
}

func (w *FlusherWorker) flushSession(ctx context.Context, tenantID, sessionID string, count int64) {
	// Get the latest message ID to use as an anchor
	msgs, err := w.msgRepo.GetSessionHistory(ctx, tenantID, sessionID, 1, "")
	if err != nil || len(msgs) == 0 {
		// Can't find messages, might be deleted. Remove tracking.
		_ = w.cache.RemoveSessionActivity(ctx, tenantID, sessionID)
		return
	}
	
	// We need UserID for the payload, which we can get from the message
	userID := msgs[0].UserID.String()
	lastMsgID := msgs[0].ID.String()

	// Reset batch count and remove from tracking
	_ = w.cache.ResetCognitiveBatch(ctx, tenantID, sessionID)

	batchPayload := map[string]interface{}{
		"tenant_id":       tenantID,
		"user_id":         userID,
		"session_id":      sessionID,
		"batch_size":      int(count),
		"last_message_id": lastMsgID,
	}

	if b, err := json.Marshal(batchPayload); err == nil {
		if err := w.cache.XAddCognitiveBatch(ctx, tenantID, string(b)); err == nil {
			log.Printf("FlusherWorker: triggered force flush for inactive session %s (count=%d)\n", sessionID, count)
		} else {
			log.Printf("FlusherWorker: error publishing batch event for session %s: %v\n", sessionID, err)
		}
	}
}
