# API Contract Testing

**Purpose**: Ensure frontend and backend API contracts remain compatible  
**Status**: ✅ Active  
**Owner**: Platform Team

---

## Overview

Contract tests validate that the backend API (FastAPI + Pydantic) and frontend types (TypeScript + Zod) remain synchronized and backward compatible.

```
Backend (Python/Pydantic)  ←→  JSON Schema  ←→  Frontend (TypeScript/Zod)
```

### Why Contract Testing?

- ✅ **Catch breaking changes early** - Before they reach production
- ✅ **Faster feedback** - Quick validation without full integration tests
- ✅ **Documentation** - Schemas serve as API documentation
- ✅ **Type safety** - Ensures frontend/backend type alignment

---

## Quick Start

### 1. Export Schemas

```bash
# Export Pydantic models to JSON Schema
python scripts/export_api_schemas.py

# Output: tests/contract/schemas/*.json
```

### 2. Run Backend Contract Tests

```bash
# Run all contract tests
pytest tests/contract/ -v

# Run specific test
pytest tests/contract/test_api_schemas.py::TestMessageRequest -v

# With coverage
pytest tests/contract/ --cov=starboard_server.api.models
```

### 3. Run Frontend Contract Tests

```bash
cd frontend

# Run contract tests
npm run test:contract

# Watch mode
npm run test:contract -- --watch

# With coverage
npm run test:coverage -- lib/validation/__tests__/api-contract.test.ts
```

---

## Directory Structure

```
tests/contract/
├── README.md                          # This file
├── schemas/                           # Exported JSON schemas
│   ├── ConversationCreateRequest.json
│   ├── ConversationResponse.json
│   ├── MessageRequest.json
│   ├── MessageResponse.json
│   ├── FeedbackRequest.json
│   ├── ChatEvent.json
│   └── NextStepOption.json
├── test_api_schemas.py                # Backend contract tests
└── __init__.py

frontend/lib/validation/__tests__/
└── api-contract.test.ts               # Frontend contract tests
```

---

## What We Test

### Backend Tests (`test_api_schemas.py`)

1. **Schema Export Validation**
   - All required schemas are exported
   - JSON Schema structure is valid
   - Schemas include proper metadata

2. **Request/Response Validation**
   - Required fields are enforced
   - Optional fields work correctly
   - Extra fields are rejected
   - Type validation works

3. **Backward Compatibility**
   - Existing fields remain required/optional
   - Serialization roundtrip preserves data
   - Validation errors are clear

4. **Documentation**
   - Schemas include descriptions
   - Error messages are helpful

### Frontend Tests (`api-contract.test.ts`)

1. **Type Matching**
   - TypeScript types match Zod schemas
   - Zod schemas match backend contracts

2. **Request Validation**
   - Valid requests pass
   - Invalid requests fail with clear errors
   - Optional fields work correctly

3. **Response Handling**
   - Response schemas validate correctly
   - Metadata is preserved
   - Enums are validated

4. **Backward Compatibility**
   - Existing code continues to work
   - New optional fields don't break
   - Unknown fields are handled gracefully

---

## Contract Test Examples

### Backend Example

```python
def test_message_request_contract():
    """Test MessageRequest matches frontend expectations."""
    # Valid request
    request = MessageRequest(
        content="Show me cost trends",
        user_id="user_123",
    )
    assert request.content == "Show me cost trends"
    
    # Invalid request
    with pytest.raises(ValidationError):
        MessageRequest(content="Test")  # Missing user_id
```

### Frontend Example

```typescript
test('should validate MessageRequest', () => {
  const data: SendMessageRequest = {
    content: 'Show me cost trends',
    user_id: 'user_123',
  };

  const result = MessageRequestSchema.safeParse(data);
  expect(result.success).toBe(true);
});
```

---

## CI/CD Integration

### Pre-Commit Hook

```bash
# .git/hooks/pre-commit
#!/bin/bash
python scripts/export_api_schemas.py
git add tests/contract/schemas/
pytest tests/contract/ -q
```

### GitHub Actions

```yaml
# .github/workflows/contract-tests.yml
name: Contract Tests

on: [pull_request]

jobs:
  contract-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      
      - name: Install dependencies
        run: pip install -e packages/starboard-server[test]
      
      - name: Export schemas
        run: python scripts/export_api_schemas.py
      
      - name: Run backend contract tests
        run: pytest tests/contract/ -v
      
      - name: Setup Node
        uses: actions/setup-node@v3
        with:
          node-version: '20'
      
      - name: Install frontend dependencies
        run: cd frontend && npm ci
      
      - name: Run frontend contract tests
        run: cd frontend && npm run test:contract
```

---

## Workflow

### Making API Changes

1. **Update Pydantic Model**
   ```python
   # starboard_server/api/models.py
   class MessageRequest(BaseModel):
       content: str
       user_id: str
       new_field: str | None = None  # Add new optional field
   ```

2. **Export Schemas**
   ```bash
   python scripts/export_api_schemas.py
   ```

3. **Update Backend Tests**
   ```python
   def test_new_field_optional():
       request = MessageRequest(content="Test", user_id="user_123")
       assert request.new_field is None
   ```

4. **Update Frontend Types**
   ```typescript
   // frontend/lib/types/api.ts
   export interface SendMessageRequest {
     content: string;
     user_id: string;
     new_field?: string;  // Add new optional field
   }
   ```

5. **Update Frontend Tests**
   ```typescript
   test('should allow new_field', () => {
     const data = {
       content: 'Test',
       user_id: 'user_123',
       new_field: 'value',
     };
     expect(MessageRequestSchema.safeParse(data).success).toBe(true);
   });
   ```

6. **Run All Contract Tests**
   ```bash
   pytest tests/contract/ -v
   cd frontend && npm run test:contract
   ```

---

## Best Practices

### ✅ DO

- **Add tests for new fields** - Both backend and frontend
- **Test backward compatibility** - Ensure old code still works
- **Export schemas after changes** - Keep schemas synchronized
- **Run contract tests in CI** - Catch breaks early
- **Document breaking changes** - In PR description
- **Use semantic versioning** - For API versions

### ❌ DON'T

- **Don't change required fields** - Without migration plan
- **Don't remove fields** - Without deprecation period
- **Don't skip schema export** - After model changes
- **Don't ignore test failures** - Fix or discuss first
- **Don't change types** - Of existing fields (breaking change)

---

## Troubleshooting

### Schema Export Fails

```bash
# Check imports
python -c "from starboard_server.api.models import MessageRequest"

# Run with verbose output
python scripts/export_api_schemas.py -v
```

### Backend Tests Fail

```bash
# Check installed packages
pip list | grep starboard

# Reinstall in editable mode
pip install -e packages/starboard-server[test]

# Run single test with verbose
pytest tests/contract/test_api_schemas.py::TestMessageRequest::test_valid_request -vv
```

### Frontend Tests Fail

```bash
# Clear Jest cache
cd frontend
npm run test:contract -- --clearCache

# Check TypeScript compilation
npx tsc --noEmit

# Run single test
npm run test:contract -- --testNamePattern="MessageRequest"
```

### Schema Mismatch

If backend and frontend schemas don't match:

1. Re-export schemas: `python scripts/export_api_schemas.py`
2. Compare schemas: `diff tests/contract/schemas/MessageRequest.json ...`
3. Update frontend types to match
4. Re-run both test suites

---

## Metrics

Track contract test health:

- **Schema Coverage**: % of API models with contract tests
- **Test Pass Rate**: % of contract tests passing
- **Breaking Changes**: # of detected breaking changes per month
- **Time to Fix**: Time from detection to resolution

---

## Future Enhancements

- [ ] Auto-generate TypeScript types from JSON Schema
- [ ] OpenAPI spec generation from Pydantic models
- [ ] Contract test coverage reporting
- [ ] Automated PR comments on schema changes
- [ ] Contract versioning and migration tools

---

**Last Updated**: 2025-11-28  
**Version**: 1.0.0  
**Related**: [Testing Guide](../../docs/TESTING.md), [API Reference](../../docs/API_REFERENCE.md)

