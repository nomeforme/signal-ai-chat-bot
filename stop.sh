#!/bin/bash

# Signal AI Chat Bot Stop Script
# This script stops the signal-cli-rest-api container

echo "🛑 Stopping Signal AI Chat Bot services..."
echo ""

# Detect Docker or Podman
if command -v podman &> /dev/null; then
    CONTAINER_CMD="podman"
elif command -v docker &> /dev/null; then
    CONTAINER_CMD="docker"
else
    echo "ℹ️  Neither Docker nor Podman found"
    exit 0
fi

# Stop and remove the signal-cli-rest-api container
if $CONTAINER_CMD ps -a --format "{{.Names}}" | grep -q "^signal-api$"; then
    echo "🔧 Stopping signal-cli-rest-api container..."
    $CONTAINER_CMD stop signal-api
    $CONTAINER_CMD rm signal-api
    echo "✅ signal-cli-rest-api stopped and removed"
else
    echo "ℹ️  signal-cli-rest-api container not found (may already be stopped)"
fi

echo ""
echo "✅ Shutdown complete"
echo ""
echo "Note: The Python bot should be stopped with Ctrl+C in its terminal"
