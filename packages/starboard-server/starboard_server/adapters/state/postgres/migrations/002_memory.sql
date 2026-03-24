-- Schema for long-term memory
-- Migration: 002_memory
-- Description: Create tables for episodic, semantic, and profile memory
-- Requires: pgvector extension, 001_initial
-- Run: psql $DATABASE_URL -f 002_memory.sql

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Episodic memory (conversation summaries)
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    conversation_id TEXT,
    summary TEXT NOT NULL,
    key_points TEXT[],
    embedding vector(1536),  -- OpenAI ada-002 embedding dimensions
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    metadata JSONB
);

-- Indexes for episodic memory
CREATE INDEX IF NOT EXISTS idx_episodes_user_id 
    ON episodes(user_id);

CREATE INDEX IF NOT EXISTS idx_episodes_created_at 
    ON episodes(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_episodes_conversation_id 
    ON episodes(conversation_id);

-- Vector similarity index (IVFFlat for large datasets, HNSW for smaller)
-- Using IVFFlat with 100 lists (good for 10K-1M vectors)
CREATE INDEX IF NOT EXISTS idx_episodes_embedding 
    ON episodes USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Semantic memory (extracted facts)
CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    statement TEXT NOT NULL,
    category TEXT NOT NULL,  -- e.g., "job_preference", "technical_skill"
    confidence FLOAT NOT NULL DEFAULT 1.0,
    source TEXT,  -- e.g., "conversation:abc123"
    verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    metadata JSONB
);

-- Indexes for semantic memory
CREATE INDEX IF NOT EXISTS idx_facts_user_id 
    ON facts(user_id);

CREATE INDEX IF NOT EXISTS idx_facts_category 
    ON facts(category);

CREATE INDEX IF NOT EXISTS idx_facts_confidence 
    ON facts(confidence DESC);

CREATE INDEX IF NOT EXISTS idx_facts_user_category 
    ON facts(user_id, category);

CREATE INDEX IF NOT EXISTS idx_facts_verified 
    ON facts(verified);

-- Profile memory (user preferences and context)
CREATE TABLE IF NOT EXISTS profiles (
    user_id TEXT PRIMARY KEY,
    data JSONB NOT NULL,  -- Stores job_preferences, technical_context, etc.
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- GIN index for JSONB queries
CREATE INDEX IF NOT EXISTS idx_profiles_data 
    ON profiles USING GIN(data);

-- Comments
COMMENT ON TABLE episodes IS 'Episodic memory: conversation summaries with embeddings';
COMMENT ON COLUMN episodes.embedding IS 'Vector embedding for semantic search (1536 dims)';
COMMENT ON COLUMN episodes.key_points IS 'Extracted key points from conversation';

COMMENT ON TABLE facts IS 'Semantic memory: extracted facts and knowledge';
COMMENT ON COLUMN facts.confidence IS 'Confidence score (0.0 to 1.0)';
COMMENT ON COLUMN facts.verified IS 'Whether fact has been verified by user';

COMMENT ON TABLE profiles IS 'User profiles with preferences and context';
COMMENT ON COLUMN profiles.data IS 'JSONB containing job_preferences, technical_context, etc.';

