#!/usr/bin/env bash
# Force restart the Starboard server to pick up code changes

set -e

echo "🛑 Stopping all Starboard processes..."
pkill -f "starboard" || true
pkill -f "uvicorn.*starboard" || true
sleep 2

echo "✅ Processes stopped"
echo ""
echo "🚀 Starting server..."
echo ""

cd "$(dirname "$0")"
make dev-server

