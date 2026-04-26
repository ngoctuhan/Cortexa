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
	pipe := c.redis.Pipeline()
	incr := pipe.Incr(ctx, key)
	pipe.Expire(ctx, key, 24*time.Hour)
	_, err := pipe.Exec(ctx)
	if err != nil {
		return 0, err
	}
	return incr.Val(), nil
}

func (c *Cache) ResetCognitiveBatch(ctx context.Context, tenantID, sessionID string) error {
	key := fmt.Sprintf("%s:sess:%s:cog_batch", tenantID, sessionID)
	return c.redis.Del(ctx, key).Err()
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
