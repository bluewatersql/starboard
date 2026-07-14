# Getting Started with Starboard AI Agent

**Version**: 1.0  
**Last Updated**: 2025-12-02  
**Audience**: New developers

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [First Run](#first-run)
5. [Verify Installation](#verify-installation)
6. [Your First Contribution](#your-first-contribution)
7. [Development Workflow](#development-workflow)
8. [Next Steps](#next-steps)

---

## Prerequisites

### Required Software

| Tool | Version | Purpose | Installation |
|------|---------|---------|--------------|
| **Python** | 3.12+ | Backend runtime | [python.org](https://python.org) |
| **uv** | Latest | Package manager | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Node.js** | 18+ | Frontend runtime | [nodejs.org](https://nodejs.org) |
| **npm** | 9+ | Frontend package manager | Comes with Node.js |
| **Git** | 2.0+ | Version control | [git-scm.com](https://git-scm.com) |

### Optional Tools

| Tool | Purpose | Installation |
|------|---------|--------------|
| **Make** | Build automation | Usually pre-installed on macOS/Linux |
| **Docker** | Containerization (optional) | [docker.com](https://docker.com) |
| **Redis** | Session caching (optional) | `brew install redis` (macOS) |
| **PostgreSQL** | Production DB (optional) | `brew install postgresql` (macOS) |

### Required Accounts

1. **Databricks Account**
   - Sign up at [databricks.com](https://databricks.com)
   - Create workspace
   - Generate personal access token

2. **OpenAI Account** (or compatible LLM provider)
   - Sign up at [openai.com](https://openai.com)
   - Generate API key
   - Note: GPT-4 access recommended

### Knowledge Prerequisites

**Required**:
- Python 3.12+ (async/await, type hints)
- Git basics (clone, commit, push, pull)
- Command line/terminal usage

**Helpful**:
- FastAPI or similar web frameworks
- React/Next.js (for frontend work)
- Databricks or Spark (for domain understanding)
- LLM/AI agent concepts

---

## Installation

### Step 1: Clone Repository

```bash
# Clone the repository
git clone https://github.com/starboard-ai/job-agent.git
cd job-agent

# Verify you're on main branch
git branch
# Should show: * main
```

### Step 2: Bootstrap Environment

```bash
# Run first-time setup (creates .venv, installs all packages)
make setup
```

**What this does**:
1. Creates Python virtual environment (`.venv/`)
2. Installs all workspace packages via `uv`
3. Installs frontend dependencies via `npm`
4. Sets up Git hooks
5. Verifies installation

**Expected output**:
```
✓ Created virtual environment at .venv
✓ Installed starboard-core
✓ Installed starboard-log-parser
✓ Installed starboard-server
✓ Installed starboard-cli
✓ Installed frontend dependencies
✓ Git hooks configured
✅ Setup complete!
```

**Troubleshooting**:
```bash
# If make is not available
./scripts/setup.sh

# If uv is not installed
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc  # or ~/.zshrc

# If Node.js is not installed
# Install from nodejs.org or use nvm
```

---

## Configuration

### Step 3: Create Environment File

```bash
# Copy example configuration
cp examples/env.example .env

# Open in editor
nano .env  # or vim, code, etc.
```

### Step 4: Configure Credentials

**Required Variables**:

```bash
# Databricks Configuration
DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
DATABRICKS_TOKEN="dapi..."

# LLM Configuration
LLM_API_KEY="<your-api-key>"
LLM_MODEL="gpt-4o"  # or gpt-4o-mini for faster/cheaper
```

**Optional Variables**:

```bash
# LLM Settings
LLM_TEMPERATURE="0.4"
LLM_MAX_TOKENS="120000"
LLM_TIMEOUT_SECONDS="120"

# Database (defaults to SQLite)
DATABASE_URL="sqlite:///dev_data/starboard_state.db"

# Redis (optional, for session caching)
REDIS_URL="redis://localhost:6379"

# Logging
LOG_LEVEL="INFO"  # DEBUG, INFO, WARNING, ERROR
LOG_FORMAT="json"  # json or text

# Development
DEBUG="false"
SAFE_MODE="false"  # Disable external calls for testing
```

### Step 5: Verify Configuration

```bash
# Test Databricks connection
python3 -c "
from starboard.adapters.apis.databricks import DatabricksAPI
api = DatabricksAPI()
print('✓ Databricks connected:', api.get_current_user())
"

# Test OpenAI connection
python3 -c "
from starboard.adapters.llm.openai.client import OpenAIProvider
from starboard.infra.core.config import get_config
provider = OpenAIProvider(cfg=get_config())
print('✓ OpenAI connected')
"
```

**Expected output**:
```
✓ Databricks connected: {'email': 'you@company.com', ...}
✓ OpenAI connected
```

---

## First Run

### Step 6: Start Development Servers

#### Option A: Start Everything (Recommended)

```bash
# Start both backend and frontend
make dev
```

**Services started**:
- Backend API: http://localhost:8000
- Frontend UI: http://localhost:3000
- API Docs: http://localhost:8000/docs

#### Option B: Start Individually

```bash
# Terminal 1: Backend only
make dev-server

# Terminal 2: Frontend only
make dev-frontend
```

### Step 7: Verify Services

**Backend Health Check**:
```bash
curl http://localhost:8000/health/ready
```

**Expected response**:
```json
{
  "status": "ready",
  "checks": {
    "database": {
      "healthy": true,
      "latency_ms": 1.2
    },
    "cache": {
      "healthy": true,
      "latency_ms": 0.5
    }
  }
}
```

Note: the `checks` object contains only the probes that are configured (database, cache, compute, ai, backpressure). A response with no configured probes returns `{"status": "ready", "checks": {}}`. When any probe is unhealthy the top-level `status` becomes `"degraded"`. The endpoint returns HTTP 200 in both cases; a `503` is only returned when the service itself has not yet initialised.

**Frontend**:
- Open http://localhost:3000
- Should see Starboard AI Agent interface

**API Documentation**:
- Open http://localhost:8000/docs
- Should see interactive Swagger UI

---

## Verify Installation

### Step 8: Run Tests

```bash
# Run all tests
make test

# Run only unit tests (fast)
make test-unit

# Run with coverage
make test-coverage
```

**Expected output**:
```
============= test session starts =============
collected 500+ items

tests/unit/agents/test_intent_router.py ........  [  2%]
tests/unit/tools/test_query_tools.py ...........  [  4%]
...
============= 500 passed in 45.23s =============
```

### Step 9: Try CLI

```bash
# Activate virtual environment
source .venv/bin/activate

# Run CLI
starboard --help
```

**Expected output**:
```
Usage: starboard [OPTIONS]

  Starboard AI Agent - Databricks workload analysis and optimization

Options:
  --goal TEXT         Your goal or question
  --mode TEXT         Mode: online, offline, diagnostic
  --verbose           Enable verbose output
  --help              Show this message and exit
```

**Try a simple query**:
```bash
starboard --goal "What agents are available?" --mode offline
```

### Step 10: Try API Call

```bash
# Create a conversation
curl -X POST http://localhost:8000/api/chat/conversations \
  -H "Content-Type: application/json" \
  -d '{"initial_message": "Hello, what can you help me with?"}'
```

**Expected response**:
```json
{
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
  "created_at": "2024-01-01T00:00:00Z",
  "status": "active"
}
```

---

## Your First Contribution

### Step 11: Make a Small Change

Let's add a simple tool to get familiar with the codebase.

**1. Create a new tool**:

```bash
# Create file
touch packages/starboard-server/starboard/tools/domain/example/hello.py
```

**2. Add domain logic**:

```python
# packages/starboard-server/starboard/tools/domain/example/hello.py
"""Example tool domain logic."""

def greet(name: str) -> str:
    """
    Greet a user by name.
    
    Args:
        name: User's name
    
    Returns:
        Greeting message
    
    Examples:
        >>> greet("Alice")
        "Hello, Alice! Welcome to Starboard."
    """
    return f"Hello, {name}! Welcome to Starboard."
```

**3. Add test**:

```bash
# Create test file
touch tests/unit/tools/domain/example/test_hello.py
```

```python
# tests/unit/tools/domain/example/test_hello.py
"""Tests for hello tool."""

from starboard.tools.domain.example.hello import greet


def test_greet():
    """Test greet function."""
    result = greet("Alice")
    assert result == "Hello, Alice! Welcome to Starboard."


def test_greet_different_name():
    """Test with different name."""
    result = greet("Bob")
    assert "Bob" in result
    assert "Welcome to Starboard" in result
```

**4. Run test**:

```bash
pytest tests/unit/tools/domain/example/test_hello.py -v
```

**Expected output**:
```
test_hello.py::test_greet PASSED
test_hello.py::test_greet_different_name PASSED

===== 2 passed in 0.05s =====
```

**5. Commit your change**:

```bash
git add packages/starboard-server/starboard/tools/domain/example/
git add tests/unit/tools/domain/example/
git commit -m "feat: Add example hello tool

- Add greet function in domain layer
- Add unit tests with 100% coverage
- Simple example for new contributors"
```

🎉 **Congratulations!** You've made your first contribution!

---

## Development Workflow

### Daily Development Cycle

```bash
# 1. Pull latest changes
git pull origin main

# 2. Create feature branch
git checkout -b feature/my-new-feature

# 3. Make changes
# ... edit files ...

# 4. Run checks locally
make check  # Runs lint, type-check, tests

# 5. Commit changes
git add .
git commit -m "feat: Add new feature"

# 6. Push to remote
git push origin feature/my-new-feature

# 7. Create Pull Request on GitHub
```

### Code Quality Checks

**Before committing**:

```bash
# Format code
make format

# Lint code
make lint

# Type check
make type-check

# Run tests
make test

# All checks at once
make check
```

### Running Specific Tests

```bash
# Single test file
pytest tests/unit/agents/test_intent_router.py -v

# Single test function
pytest tests/unit/agents/test_intent_router.py::test_classify_query -v

# Tests matching pattern
pytest -k "test_agent" -v

# With coverage
pytest --cov=starboard tests/unit/
```

### Hot Reloading

**Backend**: Auto-reloads on file changes (FastAPI)  
**Frontend**: Auto-reloads on file changes (Next.js)  
**Docs**: Auto-reloads on file changes (MkDocs)

Just save your files and see changes immediately!

---

## Next Steps

### Learn the Architecture

1. **Read System Architecture**
   - [System Overview](../architecture/SYSTEM_ARCHITECTURE.md)
   - Understand multi-agent system
   - Learn tool architecture

2. **Explore Packages**
   - [Package Integration](../integration/PACKAGE_INTEGRATION.md)
   - See how packages work together
   - Understand dependencies

3. **Study Tools**
   - [Tool Catalog](../tools/TOOL_CATALOG.md)
   - See 31 existing tools
   - Learn tool patterns

### Common Tasks

Ready to contribute? Check out:

- **[Common Tasks Guide](./COMMON_TASKS.md)** - Detailed how-tos
- **[Tool Development Guide](../tools/TOOL_DEVELOPMENT_GUIDE.md)** - Build tools
- **[API Reference](../api/API_REFERENCE.md)** - API endpoints

### Get Help

**Documentation**:
- [Quick Reference](../QUICK_REFERENCE.md) - Fast lookup
- [Runbook](../RUNBOOK.md) - Operational procedures
- [FAQ](./FAQ.md) - Frequently asked questions

**Community**:
- GitHub Issues - Report bugs
- GitHub Discussions - Ask questions

---

## Common Issues

### Issue: `uv not found`

**Solution**:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc  # or ~/.zshrc
```

### Issue: `Module not found` errors

**Solution**:
```bash
# Reinstall workspace packages
cd /path/to/project
uv sync

# Or use make
make setup
```

### Issue: Backend won't start

**Solution**:
```bash
# Check .env file exists
ls -la .env

# Verify credentials
python3 -c "from starboard.infra.core.config import get_config; print(get_config())"

# Check port not in use
lsof -i :8000
```

### Issue: Tests failing

**Solution**:
```bash
# Clean and reinstall
make clean
make setup

# Verify test database
ls -la dev_data/

# Run tests with verbose output
pytest -v -s
```

### Issue: Frontend build errors

**Solution**:
```bash
cd frontend

# Clean node_modules
rm -rf node_modules package-lock.json

# Reinstall
npm install

# Try build
npm run build
```

---

## Cheat Sheet

### Essential Commands

```bash
# Setup
make setup              # First-time setup

# Development
make dev                # Start all services
make dev-server         # Backend only
make dev-frontend       # Frontend only

# Code Quality
make format             # Auto-format
make lint               # Lint
make type-check         # Type check
make check              # All checks

# Testing
make test               # All tests
make test-unit          # Unit tests
make test-coverage      # With coverage

# Documentation
make docs-serve         # Preview docs
make diagrams           # Generate diagrams

# Cleanup
make clean              # Clean build artifacts
```

### File Locations

```
packages/starboard-server/  - Multi-agent system
packages/starboard-core/    - Domain models
packages/starboard-cli/     - CLI tool
frontend/                   - Web UI
docs/                       - Documentation
tests/                      - Test suite
.env                        - Your credentials (gitignored)
```

### Quick Links

- Backend: http://localhost:8000
- Frontend: http://localhost:3000
- API Docs: http://localhost:8000/docs
- Documentation: http://localhost:8000 (after `make docs-serve`)

---

## Summary Checklist

Before you start contributing, make sure you have:

- [ ] Installed all prerequisites (Python, uv, Node.js)
- [ ] Cloned repository
- [ ] Run `make setup` successfully
- [ ] Created `.env` with credentials
- [ ] Started dev servers (`make dev`)
- [ ] Verified backend health check
- [ ] Accessed frontend UI
- [ ] Run tests successfully (`make test`)
- [ ] Made first small change
- [ ] Read system architecture docs

**Ready to contribute?** Check out [Common Tasks Guide](./COMMON_TASKS.md)!

---

**Last Updated**: 2025-12-02  
**Version**: 1.0

