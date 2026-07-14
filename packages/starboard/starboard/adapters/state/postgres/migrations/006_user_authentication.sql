-- User authentication and session management
-- Migration: 006_user_authentication
-- Description: Create users and user_sessions tables for authentication
-- Requires: None (independent tables)
-- Run: psql $DATABASE_URL -f 006_user_authentication.sql

-- ============================================================================
-- Users Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    external_id TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'databricks',
    username TEXT NOT NULL,
    display_name TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_login TIMESTAMP,
    login_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    metadata JSONB
);

-- Unique constraint on provider + external_id
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_provider_external 
    ON users(provider, external_id);

-- Unique constraint on username
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username 
    ON users(username);

-- Index for status queries
CREATE INDEX IF NOT EXISTS idx_users_status 
    ON users(status) WHERE status = 'active';

-- Index for recent logins
CREATE INDEX IF NOT EXISTS idx_users_last_login 
    ON users(last_login DESC) WHERE last_login IS NOT NULL;

-- Comments on users table
COMMENT ON TABLE users IS 'Authenticated user accounts';
COMMENT ON COLUMN users.id IS 'Internal user ID (UUID)';
COMMENT ON COLUMN users.external_id IS 'Provider-specific user ID (e.g., Databricks user ID)';
COMMENT ON COLUMN users.provider IS 'Authentication provider (databricks, oauth, etc.)';
COMMENT ON COLUMN users.username IS 'Username or email address';
COMMENT ON COLUMN users.display_name IS 'Human-readable name';
COMMENT ON COLUMN users.created_at IS 'Account creation timestamp';
COMMENT ON COLUMN users.last_login IS 'Last successful login timestamp';
COMMENT ON COLUMN users.login_count IS 'Total number of successful logins';
COMMENT ON COLUMN users.status IS 'Account status (active, disabled, deleted)';
COMMENT ON COLUMN users.metadata IS 'Provider-specific metadata (JSONB)';

-- ============================================================================
-- User Sessions Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_activity TIMESTAMP NOT NULL DEFAULT NOW(),
    source TEXT NOT NULL,  -- 'web', 'cli', 'api'
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    context JSONB
);

-- Index for user's active sessions
CREATE INDEX IF NOT EXISTS idx_sessions_user_active 
    ON user_sessions(user_id, is_active) WHERE is_active = TRUE;

-- Index for session cleanup (find stale sessions)
CREATE INDEX IF NOT EXISTS idx_sessions_last_activity 
    ON user_sessions(last_activity) WHERE is_active = TRUE;

-- Index for source tracking
CREATE INDEX IF NOT EXISTS idx_sessions_source 
    ON user_sessions(source);

-- Comments on user_sessions table
COMMENT ON TABLE user_sessions IS 'User session tracking';
COMMENT ON COLUMN user_sessions.session_id IS 'Unique session identifier';
COMMENT ON COLUMN user_sessions.user_id IS 'User ID (foreign key to users table)';
COMMENT ON COLUMN user_sessions.started_at IS 'Session start timestamp';
COMMENT ON COLUMN user_sessions.last_activity IS 'Last activity timestamp';
COMMENT ON COLUMN user_sessions.source IS 'Session source (web, cli, api)';
COMMENT ON COLUMN user_sessions.is_active IS 'Whether session is currently active';
COMMENT ON COLUMN user_sessions.context IS 'Session metadata (IP, user agent, etc.)';

-- ============================================================================
-- Update Existing Conversations Table
-- ============================================================================
-- Note: conversations.user_id already exists, but we'll add a comment for clarity
-- and optionally add a foreign key constraint if needed

COMMENT ON COLUMN conversations.user_id IS 'User ID (now references users table)';

-- Optional: Add foreign key constraint to link conversations to users
-- Uncomment if you want to enforce referential integrity
-- ALTER TABLE conversations
--     DROP CONSTRAINT IF EXISTS fk_conversations_user,
--     ADD CONSTRAINT fk_conversations_user 
--     FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- ============================================================================
-- Migration Verification
-- ============================================================================
-- Verify tables were created
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users') THEN
        RAISE EXCEPTION 'Migration failed: users table not created';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'user_sessions') THEN
        RAISE EXCEPTION 'Migration failed: user_sessions table not created';
    END IF;
    
    RAISE NOTICE 'Migration 006_user_authentication completed successfully';
END $$;

