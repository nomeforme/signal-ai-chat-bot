#!/bin/bash

# Batch update all Signal accounts to sync UUIDs with Signal servers
# This fixes group membership issues when accounts are copied between machines

set -e  # Exit on error

ACCOUNTS_FILE="$HOME/.local/share/signal-api/data/accounts.json"
CONTAINER_NAME="signal-api"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Signal Account Batch Update Script${NC}"
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
    echo -e "${YELLOW}Start it with: docker-compose up -d signal-api${NC}"
    exit 1
fi

# Extract phone numbers from accounts.json
echo -e "${BLUE}Reading accounts from $ACCOUNTS_FILE...${NC}"
PHONE_NUMBERS=$(python3 -c "
import json
import sys

try:
    with open('$ACCOUNTS_FILE', 'r') as f:
        data = json.load(f)
        for account in data.get('accounts', []):
            print(account.get('number'))
except Exception as e:
    print(f'Error reading accounts.json: {e}', file=sys.stderr)
    sys.exit(1)
")

if [ -z "$PHONE_NUMBERS" ]; then
    echo -e "${RED}Error: No phone numbers found in accounts.json${NC}"
    exit 1
fi

# Count accounts
ACCOUNT_COUNT=$(echo "$PHONE_NUMBERS" | wc -l)
echo -e "${GREEN}Found $ACCOUNT_COUNT account(s) to update${NC}"
echo ""

# Ask for confirmation
echo -e "${YELLOW}This will run 'updateAccount' for each phone number.${NC}"
echo -e "${YELLOW}This operation is safe and will:${NC}"
echo -e "${YELLOW}  - Sync account UUIDs with Signal servers${NC}"
echo -e "${YELLOW}  - Update group memberships to use UUIDs${NC}"
echo -e "${YELLOW}  - NOT re-register or change UUIDs${NC}"
echo ""
read -p "Continue? (y/N): " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Aborted by user${NC}"
    exit 0
fi

echo ""
echo -e "${BLUE}Starting batch update...${NC}"
echo ""

# Update each account
CURRENT=0
SUCCESS=0
FAILED=0
FAILED_ACCOUNTS=()

for PHONE in $PHONE_NUMBERS; do
    CURRENT=$((CURRENT + 1))
    echo -e "${BLUE}[$CURRENT/$ACCOUNT_COUNT]${NC} Updating account: ${GREEN}$PHONE${NC}"

    # Run updateAccount command
    if docker exec "$CONTAINER_NAME" signal-cli -a "$PHONE" updateAccount 2>&1; then
        echo -e "${GREEN}✓ Success${NC}"
        SUCCESS=$((SUCCESS + 1))
    else
        echo -e "${RED}✗ Failed${NC}"
        FAILED=$((FAILED + 1))
        FAILED_ACCOUNTS+=("$PHONE")
    fi

    echo ""

    # Small delay between updates to avoid rate limiting
    if [ $CURRENT -lt $ACCOUNT_COUNT ]; then
        sleep 1
    fi
done

# Summary
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Update Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "Total accounts: ${BLUE}$ACCOUNT_COUNT${NC}"
echo -e "Successful: ${GREEN}$SUCCESS${NC}"
echo -e "Failed: ${RED}$FAILED${NC}"

if [ $FAILED -gt 0 ]; then
    echo ""
    echo -e "${RED}Failed accounts:${NC}"
    for PHONE in "${FAILED_ACCOUNTS[@]}"; do
        echo -e "  - ${RED}$PHONE${NC}"
    done
    echo ""
    echo -e "${YELLOW}Tip: Check if these accounts are properly registered${NC}"
    exit 1
else
    echo ""
    echo -e "${GREEN}All accounts updated successfully! 🎉${NC}"
    echo ""
    echo -e "${YELLOW}Next steps:${NC}"
    echo -e "  1. Restart your bot: ${BLUE}docker-compose restart bot${NC}"
    echo -e "  2. Test @mentioning the bot in a group chat"
    echo -e "  3. Group memberships should now use UUIDs"
fi
