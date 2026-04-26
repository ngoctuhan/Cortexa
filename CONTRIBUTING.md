# Contributing to Cortexa MCM

Thank you for your interest in contributing to Cortexa Memory Context Manager! We welcome contributions from the community.

---

## 🤝 How to Contribute

### Reporting Bugs

Before creating bug reports, please check existing issues to avoid duplicates. When filing a bug report, include:

- **Clear title and description**
- **Steps to reproduce** the issue
- **Expected behavior** vs **actual behavior**
- **Environment details**:
  - OS and version
  - Go version (`go version`)
  - PostgreSQL version
  - Redis version
- **Relevant logs** or error messages

### Suggesting Enhancements

Enhancement suggestions are welcome! Please provide:

- **Clear use case** for the enhancement
- **Proposed implementation** (if you have ideas)
- **Alternative approaches** considered

### Submitting Pull Requests

1. **Fork the repository** and create your branch from `main`
2. **Install dependencies**: `go mod download`
3. **Make your changes** with clear, descriptive commits
4. **Write tests** for new functionality
5. **Ensure all tests pass**: `go test ./...`
6. **Run linters**: `go vet ./...` and `gofmt -l .`
7. **Update documentation** as needed
8. **Submit your pull request**

---

## 📋 Development Setup

### Prerequisites

- Go 1.25 or later
- PostgreSQL 15+ with pgvector extension
- Redis 7+
- Docker (for local development)

### Setup Steps

```bash
# 1. Fork and clone the repository
git clone https://github.com/YOUR_USERNAME/cortexa.git
cd cortexa

# 2. Add upstream remote
git remote add upstream https://github.com/cortexa/cortexa.git

# 3. Install dependencies
go mod download

# 4. Copy environment template
cp .env.example .env

# 5. Start development infrastructure
docker-compose up -d

# 6. Run database migrations
psql $DATABASE_URL -f migrations/001_init.sql

# 7. Run tests
go test ./...
```

---

## 🧪 Testing

### Running Tests

```bash
# Run all tests
go test ./...

# Run tests with coverage
go test -cover ./...

# Run tests with race detection
go test -race ./...

# Run specific package tests
go test ./internal/config

# Run verbose tests
go test -v ./...
```

### Writing Tests

- **Table-driven tests** for multiple test cases
- **Setup/teardown** using `TestMain` when needed
- **Mock external dependencies** (LLM APIs, database)
- **Test error paths** as well as success paths

Example:

```go
func TestNewCrypto(t *testing.T) {
	tests := []struct {
		name    string
		key     string
		wantErr bool
	}{
		{
			name:    "valid key",
			key:     "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
			wantErr: false,
		},
		{
			name:    "invalid key - too short",
			key:     "0123456789abcdef",
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := NewCrypto(tt.key)
			if (err != nil) != tt.wantErr {
				t.Errorf("NewCrypto() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}
```

---

## 📝 Code Style

### Go Conventions

We follow standard Go conventions:

- **Format code**: `go fmt ./...`
- **Check errors**: Always handle errors
- **Use goimports**: `go install golang.org/x/tools/cmd/goimports@latest`
- **Effective Go**: Follow [Effective Go](https://go.dev/doc/effective_go)

### Naming Conventions

- **Package names**: lowercase, single word when possible
- **Exported functions**: PascalCase with godoc comments
- **Internal functions**: camelCase
- **Constants**: PascalCase or UPPER_CASE
- **Interfaces**: Usually `-er` suffix (e.g., `Reader`, `Writer`)

### Godoc Comments

All exported functions must have godoc comments:

```go
// EncryptValue encrypts a plaintext value using AES-GCM with a tenant-specific key.
// The returned ciphertext includes the nonce prepended to the encrypted data.
func (c *Crypto) EncryptValue(plaintext, tenantID string) ([]byte, error) {
    // ...
}
```

---

## 🔄 Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Build process or auxiliary tool changes

**Examples:**

```
feat(api): add rate limiting middleware

fix(crypto): validate key length in NewCrypto

docs(readme): update quick start guide

refactor(service): extract context retrieval logic

test(crypto): add test cases for invalid inputs
```

---

## ✅ Pull Request Checklist

Before submitting your PR, ensure:

- [ ] Tests pass locally (`go test ./...`)
- [ ] Code is formatted (`go fmt ./...`)
- [ ] `go vet ./...` passes
- [ ] New features include tests
- [ ] Documentation is updated
- [ ] Commits follow conventional commits
- [ ] PR description clearly describes changes
- [ ] Only one feature or fix per PR

---

## 📧 Getting Help

- **GitHub Issues**: For bugs and feature requests
- **GitHub Discussions**: For questions and ideas
- **Documentation**: Check `/docs` folder

---

## 🎯 Priority Areas for Contribution

We're particularly looking for help with:

1. **Tests**: We need more test coverage
2. **Documentation**: API docs, architecture docs
3. **Observability**: Metrics, tracing, logging
4. **Additional LLM Providers**: Anthropic, Cohere, etc.
5. **Performance**: Optimization and profiling
6. **Examples**: Sample integrations and use cases

---

## 📜 Code Review Process

1. **Automated checks** must pass (CI/CD)
2. **At least one maintainer** must review
3. **All feedback** should be addressed
4. **Squash commits** if requested
5. **Approval required** before merging

---

Thank you for contributing to Cortexa MCM! 🎉
