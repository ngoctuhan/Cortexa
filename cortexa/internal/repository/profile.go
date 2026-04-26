package repository

import (
	"context"

	"github.com/cortexa/cortexa/internal/model"
)

type ProfileRepository struct {
	db *DB
}

func NewProfileRepository(db *DB) *ProfileRepository {
	return &ProfileRepository{db: db}
}

func (r *ProfileRepository) Get(ctx context.Context, tenantID, userID string) (*model.UserProfile, error) {
	return &model.UserProfile{CanonicalName: "User", Aliases: []string{}}, nil
}
