package repository

import (
	"context"
	"strings"

	"github.com/cortexa/cortexa/internal/config"
	"github.com/cortexa/cortexa/internal/model"
	"github.com/cortexa/cortexa/internal/security"
)

type ProfileRepository struct {
	db *DB
}

func NewProfileRepository(db *DB) *ProfileRepository {
	return &ProfileRepository{db: db}
}

// Get derives the UserProfile from entity_type='self' facts in entity_mentions.
// All self-facts are fetched; attribute='name' becomes CanonicalName, attribute='nickname'
// and attribute='alias' become Aliases. No language-specific strings are hardcoded —
// the cognitive prompt normalises all name facts to English attribute keys.
// Falls back to "User" when no name fact has been extracted yet.
func (r *ProfileRepository) Get(ctx context.Context, tenantID, userID string) (*model.UserProfile, error) {
	cfg := config.Get()
	crypto, err := security.NewCrypto(cfg.MasterKey)
	if err != nil {
		return &model.UserProfile{CanonicalName: "User", Aliases: []string{}}, nil
	}

	rows, err := r.db.Pool.Query(ctx, `
		SELECT attribute, value_encrypted
		FROM entity_mentions
		WHERE tenant_id = $1 AND user_id = $2 AND valid_until IS NULL
		  AND entity_type = 'self'
		ORDER BY confidence DESC, created_at DESC
	`, tenantID, userID)
	if err != nil {
		return &model.UserProfile{CanonicalName: "User", Aliases: []string{}}, nil
	}
	defer rows.Close()

	canonicalName := ""
	var aliases []string

	for rows.Next() {
		var attr string
		var enc []byte
		if err := rows.Scan(&attr, &enc); err != nil {
			continue
		}
		val, err := crypto.DecryptValue(enc, tenantID)
		if err != nil || strings.TrimSpace(val) == "" {
			continue
		}
		switch strings.ToLower(attr) {
		case "name":
			if canonicalName == "" {
				canonicalName = val
			}
		case "nickname", "alias":
			aliases = append(aliases, val)
		}
	}

	if canonicalName == "" {
		canonicalName = "User"
	}
	if aliases == nil {
		aliases = []string{}
	}
	return &model.UserProfile{CanonicalName: canonicalName, Aliases: aliases}, nil
}
