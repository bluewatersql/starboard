-- Initial schema for conversations
-- Migration: 001_initial
-- Description: Create conversations table for state management
-- Requires: None
-- Run: psql $DATABASE_URL -f 001_initial.sql

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    data JSONB NOT NULL,  -- Stores messages and additional metadata
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    title TEXT,
    tags TEXT[],
    archived BOOLEAN DEFAULT FALSE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_conversations_user_id 
    ON conversations(user_id);

CREATE INDEX IF NOT EXISTS idx_conversations_updated_at 
    ON conversations(updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_conversations_user_updated 
    ON conversations(user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_conversations_tags 
    ON conversations USING GIN(tags);

-- JSONB index for message search (optional, for advanced queries)
CREATE INDEX IF NOT EXISTS idx_conversations_data 
    ON conversations USING GIN(data);

-- Comments
COMMENT ON TABLE conversations IS 'Conversation state with messages';
COMMENT ON COLUMN conversations.data IS 'JSONB containing messages array and metadata';
COMMENT ON COLUMN conversations.tags IS 'User-defined tags for categorization';
COMMENT ON COLUMN conversations.archived IS 'Soft delete flag';

