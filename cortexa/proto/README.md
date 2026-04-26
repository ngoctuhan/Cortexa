# Cortexa MCM - Protocol Buffers

This directory contains the Protocol Buffer definitions for the Cortexa Memory Context Manager gRPC service.

## 📁 Files

- `common.proto` - Common types and enums (Role, EntityType, etc.)
- `entities.proto` - Message and entity definitions
- `cortexa.proto` - Main gRPC service definition

## 🚀 Generate Code

### Prerequisites

Install Protocol Buffers compiler and plugins:

```bash
# macOS
brew install protobuf

# Go plugins
go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest

# Ensure $GOPATH/bin is in your $PATH
export PATH=$PATH:$(go env GOPATH)/bin
```

### Generate Go Code

```bash
# From the cortexa directory
make proto
```

Or manually:

```bash
protoc --go_out=. --go_opt=paths=source_relative \
       --go-grpc_out=. --go-grpc_opt=paths=source_relative \
       proto/*.proto
```

## 📋 API Methods

The gRPC service exposes 2 main methods:

### 1. AppendMessage

Store a new message in the system.

```protobuf
rpc AppendMessage(AppendMessageRequest) returns (AppendMessageResponse);
```

**Request:**
```protobuf
message AppendMessageRequest {
  UUID tenant_id = 1;
  UUID user_id = 2;
  UUID session_id = 3;
  Role role = 4;           // USER, ASSISTANT, or SYSTEM
  string content = 5;      // Message content (max 100KB)
}
```

**Response:**
```protobuf
message AppendMessageResponse {
  UUID message_id = 1;
  string status = 2;       // "success"
  string message = 3;      // Description
}
```

### 2. GetContext

Retrieve contextual information for AI agents.

```protobuf
rpc GetContext(GetContextRequest) returns (GetContextResponse);
```

**Request:**
```protobuf
message GetContextRequest {
  UUID tenant_id = 1;
  UUID user_id = 2;
  UUID session_id = 3;
  string query = 4;        // Search query (max 5000 chars)
}
```

**Response:**
```protobuf
message GetContextResponse {
  repeated Message recent_messages = 1;     // Recent conversation
  repeated EntityFact entity_facts = 2;     // Extracted entities
  repeated RagChunk relevant_chunks = 3;    // Vector search results
  MemoryRecord persona_context = 4;         // User persona
  repeated MemoryRecord upcoming_events = 5; // Scheduled events
  int64 latency_ms = 6;                     // Response time
  bool is_partial = 7;                      // True if timeout hit
}
```

## 🔄 Equivalent REST API

| gRPC Method | REST Endpoint |
|-------------|--------------|
| `AppendMessage` | `POST /v1/messages` |
| `GetContext` | `POST /v1/context` |

## 📊 Data Types

### Role Enum

```protobuf
enum Role {
  ROLE_UNSPECIFIED = 0;
  ROLE_USER = 1;
  ROLE_ASSISTANT = 2;
  ROLE_SYSTEM = 3;
}
```

### EntityType Enum

```protobuf
enum EntityType {
  ENTITY_TYPE_PERSON = 1;
  ENTITY_TYPE_PLACE = 2;
  ENTITY_TYPE_ORG = 3;
  ENTITY_TYPE_CONTACT = 4;
  ENTITY_TYPE_THING = 5;
  ENTITY_TYPE_SELF = 6;
}
```

### EntityAttribute Enum

```protobuf
enum EntityAttribute {
  ENTITY_ATTRIBUTE_EMAIL = 1;
  ENTITY_ATTRIBUTE_PHONE = 2;
  ENTITY_ATTRIBUTE_JOB = 3;
  ENTITY_ATTRIBUTE_BIRTHDAY = 4;
  ENTITY_ATTRIBUTE_ADDRESS = 5;
  ENTITY_ATTRIBUTE_LIKES = 6;
  ENTITY_ATTRIBUTE_OWNS = 7;
  ENTITY_ATTRIBUTE_WORKS_AT = 8;
  ENTITY_ATTRIBUTE_RELATIONSHIP = 9;
}
```

## 🔧 Generated Files

After running `make proto`, the following files are generated:

```
proto/
├── common.proto
├── common.pb.go
├── entities.proto
├── entities.pb.go
├── cortexa.proto
├── cortexa.pb.go
└── cortexa_grpc.pb.go
```

## 📝 Example Usage

```go
import (
    "context"
    "github.com/cortexa/cortexa/proto/v1"
    "google.golang.org/grpc"
)

func main() {
    // Connect to gRPC server
    conn, err := grpc.Dial("localhost:9090", grpc.WithInsecure())
    if err != nil {
        log.Fatal(err)
    }
    defer conn.Close()

    client := cortexav1.NewCortexaServiceClient(conn)

    // Append a message
    resp, err := client.AppendMessage(context.Background(), &cortexav1.AppendMessageRequest{
        TenantId: &cortexav1.UUID{Value: "tenant-uuid"},
        UserId:   &cortexav1.UUID{Value: "user-uuid"},
        SessionId:&cortexav1.UUID{Value: "session-uuid"},
        Role:     cortexav1.Role_ROLE_USER,
        Content:  "Hello, world!",
    })
    if err != nil {
        log.Fatal(err)
    }

    log.Printf("Message ID: %s", resp.MessageId.Value)

    // Get context
    ctx, err := client.GetContext(context.Background(), &cortexav1.GetContextRequest{
        TenantId: &cortexav1.UUID{Value: "tenant-uuid"},
        UserId:   &cortexav1.UUID{Value: "user-uuid"},
        SessionId:&cortexav1.UUID{Value: "session-uuid"},
        Query:    "What did we discuss?",
    })
    if err != nil {
        log.Fatal(err)
    }

    log.Printf("Found %d entity facts", len(ctx.EntityFacts))
    log.Printf("Latency: %dms", ctx.LatencyMs)
}
```

## 🧪 Testing

Generate mock server for testing:

```bash
# Install mock generator
go install github.com/golang/mock/mockgen@latest

# Generate mocks
make mocks
```

## 📚 Related Documentation

- [gRPC Go Quick Start](https://grpc.io/docs/languages/go/quickstart/)
- [Protocol Buffers Guide](https://protobuf.dev/getting-started/)
- [REST API Documentation](../README.md#api-reference)

---

*Last Updated: 2026-04-21*
