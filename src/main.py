import json
import time
import websocket
import multiprocessing
from config import WS_BASE_URL, BOT_INSTANCES
from message_handler import process_message


def run_websocket_for_bot(bot_phone, bot_name):
    """Run WebSocket connection for a single bot in its own process"""
    print(f"[{bot_name}] Process started (PID: {multiprocessing.current_process().pid})")

    retry_count = 0
    MAX_RECONNECT_RETRIES = 3

    def on_open(ws):
        nonlocal retry_count
        print(f"[{bot_name}] WebSocket connection opened")
        retry_count = 0  # Reset on successful connection

    def on_message(ws, message):
        try:
            data = json.loads(message)
            process_message(data, bot_phone)
        except json.JSONDecodeError:
            print(f"[{bot_name}] Failed to decode JSON: {message}")
        except Exception as e:
            import traceback
            print(f"[{bot_name}] Error processing message: {e}")
            print(f"[{bot_name}] Traceback: {traceback.format_exc()}")

    def on_error(ws, error):
        print(f"[{bot_name}] WebSocket Error: {error}")

    def on_close(ws, close_status_code, close_msg):
        print(f"[{bot_name}] WebSocket connection closed: {close_status_code} - {close_msg}")

    # Main reconnection loop
    while True:
        try:
            uri = f"{WS_BASE_URL}/v1/receive/{bot_phone}"

            ws = websocket.WebSocketApp(
                uri,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )

            # Run forever (will exit on connection close)
            ws.run_forever(ping_interval=30, ping_timeout=10)

            # If we get here, connection was closed
            retry_count += 1

            if retry_count >= MAX_RECONNECT_RETRIES:
                print(f"[{bot_name}] Max reconnection retries ({MAX_RECONNECT_RETRIES}) exceeded")
                retry_count = 0  # Reset for next attempt
                time.sleep(30)  # Longer delay after max retries
            else:
                print(f"[{bot_name}] Reconnecting WebSocket (attempt {retry_count}/{MAX_RECONNECT_RETRIES})...")
                time.sleep(5)

        except KeyboardInterrupt:
            print(f"\n[{bot_name}] Received interrupt signal, shutting down...")
            break
        except Exception as e:
            print(f"[{bot_name}] Unexpected error: {e}")
            import traceback
            print(f"[{bot_name}] Traceback: {traceback.format_exc()}")
            time.sleep(5)

    print(f"[{bot_name}] Process terminated")


def main():
    """Main entry point - spawn a process for each bot"""
    if not BOT_INSTANCES:
        print("Error: No bot instances configured. Please configure bots in config.json")
        return

    print(f"Starting {len(BOT_INSTANCES)} bot instance(s) using multiprocessing...")
    print(f"Main process PID: {multiprocessing.current_process().pid}\n")

    # Disable WebSocket debug tracing
    websocket.enableTrace(False)

    # Create a process for each bot
    processes = []

    for bot in BOT_INSTANCES:
        bot_phone = bot["phone"]
        bot_name = bot["name"]

        # Create and start a new process for this bot
        process = multiprocessing.Process(
            target=run_websocket_for_bot,
            args=(bot_phone, bot_name),
            name=f"Bot-{bot_name}",
            daemon=False
        )
        process.start()
        processes.append(process)

        # Brief delay between starting processes
        time.sleep(0.5)

    print(f"\nAll {len(BOT_INSTANCES)} bot process(es) started. Press Ctrl+C to stop.\n")

    # Wait for all processes
    try:
        for process in processes:
            process.join()
    except KeyboardInterrupt:
        print("\n\nShutting down all bot processes...")

        # Terminate all processes
        for process in processes:
            if process.is_alive():
                print(f"Terminating process {process.name} (PID: {process.pid})...")
                process.terminate()

        # Wait for all processes to terminate (with timeout)
        for process in processes:
            process.join(timeout=5)
            if process.is_alive():
                print(f"Force killing process {process.name} (PID: {process.pid})...")
                process.kill()

        print("All bot processes stopped.")


if __name__ == "__main__":
    # Required for multiprocessing on Windows/macOS
    multiprocessing.set_start_method('spawn', force=True)
    main()
