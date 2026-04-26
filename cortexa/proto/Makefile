# Proto file compilation for Cortexa MCM

# Variables
PROTO_DIR := .
PROTO_FILES := $(wildcard $(PROTO_DIR)/*.proto)
GO_OUT := .

# Tools
PROTOC := protoc
PROTOC_GO := protoc-gen-go
PROTOC_GRPC := protoc-gen-go-grpc

# Check if tools are installed
.PHONY: check-tools
check-tools:
	@echo "Checking for required tools..."
	@which $(PROTOC) > /dev/null || (echo "protoc not found. Install with: brew install protobuf" && exit 1)
	@which $(PROTOC_GO) > /dev/null || (echo "protoc-gen-go not found. Install with: go install google.golang.org/protobuf/cmd/protoc-gen-go@latest" && exit 1)
	@which $(PROTOC_GRPC) > /dev/null || (echo "protoc-gen-go-grpc not found. Install with: go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest" && exit 1)
	@echo "All tools installed!"

# Generate Go code from proto files
.PHONY: proto
proto: check-tools
	@echo "Generating Go code from proto files..."
	$(PROTOC) \
		--go_out=$(GO_OUT) \
		--go_opt=paths=source_relative \
		--go-grpc_out=$(GO_OUT) \
		--go-grpc_opt=paths=source_relative \
		$(PROTO_FILES)
	@echo "Done! Generated files:"
	@ls -la $(PROTO_DIR)/*.pb.go 2>/dev/null || echo "No .pb.go files found"

# Clean generated files
.PHONY: clean
clean:
	@echo "Cleaning generated files..."
	@rm -f $(PROTO_DIR)/*.pb.go
	@echo "Cleaned!"

# Regenerate (clean + proto)
.PHONY: regenerate
regenerate: clean proto

# Format generated Go code
.PHONY: fmt
fmt:
	@echo "Formatting generated Go files..."
	@gofmt -w $(PROTO_DIR)/*.pb.go 2>/dev/null || echo "No .pb.go files to format"

# Lint proto files
.PHONY: lint
lint:
	@echo "Linting proto files..."
	@which buf > /dev/null || (echo "buf not found. Install with: go install github.com/bufbuild/buf/cmd/buf@latest" && exit 1)
	@buf lint

# Generate mocks for testing
.PHONY: mocks
mocks: proto
	@echo "Generating mocks..."
	@which mockgen > /dev/null || (echo "mockgen not found. Install with: go install github.com/golang/mock/mockgen@latest" && exit 1)
	@mockgen -source=mcm_grpc.pb.go -destination=mcm_mock.pb.go -package=mcmv1
	@echo "Mocks generated!"

# Show help
.PHONY: help
help:
	@echo "Available targets:"
	@echo "  make proto      - Generate Go code from proto files"
	@echo "  make clean     - Remove generated files"
	@echo "  make regenerate - Clean and regenerate"
	@echo "  make fmt       - Format generated Go files"
	@echo "  make lint      - Lint proto files (requires buf)"
	@echo "  make mocks     - Generate mocks for testing"
	@echo "  make check-tools - Verify required tools are installed"
	@echo "  make help      - Show this help message"

# Default target
.DEFAULT_GOAL := help
