#!/bin/bash
# Development server startup with validation
#
# This script validates the codebase before starting the server
# to catch integration issues early.

set -e  # Exit on error

cd "$(dirname "$0")"

echo "🔍 Activating virtual environment..."
source ../../.venv/bin/activate

echo ""
echo "🔍 Running validation checks..."
python validate.py

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Validation failed. Please fix the issues above before starting the server."
    exit 1
fi

echo ""
echo "🚀 Starting development server..."
echo ""
uvicorn starboard.main:app --reload --host 0.0.0.0 --port 8000
