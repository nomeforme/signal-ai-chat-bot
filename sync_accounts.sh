#!/bin/bash

# Sync all Signal accounts with proper config path
set -e

ACCOUNTS_FILE="$HOME/.local/share/signal-api/data/accounts.json"
CONTAINER_NAME="signal-api"
SIGNAL_CONFIG="/home/.local/share/signal-cli"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Signal Account Sync (with --config)${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

if [ ! -f "$ACCOUNTS_FILE" ]; then
    echo -e "${RED}Error: accounts.json not found${NC}"
    exit 1
fi

if ! docker ps | grep -q "$CONTAINER_NAME"; then
    echo -e "${RED}Error: $CONTAINER_NAME not running${NC}"
    exit 1
fi

# Extract phone numbers
PHONE_NUMBERS=$(python3 -c "
import json
with open('$ACCOUNTS_FILE', 'r') as f:
    data = json.load(f)
    for account in data.get('accounts', []):
        print(account.get('number'))
")

if [ -z "$PHONE_NUMBERS" ]; then
    echo -e "${RED}Error: No accounts found${NC}"
    exit 1
fi

ACCOUNT_COUNT=$(echo "$PHONE_NUMBERS" | wc -l)
echo -e "${GREEN}Found $ACCOUNT_COUNT account(s)${NC}"
echo ""

# Test first account to verify config works
FIRST_PHONE=$(echo "$PHONE_NUMBERS" | head -1)
echo -e "${YELLOW}Testing config with first account: $FIRST_PHONE${NC}"
if docker exec "$CONTAINER_NAME" signal-cli --config "$SIGNAL_CONFIG" -a "$FIRST_PHONE" listIdentities 2>&1 | grep -q "Number:"; then
    echo -e "${GREEN}✓ Config path is correct!${NC}"
    echo ""
else
    echo -e "${RED}✗ Config test failed. Showing output:${NC}"
    docker exec "$CONTAINER_NAME" signal-cli --config "$SIGNAL_CONFIG" -a "$FIRST_PHONE" listIdentities
    exit 1
fi

# Sync each account
CURRENT=0
SUCCESS=0
FAILED=0

for PHONE in $PHONE_NUMBERS; do
    CURRENT=$((CURRENT + 1))
    echo -e "${BLUE}[$CURRENT/$ACCOUNT_COUNT]${NC} Syncing ${GREEN}$PHONE${NC}"

    # Run receive to sync with server (with timeout)
    if timeout 10 docker exec "$CONTAINER_NAME" signal-cli --config "$SIGNAL_CONFIG" -a "$PHONE" receive --timeout 5 2>&1; then
        echo -e "  ${GREEN}✓ Synced${NC}"
        SUCCESS=$((SUCCESS + 1))
    else
        EXIT_CODE=$?
        if [ $EXIT_CODE -eq 124 ]; then
            echo -e "  ${YELLOW}⚠ Timeout (may be normal if no new messages)${NC}"
            SUCCESS=$((SUCCESS + 1))
        else
            echo -e "  ${RED}✗ Failed${NC}"
            FAILED=$((FAILED + 1))
        fi
    fi
    echo ""
done

# Summary
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "Total: ${BLUE}$ACCOUNT_COUNT${NC}"
echo -e "Success: ${GREEN}$SUCCESS${NC}"
echo -e "Failed: ${RED}$FAILED${NC}"
echo ""

if [ $SUCCESS -gt 0 ]; then
    echo -e "${GREEN}✓ Accounts synced successfully!${NC}"
    echo -e "${YELLOW}Restart your bot to apply changes:${NC}"
    echo -e "  ${BLUE}docker compose restart bot${NC}"
fi
