-- Additional indexes for performance
-- Migration: 003_indexes
-- Description: Performance and query optimization indexes
-- Requires: 001_initial, 002_memory
-- Run: psql $DATABASE_URL -f 003_indexes.sql

-- Composite index for conversation listing with filters
CREATE INDEX IF NOT EXISTS idx_conversations_user_archived_updated 
    ON conversations(user_id, archived, updated_at DESC);

-- Full-text search index on conversation data (optional)
-- Enables fast text search across all messages
CREATE INDEX IF NOT EXISTS idx_conversations_fts 
    ON conversations USING GIN(to_tsvector('english', data::text));

-- Partial index for active conversations only
-- Significantly faster for queries filtering archived = false
CREATE INDEX IF NOT EXISTS idx_conversations_active 
    ON conversations(user_id, updated_at DESC) 
    WHERE archived = false;

-- Partial index for recent episodes (last 30 days)
-- Optimizes queries for recent memory recall
CREATE INDEX IF NOT EXISTS idx_episodes_recent 
    ON episodes(user_id, created_at DESC)
    WHERE created_at > NOW() - INTERVAL '30 days';

-- Composite index for fact queries with category and confidence
CREATE INDEX IF NOT EXISTS idx_facts_user_category_confidence 
    ON facts(user_id, category, confidence DESC)
    WHERE verified = true;

-- Partial index for high-confidence facts
CREATE INDEX IF NOT EXISTS idx_facts_high_confidence 
    ON facts(user_id, category)
    WHERE confidence >= 0.8 AND verified = true;

-- Comments
COMMENT ON INDEX idx_conversations_active IS 'Optimized for listing active conversations';
COMMENT ON INDEX idx_conversations_fts IS 'Full-text search across message content';
COMMENT ON INDEX idx_episodes_recent IS 'Fast access to recent episodic memories';
COMMENT ON INDEX idx_facts_high_confidence IS 'Quick lookup of verified, high-confidence facts';

