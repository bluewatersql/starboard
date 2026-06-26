# Contributing Guide

**Version**: 1.0  
**Last Updated**: 2025-12-02  
**Welcome Contributors!** 🎉

---

## Table of Contents

1. [Welcome](#welcome)
2. [Code of Conduct](#code-of-conduct)
3. [How to Contribute](#how-to-contribute)
4. [Development Workflow](#development-workflow)
5. [Code Standards](#code-standards)
6. [Testing Requirements](#testing-requirements)
7. [Documentation](#documentation)
8. [Pull Request Process](#pull-request-process)
9. [Review Process](#review-process)
10. [Getting Help](#getting-help)

---

## Welcome

Thank you for considering contributing to Starboard AI Agent! Whether you're fixing a bug, adding a feature, improving documentation, or suggesting improvements, your contribution is valued.

### Types of Contributions

We welcome all types of contributions:

**Code**:
- 🐛 Bug fixes
- ✨ New features
- 🛠️ New tools
- 🤖 New agents
- ⚡ Performance improvements

**Documentation**:
- 📝 Documentation improvements
- 📖 Tutorial writing
- 🎨 Diagram creation
- 🌐 Translation

**Community**:
- 🐛 Bug reports
- 💡 Feature requests
- ❓ Answering questions
- 👀 Code reviews

---

## Code of Conduct

### Our Pledge

We are committed to providing a welcoming and inclusive environment for all contributors, regardless of:
- Experience level
- Gender identity and expression
- Sexual orientation
- Disability
- Personal appearance
- Body size
- Race or ethnicity
- Age
- Religion
- Nationality

### Our Standards

**Positive behaviors**:
- Using welcoming and inclusive language
- Being respectful of differing viewpoints
- Gracefully accepting constructive criticism
- Focusing on what is best for the community
- Showing empathy towards other contributors

**Unacceptable behaviors**:
- Trolling, insulting/derogatory comments
- Public or private harassment
- Publishing others' private information
- Other conduct which could reasonably be considered inappropriate

### Enforcement

Violations of the Code of Conduct may be reported to the project team. All complaints will be reviewed and investigated.

---

## How to Contribute

### First-Time Contributors

1. **Start small**: Look for issues labeled `good-first-issue`
2. **Read documentation**: Familiarize yourself with the [system architecture](../architecture/SYSTEM_ARCHITECTURE.md)
3. **Set up environment**: Follow the [Getting Started Guide](./GETTING_STARTED.md)
4. **Join discussions**: Introduce yourself in GitHub Discussions

### Finding Work

**Good first issues**:
- Label: `good-first-issue`
- Small, well-defined tasks
- Clear acceptance criteria

**Help wanted**:
- Label: `help-wanted`
- Important issues needing contributors
- May require more experience

**Feature requests**:
- Label: `enhancement`
- New functionality or improvements
- May require design discussion first

### Claiming an Issue

1. Comment on the issue: "I'd like to work on this"
2. Wait for acknowledgment from maintainer
3. Start working (aim to submit PR within 2 weeks)
4. If you can't complete it, let us know - no problem!

---

## Development Workflow

### Step 1: Fork and Clone

```bash
# Fork repository on GitHub (click Fork button)

# Clone your fork
git clone https://github.com/YOUR_USERNAME/job-agent.git
cd job-agent

# Add upstream remote
git remote add upstream https://github.com/<your-org>/job-agent.git

# Verify remotes
git remote -v
```

### Step 2: Create Branch

```bash
# Sync with upstream
git checkout main
git pull upstream main

# Create feature branch
git checkout -b feature/your-feature-name

# Branch naming:
# - feature/* for new features
# - fix/* for bug fixes
# - docs/* for documentation
# - test/* for test improvements
```

### Step 3: Set Up Environment

```bash
# First-time setup
make setup

# Copy and configure .env
cp examples/env.example .env
# Edit .env with your credentials
```

### Step 4: Make Changes

```bash
# Make your changes
# ... edit files ...

# Run checks frequently
make lint       # Lint code
make type-check # Type check
make test-unit  # Fast unit tests

# Format before committing
make format
```

### Step 5: Write Tests

**Required**: All code changes must include tests

```bash
# Unit tests (for domain logic)
# Location: tests/unit/
# Coverage: 100% for domain, 80%+ for service

# Integration tests (for external I/O)
# Location: tests/integration/
# Coverage: 80%+

# Run tests
make test

# Check coverage
make test-coverage
```

See [Testing Guide](../TESTING.md) for details.

### Step 6: Update Documentation

**Required if you**:
- Add new tool → Update [Tool Catalog](../tools/TOOL_CATALOG.md)
- Add new agent → Update [System Architecture](../architecture/SYSTEM_ARCHITECTURE.md)
- Add new API → Update [API Reference](../api/API_REFERENCE.md)
- Change prompts → Update golden tests
- Add new diagram → Regenerate: `make diagrams`

### Step 7: Commit Changes

```bash
# Add files
git add .

# Commit with conventional commit message
git commit -m "feat: Add cost analysis tool

- Add domain logic for cost analysis
- Add service with Databricks integration
- Add adapter interface
- Add comprehensive tests (100% coverage)
- Update tool catalog documentation

Closes #123"
```

### Commit Message Format

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Types**:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `test`: Adding/updating tests
- `refactor`: Code change without feature/fix
- `perf`: Performance improvement
- `chore`: Maintenance tasks
- `ci`: CI/CD changes

**Examples**:
```
feat(tools): Add analyze_cluster_costs tool
fix(agents): Fix infinite loop in QueryAgent
docs(api): Update API reference with new endpoints
test(tools): Add integration tests for cost service
refactor(tools): Extract common tool logic to base class
perf(agents): Cache tool results to reduce LLM calls
```

### Step 8: Push and Create PR

```bash
# Push to your fork
git push origin feature/your-feature-name

# Go to GitHub and create Pull Request
# Fill out the PR template
```

---

## Code Standards

### Python Code Style

**We enforce**:
- PEP 8 via Ruff (88 char lines)
- Import sorting via Ruff
- Type hints on all public functions
- Google-style docstrings

**Example**:
```python
from typing import Any


async def analyze_costs(
    start_date: str,
    end_date: str,
    threshold: float = 0.1,
) -> dict[str, Any]:
    """
    Analyze cluster costs for date range.
    
    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        threshold: Threshold for high consumers (default: 0.1)
    
    Returns:
        Dictionary with cost analysis:
            - total_cost: Total cost for period
            - top_consumers: List of top consumers
            - recommendations: Optimization suggestions
    
    Raises:
        ValueError: If date format invalid
        ToolExecutionError: If API call fails
    
    Examples:
        >>> result = await analyze_costs("2024-01-01", "2024-01-31")
        >>> result["total_cost"]
        12345.67
    """
    # Implementation
    ...
```

### Architecture Principles

**Must follow**:
1. **Three-layer architecture**: Domain → Service → Adapter
2. **Pure domain logic**: No I/O in domain layer
3. **Immutable data**: Use `dataclass(frozen=True)`
4. **Explicit errors**: Specific exception types
5. **Dependency injection**: No globals

**Example**:
```python
# Domain (pure logic)
@dataclass(frozen=True)
class CostAnalysis:
    total_cost: float
    recommendations: list[str]

def analyze_costs(records: list[dict]) -> CostAnalysis:
    """Pure function - no I/O."""
    ...

# Service (orchestration + I/O)
class CostService:
    def __init__(self, api: DatabricksAPI):
        self.api = api
    
    async def analyze(self, ...) -> CostAnalysis:
        data = await self.api.fetch_data()  # I/O
        return analyze_costs(data)  # Pure logic

# Adapter (LLM interface)
class CostTools:
    def __init__(self, api: DatabricksAPI):
        self.service = CostService(api)
    
    async def analyze_cluster_costs(self, ...) -> dict[str, Any]:
        result = await self.service.analyze(...)
        return {"total_cost": result.total_cost, ...}  # Dict for LLM
```

### Type Hints

**Required on**:
- All public functions
- All public methods
- All public classes

**Example**:
```python
# Good ✓
def process(data: dict[str, Any]) -> list[str]:
    ...

async def fetch(id: str) -> dict[str, Any] | None:
    ...

# Bad ✗
def process(data):  # No type hints
    ...

def fetch(id):  # No type hints
    ...
```

### Error Handling

**Use specific exceptions**:
```python
# Good ✓
from starboard_server.tools.exceptions import (
    ToolExecutionError,
    ResourceNotFoundError,
)

if not resource_exists:
    raise ResourceNotFoundError(f"Resource {id} not found")

# Bad ✗
if not resource_exists:
    raise Exception("Not found")  # Too generic
```

### Logging

**Use structured logging**:
```python
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)

# Good ✓
logger.info(
    "tool_execution_complete",
    tool_name="analyze_costs",
    duration_ms=123,
    success=True,
)

# Bad ✗
logger.info("Tool done")  # Not structured
```

---

## Testing Requirements

### Coverage Targets

| Layer | Target |
|-------|--------|
| Domain logic | 100% |
| Service layer | 80%+ |
| Adapter layer | 80%+ |
| Agent policies | 100% |
| Schema validators | 100% |

### Test Types

**Unit Tests** (required):
- Fast (< 0.1s each)
- No external dependencies
- Mock all I/O

**Integration Tests** (recommended):
- Test external integrations
- May be slower
- Use real or mocked services

**Golden Tests** (for prompts):
- Snapshot LLM prompts
- Catch unintended changes
- Update with `--update-snapshots`

### Test Structure

```python
# tests/unit/tools/domain/test_cost_analyzer.py

def test_analyze_costs_basic():
    """Test basic cost analysis."""
    # Arrange
    records = [{"resource": "cluster-1", "cost": 100}]
    
    # Act
    result = analyze_costs(records)
    
    # Assert
    assert result.total_cost == 100
    assert len(result.recommendations) > 0


@pytest.mark.parametrize("cost,expected_recommendations", [
    (100, 1),
    (50, 0),
])
def test_analyze_costs_thresholds(cost, expected_recommendations):
    """Test various thresholds."""
    records = [{"resource": "test", "cost": cost}]
    result = analyze_costs(records, threshold=0.5)
    assert len(result.recommendations) == expected_recommendations
```

### Running Tests

```bash
# All tests
make test

# Unit only (fast)
make test-unit

# With coverage
make test-coverage

# Specific file
pytest tests/unit/path/to/test_file.py -v

# Specific function
pytest tests/unit/path/to/test_file.py::test_function -v
```

---

## Documentation

### When to Update Documentation

**Always update** when you:
- Add new tool → [Tool Catalog](../tools/TOOL_CATALOG.md)
- Add new agent → [System Architecture](../architecture/SYSTEM_ARCHITECTURE.md)
- Add new API → [API Reference](../api/API_REFERENCE.md)
- Add new package → [Package Integration](../integration/PACKAGE_INTEGRATION.md)
- Change architecture → Update relevant docs + diagrams

### Documentation Standards

**Code documentation**:
- Google-style docstrings
- Type hints
- Examples in docstrings

**Markdown documentation**:
- Clear headings
- Code examples
- Cross-references to related docs

**Diagrams**:
- Mermaid (.mmd files)
- Source in `docs/diagrams/source/`
- Generate with `make diagrams`

### Testing Documentation

```bash
# Preview documentation locally
make docs-serve

# Open http://localhost:8000

# Generate diagrams
make diagrams

# Build static site
make docs-build
```

---

## Pull Request Process

### Before Creating PR

**Checklist**:
- [ ] Code follows style guide
- [ ] All tests pass (`make test`)
- [ ] Coverage targets met
- [ ] Type checking passes (`make type-check`)
- [ ] Linting passes (`make lint`)
- [ ] Documentation updated
- [ ] Commit messages follow convention
- [ ] Branch is up to date with main

### Creating PR

1. **Push to your fork**
2. **Create PR on GitHub**
3. **Fill out PR template completely**
4. **Link related issues** (Fixes #123, Relates to #456)
5. **Request reviewers** (optional, maintainers will assign)

### PR Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Changes Made
- Bullet list of changes

## Testing
How was this tested?

## Checklist
- [ ] Tests added/updated
- [ ] Documentation updated
- [ ] All tests pass
- [ ] Lint/type checks pass
- [ ] Commit messages follow convention
```

### PR Title

Use conventional commit format:
```
feat(tools): Add cost analysis tool
fix(agents): Fix infinite loop in QueryAgent
docs: Update API reference
```

---

## Review Process

### What to Expect

1. **Automated checks** run (tests, lint, type check)
2. **Maintainer review** within 2-3 days
3. **Feedback** or approval
4. **Iteration** if changes requested
5. **Merge** when approved

### Responding to Feedback

- Be receptive to feedback
- Ask questions if unclear
- Make requested changes
- Mark conversations as resolved
- Be patient and respectful

### Review Criteria

Reviewers check for:
- **Correctness**: Does it work?
- **Tests**: Adequate coverage?
- **Style**: Follows conventions?
- **Documentation**: Updated?
- **Design**: Fits architecture?
- **Performance**: Efficient?

---

## Getting Help

### Where to Ask

**Before coding**:
- GitHub Discussions: Design questions
- GitHub Issues: Clarify requirements

**During development**:
- GitHub Discussions: Technical help
- Documentation: Check guides first

**PR feedback**:
- PR comments: Ask for clarification
- GitHub Discussions: Broader questions

### Response Times

- **Issue comments**: 1-2 days
- **PR reviews**: 2-3 days
- **Discussions**: 1-3 days

Please be patient! This is a community project.

---

## Recognition

### Contributors

All contributors are recognized:
- Listed in the [GitHub contributors graph](https://github.com/starboard-ai/job-agent/graphs/contributors)
- Mentioned in release notes
- GitHub contributor badge

### Significant Contributions

Major contributions may receive:
- Maintainer status
- Write access to repository
- Special recognition

---

## Release Process

### Versioning

We follow [Semantic Versioning](https://semver.org/):
- MAJOR: Breaking changes
- MINOR: New features (backward compatible)
- PATCH: Bug fixes

### Release Cycle

- **Patch releases**: As needed for bugs
- **Minor releases**: Monthly
- **Major releases**: When needed

---

## Additional Resources

- **[Getting Started Guide](./GETTING_STARTED.md)** - Setup instructions
- **[Common Tasks Guide](./COMMON_TASKS.md)** - How-to guides
- **[Runbook](../RUNBOOK.md)** - Operational procedures
- **[Tool Development Guide](../tools/TOOL_DEVELOPMENT_GUIDE.md)** - Build tools
- **[System Architecture](../architecture/SYSTEM_ARCHITECTURE.md)** - Understand design

---

## Thank You! 🙏

Your contributions make this project better for everyone. Whether you're fixing a typo or adding a major feature, thank you for taking the time to contribute!

**Questions?** Ask in [GitHub Discussions](https://github.com/starboard-ai/job-agent/discussions)

---

**Last Updated**: 2025-12-02  
**Version**: 1.0

