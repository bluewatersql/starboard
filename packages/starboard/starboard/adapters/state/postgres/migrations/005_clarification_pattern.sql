-- Clarification Request Pattern support (Phase 7)
-- Migration: 005_clarification_pattern
-- Description: Add table for clarification requests and responses
-- Requires: 001_initial, 002_memory, 003_indexes, 004_conversation_patterns
-- Run: psql $DATABASE_URL -f 005_clarification_pattern.sql

-- Note: Phase 7 (Clarification Request Pattern) enables the framework to
-- intelligently detect ambiguous queries and ask targeted clarification questions
-- before proceeding with execution. This is a framework-level pattern that
-- complements agent-driven clarification (via request_user_input tool).

-- ============================================================================
-- Phase 7: Clarification Request Pattern - Ambiguity detection and resolution
-- ============================================================================

CREATE TABLE IF NOT EXISTS clarification_requests (
    -- Identity
    clarification_id VARCHAR(100) PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_id UUID NOT NULL,
    
    -- Clarification type and content
    clarification_type VARCHAR(50) NOT NULL CHECK (clarification_type IN (
        'ambiguous_entity',
        'missing_parameter',
        'vague_reference',
        'insufficient_context'
    )),
    question TEXT NOT NULL,
    options JSONB,  -- Array of ClarificationOption objects (optional)
    allow_custom_response BOOLEAN NOT NULL DEFAULT TRUE,
    is_required BOOLEAN NOT NULL DEFAULT TRUE,
    default_value JSONB,
    
    -- Resolution tracking
    resolved_at TIMESTAMP,
    resolution JSONB,  -- User's response (option ID, custom text, or value)
    
    -- Metadata
    target_tool VARCHAR(100),  -- Tool that triggered clarification
    ambiguity_score JSONB,  -- AmbiguityScore details for analysis
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- Indexes for clarification requests
-- ============================================================================

-- Primary query patterns
CREATE INDEX IF NOT EXISTS idx_clarification_conversation 
    ON clarification_requests(conversation_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_clarification_message 
    ON clarification_requests(message_id);

-- Partial index for unresolved clarifications (active queries)
CREATE INDEX IF NOT EXISTS idx_clarification_unresolved 
    ON clarification_requests(conversation_id, created_at DESC)
    WHERE resolved_at IS NULL;

-- Analytics indexes
CREATE INDEX IF NOT EXISTS idx_clarification_type 
    ON clarification_requests(clarification_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_clarification_tool 
    ON clarification_requests(target_tool, clarification_type, created_at DESC)
    WHERE target_tool IS NOT NULL;

-- GIN index for JSONB fields (for complex queries)
CREATE INDEX IF NOT EXISTS idx_clarification_ambiguity_score 
    ON clarification_requests USING GIN(ambiguity_score)
    WHERE ambiguity_score IS NOT NULL;

-- ============================================================================
-- Comments for documentation
-- ============================================================================

COMMENT ON TABLE clarification_requests IS 'Phase 7: Framework-level clarification requests for ambiguous queries';

COMMENT ON COLUMN clarification_requests.clarification_type IS 
    'Type of ambiguity: ambiguous_entity, missing_parameter, vague_reference, or insufficient_context';

COMMENT ON COLUMN clarification_requests.question IS 
    'User-friendly clarification question';

COMMENT ON COLUMN clarification_requests.options IS 
    'Optional array of predefined options (ClarificationOption objects as JSONB)';

COMMENT ON COLUMN clarification_requests.allow_custom_response IS 
    'Whether user can provide custom text response (not just select from options)';

COMMENT ON COLUMN clarification_requests.resolution IS 
    'User response: option ID, custom text, or structured value (JSONB)';

COMMENT ON COLUMN clarification_requests.ambiguity_score IS 
    'Detailed ambiguity score for analytics (AmbiguityScore object as JSONB)';

COMMENT ON COLUMN clarification_requests.target_tool IS 
    'Tool that triggered this clarification (for analytics)';

-- ============================================================================
-- Views for analytics
-- ============================================================================

-- View: Clarification request statistics by type
CREATE OR REPLACE VIEW clarification_stats_by_type AS
SELECT 
    clarification_type,
    COUNT(*) as total_requests,
    COUNT(*) FILTER (WHERE resolved_at IS NOT NULL) as resolved_count,
    COUNT(*) FILTER (WHERE resolved_at IS NULL) as pending_count,
    ROUND(
        COUNT(*) FILTER (WHERE resolved_at IS NOT NULL)::NUMERIC / 
        NULLIF(COUNT(*)::NUMERIC, 0) * 100, 
        2
    ) as resolution_rate_pct,
    AVG(EXTRACT(EPOCH FROM (resolved_at - created_at))) FILTER (WHERE resolved_at IS NOT NULL) as avg_resolution_time_seconds
FROM clarification_requests
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY clarification_type
ORDER BY total_requests DESC;

COMMENT ON VIEW clarification_stats_by_type IS 
    'Clarification request statistics by type (last 7 days)';

-- View: Tool-specific clarification patterns
CREATE OR REPLACE VIEW tool_clarification_patterns AS
SELECT 
    target_tool,
    clarification_type,
    COUNT(*) as request_count,
    ROUND(
        COUNT(*)::NUMERIC / 
        SUM(COUNT(*)) OVER (PARTITION BY target_tool) * 100,
        2
    ) as percentage,
    AVG(EXTRACT(EPOCH FROM (resolved_at - created_at))) FILTER (WHERE resolved_at IS NOT NULL) as avg_resolution_time_seconds
FROM clarification_requests
WHERE created_at > NOW() - INTERVAL '30 days'
    AND target_tool IS NOT NULL
GROUP BY target_tool, clarification_type
ORDER BY target_tool, request_count DESC;

COMMENT ON VIEW tool_clarification_patterns IS 
    'Tool-specific clarification patterns and resolution times (last 30 days)';

-- View: Unresolved clarifications (operational monitoring)
CREATE OR REPLACE VIEW unresolved_clarifications AS
SELECT 
    clarification_id,
    conversation_id,
    message_id,
    clarification_type,
    question,
    target_tool,
    created_at,
    EXTRACT(EPOCH FROM (NOW() - created_at)) as age_seconds
FROM clarification_requests
WHERE resolved_at IS NULL
ORDER BY created_at ASC;

COMMENT ON VIEW unresolved_clarifications IS 
    'Currently unresolved clarification requests (for monitoring)';

-- ============================================================================
-- Functions for analytics
-- ============================================================================

-- Function: Get tool clarification rate
-- Returns the percentage of queries to a tool that require clarification
CREATE OR REPLACE FUNCTION get_tool_clarification_rate(
    p_tool_name VARCHAR(100),
    p_days INTEGER DEFAULT 7
) RETURNS NUMERIC AS $$
DECLARE
    v_clarification_rate NUMERIC;
BEGIN
    -- Note: This assumes messages are tracked somewhere
    -- For MVP, we just return the count of clarifications
    -- In Phase 7.2, we'd correlate with message counts
    SELECT COUNT(*)::NUMERIC
    INTO v_clarification_rate
    FROM clarification_requests
    WHERE target_tool = p_tool_name
        AND created_at > NOW() - (p_days || ' days')::INTERVAL;
    
    RETURN v_clarification_rate;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_tool_clarification_rate IS 
    'Count of clarification requests for a tool (MVP - returns count, Phase 7.2 will return rate)';

-- Function: Get average clarification resolution time
CREATE OR REPLACE FUNCTION get_avg_clarification_resolution_time(
    p_clarification_type VARCHAR(50) DEFAULT NULL,
    p_days INTEGER DEFAULT 7
) RETURNS NUMERIC AS $$
DECLARE
    v_avg_time NUMERIC;
BEGIN
    SELECT AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)))
    INTO v_avg_time
    FROM clarification_requests
    WHERE resolved_at IS NOT NULL
        AND created_at > NOW() - (p_days || ' days')::INTERVAL
        AND (p_clarification_type IS NULL OR clarification_type = p_clarification_type);
    
    RETURN COALESCE(v_avg_time, 0);
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_avg_clarification_resolution_time IS 
    'Calculate average time to resolve clarifications in seconds';

-- ============================================================================
-- Backward compatibility notes
-- ============================================================================

-- This migration is fully backward compatible:
-- 1. New table only (no modifications to existing tables)
-- 2. Framework-level pattern (complements, does not replace agent-driven clarification)
-- 3. Foreign key to conversations with CASCADE DELETE for cleanup
-- 4. All constraints use CHECK for data integrity
-- 5. All indexes use IF NOT EXISTS for idempotency
-- 6. JSONB fields for flexible future extensions
--
-- Phase 7 Implementation Phases:
-- - Phase 7.1 (MVP): Parameter completeness checking only
-- - Phase 7.2: Entity disambiguation
-- - Phase 7.3: Context-aware clarification
-- - Phase 7.4: Multi-turn clarification chains
--
-- To rollback this migration (if needed):
-- DROP FUNCTION IF EXISTS get_avg_clarification_resolution_time;
-- DROP FUNCTION IF EXISTS get_tool_clarification_rate;
-- DROP VIEW IF EXISTS unresolved_clarifications;
-- DROP VIEW IF EXISTS tool_clarification_patterns;
-- DROP VIEW IF EXISTS clarification_stats_by_type;
-- DROP TABLE IF EXISTS clarification_requests;


