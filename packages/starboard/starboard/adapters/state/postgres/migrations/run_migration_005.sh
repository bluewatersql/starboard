#!/bin/bash
# Run Phase 7 clarification pattern migration (005)
# 
# Usage:
#   ./run_migration_005.sh [environment]
#
# Environment: dev (default), staging, prod
#
# Requirements:
#   - psql installed
#   - DATABASE_URL environment variable set
#   - Or .env file with DATABASE_URL

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATION_FILE="$SCRIPT_DIR/005_clarification_pattern.sql"
ENV="${1:-dev}"

echo "╔═══════════════════════════════════════════════════════════════════════════╗"
echo "║                                                                           ║"
echo "║            Phase 7 Clarification Pattern Migration (005)                 ║"
echo "║                                                                           ║"
echo "╚═══════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Environment: $ENV"
echo "Migration File: $MIGRATION_FILE"
echo ""

# Load environment variables
if [ -f "$SCRIPT_DIR/../../../../../.env.$ENV" ]; then
    echo "Loading environment from .env.$ENV..."
    export $(cat "$SCRIPT_DIR/../../../../../.env.$ENV" | grep -v '^#' | xargs)
elif [ -f "$SCRIPT_DIR/../../../../../.env" ]; then
    echo "Loading environment from .env..."
    export $(cat "$SCRIPT_DIR/../../../../../.env" | grep -v '^#' | xargs)
fi

# Check DATABASE_URL
if [ -z "$DATABASE_URL" ]; then
    echo "❌ ERROR: DATABASE_URL not set"
    echo ""
    echo "Set DATABASE_URL or create .env file with:"
    echo "  DATABASE_URL=postgresql://user:password@localhost:5432/starboard_dev"
    exit 1
fi

# Mask password in DATABASE_URL for display
SAFE_URL=$(echo "$DATABASE_URL" | sed 's/:\/\/[^:]*:[^@]*@/:\/\/***:***@/')
echo "Database: $SAFE_URL"
echo ""

# Confirmation for prod
if [ "$ENV" = "prod" ]; then
    echo "⚠️  WARNING: You are about to run migration on PRODUCTION"
    read -p "Type 'yes' to confirm: " confirm
    if [ "$confirm" != "yes" ]; then
        echo "Migration cancelled."
        exit 0
    fi
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 1: Checking prerequisites..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check psql
if ! command -v psql &> /dev/null; then
    echo "❌ ERROR: psql not found"
    echo "Install PostgreSQL client: brew install postgresql (macOS)"
    exit 1
fi
echo "✅ psql found"

# Check database connection
if ! psql "$DATABASE_URL" -c "SELECT 1" &> /dev/null; then
    echo "❌ ERROR: Cannot connect to database"
    exit 1
fi
echo "✅ Database connection OK"

# Check if previous migrations exist
echo ""
echo "Checking previous migrations..."
CONVERSATIONS_EXISTS=$(psql "$DATABASE_URL" -tAc "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'conversations');")
if [ "$CONVERSATIONS_EXISTS" = "t" ]; then
    echo "✅ conversations table exists (migration 001 OK)"
else
    echo "❌ ERROR: conversations table not found"
    echo "Run migrations 001-004 first"
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 2: Running migration..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Run migration
if psql "$DATABASE_URL" -f "$MIGRATION_FILE"; then
    echo ""
    echo "✅ Migration completed successfully"
else
    echo ""
    echo "❌ Migration failed"
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 3: Verifying migration..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check table exists
TABLE_EXISTS=$(psql "$DATABASE_URL" -tAc "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'clarification_requests');")
if [ "$TABLE_EXISTS" = "t" ]; then
    echo "✅ clarification_requests table created"
else
    echo "❌ ERROR: clarification_requests table not found"
    exit 1
fi

# Check indexes
INDEX_COUNT=$(psql "$DATABASE_URL" -tAc "SELECT COUNT(*) FROM pg_indexes WHERE tablename = 'clarification_requests';")
echo "✅ Created $INDEX_COUNT indexes"

# Check views
VIEW_COUNT=$(psql "$DATABASE_URL" -tAc "SELECT COUNT(*) FROM information_schema.views WHERE table_name LIKE 'clarification%' OR table_name LIKE '%clarification%';")
echo "✅ Created $VIEW_COUNT analytics views"

# Check functions
FUNCTION_COUNT=$(psql "$DATABASE_URL" -tAc "SELECT COUNT(*) FROM pg_proc WHERE proname LIKE '%clarification%';")
echo "✅ Created $FUNCTION_COUNT functions"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 4: Testing schema..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Test insert
echo "Testing INSERT..."
psql "$DATABASE_URL" <<EOF > /dev/null
-- Create test conversation first
INSERT INTO conversations (id, user_id, created_at, updated_at)
VALUES ('test_conv_phase7', 'test_user', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- Test clarification insert
INSERT INTO clarification_requests (
    clarification_id,
    conversation_id,
    message_id,
    clarification_type,
    question,
    options,
    allow_custom_response,
    is_required,
    target_tool,
    created_at
) VALUES (
    'test_clar_001',
    'test_conv_phase7',
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
    'missing_parameter',
    'What warehouse size would you like?',
    '[{"option_id": "1", "display_text": "Small", "value": "small", "is_recommended": false}]'::jsonb,
    true,
    true,
    'create_warehouse',
    NOW()
);
EOF
echo "✅ INSERT test passed"

# Test SELECT
echo "Testing SELECT..."
RECORD_COUNT=$(psql "$DATABASE_URL" -tAc "SELECT COUNT(*) FROM clarification_requests WHERE clarification_id = 'test_clar_001';")
if [ "$RECORD_COUNT" = "1" ]; then
    echo "✅ SELECT test passed"
else
    echo "❌ SELECT test failed"
    exit 1
fi

# Test UPDATE
echo "Testing UPDATE..."
psql "$DATABASE_URL" <<EOF > /dev/null
UPDATE clarification_requests
SET resolved_at = NOW(),
    resolution = '{"option_id": "1", "value": "small"}'::jsonb
WHERE clarification_id = 'test_clar_001';
EOF
echo "✅ UPDATE test passed"

# Test views
echo "Testing analytics views..."
psql "$DATABASE_URL" -c "SELECT * FROM clarification_stats_by_type LIMIT 1;" > /dev/null
echo "✅ clarification_stats_by_type view OK"

psql "$DATABASE_URL" -c "SELECT * FROM tool_clarification_patterns LIMIT 1;" > /dev/null
echo "✅ tool_clarification_patterns view OK"

psql "$DATABASE_URL" -c "SELECT * FROM unresolved_clarifications LIMIT 1;" > /dev/null
echo "✅ unresolved_clarifications view OK"

# Test functions
echo "Testing functions..."
psql "$DATABASE_URL" -tAc "SELECT get_tool_clarification_rate('create_warehouse', 7);" > /dev/null
echo "✅ get_tool_clarification_rate() OK"

psql "$DATABASE_URL" -tAc "SELECT get_avg_clarification_resolution_time('missing_parameter', 7);" > /dev/null
echo "✅ get_avg_clarification_resolution_time() OK"

# Cleanup test data
echo ""
echo "Cleaning up test data..."
psql "$DATABASE_URL" <<EOF > /dev/null
DELETE FROM clarification_requests WHERE clarification_id = 'test_clar_001';
DELETE FROM conversations WHERE id = 'test_conv_phase7';
EOF
echo "✅ Test data cleaned up"

echo ""
echo "╔═══════════════════════════════════════════════════════════════════════════╗"
echo "║                                                                           ║"
echo "║              ✅ MIGRATION 005 COMPLETED SUCCESSFULLY ✅                  ║"
echo "║                                                                           ║"
echo "╚═══════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Summary:"
echo "  - clarification_requests table created"
echo "  - $INDEX_COUNT indexes created"
echo "  - $VIEW_COUNT analytics views created"
echo "  - $FUNCTION_COUNT functions created"
echo "  - All tests passed ✅"
echo ""
echo "Next steps:"
echo "  1. Enable clarification pattern in application config"
echo "  2. Deploy application code with Phase 7 support"
echo "  3. Monitor analytics views for clarification patterns"
echo ""
echo "Rollback (if needed):"
echo "  See migration file footer for rollback SQL"
echo ""

