import os
import json
import prompts
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Use environment variables with localhost as fallback
WS_BASE_URL = os.environ.get("WS_BASE_URL", "ws://localhost:8080")
HTTP_BASE_URL = os.environ.get("HTTP_BASE_URL", "http://localhost:8080")

# Load configuration from config.json
config_path = Path(__file__).parent.parent / "config.json"
try:
    with open(config_path, 'r') as f:
        CONFIG = json.load(f)
except FileNotFoundError:
    print(f"Warning: config.json not found at {config_path}, using defaults")
    CONFIG = {
        "bots": [],
        "max_history_messages": 200,
        "group_privacy_mode": "opt-in",
        "trusted_phone_numbers": [],
        "session_timeout": 30,
        "default_model": "(6) claude-haiku-4-5-20251001",
        "default_system_instruction": "(1) Standard",
        "default_image_size": "(5) portrait_3_4",
        "lora_path_to_url": {},
        "prompt_replace_dict": {}
    }
except json.JSONDecodeError as e:
    print(f"Error: Failed to parse config.json: {e}")
    exit(1)

# Extract bot instances from config.json
BOT_INSTANCES = CONFIG.get("bots", [])

# Load phone numbers from .env
bot_phone_numbers_env = os.environ.get("BOT_PHONE_NUMBERS", "")
bot_phones = [p.strip() for p in bot_phone_numbers_env.split(",") if p.strip()]

# Merge phone numbers with bot configs
if bot_phones:
    if len(bot_phones) != len(BOT_INSTANCES):
        print(f"Warning: Number of phone numbers ({len(bot_phones)}) doesn't match number of bots ({len(BOT_INSTANCES)})")
        print(f"Using first {min(len(bot_phones), len(BOT_INSTANCES))} entries")

    # Add phone numbers to bot configs by index
    for i, phone in enumerate(bot_phones):
        if i < len(BOT_INSTANCES):
            BOT_INSTANCES[i]["phone"] = phone
else:
    # Legacy fallback: check for SIGNAL_PHONE_NUMBER in environment
    SIGNAL_PHONE_NUMBER = os.environ.get("SIGNAL_PHONE_NUMBER")
    BOT_NAME = os.environ.get("BOT_NAME", "AI Bot")
    if SIGNAL_PHONE_NUMBER:
        print(f"Warning: Using legacy SIGNAL_PHONE_NUMBER from .env. Consider using BOT_PHONE_NUMBERS instead")
        BOT_INSTANCES = [{
            "phone": SIGNAL_PHONE_NUMBER,
            "name": BOT_NAME,
            "model": None,
            "prompt": None
        }]

if not BOT_INSTANCES:
    print("Error: No bot instances configured. Please configure bots in config.json and BOT_PHONE_NUMBERS in .env")
    exit(1)

# Verify all bots have phone numbers
for i, bot in enumerate(BOT_INSTANCES):
    if "phone" not in bot or not bot["phone"]:
        print(f"Error: Bot at index {i} ('{bot.get('name', 'unnamed')}') is missing a phone number")
        print(f"Please add phone number to BOT_PHONE_NUMBERS in .env")
        exit(1)

# Create a mapping of phone number to bot config
BOT_CONFIGS = {bot["phone"]: bot for bot in BOT_INSTANCES}

# For legacy compatibility, set SIGNAL_PHONE_NUMBER to first bot's phone
SIGNAL_PHONE_NUMBER = BOT_INSTANCES[0]["phone"]

# Load configuration values
SESSION_TIMEOUT = CONFIG.get("session_timeout", 30)
MAX_HISTORY_MESSAGES = CONFIG.get("max_history_messages", 200)
GROUP_PRIVACY_MODE = CONFIG.get("group_privacy_mode", "opt-in").lower()
TRUSTED_PHONE_NUMBERS = CONFIG.get("trusted_phone_numbers", [])
VALID_MODELS = [
    "(1) gemini-1.5-flash-8b",
    "(2) gemini-1.5-flash-002",
    "(3) gemini-1.5-pro-002",
    "(4) claude-3-haiku-20240307",
    "(5) claude-3-5-haiku-20241022",
    "(6) claude-haiku-4-5-20251001",
    "(7) claude-3-opus-20240229",
    "(8) claude-3-7-sonnet-20250219",
    "(9) claude-sonnet-4-20250514",
    "(10) claude-sonnet-4-5-20250929",
    "(11) claude-opus-4-20250514",
    "(12) claude-opus-4-1-20250805",
    "(13) bedrock-claude-3-haiku-20240307",
    "(14) bedrock-claude-3-sonnet-20240229",
    "(15) bedrock-claude-3-5-haiku-20241022",
    "(16) bedrock-claude-3-5-sonnet-20240620",
    "(17) bedrock-claude-3-5-sonnet-20241022",
    "(18) bedrock-claude-3-7-sonnet-20250219",
]
DEFAULT_MODEL = CONFIG.get("default_model", "(6) claude-haiku-4-5-20251001")
LORA_PATH_TO_URL = CONFIG.get("lora_path_to_url", {})
PROMPT_REPLACE_DICT = CONFIG.get("prompt_replace_dict", {})
RANDOM_REPLY_CHANCE = CONFIG.get("random_reply_chance", 0)  # Set to N for 1 in N chance (0 = disabled)
SPONTANEOUS_REPLY_ENABLED = CONFIG.get("spontaneous_reply_enabled", False)
SPONTANEOUS_REPLY_MIN_INTERVAL_HOURS = CONFIG.get("spontaneous_reply_min_interval_hours", 2)
SPONTANEOUS_REPLY_MEAN_INTERVAL_HOURS = CONFIG.get("spontaneous_reply_mean_interval_hours", 6)
IMAGE_SIZES = {
    "(1) square": {"width": 512, "height": 512},
    "(2) square_hd": {"width": 1024, "height": 1024},
    "(3) landscape_4_3": {"width": 1024, "height": 768},
    "(4) landscape_16_9": {"width": 1024, "height": 576},
    "(5) portrait_3_4": {"width": 768, "height": 1024},
    "(6) portrait_9_16": {"width": 576, "height": 1024},
}
default_image_size_key = CONFIG.get("default_image_size", "(5) portrait_3_4")
DEFAULT_IMAGE_SIZE = IMAGE_SIZES.get(default_image_size_key, IMAGE_SIZES["(5) portrait_3_4"])
OUTPUT_DIR = "generated_images"
DEFAULT_LORA_SCALE = 1
DEFAULT_IMG_API_ENDPOINT = "fal-ai/flux-pro/v1.1"  # alternative: fal-ai/flux/schnell


SYSTEM_INSTRUCTIONS = {
    "(1) Standard": None,
    "(2) Smileys": prompts.smileys,
    "(3) Close Friend": prompts.close_friend,
    "(4) Plant": prompts.plant,
    "(5) Spiritual Guide": prompts.spiritual_guide,
    "(6) Wittgenstein": prompts.wittgenstein,
}
DEFAULT_SYSTEM_INSTRUCTION = SYSTEM_INSTRUCTIONS["(1) Standard"]
