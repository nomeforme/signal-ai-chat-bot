import json
import websocket
import threading
import time
from config import WS_BASE_URL, BOT_INSTANCES
from message_handler import process_message


def create_message_handler(bot_phone):
    """Create a message handler for a specific bot instance"""
    def on_message(ws, message):
        try:
            data = json.loads(message)
            process_message(data, bot_phone)
        except json.JSONDecodeError:
            print(f"[{bot_phone}] Failed to decode JSON: {message}")
        except Exception as e:
            print(f"[{bot_phone}] Error processing message: {e}")
    return on_message


def create_error_handler(bot_phone):
    def on_error(ws, error):
        print(f"[{bot_phone}] WebSocket Error: {error}")
    return on_error


def create_close_handler(bot_phone):
    def on_close(ws, close_status_code, close_msg):
        print(f"[{bot_phone}] WebSocket connection closed: {close_status_code} - {close_msg}")
    return on_close


def create_open_handler(bot_phone, bot_name):
    def on_open(ws):
        print(f"[{bot_phone}] WebSocket connection opened for '{bot_name}'")
    return on_open


if __name__ == "__main__":
    if not BOT_INSTANCES:
        print("Error: No bot instances configured. Please configure bots in config.json")
        exit(1)

    print(f"Starting {len(BOT_INSTANCES)} bot instance(s)...")

    websocket.enableTrace(False)  # Disable tracing

    # Create WebSocket connections for each bot instance
    websockets = []
    threads = []

    for bot in BOT_INSTANCES:
        bot_phone = bot["phone"]
        bot_name = bot["name"]

        ws = websocket.WebSocketApp(
            f"{WS_BASE_URL}/v1/receive/{bot_phone}",
            on_open=create_open_handler(bot_phone, bot_name),
            on_message=create_message_handler(bot_phone),
            on_error=create_error_handler(bot_phone),
            on_close=create_close_handler(bot_phone),
        )

        # Run each WebSocket in its own thread
        thread = threading.Thread(target=ws.run_forever, daemon=False)
        thread.start()
        threads.append(thread)
        websockets.append(ws)

    print(f"All {len(BOT_INSTANCES)} bot(s) started. Press Ctrl+C to stop.")
    print("")

    # Keep main thread alive and wait for all threads
    try:
        for thread in threads:
            thread.join()
    except KeyboardInterrupt:
        print("\n\nShutting down bots...")
        for ws in websockets:
            ws.close()
        print("Bots stopped.")
