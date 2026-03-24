#!/bin/bash
# ============================================================================
# Databricks Deployment Script
# ============================================================================
#
# Comprehensive deployment script for Starboard Agent to Databricks Apps
#
# Usage:
#   ./scripts/databricks_deploy.sh [dev|prod] [options]
#
# Options:
#   --build-only       Build container without deploying
#   --deploy-only      Deploy without rebuilding
#   --skip-tests       Skip smoke tests after deployment
#   --force            Force deployment without confirmation
#
# Examples:
#   ./scripts/databricks_deploy.sh dev              # Deploy to dev
#   ./scripts/databricks_deploy.sh prod             # Deploy to prod (with confirmation)
#   ./scripts/databricks_deploy.sh dev --build-only # Build only
#
# ============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

log_error() {
    echo -e "${RED}[✗]${NC} $1"
}

log_step() {
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

# Parse arguments
TARGET=${1:-dev}
BUILD_ONLY=false
DEPLOY_ONLY=false
SKIP_TESTS=false
FORCE=false

shift || true
while [[ $# -gt 0 ]]; do
    case $1 in
        --build-only)
            BUILD_ONLY=true
            shift
            ;;
        --deploy-only)
            DEPLOY_ONLY=true
            shift
            ;;
        --skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Validate target
if [[ "$TARGET" != "dev" && "$TARGET" != "prod" ]]; then
    log_error "Invalid target: $TARGET (must be 'dev' or 'prod')"
    exit 1
fi

# ============================================================================
# Pre-flight Checks
# ============================================================================

log_step "Pre-flight Checks"

# Check Databricks CLI
if ! command -v databricks &> /dev/null; then
    log_error "Databricks CLI not found!"
    echo "Install: pip install databricks-cli"
    exit 1
fi
log_success "Databricks CLI installed"

# Check Docker (if building)
if [ "$DEPLOY_ONLY" = false ]; then
    if ! command -v docker &> /dev/null; then
        log_error "Docker not found!"
        exit 1
    fi
    log_success "Docker installed"
fi

# Check if CLI is configured
if ! databricks workspace list / &> /dev/null; then
    log_error "Databricks CLI not configured!"
    echo "Configure: databricks configure --token"
    exit 1
fi
log_success "Databricks CLI configured"

# Check if bundle is valid
log_info "Validating bundle..."
if databricks bundle validate -t "$TARGET" &> /dev/null; then
    log_success "Bundle validation passed"
else
    log_error "Bundle validation failed!"
    databricks bundle validate -t "$TARGET"
    exit 1
fi

# ============================================================================
# Production Confirmation
# ============================================================================

if [[ "$TARGET" == "prod" && "$FORCE" != true ]]; then
    log_step "Production Deployment Confirmation"
    
    echo -e "${YELLOW}⚠️  You are about to deploy to PRODUCTION!${NC}"
    echo ""
    echo "This will:"
    echo "  • Deploy to production workspace"
    echo "  • Potentially disrupt active users"
    echo "  • Update production configurations"
    echo ""
    
    read -p "Are you sure you want to continue? (yes/no): " confirm
    
    if [[ "$confirm" != "yes" ]]; then
        log_warning "Deployment cancelled"
        exit 0
    fi
fi

# ============================================================================
# Build Container
# ============================================================================

if [ "$DEPLOY_ONLY" = false ]; then
    log_step "Building Container"
    
    IMAGE_TAG="starboard-agent:${TARGET}-$(date +%Y%m%d-%H%M%S)"
    
    log_info "Building image: $IMAGE_TAG"
    
    docker build \
        -f Dockerfile.databricks \
        -t "$IMAGE_TAG" \
        -t "starboard-agent:${TARGET}-latest" \
        --build-arg ENVIRONMENT="$TARGET" \
        .
    
    log_success "Container built: $IMAGE_TAG"
    
    # Display image size
    IMAGE_SIZE=$(docker images "$IMAGE_TAG" --format "{{.Size}}")
    log_info "Image size: $IMAGE_SIZE"
    
    if [ "$BUILD_ONLY" = true ]; then
        log_success "Build complete (deploy skipped)"
        exit 0
    fi
fi

# ============================================================================
# Deploy to Databricks
# ============================================================================

log_step "Deploying to Databricks ($TARGET)"

log_info "Deploying bundle..."

if databricks bundle deploy -t "$TARGET"; then
    log_success "Bundle deployed successfully"
else
    log_error "Deployment failed!"
    exit 1
fi

# ============================================================================
# Wait for App to be Ready
# ============================================================================

log_step "Waiting for App to be Ready"

APP_NAME=$(databricks bundle validate -t "$TARGET" 2>/dev/null | grep -o "name: starboard-[^ ]*" | head -1 | cut -d' ' -f2)

if [ -z "$APP_NAME" ]; then
    log_warning "Could not determine app name, skipping readiness check"
else
    log_info "Checking app status: $APP_NAME"
    
    MAX_WAIT=300  # 5 minutes
    ELAPSED=0
    POLL_INTERVAL=10
    
    while [ $ELAPSED -lt $MAX_WAIT ]; do
        STATUS=$(databricks apps get "$APP_NAME" --output json 2>/dev/null | jq -r '.status.state' 2>/dev/null || echo "UNKNOWN")
        
        case "$STATUS" in
            "RUNNING")
                log_success "App is running!"
                break
                ;;
            "FAILED"|"ERROR")
                log_error "App failed to start!"
                databricks apps logs "$APP_NAME" --tail 50
                exit 1
                ;;
            "PENDING"|"STARTING"|"UNKNOWN")
                log_info "App status: $STATUS (waiting...)"
                sleep $POLL_INTERVAL
                ELAPSED=$((ELAPSED + POLL_INTERVAL))
                ;;
            *)
                log_warning "Unknown status: $STATUS"
                sleep $POLL_INTERVAL
                ELAPSED=$((ELAPSED + POLL_INTERVAL))
                ;;
        esac
    done
    
    if [ $ELAPSED -ge $MAX_WAIT ]; then
        log_error "Timeout waiting for app to start"
        databricks apps logs "$APP_NAME" --tail 50
        exit 1
    fi
fi

# ============================================================================
# Run Smoke Tests
# ============================================================================

if [ "$SKIP_TESTS" = false ]; then
    log_step "Running Smoke Tests"
    
    if [ -f "scripts/smoke_test.sh" ]; then
        ./scripts/smoke_test.sh "$TARGET"
    else
        log_warning "Smoke test script not found, skipping tests"
    fi
fi

# ============================================================================
# Deployment Summary
# ============================================================================

log_step "Deployment Summary"

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✓ Deployment Complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Target:       $TARGET"
echo "App Name:     $APP_NAME"
echo ""

if [ -n "$APP_NAME" ]; then
    # Get app URL
    APP_URL=$(databricks apps get "$APP_NAME" --output json 2>/dev/null | jq -r '.url' 2>/dev/null || echo "N/A")
    
    echo "App URL:      $APP_URL"
    echo ""
    echo "Useful commands:"
    echo "  View logs:        databricks apps logs $APP_NAME --follow"
    echo "  Check status:     databricks apps get $APP_NAME"
    echo "  Restart app:      databricks apps restart $APP_NAME"
    echo "  Destroy app:      databricks bundle destroy -t $TARGET"
fi

echo ""
echo "Documentation:  docs/DATABRICKS_ASSET_BUNDLES.md"
echo ""

# ============================================================================
# Post-deployment Actions
# ============================================================================

if [[ "$TARGET" == "prod" ]]; then
    log_step "Post-deployment Checklist"
    
    echo "Don't forget to:"
    echo "  [ ] Monitor app logs for errors"
    echo "  [ ] Verify health endpoints"
    echo "  [ ] Test critical user flows"
    echo "  [ ] Check resource utilization"
    echo "  [ ] Update documentation"
    echo "  [ ] Notify team of deployment"
    echo ""
fi

log_success "All done! 🚀"

