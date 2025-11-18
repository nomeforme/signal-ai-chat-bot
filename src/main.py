import json
import websocket
import threading
import time
from config import WS_BASE_URL, BOT_INSTANCES
from message_handler import process_message


# Global state for tracking WebSocket health
websocket_state = {}  # {bot_phone: {"ws": ws, "thread": thread, "last_message": timestamp, "connected": bool, "retry_count": int}}
reconnect_lock = threading.Lock()
last_user_message = {}  # Track the last user message: {"message_id": timestamp, "received_by": set(), "data": {}, "mentioned_bots": set()}
message_check_lock = threading.Lock()
pending_messages = {}  # Messages to re-process after reconnection: {bot_phone: [message_data]}
MAX_RECONNECT_RETRIES = 3  # Maximum reconnection attempts before giving up


def create_message_handler(bot_phone):
    """Create a message handler for a specific bot instance"""
    def on_message(ws, message):
        try:
            # Update last message time for liveness check
            with reconnect_lock:
                if bot_phone in websocket_state:
                    websocket_state[bot_phone]["last_message"] = time.time()

            data = json.loads(message)
            envelope = data.get("envelope", {})
            source = envelope.get("source") or envelope.get("sourceNumber") or "unknown"
            timestamp = envelope.get("timestamp", "unknown")
            data_message = envelope.get("dataMessage", {})

            # Track user messages for consistency checking
            if data_message and timestamp != "unknown":
                # Check if this is a user message (not from a bot)
                is_bot_message = False
                with reconnect_lock:
                    for state in websocket_state.values():
                        # Check if source matches any bot UUID
                        if source in [state.get("bot_name", ""), bot_phone]:
                            is_bot_message = True
                            break

                is_first_receiver_for_message = False
                if not is_bot_message:
                    # This is a user message, track it
                    message_id = f"{source}:{timestamp}"

                    # Extract mentioned bot UUIDs from the message (both @mentions and replies/quotes)
                    mentioned_bot_uuids = set()

                    # Check for @mentions
                    mentions = data_message.get("mentions", [])
                    for mention in mentions:
                        mention_uuid = mention.get("uuid")
                        if mention_uuid:
                            mentioned_bot_uuids.add(mention_uuid)

                    # Check for quote/reply
                    quote = data_message.get("quote")
                    if quote:
                        quote_author_uuid = quote.get("authorUuid")
                        if quote_author_uuid:
                            mentioned_bot_uuids.add(quote_author_uuid)

                    with message_check_lock:
                        if message_id not in last_user_message:
                            last_user_message[message_id] = {
                                "timestamp": time.time(),
                                "received_by": set(),
                                "check_scheduled": False,
                                "data": data,  # Store the raw message data
                                "mentioned_bot_uuids": mentioned_bot_uuids
                            }
                            is_first_receiver_for_message = True
                        last_user_message[message_id]["received_by"].add(bot_phone)

                        # If this is the first bot to receive this message, schedule a check
                        if is_first_receiver_for_message and not last_user_message[message_id]["check_scheduled"]:
                            last_user_message[message_id]["check_scheduled"] = True
                            # Schedule consistency check in a separate thread after 3 seconds
                            threading.Timer(3.0, check_message_consistency, args=[message_id]).start()

            process_message(data, bot_phone, is_first_receiver=is_first_receiver_for_message)
        except json.JSONDecodeError:
            print(f"[{bot_phone}] Failed to decode JSON: {message}")
        except Exception as e:
            import traceback
            print(f"[{bot_phone}] Error processing message: {e}")
            print(f"[{bot_phone}] Traceback: {traceback.format_exc()}")
    return on_message


def create_error_handler(bot_phone):
    def on_error(ws, error):
        print(f"[{bot_phone}] WebSocket Error: {error}")
        # Mark as disconnected on error
        with reconnect_lock:
            if bot_phone in websocket_state:
                websocket_state[bot_phone]["connected"] = False
    return on_error


def create_close_handler(bot_phone, bot_name):
    def on_close(ws, close_status_code, close_msg):
        print(f"[{bot_phone}] WebSocket connection closed: {close_status_code} - {close_msg}")
        # Mark as disconnected
        with reconnect_lock:
            if bot_phone in websocket_state:
                websocket_state[bot_phone]["connected"] = False

        # Attempt immediate reconnection
        print(f"[{bot_phone}] Attempting to reconnect...")
        reconnect_websocket(bot_phone, bot_name)
    return on_close


def create_open_handler(bot_phone):
    def on_open(ws):
        print(f"[{bot_phone}] WebSocket connection opened")
        # Mark as connected, update last message time, and reset retry count
        with reconnect_lock:
            if bot_phone in websocket_state:
                websocket_state[bot_phone]["connected"] = True
                websocket_state[bot_phone]["last_message"] = time.time()
                websocket_state[bot_phone]["retry_count"] = 0  # Reset on successful connection

        # Process any pending messages for this bot
        if bot_phone in pending_messages and pending_messages[bot_phone]:
            messages_to_process = pending_messages[bot_phone][:]
            pending_messages[bot_phone] = []  # Clear the queue

            print(f"[{bot_phone}] Re-processing {len(messages_to_process)} pending message(s)...")
            for msg_data in messages_to_process:
                try:
                    # Re-trigger message processing (not first receiver for re-processed messages)
                    process_message(msg_data, bot_phone, is_first_receiver=False)
                    print(f"[{bot_phone}] ✓ Successfully re-processed pending message")
                except Exception as e:
                    print(f"[{bot_phone}] ⚠ Error re-processing message: {e}")
    return on_open


def create_websocket(bot_phone, bot_name):
    """Create a new WebSocket connection for a bot"""
    ws = websocket.WebSocketApp(
        f"{WS_BASE_URL}/v1/receive/{bot_phone}",
        on_open=create_open_handler(bot_phone),
        on_message=create_message_handler(bot_phone),
        on_error=create_error_handler(bot_phone),
        on_close=create_close_handler(bot_phone, bot_name),
    )
    return ws


def run_websocket(bot_phone, bot_name):
    """Run WebSocket with automatic reconnection"""
    while True:
        try:
            ws = create_websocket(bot_phone, bot_name)

            # Store in global state
            with reconnect_lock:
                if bot_phone not in websocket_state:
                    websocket_state[bot_phone] = {
                        "ws": ws,
                        "thread": threading.current_thread(),
                        "last_message": time.time(),
                        "connected": False,
                        "bot_name": bot_name,
                        "retry_count": 0
                    }
                else:
                    websocket_state[bot_phone]["ws"] = ws

            # Run forever (will exit on connection close)
            ws.run_forever(ping_interval=30, ping_timeout=10)

            # If we get here, connection was closed
            print(f"[{bot_phone}] WebSocket run_forever exited, will reconnect...")
            time.sleep(5)

        except Exception as e:
            print(f"[{bot_phone}] Exception in WebSocket thread: {e}")
            time.sleep(5)


def check_message_consistency(message_id):
    """Check if all bots received a user message, reconnect mentioned bots that didn't"""
    with message_check_lock:
        if message_id not in last_user_message:
            return

        msg_data = last_user_message[message_id]
        received_by = msg_data["received_by"]
        mentioned_bot_uuids = msg_data.get("mentioned_bot_uuids", set())
        message_data = msg_data.get("data", {})

    # Get all bot phones, names, and UUIDs
    all_bots = {}
    bot_uuid_to_phone = {}
    with reconnect_lock:
        for phone, state in websocket_state.items():
            all_bots[phone] = state.get("bot_name", "unknown")
            # Get UUID from message_handler's cache
            from message_handler import get_bot_uuid
            bot_uuid = get_bot_uuid(phone)
            if bot_uuid:
                bot_uuid_to_phone[bot_uuid] = phone

    missing_bots = set(all_bots.keys()) - received_by

    # Determine which missing bots were mentioned
    mentioned_missing_bots = set()
    for bot_uuid in mentioned_bot_uuids:
        bot_phone = bot_uuid_to_phone.get(bot_uuid)
        if bot_phone and bot_phone in missing_bots:
            mentioned_missing_bots.add(bot_phone)

    if missing_bots:
        print(f"\n{'='*60}")
        print(f"MESSAGE CONSISTENCY CHECK")
        print(f"{'='*60}")
        print(f"Message ID: {message_id}")
        print(f"Received by: {len(received_by)}/{len(all_bots)} bots")

        if mentioned_missing_bots:
            print(f"\n⚠ MENTIONED bots that MISSED the message:")
            for phone in sorted(mentioned_missing_bots):
                bot_name = all_bots.get(phone, "unknown")
                print(f"  ✗ [{phone}] ({bot_name}) - WILL RECONNECT AND RE-TRIGGER")

        other_missing = missing_bots - mentioned_missing_bots
        if other_missing:
            print(f"\nOther bots that missed (not mentioned, ignoring):")
            for phone in sorted(other_missing):
                bot_name = all_bots.get(phone, "unknown")
                print(f"  • [{phone}] ({bot_name})")

        # Only reconnect and re-trigger for mentioned bots that missed the message
        if mentioned_missing_bots:
            print(f"\nReconnecting {len(mentioned_missing_bots)} mentioned bot(s)...")

            for bot_phone in mentioned_missing_bots:
                # Queue the message for re-processing after reconnection
                if bot_phone not in pending_messages:
                    pending_messages[bot_phone] = []
                pending_messages[bot_phone].append(message_data)

                with reconnect_lock:
                    if bot_phone in websocket_state:
                        bot_name = websocket_state[bot_phone].get("bot_name", "unknown")
                        print(f"  → Reconnecting [{bot_phone}] ({bot_name}) and will re-trigger response")

                        ws = websocket_state[bot_phone].get("ws")
                        if ws:
                            try:
                                websocket_state[bot_phone]["connected"] = False
                                ws.close()
                            except Exception as e:
                                print(f"    ⚠ Error closing connection: {e}")
        else:
            print(f"\nℹ No mentioned bots missed the message, no reconnection needed")

        print(f"{'='*60}\n")
    else:
        # All bots received the message
        print(f"✓ Message consistency OK: {message_id[:40]}... ({len(received_by)}/{len(all_bots)} bots)")


def send_reconnect_failure_message(bot_phone, bot_name, message_data):
    """Send a message indicating reconnection failure"""
    import requests
    from config import HTTP_BASE_URL

    envelope = message_data.get("envelope", {})
    group_id = envelope.get("dataMessage", {}).get("groupInfo", {}).get("groupId")

    # Determine recipient
    if group_id:
        # Group message
        recipients = [group_id]
    else:
        # DM - respond to sender
        sender = envelope.get("sourceNumber") or envelope.get("source")
        if not sender:
            print(f"[{bot_phone}] Cannot send failure message - no sender found")
            return
        recipients = [sender]

    error_message = f"[{bot_name}] Sorry, I couldn't reconnect to Signal after {MAX_RECONNECT_RETRIES} attempts. I'll try again next time you mention me."

    try:
        url = f"{HTTP_BASE_URL}/v2/send"
        payload = {
            "number": bot_phone,
            "recipients": recipients,
            "message": error_message,
            "text_mode": "styled"
        }
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print(f"[{bot_phone}] Sent reconnection failure message")
    except Exception as e:
        print(f"[{bot_phone}] Failed to send reconnection failure message: {e}")


def reconnect_websocket(bot_phone, bot_name):
    """Reconnect a WebSocket that has disconnected"""
    with reconnect_lock:
        if bot_phone not in websocket_state:
            print(f"[{bot_phone}] Cannot reconnect - not in websocket_state")
            return False

        # Check if already connected
        if websocket_state[bot_phone]["connected"]:
            print(f"[{bot_phone}] Already connected, skipping reconnection")
            return True

        # Check retry count
        retry_count = websocket_state[bot_phone].get("retry_count", 0)
        if retry_count >= MAX_RECONNECT_RETRIES:
            print(f"[{bot_phone}] Max reconnection retries ({MAX_RECONNECT_RETRIES}) exceeded")

            # Send error message to the group/user if we have pending messages
            if bot_phone in pending_messages and pending_messages[bot_phone]:
                # Get the last pending message to send error response
                last_message = pending_messages[bot_phone][-1]
                send_reconnect_failure_message(bot_phone, bot_name, last_message)

                # Clear pending messages for this bot
                pending_messages[bot_phone] = []

            # Reset retry count for next attempt
            websocket_state[bot_phone]["retry_count"] = 0
            return False

        # Increment retry count
        websocket_state[bot_phone]["retry_count"] = retry_count + 1
        print(f"[{bot_phone}] Reconnecting WebSocket (attempt {websocket_state[bot_phone]['retry_count']}/{MAX_RECONNECT_RETRIES})...")

        # Close old connection if it exists
        old_ws = websocket_state[bot_phone].get("ws")
        if old_ws:
            try:
                old_ws.close()
            except:
                pass

        return True  # Allow reconnection attempt
        # The on_close handler will trigger run_websocket to create a new connection


def check_websocket_health():
    """Monitor WebSocket threads and clean up old message tracking"""
    HEALTH_CHECK_INTERVAL = 30  # Check every 30 seconds
    MESSAGE_HISTORY_CLEANUP = 60  # Clean up message tracking older than 60 seconds

    print(f"Health monitor started - checking for dead threads and cleaning up old message tracking")

    while True:
        time.sleep(HEALTH_CHECK_INTERVAL)

        current_time = time.time()

        # Check for dead threads
        with reconnect_lock:
            for bot_phone, state in list(websocket_state.items()):
                bot_name = state.get("bot_name", "unknown")
                connected = state.get("connected", False)

                # Check if thread is alive
                thread = state.get("thread")
                if thread and not thread.is_alive():
                    print(f"\nWARNING - [{bot_phone}] ({bot_name}) WebSocket thread died! Restarting...")
                    state["connected"] = False
                    # Start a new thread
                    new_thread = threading.Thread(
                        target=run_websocket,
                        args=(bot_phone, bot_name),
                        daemon=False,
                        name=f"WS-{bot_name}"
                    )
                    new_thread.start()
                    state["thread"] = new_thread
                    print(f"  New thread started for {bot_name}\n")

        # Clean up old message tracking
        with message_check_lock:
            old_messages = [
                msg_id for msg_id, data in last_user_message.items()
                if current_time - data["timestamp"] > MESSAGE_HISTORY_CLEANUP
            ]
            for msg_id in old_messages:
                del last_user_message[msg_id]


if __name__ == "__main__":
    if not BOT_INSTANCES:
        print("Error: No bot instances configured. Please configure bots in config.json")
        exit(1)

    print(f"Starting {len(BOT_INSTANCES)} bot instance(s)...")

    websocket.enableTrace(False)  # Disable tracing

    # Start WebSocket connections for each bot
    threads = []

    for bot in BOT_INSTANCES:
        bot_phone = bot["phone"]
        bot_name = bot["name"]

        # Start WebSocket in its own thread with automatic reconnection
        thread = threading.Thread(
            target=run_websocket,
            args=(bot_phone, bot_name),
            daemon=False,
            name=f"WS-{bot_name}"
        )
        thread.start()
        threads.append(thread)

        # Brief delay between starting connections to avoid overwhelming the server
        time.sleep(0.5)

    print(f"\nAll {len(BOT_INSTANCES)} bot(s) started. Press Ctrl+C to stop.")
    print("Smart message consistency checking: ACTIVE")
    print("  → Mentioned bots that miss messages will auto-reconnect and respond")
    print("  → Non-mentioned bots that miss messages will be ignored")
    print("")

    # Start health monitoring thread
    health_thread = threading.Thread(target=check_websocket_health, daemon=True)
    health_thread.start()

    # Keep main thread alive and wait for all threads
    try:
        for thread in threads:
            thread.join()
    except KeyboardInterrupt:
        print("\n\nShutting down bots...")
        with reconnect_lock:
            for bot_phone, state in websocket_state.items():
                ws = state.get("ws")
                if ws:
                    try:
                        ws.close()
                    except:
                        pass
        print("Bots stopped.")
