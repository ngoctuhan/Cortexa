package api

import (
	"log/slog"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

var (
	httpRequestsTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "cortexa_http_requests_total",
		Help: "Total number of HTTP requests processed.",
	}, []string{"method", "path", "status_code"})

	httpRequestDuration = promauto.NewHistogramVec(prometheus.HistogramOpts{
		Name:    "cortexa_http_request_duration_seconds",
		Help:    "HTTP request latency in seconds.",
		Buckets: prometheus.DefBuckets,
	}, []string{"method", "path"})
)

// RequestIDMiddleware injects an X-Request-ID into every request. If the
// caller already provides one, it is echoed back; otherwise a new UUID is
// generated. The ID is stored in the Gin context under the key "request_id".
func RequestIDMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		reqID := c.GetHeader("X-Request-ID")
		if reqID == "" {
			reqID = uuid.New().String()
		}
		c.Set("request_id", reqID)
		c.Header("X-Request-ID", reqID)
		c.Next()
	}
}

// SlogMiddleware logs each completed request using the structured log/slog logger.
func SlogMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()

		path := c.FullPath()
		if path == "" {
			path = c.Request.URL.Path
		}

		reqID, _ := c.Get("request_id")
		slog.Info("http request",
			"method", c.Request.Method,
			"path", path,
			"status", c.Writer.Status(),
			"latency_ms", time.Since(start).Milliseconds(),
			"request_id", reqID,
			"ip", c.ClientIP(),
		)
	}
}

// MetricsMiddleware records Prometheus counters and histograms for every request.
func MetricsMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()

		path := c.FullPath()
		if path == "" {
			path = c.Request.URL.Path
		}

		status := c.Writer.Status()
		httpRequestsTotal.WithLabelValues(
			c.Request.Method,
			path,
			strconv.Itoa(status),
		).Inc()
		httpRequestDuration.WithLabelValues(
			c.Request.Method,
			path,
		).Observe(time.Since(start).Seconds())
	}
}

// PrometheusHandler wraps the standard promhttp handler for use as a Gin route.
func PrometheusHandler() gin.HandlerFunc {
	h := promhttp.Handler()
	return func(c *gin.Context) {
		h.ServeHTTP(c.Writer, c.Request)
	}
}
