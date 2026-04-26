package worker

import (
	"context"
	"log"
	"time"

	"github.com/cortexa/cortexa/internal/repository"
)

// DecayWorker periodically reduces the importance of memory records that have not
// been accessed recently, preventing stale facts from dominating context retrieval.
//
// It runs on a configurable ticker interval (DECAY_INTERVAL_HOURS) and only
// targets records older than DECAY_AFTER_DAYS days. The decay formula is:
//
//	importance = GREATEST(0.01, importance * (1 - rate))
//
// where rate defaults to the TimeDecayRate used by the retriever reranker (0.05).
type DecayWorker struct {
	memRepo  *repository.MemoryRepository
	interval time.Duration
	rate     float64
	ageDays  int
}

// NewDecayWorker creates a new DecayWorker.
//
//   - interval: how often to run the decay job
//   - rate:     fraction to subtract from importance each cycle (e.g. 0.05 = 5%)
//   - ageDays:  only decay records whose last_accessed_at is older than this many days
func NewDecayWorker(memRepo *repository.MemoryRepository, interval time.Duration, rate float64, ageDays int) *DecayWorker {
	return &DecayWorker{
		memRepo:  memRepo,
		interval: interval,
		rate:     rate,
		ageDays:  ageDays,
	}
}

// Run starts the decay loop. It fires once immediately on startup so that the
// first run does not wait a full interval, then fires on each ticker tick until
// ctx is cancelled.
func (w *DecayWorker) Run(ctx context.Context) {
	w.decay(ctx)

	ticker := time.NewTicker(w.interval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			w.decay(ctx)
		case <-ctx.Done():
			return
		}
	}
}

func (w *DecayWorker) decay(ctx context.Context) {
	n, err := w.memRepo.DecayImportance(ctx, w.rate, w.ageDays)
	if err != nil {
		log.Printf("DecayWorker: decay run failed: %v", err)
		return
	}
	if n > 0 {
		log.Printf("DecayWorker: decayed importance for %d memory record(s) (rate=%.2f, age>%dd)",
			n, w.rate, w.ageDays)
	}
}
