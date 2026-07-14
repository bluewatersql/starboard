-- Interactive conversation patterns support
-- Migration: 004_conversation_patterns
-- Description: Add tables for agent routing, feedback, and suggestions
-- Requires: 001_initial, 002_memory, 003_indexes
-- Run: psql $DATABASE_URL -f 004_conversation_patterns.sql

-- Note: Pattern 1 (Option Selection) uses existing conversations.data JSONB field
-- Pattern 2 (Conversation Extension) uses existing conversations.data JSONB field
-- This migration adds support for Patterns 3, 4, and 5

-- ============================================================================
-- Pattern 3: Agent Routing - Track agent-to-agent handoffs
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_handoffs (
    handoff_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    source_agent_id VARCHAR(100) NOT NULL,
    target_agent_id VARCHAR(100) NOT NULL,
    capability_id VARCHAR(100),
    handoff_context JSONB NOT NULL DEFAULT '{}',
    status VARCHAR(20) NOT NULL CHECK (status IN ('initiated', 'completed', 'failed')),
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- Indexes for agent handoffs
CREATE INDEX IF NOT EXISTS idx_handoffs_conversation 
    ON agent_handoffs(conversation_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_handoffs_target_agent 
    ON agent_handoffs(target_agent_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_handoffs_status 
    ON agent_handoffs(status, created_at DESC)
    WHERE status = 'initiated';

-- Comments
COMMENT ON TABLE agent_handoffs IS 'Pattern 3: Agent-to-agent handoff tracking';
COMMENT ON COLUMN agent_handoffs.handoff_context IS 'Context passed from source to target agent (JSONB)';
COMMENT ON COLUMN agent_handoffs.status IS 'Handoff status: initiated, completed, or failed';

-- ============================================================================
-- Pattern 4: Feedback Collection - User feedback on agent responses
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_feedback (
    feedback_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_id UUID NOT NULL,
    user_id TEXT NOT NULL,
    agent_name VARCHAR(100) NOT NULL,
    rating VARCHAR(20) NOT NULL CHECK (rating IN ('positive', 'negative')),
    categories TEXT[],
    comment TEXT,
    context_snapshot JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indexes for user feedback
CREATE INDEX IF NOT EXISTS idx_feedback_conversation 
    ON user_feedback(conversation_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_feedback_message 
    ON user_feedback(message_id);

CREATE INDEX IF NOT EXISTS idx_feedback_agent 
    ON user_feedback(agent_name, rating, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_feedback_user 
    ON user_feedback(user_id, created_at DESC);

-- Partial index for negative feedback (for analysis)
CREATE INDEX IF NOT EXISTS idx_feedback_negative 
    ON user_feedback(agent_name, created_at DESC)
    WHERE rating = 'negative';

-- GIN index for category searches
CREATE INDEX IF NOT EXISTS idx_feedback_categories 
    ON user_feedback USING GIN(categories);

-- Comments
COMMENT ON TABLE user_feedback IS 'Pattern 4: User feedback on agent responses';
COMMENT ON COLUMN user_feedback.rating IS 'User rating: positive or negative';
COMMENT ON COLUMN user_feedback.categories IS 'Negative feedback categories (array)';
COMMENT ON COLUMN user_feedback.context_snapshot IS 'Full context at time of feedback (JSONB)';

-- ============================================================================
-- Pattern 5: Agent Discovery - Track suggestion interactions
-- ============================================================================

CREATE TABLE IF NOT EXISTS suggestion_interactions (
    interaction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    suggestion_id VARCHAR(100) NOT NULL,
    user_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    target_agent_id VARCHAR(100) NOT NULL,
    action VARCHAR(20) NOT NULL CHECK (action IN ('presented', 'clicked', 'dismissed', 'converted')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indexes for suggestion interactions
CREATE INDEX IF NOT EXISTS idx_suggestions_conversation 
    ON suggestion_interactions(conversation_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_suggestions_user 
    ON suggestion_interactions(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_suggestions_target_agent 
    ON suggestion_interactions(target_agent_id, action, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_suggestions_metrics 
    ON suggestion_interactions(suggestion_id, action, created_at DESC);

-- Partial index for conversions (successful suggestions)
CREATE INDEX IF NOT EXISTS idx_suggestions_converted 
    ON suggestion_interactions(target_agent_id, created_at DESC)
    WHERE action = 'converted';

-- Comments
COMMENT ON TABLE suggestion_interactions IS 'Pattern 5: User interactions with agent suggestions';
COMMENT ON COLUMN suggestion_interactions.action IS 'User action: presented, clicked, dismissed, or converted';
COMMENT ON COLUMN suggestion_interactions.suggestion_id IS 'Unique identifier for the suggestion';

-- ============================================================================
-- Views for analytics
-- ============================================================================

-- View: Agent routing statistics
CREATE OR REPLACE VIEW agent_routing_stats AS
SELECT 
    target_agent_id,
    status,
    COUNT(*) as count,
    AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) as avg_duration_seconds
FROM agent_handoffs
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY target_agent_id, status;

COMMENT ON VIEW agent_routing_stats IS 'Agent routing statistics (last 7 days)';

-- View: Agent performance by feedback
CREATE OR REPLACE VIEW agent_feedback_stats AS
SELECT 
    agent_name,
    rating,
    COUNT(*) as count,
    COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY agent_name) as percentage
FROM user_feedback
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY agent_name, rating
ORDER BY agent_name, rating;

COMMENT ON VIEW agent_feedback_stats IS 'Agent feedback statistics (last 7 days)';

-- View: Suggestion effectiveness
CREATE OR REPLACE VIEW suggestion_effectiveness AS
SELECT 
    target_agent_id,
    action,
    COUNT(*) as count,
    COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY target_agent_id) as percentage
FROM suggestion_interactions
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY target_agent_id, action
ORDER BY target_agent_id, action;

COMMENT ON VIEW suggestion_effectiveness IS 'Suggestion click-through and conversion rates (last 7 days)';

-- ============================================================================
-- Functions for analytics
-- ============================================================================

-- Function: Get agent satisfaction rate
CREATE OR REPLACE FUNCTION get_agent_satisfaction_rate(
    p_agent_name VARCHAR(100),
    p_days INTEGER DEFAULT 7
) RETURNS NUMERIC AS $$
DECLARE
    v_satisfaction_rate NUMERIC;
BEGIN
    SELECT 
        COALESCE(
            COUNT(*) FILTER (WHERE rating = 'positive')::NUMERIC / 
            NULLIF(COUNT(*)::NUMERIC, 0),
            0
        )
    INTO v_satisfaction_rate
    FROM user_feedback
    WHERE agent_name = p_agent_name
        AND created_at > NOW() - (p_days || ' days')::INTERVAL;
    
    RETURN v_satisfaction_rate;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_agent_satisfaction_rate IS 'Calculate agent satisfaction rate (0.0-1.0)';

-- Function: Get suggestion conversion rate
CREATE OR REPLACE FUNCTION get_suggestion_conversion_rate(
    p_target_agent_id VARCHAR(100),
    p_days INTEGER DEFAULT 7
) RETURNS NUMERIC AS $$
DECLARE
    v_conversion_rate NUMERIC;
BEGIN
    SELECT 
        COALESCE(
            COUNT(*) FILTER (WHERE action = 'converted')::NUMERIC / 
            NULLIF(COUNT(*) FILTER (WHERE action = 'presented')::NUMERIC, 0),
            0
        )
    INTO v_conversion_rate
    FROM suggestion_interactions
    WHERE target_agent_id = p_target_agent_id
        AND created_at > NOW() - (p_days || ' days')::INTERVAL;
    
    RETURN v_conversion_rate;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_suggestion_conversion_rate IS 'Calculate suggestion conversion rate (0.0-1.0)';

-- ============================================================================
-- Backward compatibility notes
-- ============================================================================

-- This migration is fully backward compatible:
-- 1. All new tables (no modifications to existing tables)
-- 2. Existing conversations.data JSONB field supports next_steps (Pattern 1)
-- 3. Existing conversations.data JSONB field supports context (Pattern 2)
-- 4. New tables only referenced via foreign keys (CASCADE DELETE for cleanup)
-- 5. All constraints use CHECK for data integrity
-- 6. All indexes use IF NOT EXISTS for idempotency

-- To rollback this migration (if needed):
-- DROP VIEW IF EXISTS suggestion_effectiveness;
-- DROP VIEW IF EXISTS agent_feedback_stats;
-- DROP VIEW IF EXISTS agent_routing_stats;
-- DROP FUNCTION IF EXISTS get_suggestion_conversion_rate;
-- DROP FUNCTION IF EXISTS get_agent_satisfaction_rate;
-- DROP TABLE IF EXISTS suggestion_interactions;
-- DROP TABLE IF EXISTS user_feedback;
-- DROP TABLE IF EXISTS agent_handoffs;


