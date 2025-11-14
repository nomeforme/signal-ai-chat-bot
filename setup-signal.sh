#!/bin/bash

# Signal CLI Setup Script
# This script helps you register your Twilio number with Signal

set -e

echo "📱 Signal CLI Registration Helper"
echo "=================================="
echo ""

# Load .env file
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found!"
    exit 1
fi

source .env

if [ -z "$SIGNAL_PHONE_NUMBER" ]; then
    echo "❌ Error: SIGNAL_PHONE_NUMBER not set in .env file"
    exit 1
fi

echo "Phone number from .env: $SIGNAL_PHONE_NUMBER"
echo ""

# Check if signal-cli-rest-api is running
echo "🔍 Checking if signal-cli-rest-api is running..."
if ! curl -s http://localhost:8080/v1/about > /dev/null 2>&1; then
    echo "⚠️  signal-cli-rest-api is not running. Starting it now..."

    # Detect Docker or Podman
    if command -v podman &> /dev/null; then
        CONTAINER_CMD="podman"
    elif command -v docker &> /dev/null; then
        CONTAINER_CMD="docker"
    else
        echo "❌ Error: Neither Docker nor Podman found"
        exit 1
    fi

    # Start signal-cli-rest-api
    $CONTAINER_CMD run -d --name signal-api \
        -p 8080:8080 \
        -v $HOME/.local/share/signal-api:/home/.local/share/signal-cli \
        -e 'MODE=json-rpc' \
        bbernhard/signal-cli-rest-api

    echo "⏳ Waiting for signal-cli-rest-api to start..."
    sleep 5
fi

echo "✅ signal-cli-rest-api is running"
echo ""

# Check if already registered
echo "🔍 Checking registration status..."
REGISTERED=$(curl -s http://localhost:8080/v1/accounts)

if echo "$REGISTERED" | grep -q "$SIGNAL_PHONE_NUMBER"; then
    echo "✅ This number is already registered with Signal!"
    echo ""
    echo "You can now start the bot with: ./start.sh"
    exit 0
fi

echo "📝 Number is not registered yet. Starting registration process..."
echo ""

# Step 1: Get captcha token
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔐 CAPTCHA REQUIRED"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Signal requires a captcha for new registrations."
echo ""
echo "Steps to get the captcha token:"
echo "1. Open this URL in your browser:"
echo "   https://signalcaptchas.org/registration/generate.html"
echo ""
echo "2. Complete the captcha challenge"
echo ""
echo "3. After solving, right-click the 'Open Signal' button"
echo ""
echo "4. Select 'Copy Link Address'"
echo "   The link looks like: signalcaptcha://signal-recaptcha-v2.LONG_TOKEN_HERE"
echo ""
echo "5. Paste the ENTIRE link below"
echo ""
read -p "Paste the captcha link: " CAPTCHA_LINK

# Extract just the token part after the signalcaptcha://
CAPTCHA_TOKEN=$(echo "$CAPTCHA_LINK" | sed 's/signalcaptcha:\/\///')

if [ -z "$CAPTCHA_TOKEN" ]; then
    echo "❌ Error: Invalid captcha link"
    exit 1
fi

echo ""
echo "✅ Captcha token received"
echo ""

# Step 2: Register the number with captcha
echo "Step 2: Registering $SIGNAL_PHONE_NUMBER with Signal..."
echo ""

REGISTER_RESPONSE=$(curl -X POST -H "Content-Type: application/json" \
    -d "{\"number\":\"$SIGNAL_PHONE_NUMBER\", \"use_voice\":false, \"captcha\":\"$CAPTCHA_TOKEN\"}" \
    http://localhost:8080/v1/register/$SIGNAL_PHONE_NUMBER 2>/dev/null)

if echo "$REGISTER_RESPONSE" | grep -q "error"; then
    echo "❌ Registration failed!"
    echo "Response: $REGISTER_RESPONSE"
    echo ""
    echo "Common issues:"
    echo "- Captcha may have expired (they expire quickly - try again)"
    echo "- Make sure you copied the entire link including 'signalcaptcha://'"
    exit 1
fi

echo "✅ Registration request sent!"
echo ""

# Step 3: Wait for verification code
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📬 IMPORTANT: Check your Twilio account for the SMS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Signal will send a 6-digit verification code to your Twilio number."
echo ""
echo "To get the code:"
echo "1. Go to: https://console.twilio.com/us1/monitor/logs/sms"
echo "2. Look for the most recent incoming SMS"
echo "3. Copy the 6-digit verification code"
echo ""
read -p "Enter the 6-digit verification code: " VERIFICATION_CODE

# Step 4: Verify the code
echo ""
echo "🔐 Verifying code $VERIFICATION_CODE..."

VERIFY_RESPONSE=$(curl -X POST -H "Content-Type: application/json" \
    http://localhost:8080/v1/register/$SIGNAL_PHONE_NUMBER/verify/$VERIFICATION_CODE 2>/dev/null)

if echo "$VERIFY_RESPONSE" | grep -q "error"; then
    echo "❌ Verification failed!"
    echo "Response: $VERIFY_RESPONSE"
    echo ""
    echo "Please check the code and try again by running this script again."
    exit 1
fi

echo "✅ Verification successful!"
echo ""

# Step 5: Set a profile name (optional but recommended)
echo "📝 Setting up Signal profile..."
read -p "Enter a display name for your bot (e.g., 'AI Bot'): " BOT_NAME

if [ ! -z "$BOT_NAME" ]; then
    curl -X PUT -H "Content-Type: application/json" \
        -d "{\"name\":\"$BOT_NAME\"}" \
        http://localhost:8080/v1/profiles/$SIGNAL_PHONE_NUMBER 2>/dev/null
    echo "✅ Profile name set to: $BOT_NAME"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉 Signal registration complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Your bot is now registered with Signal!"
echo "You can start the bot with: ./start.sh"
echo ""
echo "To test it, send a message to $SIGNAL_PHONE_NUMBER from your Signal app"
echo ""
