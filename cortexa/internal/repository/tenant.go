package repository

import "context"

type tenantIDKeyType struct{}

var tenantIDKey = tenantIDKeyType{}

// WithTenantID injects a tenant ID into the context. All repository calls
// that acquire a DB connection will propagate this value to the PostgreSQL
// session-level setting `app.tenant_id`, which activates Row-Level Security.
func WithTenantID(ctx context.Context, tenantID string) context.Context {
	return context.WithValue(ctx, tenantIDKey, tenantID)
}

// TenantIDFromCtx extracts the tenant ID from the context.
// Returns an empty string if not set.
func TenantIDFromCtx(ctx context.Context) string {
	if v, ok := ctx.Value(tenantIDKey).(string); ok {
		return v
	}
	return ""
}
