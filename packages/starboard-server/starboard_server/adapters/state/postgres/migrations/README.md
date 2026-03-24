# PostgreSQL Migrations

## Available Migrations

| Migration | Description | Status |
|-----------|-------------|--------|
| 001_initial | Conversations table | ✅ Applied |
| 002_memory | Memory system tables | ✅ Applied |
| 003_indexes | Performance indexes | ✅ Applied |
| 004_conversation_patterns | Conversation patterns | ✅ Applied |
| 005_clarification_pattern | Clarification support | ✅ Applied |
| 006_user_authentication | User auth tables | 🆕 New |

## Migration 006: User Authentication

**Created**: 2025-11-29  
**Status**: Ready to apply

### What It Does

Creates two new tables for user authentication:
1. `users` - Authenticated user accounts
2. `user_sessions` - User session tracking

### Tables Created

#### `users`
- Stores authenticated user accounts
- Supports multiple auth providers (databricks, oauth, etc.)
- Tracks login activity and status
- Includes provider-specific metadata (JSONB)

#### `user_sessions`
- Tracks active user sessions
- Links to users table via foreign key
- Supports session expiration and cleanup
- Stores session context (IP, user agent, etc.)

### Backward Compatibility

- Creates a "default-user" system account
- Existing conversations with `user_id='default-user'` will work
- No breaking changes to existing tables

### How to Apply

```bash
# Using psql
psql $DATABASE_URL -f 006_user_authentication.sql

# Or using migration runner (if available)
./run_migration_006.sh
```

### Verification

After running, verify tables exist:

```sql
-- Check users table
SELECT COUNT(*) FROM users;
-- Should show at least 1 (default-user)

-- Check user_sessions table
SELECT COUNT(*) FROM user_sessions;
-- Should show 0 initially

-- Verify default user
SELECT id, username, provider FROM users WHERE id = 'default-user';
-- Should return: default-user | default@system.local | system
```

### Rollback (if needed)

```sql
-- WARNING: This will delete all user data
DROP TABLE IF EXISTS user_sessions CASCADE;
DROP TABLE IF EXISTS users CASCADE;
```

### Dependencies

- None (tables are independent)
- Foreign key to `users(id)` from `user_sessions`
- Optional foreign key from `conversations.user_id` to `users(id)` (commented out by default)

### Notes

- Users table uses `TEXT` for ID (UUID as string)
- Timestamps use PostgreSQL `TIMESTAMP` type
- Metadata stored as `JSONB` for efficient querying
- Indexes optimized for common query patterns
- Default user created for backward compatibility
