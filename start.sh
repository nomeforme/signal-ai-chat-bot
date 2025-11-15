#!/bin/bash

# Signal AI Chat Bot Startup Script
# This script starts the signal-cli-rest-api and the Python bot

set -e  # Exit on error

echo "🚀 Starting Signal AI Chat Bot..."
echo ""

# Check if config.json file exists
if [ ! -f config.json ]; then
    echo "❌ Error: config.json file not found!"
    echo "Please copy config.example.json to config.json and configure it:"
    echo "  cp config.example.json config.json"
    echo "  nano config.json"
    exit 1
fi

# Check if .env file exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found!"
    echo "Please copy .env.example to .env and configure it with your API keys:"
    echo "  cp .env.example .env"
    echo "  nano .env"
    exit 1
fi

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "❌ Error: uv is not installed"
    echo "Please install uv first:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "⚠️  Virtual environment not found. Creating one with uv..."
    uv venv
fi

echo "📦 Syncing dependencies with uv..."
uv sync

echo "✅ Environment ready"
echo ""

# Check if signal-cli-rest-api is already running
if curl -s http://localhost:8080/v1/about > /dev/null 2>&1; then
    echo "✅ signal-cli-rest-api is already running on port 8080"
else
    echo "🔧 Starting signal-cli-rest-api..."
    echo "   Using podman to start the container..."

    # Detect Docker or Podman
    if command -v podman &> /dev/null; then
        CONTAINER_CMD="podman"
    elif command -v docker &> /dev/null; then
        CONTAINER_CMD="docker"
    else
        echo "❌ Error: Neither Docker nor Podman found"
        exit 1
    fi

    # Start signal-cli-rest-api in the background
    $CONTAINER_CMD run -d --name signal-api \
        -p 8080:8080 \
        -v $HOME/.local/share/signal-api:/home/.local/share/signal-cli \
        -e 'MODE=json-rpc' \
        bbernhard/signal-cli-rest-api

    echo "⏳ Waiting for signal-cli-rest-api to be ready..."
    sleep 5

    # Check if it started successfully
    if curl -s http://localhost:8080/v1/about > /dev/null 2>&1; then
        echo "✅ signal-cli-rest-api started successfully"
    else
        echo "❌ Failed to start signal-cli-rest-api"
        echo "   Check if podman is installed and running"
        exit 1
    fi
fi

echo ""
echo "🤖 Starting Signal AI Bot..."
echo "   Configuration loaded from config.json"
echo "   Press Ctrl+C to stop the bot"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Start the Python bot using uv run
uv run python src/main.py
