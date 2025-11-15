import json
import asyncio
import time
import websocket
from config import WS_BASE_URL, BOT_INSTANCES
from message_handler import process_message, get_bot_uuid


# Global state for tracking WebSocket health
websocket_state = {}  # {bot_phone: {"task": task, "last_message": timestamp, "connected": bool, "retry_count": int, "bot_name": str}}
last_user_message = {}  # Track the last user message: {"message_id": timestamp, "received_by": set(), "data": {}, "mentioned_bots": set()}
pending_messages = {}  # Messages to re-process after reconnection: {bot_phone: [message_data]}
MAX_RECONNECT_RETRIES = 3  # Maximum reconnection attempts before giving up
state_lock = asyncio.Lock()  # Async lock for state management


async def handle_message(data, bot_phone):
    """Process incoming WebSocket message"""
    try:
        envelope = data.get("envelope", {})
        source = envelope.get("source") or envelope.get("sourceNumber") or "unknown"
        timestamp = envelope.get("timestamp", "unknown")
        data_message = envelope.get("dataMessage", {})

        # Track user messages for consistency checking
        if data_message and timestamp != "unknown":
            # Check if this is a user message (not from a bot)
            is_bot_message = False
            async with state_lock:
                for state in websocket_state.values():
                    # Check if source matches any bot UUID
                    if source in [state.get("bot_name", ""), bot_phone]:
                        is_bot_message = True
                        break

            if not is_bot_message:
                # This is a user message, track it
                message_id = f"{source}:{timestamp}"
                is_first_receiver = False

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

                async with state_lock:
                    if message_id not in last_user_message:
                        last_user_message[message_id] = {
                            "timestamp": time.time(),
                            "received_by": set(),
                            "check_scheduled": False,
                            "data": data,  # Store the raw message data
                            "mentioned_bot_uuids": mentioned_bot_uuids
                        }
                        is_first_receiver = True
                    last_user_message[message_id]["received_by"].add(bot_phone)

                    # If this is the first bot to receive this message, schedule a check
                    if is_first_receiver and not last_user_message[message_id]["check_scheduled"]:
                        last_user_message[message_id]["check_scheduled"] = True
                        # Schedule consistency check after 3 seconds
                        asyncio.create_task(schedule_consistency_check(message_id))

        # Process the message
        await asyncio.to_thread(process_message, data, bot_phone)

    except Exception as e:
        import traceback
        print(f"[{bot_phone}] Error processing message: {e}")
        print(f"[{bot_phone}] Traceback: {traceback.format_exc()}")


async def schedule_consistency_check(message_id):
    """Schedule a consistency check after delay"""
    await asyncio.sleep(3.0)
    await check_message_consistency(message_id)


async def check_message_consistency(message_id):
    """Check if all bots received a user message, reconnect mentioned bots that didn't"""
    async with state_lock:
        if message_id not in last_user_message:
            return

        msg_data = last_user_message[message_id]
        received_by = msg_data["received_by"].copy()
        mentioned_bot_uuids = msg_data.get("mentioned_bot_uuids", set()).copy()
        message_data = msg_data.get("data", {})

        # Get all bot phones, names, and UUIDs
        all_bots = {}
        bot_uuid_to_phone = {}
        for phone, state in websocket_state.items():
            all_bots[phone] = state.get("bot_name", "unknown")
            # Get UUID from message_handler's cache
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

                async with state_lock:
                    if bot_phone in websocket_state:
                        bot_name = websocket_state[bot_phone].get("bot_name", "unknown")
                        print(f"  → Reconnecting [{bot_phone}] ({bot_name}) and will re-trigger response")

                        # Cancel the current task to trigger reconnection
                        task = websocket_state[bot_phone].get("task")
                        if task and not task.done():
                            task.cancel()
        else:
            print(f"\nℹ No mentioned bots missed the message, no reconnection needed")

        print(f"{'='*60}\n")
    else:
        # All bots received the message
        print(f"✓ Message consistency OK: {message_id[:40]}... ({len(received_by)}/{len(all_bots)} bots)")


async def send_reconnect_failure_message(bot_phone, bot_name, message_data):
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
        # Run in thread to avoid blocking
        await asyncio.to_thread(requests.post, url, json=payload)
        print(f"[{bot_phone}] Sent reconnection failure message")
    except Exception as e:
        print(f"[{bot_phone}] Failed to send reconnection failure message: {e}")


async def run_websocket(bot_phone, bot_name):
    """Run WebSocket with automatic reconnection using asyncio + websocket-client"""
    retry_count = 0
    ws_instance = None
    loop = asyncio.get_running_loop()

    def create_open_handler(phone):
        def on_open(ws):
            print(f"[{phone}] WebSocket connection opened")
            asyncio.run_coroutine_threadsafe(update_connected_state(phone, True), loop)

            # Process pending messages after reconnection
            if phone in pending_messages and pending_messages[phone]:
                asyncio.run_coroutine_threadsafe(process_pending_messages(phone), loop)
        return on_open

    def create_message_handler(phone):
        def on_message(ws, message):
            try:
                asyncio.run_coroutine_threadsafe(update_last_message_time(phone), loop)
                data = json.loads(message)
                asyncio.run_coroutine_threadsafe(handle_message(data, phone), loop)
            except json.JSONDecodeError:
                print(f"[{phone}] Failed to decode JSON: {message}")
            except Exception as e:
                print(f"[{phone}] Error in message handler: {e}")
        return on_message

    def create_error_handler(phone):
        def on_error(ws, error):
            print(f"[{phone}] WebSocket error: {error}")
        return on_error

    def create_close_handler(phone):
        def on_close(ws, close_status_code, close_msg):
            print(f"[{phone}] WebSocket closed: {close_status_code} - {close_msg}")
            asyncio.run_coroutine_threadsafe(update_connected_state(phone, False), loop)
        return on_close

    async def update_connected_state(phone, connected):
        async with state_lock:
            if phone in websocket_state:
                websocket_state[phone]["connected"] = connected
                websocket_state[phone]["last_message"] = time.time()
                if connected:
                    websocket_state[phone]["retry_count"] = 0

    async def update_last_message_time(phone):
        async with state_lock:
            if phone in websocket_state:
                websocket_state[phone]["last_message"] = time.time()

    async def process_pending_messages(phone):
        if phone in pending_messages and pending_messages[phone]:
            messages_to_process = pending_messages[phone][:]
            pending_messages[phone] = []

            print(f"[{phone}] Re-processing {len(messages_to_process)} pending message(s)...")
            for msg_data in messages_to_process:
                try:
                    await asyncio.to_thread(process_message, msg_data, phone)
                    print(f"[{phone}] ✓ Successfully re-processed pending message")
                except Exception as e:
                    print(f"[{phone}] ⚠ Error re-processing message: {e}")

    while True:
        try:
            async with state_lock:
                websocket_state[bot_phone] = {
                    "task": asyncio.current_task(),
                    "last_message": time.time(),
                    "connected": False,
                    "bot_name": bot_name,
                    "retry_count": retry_count
                }

            uri = f"{WS_BASE_URL}/v1/receive/{bot_phone}"

            # Create WebSocketApp with callbacks
            ws_instance = websocket.WebSocketApp(
                uri,
                on_open=create_open_handler(bot_phone),
                on_message=create_message_handler(bot_phone),
                on_error=create_error_handler(bot_phone),
                on_close=create_close_handler(bot_phone)
            )

            # Run WebSocket in executor (blocking call)
            await loop.run_in_executor(
                None,
                lambda: ws_instance.run_forever(ping_interval=30, ping_timeout=10)
            )

            # If we get here, connection closed
            retry_count += 1
            if retry_count >= MAX_RECONNECT_RETRIES:
                print(f"[{bot_phone}] Max reconnection retries ({MAX_RECONNECT_RETRIES}) exceeded")

                # Send error message if we have pending messages
                if bot_phone in pending_messages and pending_messages[bot_phone]:
                    last_message = pending_messages[bot_phone][-1]
                    await send_reconnect_failure_message(bot_phone, bot_name, last_message)
                    pending_messages[bot_phone] = []

                retry_count = 0  # Reset for next attempt
                await asyncio.sleep(30)  # Longer delay after max retries
            else:
                print(f"[{bot_phone}] Reconnecting WebSocket (attempt {retry_count}/{MAX_RECONNECT_RETRIES})...")
                await asyncio.sleep(5)

        except asyncio.CancelledError:
            print(f"[{bot_phone}] WebSocket task cancelled, reconnecting...")
            if ws_instance:
                ws_instance.close()
            async with state_lock:
                if bot_phone in websocket_state:
                    websocket_state[bot_phone]["connected"] = False
            await asyncio.sleep(1)

        except Exception as e:
            print(f"[{bot_phone}] Unexpected error: {e}")
            import traceback
            print(f"[{bot_phone}] Traceback: {traceback.format_exc()}")
            await asyncio.sleep(5)


async def cleanup_old_messages():
    """Periodically clean up old message tracking"""
    MESSAGE_HISTORY_CLEANUP = 60  # Clean up message tracking older than 60 seconds

    while True:
        await asyncio.sleep(30)  # Run every 30 seconds

        current_time = time.time()
        async with state_lock:
            old_messages = [
                msg_id for msg_id, data in last_user_message.items()
                if current_time - data["timestamp"] > MESSAGE_HISTORY_CLEANUP
            ]
            for msg_id in old_messages:
                del last_user_message[msg_id]


async def health_monitor():
    """Monitor WebSocket connection health"""
    print("Health monitor started - monitoring WebSocket connections")

    while True:
        await asyncio.sleep(30)  # Check every 30 seconds

        async with state_lock:
            for bot_phone, state in websocket_state.items():
                bot_name = state.get("bot_name", "unknown")
                connected = state.get("connected", False)
                task = state.get("task")

                # Check if task is dead
                if task and task.done() and not task.cancelled():
                    exception = task.exception()
                    if exception:
                        print(f"\nWARNING - [{bot_phone}] ({bot_name}) Task failed with exception: {exception}")
                        # Task will auto-restart due to while True loop


async def main():
    """Main async entry point"""
    if not BOT_INSTANCES:
        print("Error: No bot instances configured. Please configure bots in config.json")
        return

    print(f"Starting {len(BOT_INSTANCES)} bot instance(s)...")

    # Create tasks for all bots
    bot_tasks = []
    for bot in BOT_INSTANCES:
        bot_phone = bot["phone"]
        bot_name = bot["name"]

        task = asyncio.create_task(run_websocket(bot_phone, bot_name))
        bot_tasks.append(task)

        # Brief delay between starting connections
        await asyncio.sleep(0.5)

    print(f"\nAll {len(BOT_INSTANCES)} bot(s) started. Press Ctrl+C to stop.")
    print("Smart message consistency checking: ACTIVE")
    print("  → Mentioned bots that miss messages will auto-reconnect and respond")
    print("  → Non-mentioned bots that miss messages will be ignored")
    print("")

    # Start background tasks
    cleanup_task = asyncio.create_task(cleanup_old_messages())
    health_task = asyncio.create_task(health_monitor())

    try:
        # Wait for all tasks (they run forever)
        await asyncio.gather(*bot_tasks, cleanup_task, health_task)
    except asyncio.CancelledError:
        print("\n\nShutting down bots...")
        # Cancel all tasks
        for task in bot_tasks + [cleanup_task, health_task]:
            task.cancel()
        # Wait for cancellation to complete
        await asyncio.gather(*bot_tasks, *[cleanup_task, health_task], return_exceptions=True)
        print("Bots stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nReceived interrupt signal")
