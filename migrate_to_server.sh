#!/bin/bash

# Script to migrate Signal bot data to remote server
# This copies the entire signal-cli database to the server

set -e

# Configuration
SERVER_HOST=""
SERVER_USER=""
SSH_KEY="~/.ssh/"
LOCAL_SIGNAL_DATA="${HOME}/.local/share/signal-api"
REMOTE_SIGNAL_DATA="/root/.local/share/signal-api"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== Signal Bot Migration Script ===${NC}"
echo -e "${YELLOW}This script will:${NC}"
echo -e "  1. Stop local signal-api container"
echo -e "  2. Copy signal-cli data to server: $SERVER_HOST"
echo -e "  3. Restart local signal-api container"
echo -e "  4. Stop server signal-api container"
echo -e "  5. Verify migration"
echo -e "  6. Restart server signal-api container"
echo ""

# Step 1: Stop local container
echo -e "${YELLOW}Step 1: Stopping local signal-api container...${NC}"
if docker ps | grep -q signal-api; then
    echo "  → Container is running, stopping..."
    docker stop signal-api
    echo -e "  ${GREEN}✓ Container stopped${NC}"
else
    echo "  → Container is already stopped"
fi
echo ""

# Step 2: Copy data to server
echo -e "${YELLOW}Step 2: Copying signal-cli data to server...${NC}"
echo "  → Source: $LOCAL_SIGNAL_DATA"
echo "  → Destination: $SERVER_USER@$SERVER_HOST:$REMOTE_SIGNAL_DATA"
echo ""

# Check if local data exists
if [ ! -d "$LOCAL_SIGNAL_DATA" ]; then
    echo -e "${RED}Error: Local signal-cli data directory not found at $LOCAL_SIGNAL_DATA${NC}"
    echo -e "${YELLOW}Starting local container...${NC}"
    docker start signal-api
    exit 1
fi

# Create parent directory on server if it doesn't exist
echo "  → Creating parent directory on server..."
ssh -i "$SSH_KEY" "$SERVER_USER@$SERVER_HOST" "mkdir -p $(dirname $REMOTE_SIGNAL_DATA)"

# Stop server container before copying
echo "  → Stopping server signal-api container..."
ssh -i "$SSH_KEY" "$SERVER_USER@$SERVER_HOST" "cd /opt/signal-ai-chat-bot && docker stop signal-api 2>/dev/null || true"

# Remove old data on server
echo "  → Removing old signal-cli data on server..."
ssh -i "$SSH_KEY" "$SERVER_USER@$SERVER_HOST" "rm -rf $REMOTE_SIGNAL_DATA"

# Copy data using rsync for efficiency
echo "  → Syncing data (this may take a moment)..."
rsync -avz --progress -e "ssh -i $SSH_KEY" "$LOCAL_SIGNAL_DATA/" "$SERVER_USER@$SERVER_HOST:$REMOTE_SIGNAL_DATA/"

if [ $? -eq 0 ]; then
    echo -e "  ${GREEN}✓ Data copied successfully${NC}"
else
    echo -e "  ${RED}✗ Failed to copy data${NC}"
    echo -e "${YELLOW}Starting local container...${NC}"
    docker start signal-api
    exit 1
fi
echo ""

# Step 3: Restart local container
echo -e "${YELLOW}Step 3: Restarting local signal-api container...${NC}"
docker start signal-api
echo "  → Waiting for container to be ready..."
sleep 3
echo -e "  ${GREEN}✓ Local container restarted${NC}"
echo ""

# Step 4: Verify migration on server
echo -e "${YELLOW}Step 4: Verifying migration on server...${NC}"

# Check accounts.json
echo "  → Checking accounts.json..."
ACCOUNT_COUNT=$(ssh -i "$SSH_KEY" "$SERVER_USER@$SERVER_HOST" "jq '.accounts | length' $REMOTE_SIGNAL_DATA/data/accounts.json" 2>/dev/null || echo "0")

if [ "$ACCOUNT_COUNT" -gt 0 ]; then
    echo -e "  ${GREEN}✓ Found $ACCOUNT_COUNT account(s) in accounts.json${NC}"
else
    echo -e "  ${RED}✗ No accounts found in accounts.json${NC}"
    exit 1
fi

# List account phone numbers
echo "  → Account phone numbers:"
ssh -i "$SSH_KEY" "$SERVER_USER@$SERVER_HOST" "jq -r '.accounts[].number' $REMOTE_SIGNAL_DATA/data/accounts.json" | while read phone; do
    echo "    • $phone"
done
echo ""

# Step 5: Restart server container
echo -e "${YELLOW}Step 5: Starting server signal-api container...${NC}"
ssh -i "$SSH_KEY" "$SERVER_USER@$SERVER_HOST" "cd /opt/signal-ai-chat-bot && docker start signal-api"
echo "  → Waiting for container to be ready..."
sleep 5
echo -e "  ${GREEN}✓ Server container started${NC}"
echo ""

# Final verification
echo -e "${YELLOW}Step 6: Final verification...${NC}"
echo "  → Testing server API..."
if ssh -i "$SSH_KEY" "$SERVER_USER@$SERVER_HOST" "curl -s http://localhost:8080/v1/accounts | jq -r '.[]' | wc -l" | grep -q "$ACCOUNT_COUNT"; then
    echo -e "  ${GREEN}✓ Server API is responding correctly${NC}"
else
    echo -e "  ${YELLOW}⚠ Server API might not be fully ready yet${NC}"
    echo "  → You can check with: ssh -i $SSH_KEY $SERVER_USER@$SERVER_HOST 'curl http://localhost:8080/v1/accounts'"
fi
echo ""

# Summary
echo -e "${GREEN}=== Migration Complete! ===${NC}"
echo -e "Successfully migrated $ACCOUNT_COUNT Signal account(s) to server"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo -e "  1. Verify bots are working on server:"
echo -e "     ssh -i $SSH_KEY $SERVER_USER@$SERVER_HOST"
echo -e "     cd /opt/signal-ai-chat-bot"
echo -e "     docker compose logs -f bot"
echo -e "  2. Send a test message to one of the bots"
echo -e "  3. If everything works, you can stop the local container"
echo ""
