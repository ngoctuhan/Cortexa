# ── Build stage ───────────────────────────────────────────────────────────────
FROM golang:1.25-alpine AS builder

WORKDIR /app

COPY go.mod go.sum ./
RUN go mod download

COPY . .

RUN go build -o cortexa-server ./cmd/server \
 && go build -o cortexa-worker ./cmd/worker

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM alpine:3.20

RUN apk add --no-cache ca-certificates tzdata

WORKDIR /app

COPY --from=builder /app/cortexa-server ./cortexa-server
COPY --from=builder /app/cortexa-worker ./cortexa-worker
COPY prompts/ ./prompts/
