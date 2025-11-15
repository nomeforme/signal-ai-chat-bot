#!/bin/bash

# Signal AI Chat Bot Startup Script
# This script starts both services using Docker Compose

set -e  # Exit on error

echo "🚀 Starting Signal AI Chat Bot with Docker Compose..."
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

# Detect Docker or Podman
if command -v docker &> /dev/null && docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
elif command -v podman &> /dev/null && command -v podman-compose &> /dev/null; then
    COMPOSE_CMD="podman-compose"
else
    echo "❌ Error: Neither 'docker compose' nor 'podman-compose' found"
    echo "Please install Docker Compose or Podman Compose:"
    echo "  Docker: https://docs.docker.com/compose/install/"
    echo "  Podman: pip install podman-compose"
    exit 1
fi

echo "📦 Using: $COMPOSE_CMD"
echo ""
echo "🔧 Building and starting services..."
echo "   - signal-api: Signal CLI REST API"
echo "   - bot: Python bot with auto-reload"
echo ""

# Build and start services
$COMPOSE_CMD up --build -d

echo ""
echo "⏳ Waiting for services to be ready..."
sleep 5

# Check if services are running
if $COMPOSE_CMD ps | grep -q "signal-api.*Up"; then
    echo "✅ signal-api is running"
else
    echo "❌ signal-api failed to start"
    echo "Check logs with: $COMPOSE_CMD logs signal-api"
    exit 1
fi

if $COMPOSE_CMD ps | grep -q "signal-bot.*Up"; then
    echo "✅ signal-bot is running with auto-reload"
else
    echo "❌ signal-bot failed to start"
    echo "Check logs with: $COMPOSE_CMD logs bot"
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ All services started successfully!"
echo ""
echo "📝 Useful commands:"
echo "  View logs:        $COMPOSE_CMD logs -f"
echo "  View bot logs:    $COMPOSE_CMD logs -f bot"
echo "  Restart services: $COMPOSE_CMD restart"
echo "  Stop services:    $COMPOSE_CMD down"
echo ""
echo "🔄 Auto-reload is ENABLED - code changes will restart the bot automatically"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Follow logs (can be stopped with Ctrl+C)
echo "Following bot logs (Ctrl+C to stop)..."
echo ""
$COMPOSE_CMD logs -f bot
