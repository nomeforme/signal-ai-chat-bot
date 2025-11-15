#!/bin/bash

# Update Signal accounts using their path/account ID instead of phone number
set -e

ACCOUNTS_FILE="$HOME/.local/share/signal-api/data/accounts.json"
CONTAINER_NAME="signal-api"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Signal Account Update (By Path)${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if accounts.json exists
if [ ! -f "$ACCOUNTS_FILE" ]; then
    echo -e "${RED}Error: accounts.json not found at $ACCOUNTS_FILE${NC}"
    exit 1
fi

# Check if signal-api container is running
if ! docker ps | grep -q "$CONTAINER_NAME"; then
    echo -e "${RED}Error: $CONTAINER_NAME container is not running${NC}"
    exit 1
fi

# Extract account paths and phone numbers
echo -e "${BLUE}Reading accounts...${NC}"
ACCOUNTS=$(python3 << 'EOF'
import json
import sys

try:
    with open('/root/.local/share/signal-api/data/accounts.json', 'r') as f:
        data = json.load(f)
        for account in data.get('accounts', []):
            path = account.get('path')
            number = account.get('number')
            uuid = account.get('uuid')
            if path and number and uuid:
                print(f"{path}|{number}|{uuid}")
except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
    sys.exit(1)
EOF
)

if [ -z "$ACCOUNTS" ]; then
    echo -e "${RED}Error: No accounts found${NC}"
    exit 1
fi

ACCOUNT_COUNT=$(echo "$ACCOUNTS" | wc -l)
echo -e "${GREEN}Found $ACCOUNT_COUNT account(s)${NC}"
echo ""

# Process each account
CURRENT=0
SUCCESS=0
FAILED=0
FAILED_ACCOUNTS=()

while IFS='|' read -r PATH NUMBER UUID; do
    CURRENT=$((CURRENT + 1))
    echo -e "${BLUE}[$CURRENT/$ACCOUNT_COUNT]${NC} Account: ${GREEN}$NUMBER${NC} (path: $PATH, uuid: ${UUID:0:8}...)"

    # Try to send a sync request using the account path
    # This forces signal-cli to sync with servers
    echo "  Attempting to sync account data..."

    if docker exec "$CONTAINER_NAME" signal-cli -a "$NUMBER" receive --send-read-receipts 2>&1; then
        echo -e "  ${GREEN}✓ Sync attempted${NC}"
        SUCCESS=$((SUCCESS + 1))
    else
        echo -e "  ${RED}✗ Sync failed${NC}"
        FAILED=$((FAILED + 1))
        FAILED_ACCOUNTS+=("$NUMBER")
    fi

    echo ""
done <<< "$ACCOUNTS"

# Summary
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "Total: ${BLUE}$ACCOUNT_COUNT${NC}"
echo -e "Success: ${GREEN}$SUCCESS${NC}"
echo -e "Failed: ${RED}$FAILED${NC}"

if [ $FAILED -gt 0 ]; then
    echo ""
    echo -e "${RED}Failed accounts:${NC}"
    for NUMBER in "${FAILED_ACCOUNTS[@]}"; do
        echo -e "  - ${RED}$NUMBER${NC}"
    done
fi

echo ""
echo -e "${YELLOW}Note: The 'receive' command attempts to fetch new messages and sync with servers.${NC}"
echo -e "${YELLOW}This may help update group membership information.${NC}"
