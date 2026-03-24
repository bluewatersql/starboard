#!/bin/bash
# ============================================================================
# Setup Databricks Secrets for Starboard Agent
# ============================================================================
#
# This script creates a Databricks secret scope and populates it with
# required secrets for the Starboard AI Agent.
#
# Prerequisites:
#   - Databricks CLI installed and configured
#   - Appropriate workspace permissions
#
# Usage:
#   ./scripts/setup_databricks_secrets.sh
#
# ============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Configuration
SCOPE_NAME="starboard-secrets"

# ============================================================================
# Check Prerequisites
# ============================================================================

log_info "Checking prerequisites..."

# Check if Databricks CLI is installed
if ! command -v databricks &> /dev/null; then
    log_error "Databricks CLI is not installed!"
    echo "Install it with: pip install databricks-cli"
    exit 1
fi

# Check if CLI is configured
if ! databricks workspace list / &> /dev/null; then
    log_error "Databricks CLI is not configured!"
    echo "Configure it with: databricks configure --token"
    exit 1
fi

log_success "Prerequisites check passed"

# ============================================================================
# Create Secret Scope
# ============================================================================

log_info "Creating secret scope: $SCOPE_NAME"

# Check if scope already exists
if databricks secrets list-scopes | grep -q "$SCOPE_NAME"; then
    log_warning "Secret scope '$SCOPE_NAME' already exists"
else
    # Create scope
    databricks secrets create-scope --scope "$SCOPE_NAME"
    log_success "Secret scope created: $SCOPE_NAME"
fi

# ============================================================================
# Add Secrets
# ============================================================================

log_info "Adding secrets to scope..."

# Function to add or update secret
add_secret() {
    local key=$1
    local description=$2
    local secret_value=""
    
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}$description${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    # Prompt for secret value
    read -sp "Enter value for '$key': " secret_value
    echo ""
    
    if [ -z "$secret_value" ]; then
        log_warning "Skipping '$key' (empty value)"
        return
    fi
    
    # Add secret
    echo "$secret_value" | databricks secrets put-secret \
        --scope "$SCOPE_NAME" \
        --key "$key" \
        2>/dev/null
    
    log_success "Added secret: $key"
}

# Required secrets
add_secret "databricks-token" \
    "Databricks Personal Access Token\nGenerate at: Workspace Settings > Developer > Access Tokens"

# Optional secrets
echo ""
log_info "The following secrets are optional:"
echo ""

read -p "Do you want to add Redis URL? (y/N): " add_redis
if [[ "$add_redis" =~ ^[Yy]$ ]]; then
    add_secret "redis-url" \
        "Redis URL for caching\nExample: redis://localhost:6379"
fi

read -p "Do you want to add OpenAI API key? (y/N): " add_openai
if [[ "$add_openai" =~ ^[Yy]$ ]]; then
    add_secret "openai-api-key" \
        "OpenAI API Key (if not using Databricks models)\nFormat: sk-..."
fi

# ============================================================================
# Verify Secrets
# ============================================================================

echo ""
log_info "Verifying secrets..."

echo ""
echo "Secrets in scope '$SCOPE_NAME':"
databricks secrets list --scope "$SCOPE_NAME"

# ============================================================================
# Summary
# ============================================================================

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✓ Setup Complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Secret scope '$SCOPE_NAME' is ready to use."
echo ""
echo "Next steps:"
echo "  1. Validate bundle:   databricks bundle validate"
echo "  2. Deploy to dev:     databricks bundle deploy -t dev"
echo "  3. Deploy to prod:    databricks bundle deploy -t prod"
echo ""
echo "Documentation: docs/DATABRICKS_ASSET_BUNDLES.md"
echo ""

# ============================================================================
# Grant Permissions (Optional)
# ============================================================================

read -p "Do you want to grant permissions to groups? (y/N): " grant_perms
if [[ "$grant_perms" =~ ^[Yy]$ ]]; then
    echo ""
    log_info "Granting permissions..."
    
    # Grant to data scientists (read)
    read -p "Enter group name for READ access (e.g., 'data_scientists'): " read_group
    if [ -n "$read_group" ]; then
        databricks secrets put-acl \
            --scope "$SCOPE_NAME" \
            --principal "$read_group" \
            --permission READ \
            2>/dev/null || log_warning "Failed to grant READ permission to $read_group"
        log_success "Granted READ permission to: $read_group"
    fi
    
    # Grant to admins (manage)
    read -p "Enter group name for MANAGE access (e.g., 'platform_admins'): " manage_group
    if [ -n "$manage_group" ]; then
        databricks secrets put-acl \
            --scope "$SCOPE_NAME" \
            --principal "$manage_group" \
            --permission MANAGE \
            2>/dev/null || log_warning "Failed to grant MANAGE permission to $manage_group"
        log_success "Granted MANAGE permission to: $manage_group"
    fi
    
    # List ACLs
    echo ""
    log_info "Secret scope permissions:"
    databricks secrets list-acls --scope "$SCOPE_NAME"
fi

echo ""
log_success "All done! 🚀"

