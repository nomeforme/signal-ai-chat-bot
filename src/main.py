import json
import websocket
import threading
import time
from config import WS_BASE_URL, BOT_INSTANCES
from message_handler import process_message


# Global state for tracking WebSocket health
websocket_state = {}  # {bot_phone: {"ws": ws, "thread": thread, "last_message": timestamp, "connected": bool}}
reconnect_lock = threading.Lock()


def create_message_handler(bot_phone):
    """Create a message handler for a specific bot instance"""
    def on_message(ws, message):
        try:
            # Update last message time for liveness check
            with reconnect_lock:
                if bot_phone in websocket_state:
                    websocket_state[bot_phone]["last_message"] = time.time()

            data = json.loads(message)
            # Log message receipt at WebSocket level
            envelope = data.get("envelope", {})
            source = envelope.get("source") or envelope.get("sourceNumber") or "unknown"
            timestamp = envelope.get("timestamp", "unknown")
            data_message = envelope.get("dataMessage", {})
            message_text = data_message.get("message", "")[:50]  # First 50 chars
            print(f"DEBUG - [{bot_phone}] WebSocket received message from {source} at {timestamp}: {message_text}...")
            print(f"DEBUG - [{bot_phone}] About to call process_message()")

            process_message(data, bot_phone)

            print(f"DEBUG - [{bot_phone}] process_message() completed successfully")
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

        # Attempt reconnection
        print(f"[{bot_phone}] Attempting to reconnect in 5 seconds...")
        time.sleep(5)
        reconnect_websocket(bot_phone, bot_name)
    return on_close


def create_open_handler(bot_phone):
    def on_open(ws):
        print(f"[{bot_phone}] WebSocket connection opened")
        # Mark as connected and update last message time
        with reconnect_lock:
            if bot_phone in websocket_state:
                websocket_state[bot_phone]["connected"] = True
                websocket_state[bot_phone]["last_message"] = time.time()
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
                        "bot_name": bot_name
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


def reconnect_websocket(bot_phone, bot_name):
    """Reconnect a WebSocket that has disconnected"""
    with reconnect_lock:
        if bot_phone not in websocket_state:
            print(f"[{bot_phone}] Cannot reconnect - not in websocket_state")
            return

        # Check if already connected
        if websocket_state[bot_phone]["connected"]:
            print(f"[{bot_phone}] Already connected, skipping reconnection")
            return

        print(f"[{bot_phone}] Reconnecting WebSocket...")

        # Close old connection if it exists
        old_ws = websocket_state[bot_phone].get("ws")
        if old_ws:
            try:
                old_ws.close()
            except:
                pass

        # The on_close handler will trigger run_websocket to create a new connection


def check_websocket_health():
    """Monitor WebSocket connections and reconnect if necessary"""
    HEALTH_CHECK_INTERVAL = 60  # Check every 60 seconds
    MESSAGE_TIMEOUT = 300  # If no messages for 5 minutes, consider connection stale

    while True:
        time.sleep(HEALTH_CHECK_INTERVAL)

        current_time = time.time()

        with reconnect_lock:
            for bot_phone, state in websocket_state.items():
                bot_name = state.get("bot_name", "unknown")
                connected = state.get("connected", False)
                last_message = state.get("last_message", 0)
                time_since_message = current_time - last_message

                # Check if connected
                if not connected:
                    print(f"WARNING - [{bot_phone}] ({bot_name}) WebSocket marked as disconnected")
                    continue

                # Check if we've received any messages recently (heartbeat)
                # Note: This might not work well if the group is quiet
                # The ping_interval in run_forever should keep connection alive
                if time_since_message > MESSAGE_TIMEOUT:
                    print(f"INFO - [{bot_phone}] ({bot_name}) No messages for {int(time_since_message)}s (connection may be idle)")

                # Check if thread is alive
                thread = state.get("thread")
                if thread and not thread.is_alive():
                    print(f"WARNING - [{bot_phone}] ({bot_name}) WebSocket thread died! Attempting reconnection...")
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

    print(f"All {len(BOT_INSTANCES)} bot(s) started. Press Ctrl+C to stop.")
    print("WebSocket health monitoring active (checks every 60s)")
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
