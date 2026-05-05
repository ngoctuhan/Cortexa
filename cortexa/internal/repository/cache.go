package repository

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/cortexa/cortexa/internal/model"
	"github.com/redis/go-redis/v9"
	"golang.org/x/sync/singleflight"
)

type Cache struct {
	redis     *redis.Client
	msgRepo   *MessageRepository
	warmGroup singleflight.Group
}

func NewCache(r *redis.Client, msgRepo *MessageRepository) *Cache {
	return &Cache{
		redis:   r,
		msgRepo: msgRepo,
	}
}

func (c *Cache) AppendMessages(ctx context.Context, tenantID, sessionID string, msgs []model.Message) error {
	key := fmt.Sprintf("%s:sess:%s:msgs", tenantID, sessionID)
	exists, err := c.redis.Exists(ctx, key).Result()
	if err != nil {
		return err
	}
	if exists == 0 {
		return c.reloadAndAppend(ctx, key, tenantID, sessionID, msgs)
	}

	pipe := c.redis.Pipeline()
	for _, m := range msgs {
		b, _ := json.Marshal(m)
		pipe.LPush(ctx, key, b)
	}
	pipe.LTrim(ctx, key, 0, 49) // Keep last 50
	pipe.Expire(ctx, key, 2*time.Hour)
	_, err = pipe.Exec(ctx)
	return err
}

func (c *Cache) IncrementCognitiveBatch(ctx context.Context, tenantID, sessionID string) (int64, error) {
	key := fmt.Sprintf("%s:sess:%s:cog_batch", tenantID, sessionID)
	activeKey := "global:active_sessions"
	member := fmt.Sprintf("%s:%s", tenantID, sessionID)

	pipe := c.redis.Pipeline()
	incr := pipe.Incr(ctx, key)
	pipe.Expire(ctx, key, 24*time.Hour)
	// Track activity for timeout flush
	pipe.ZAdd(ctx, activeKey, redis.Z{Score: float64(time.Now().Unix()), Member: member})
	_, err := pipe.Exec(ctx)
	if err != nil {
		return 0, err
	}
	return incr.Val(), nil
}

// GetCognitiveBatchCount returns the current number of pending messages for a session.
func (c *Cache) GetCognitiveBatchCount(ctx context.Context, tenantID, sessionID string) (int64, error) {
	key := fmt.Sprintf("%s:sess:%s:cog_batch", tenantID, sessionID)
	val, err := c.redis.Get(ctx, key).Int64()
	if err == redis.Nil {
		return 0, nil
	}
	return val, err
}

func (c *Cache) ResetCognitiveBatch(ctx context.Context, tenantID, sessionID string) error {
	key := fmt.Sprintf("%s:sess:%s:cog_batch", tenantID, sessionID)
	activeKey := "global:active_sessions"
	member := fmt.Sprintf("%s:%s", tenantID, sessionID)

	pipe := c.redis.Pipeline()
	pipe.Del(ctx, key)
	pipe.ZRem(ctx, activeKey, member)
	_, err := pipe.Exec(ctx)
	return err
}

// GetInactiveSessions returns sessions that haven't had activity in the specified duration.
func (c *Cache) GetInactiveSessions(ctx context.Context, olderThan time.Duration, limit int64) ([]string, error) {
	key := "global:active_sessions"
	maxScore := fmt.Sprintf("%f", float64(time.Now().Add(-olderThan).Unix()))
	return c.redis.ZRangeByScore(ctx, key, &redis.ZRangeBy{
		Min:    "-inf",
		Max:    maxScore,
		Offset: 0,
		Count:  limit,
	}).Result()
}

func (c *Cache) RemoveSessionActivity(ctx context.Context, tenantID, sessionID string) error {
	key := "global:active_sessions"
	member := fmt.Sprintf("%s:%s", tenantID, sessionID)
	return c.redis.ZRem(ctx, key, member).Err()
}

// TryLock attempts to acquire a distributed lock. Returns true if acquired.
func (c *Cache) TryLock(ctx context.Context, key string, ttl time.Duration) (bool, error) {
	return c.redis.SetNX(ctx, key, "locked", ttl).Result()
}

func (c *Cache) PublishEvent(ctx context.Context, channel, payload string) error {
	return c.redis.Publish(ctx, channel, payload).Err()
}

// XAddCognitiveBatch enqueues a cognitive extraction job to the tenant's Redis Stream.
func (c *Cache) XAddCognitiveBatch(ctx context.Context, tenantID, payload string) error {
	stream := tenantID + ":stream:cognitive"
	return c.redis.XAdd(ctx, &redis.XAddArgs{
		Stream: stream,
		MaxLen: 10000,
		Approx: true,
		Values: map[string]interface{}{"payload": payload, "retries": "0"},
	}).Err()
}

func (c *Cache) reloadAndAppend(ctx context.Context, key, tenantID, sessionID string, msgs []model.Message) error {
	// Warm the cache from DB before appending the new messages so that
	// subsequent GetRawMessages calls return a complete recent-message window.
	existing, err := c.msgRepo.GetSessionHistory(ctx, tenantID, sessionID, 50, "")
	if err != nil {
		existing = nil // non-fatal: proceed with just the new messages
	}

	pipe := c.redis.Pipeline()
	// Push existing (older) messages first, then the new ones on top.
	for _, m := range existing {
		b, _ := json.Marshal(m)
		pipe.RPush(ctx, key, b)
	}
	for _, m := range msgs {
		b, _ := json.Marshal(m)
		pipe.LPush(ctx, key, b)
	}
	pipe.LTrim(ctx, key, 0, 49)
	pipe.Expire(ctx, key, 2*time.Hour)
	_, err = pipe.Exec(ctx)
	return err
}

func (c *Cache) GetRawMessages(ctx context.Context, tenantID, sessionID string, count int) ([]model.Message, error) {
	key := fmt.Sprintf("%s:sess:%s:msgs", tenantID, sessionID)
	vals, err := c.redis.LRange(ctx, key, 0, int64(count-1)).Result()
	if err != nil {
		return nil, err
	}
	if len(vals) == 0 {
		// Cache miss (key expired or Redis restarted) — fall back to DB.
		return c.msgRepo.GetSessionHistory(ctx, tenantID, sessionID, count, "")
	}
	var msgs []model.Message
	for _, v := range vals {
		var m model.Message
		json.Unmarshal([]byte(v), &m) //nolint:errcheck // malformed entries are simply skipped
		msgs = append(msgs, m)
	}
	return msgs, nil
}

// GetRawMessagesUntil returns up to count messages from the cache anchored at
// anchorMsgID: the anchor message itself plus older messages, in newest-first
// order (consistent with GetRawMessages). This prevents window drift when
// newer messages arrive in the cache between event publish and worker processing.
//
// Returns (nil, nil) on cache miss or when anchor is not found — callers should
// fall back to a DB query in that case.
func (c *Cache) GetRawMessagesUntil(ctx context.Context, tenantID, sessionID, anchorMsgID string, count int) ([]model.Message, error) {
	if anchorMsgID == "" {
		return c.GetRawMessages(ctx, tenantID, sessionID, count)
	}
	key := fmt.Sprintf("%s:sess:%s:msgs", tenantID, sessionID)
	// Fetch the full cached window (up to 50 entries) to locate the anchor.
	vals, err := c.redis.LRange(ctx, key, 0, 49).Result()
	if err != nil || len(vals) == 0 {
		return nil, err
	}
	// Decode and find the anchor index (list is newest-first: index 0 = newest).
	all := make([]model.Message, 0, len(vals))
	anchorIdx := -1
	for _, v := range vals {
		var m model.Message
		if jsonErr := json.Unmarshal([]byte(v), &m); jsonErr != nil {
			continue
		}
		if m.ID.String() == anchorMsgID {
			anchorIdx = len(all)
		}
		all = append(all, m)
	}
	if anchorIdx < 0 {
		// Anchor not in cache (evicted or not yet written) — signal cache miss.
		return nil, nil
	}
	// Return count messages starting from the anchor towards older entries.
	end := anchorIdx + count
	if end > len(all) {
		end = len(all)
	}
	return all[anchorIdx:end], nil
}
