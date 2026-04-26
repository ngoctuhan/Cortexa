package repository

import (
	"context"
	"sync"

	"github.com/cortexa/cortexa/internal/config"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type DB struct {
	Pool *pgxpool.Pool
}

var (
	dbInstance *DB
	dbOnce     sync.Once
	dbErr      error
)

// GetDB returns a singleton instance of the database connection pool.
// It relies on the config package to retrieve settings.
func GetDB(ctx context.Context) (*DB, error) {
	dbOnce.Do(func() {
		cfg := config.Get()
		pgxConfig, err := pgxpool.ParseConfig(cfg.DatabaseURL)
		if err != nil {
			dbErr = err
			return
		}

		// Configure connection pool from singleton config
		pgxConfig.MaxConns = cfg.DBMaxConns

		// Activate Row-Level Security by injecting the tenant ID from context
		// into the PostgreSQL session setting `app.tenant_id` on every acquire.
		pgxConfig.BeforeAcquire = func(ctx context.Context, conn *pgx.Conn) bool {
			tid := TenantIDFromCtx(ctx)
			if tid != "" {
				if _, err := conn.Exec(ctx, "SELECT set_config('app.tenant_id', $1, false)", tid); err != nil {
					return false
				}
			} else {
				// No tenant in context — reset to deny-all state.
				_, _ = conn.Exec(ctx, "RESET app.tenant_id")
			}
			return true
		}

		pool, err := pgxpool.NewWithConfig(ctx, pgxConfig)
		if err != nil {
			dbErr = err
			return
		}
		dbInstance = &DB{Pool: pool}
	})

	return dbInstance, dbErr
}
