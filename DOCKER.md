# Docker Compose Setup

This project uses Docker Compose for containerized development with auto-reload.

## Architecture

- **signal-api**: Signal CLI REST API container (official image)
- **bot**: Python bot container with watchdog auto-reload

## Quick Start

```bash
# Start all services
./start.sh

# Or manually with docker compose
docker compose up --build -d
docker compose logs -f bot
```

## Development Workflow

1. **Start services**: `./start.sh`
2. **Edit code**: Modify files in `src/`
3. **Auto-reload**: Bot automatically restarts on file changes
4. **View logs**: `docker compose logs -f bot`

## Volume Mounts

- `./src` → `/app/src` (read-only, for live code editing)
- `./config.json` → `/app/config.json` (read-only)
- `./.env` → `/app/.env` (read-only)
- `~/.local/share/signal-api` → Signal CLI data (persistent)

## Useful Commands

```bash
# View all logs
docker compose logs -f

# View bot logs only
docker compose logs -f bot

# View signal-api logs
docker compose logs -f signal-api

# Restart services
docker compose restart

# Restart bot only
docker compose restart bot

# Stop all services
docker compose down

# Rebuild and restart
docker compose up --build -d

# Check service status
docker compose ps
```

## Environment Variables

The bot container uses these environment variables:
- `WS_BASE_URL=ws://signal-api:8080` (container network)
- `HTTP_BASE_URL=http://signal-api:8080` (container network)
- `PYTHONUNBUFFERED=1` (real-time logs)

## Auto-Reload

Watchdog monitors `*.py` files and automatically restarts the bot on changes:
- Watches: `src/**/*.py`
- Ignores: `__pycache__/`, `.venv/`
- Signal: `SIGTERM` (graceful shutdown)

## Deployment to Server

1. **Push changes**: `git push`
2. **SSH to server**: `ssh user@X`
3. **Pull updates**: `cd /opt/signal-ai-chat-bot && git pull`
4. **Restart**: `docker compose down && ./start.sh`

## Troubleshooting

**Container won't start:**
```bash
docker compose logs signal-api
docker compose logs bot
```

**Port already in use:**
```bash
# Stop existing containers
docker stop signal-api signal-bot
docker rm signal-api signal-bot
# Or use compose
docker compose down
```

**Permission issues with Signal data:**
```bash
ls -la ~/.local/share/signal-api
# Ensure readable by container
```

**Auto-reload not working:**
- Check volume mount: `docker compose exec bot ls -la /app/src`
- Check watchdog is running: `docker compose logs bot | grep watchmedo`
