import io
import os
from datetime import datetime
from typing import Dict
from PIL import Image
import requests
import google.generativeai as genai
import anthropic
import fal_client
import config
from config import *
from user import User

genai.configure(api_key=os.environ["GOOGLE_AI_STUDIO_API"])
anthropic_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

users = {}
bot_uuid_cache = {}  # Cache for bot phone -> UUID mapping
group_histories = {}  # Shared conversation history for group chats: {group_id: [messages]}

def get_bot_uuid(bot_phone):
    """Get the UUID for a bot's phone number by querying Signal API"""
    if bot_phone in bot_uuid_cache:
        return bot_uuid_cache[bot_phone]

    # Try to get UUID from accounts endpoint
    try:
        url = f"{HTTP_BASE_URL}/v1/accounts"
        response = requests.get(url)
        response.raise_for_status()
        accounts = response.json()

        # The accounts endpoint only returns phone numbers, not UUIDs
        # We need to check the local data directory for UUIDs
        import json
        from pathlib import Path

        accounts_file = Path.home() / ".local/share/signal-api/data/accounts.json"
        if accounts_file.exists():
            with open(accounts_file, 'r') as f:
                data = json.load(f)
                for account in data.get("accounts", []):
                    if account.get("number") == bot_phone:
                        uuid = account.get("uuid")
                        if uuid:
                            bot_uuid_cache[bot_phone] = uuid
                            return uuid
    except Exception as e:
        print(f"Warning: Could not fetch UUID for {bot_phone}: {e}")

    return None

# Build formatted lists for help message
models_list = '\n  '.join(VALID_MODELS)
prompts_list = '\n  '.join(SYSTEM_INSTRUCTIONS.keys())
sizes_list = '\n  '.join(IMAGE_SIZES.keys())

def get_help_message(privacy_mode):
    """Generate help message based on current privacy mode"""
    if privacy_mode == "opt-in":
        privacy_help = """💬 Group Chat Usage (Opt-In Mode):
- @mention the bot to use commands or get responses
- Prefix messages with . (dot) to include in conversation history without response
- Messages without mention or . prefix are ignored (privacy-first)"""
    else:
        privacy_help = """💬 Group Chat Usage (Opt-Out Mode):
- @mention the bot to use commands or get responses
- Bot sees and learns from all group messages
- Prefix messages with . (dot) to exclude from conversation history"""

    return f"""
📋 Available Commands:
- !help: Show this help message
- !cp <number>: Change system prompt
- !cm <number>: Change AI model
- !cup <text>: Set a custom system prompt
- !im <prompt>: Generate an image
- !is <number>: Change image size
- !privacy <opt-in|opt-out>: Change privacy mode for this chat

{privacy_help}

🤖 Available Models:
  {models_list}

💭 System Prompts:
  {prompts_list}

📐 Image Sizes:
  {sizes_list}
"""


def download_attachment(attachment_id: str):
    url = f"{HTTP_BASE_URL}/v1/attachments/{attachment_id}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.content
    except requests.RequestException as e:
        print(f"Error downloading attachment: {e}")
        return None


def get_group_id_from_internal(internal_id: str, bot_phone: str):
    """Convert internal group ID to the proper Signal API group ID"""
    url = f"{HTTP_BASE_URL}/v1/groups/{bot_phone}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        groups = response.json()

        # Find the group with matching internal_id
        for group in groups:
            if group.get("internal_id") == internal_id:
                return group.get("id")

        # If not found, return the internal_id with group. prefix as fallback
        return f"group.{internal_id}" if not internal_id.startswith("group.") else internal_id
    except requests.RequestException as e:
        print(f"Error fetching groups: {e}")
        # Fallback
        return f"group.{internal_id}" if not internal_id.startswith("group.") else internal_id


def get_or_create_user(sender, group_id=None, bot_phone=None):
    # Create unique key: always include bot_phone to keep bot contexts separate
    # Format: "bot_phone:sender" or "bot_phone:group_id"
    base_key = group_id if group_id else sender
    user_key = f"{bot_phone}:{base_key}"

    if user_key not in users:
        # Get bot-specific defaults
        bot_config = config.BOT_CONFIGS.get(bot_phone, {})
        default_model = bot_config.get("model") or DEFAULT_MODEL
        default_prompt_key = bot_config.get("prompt")

        # Resolve prompt key to actual prompt
        if default_prompt_key and default_prompt_key in SYSTEM_INSTRUCTIONS:
            default_prompt = SYSTEM_INSTRUCTIONS[default_prompt_key]
        else:
            default_prompt = DEFAULT_SYSTEM_INSTRUCTION

        users[user_key] = User(sender, default_prompt, default_model, group_id=group_id, bot_phone=bot_phone)
    return users[user_key]


def handle_change_prompt_cmd(user, system_instruction_number):
    if system_instruction_number.isdigit() and 1 <= int(
        system_instruction_number
    ) <= len(SYSTEM_INSTRUCTIONS):
        system_prompt_name = list(SYSTEM_INSTRUCTIONS.keys())[
            int(system_instruction_number) - 1
        ]
        print(system_prompt_name)
        user.set_system_instruction(SYSTEM_INSTRUCTIONS[system_prompt_name])
        user.send_message(f'System prompt changed to "{system_prompt_name}"')
    else:
        prompts_list = '\n'.join(SYSTEM_INSTRUCTIONS.keys())
        user.send_message(f"Available system prompts:\n{prompts_list}")


def handle_change_model_cmd(user, ai_model_number):
    if ai_model_number.isdigit() and 1 <= int(ai_model_number) <= len(VALID_MODELS):
        user.set_model(VALID_MODELS[int(ai_model_number) - 1])
        user.send_message(f'AI model changed to: "{user.current_model}"')
    else:
        models_list = '\n'.join(VALID_MODELS)
        user.send_message(f"Available AI models:\n{models_list}")


def handle_custom_prompt_cmd(user, custom_prompt):
    if custom_prompt == "":
        user.send_message("Please provide a custom prompt.")
    else:
        user.set_system_instruction(custom_prompt)
        user.send_message(
            f"System prompt changed to:\n{user.current_system_instruction}"
        )


def handle_image_size_cmd(user, size_number):
    if size_number.isdigit() and 1 <= int(size_number) <= len(IMAGE_SIZES):
        image_size_name = list(IMAGE_SIZES.keys())[int(size_number) - 1]
        user.set_image_size(IMAGE_SIZES[image_size_name])
        user.send_message(
            f'Image size changed to: "{image_size_name}" with {user.image_size})'
        )
    else:
        sizes_list = '\n'.join(IMAGE_SIZES.keys())
        user.send_message(f"Invalid image size. Available sizes:\n{sizes_list}")


def handle_privacy_cmd(user, mode):
    mode = mode.lower().strip()
    if user.set_privacy_mode(mode):
        user.send_message(f'Privacy mode changed to: "{mode}"')
    else:
        user.send_message("Invalid privacy mode. Use 'opt-in' or 'opt-out'.")


def handle_generate_image_cmd(user, prompt):
    for old_word, new_word in PROMPT_REPLACE_DICT.items():
        prompt = prompt.replace(old_word, new_word)

    lora_arguments = []
    for lora_name in LORA_PATH_TO_URL.keys():
        if lora_name in prompt:
            lora_arguments.append(
                {"path": LORA_PATH_TO_URL[lora_name], "scale": DEFAULT_LORA_SCALE}
            )

    api_endpoint = (
        DEFAULT_IMG_API_ENDPOINT if len(lora_arguments) == 0 else "fal-ai/flux-lora"
    )

    arguments = {
        "prompt": prompt,
        "image_size": user.image_size,
        "num_images": 1,
        "enable_safety_checker": False,
        "output_format": "png",
    }

    if api_endpoint == "fal-ai/flux/schnell":
        arguments = {
            **arguments,
            "num_inference_steps": 4,
        }
    elif api_endpoint == "fal-ai/flux-lora":
        arguments = {
            **arguments,
            "num_inference_steps": 28,
            "guidance_scale": 3.5,
            "loras": lora_arguments,
        }
    elif api_endpoint == "fal-ai/flux-pro/v1.1":
        arguments = {**arguments, "num_inference_steps": 28, "guidance_scale": 3.5}
    else:
        raise Exception(f"unknown fal.ai API endpoint: {api_endpoint}")

    print("Generating an image with these arguments:", arguments)

    handler = fal_client.submit(api_endpoint, arguments)

    result = handler.get()

    if "images" in result and result["images"]:
        image_data = result["images"][0]
        response = requests.get(image_data["url"])
        if response.status_code == 200:
            user.send_message("", attachment=response.content)
    else:
        user.send_message("Failed to generate the image.")


def handle_ai_message(user, content, attachments, sender_name=None, should_respond=True):
    # Prepend sender name to content for group chats
    if user.group_id and sender_name:
        # For group chats, prefix the message with the sender's name
        if content:
            content = f"[{sender_name}]: {content}"
        else:
            content = f"[{sender_name}] sent an image"

    message_components = [content] if content else []

    model_name = user.current_model.split(" ")[1]
    is_claude = model_name.startswith("claude-")

    # Process attachments for image understanding
    image_contents = []
    for attachment in attachments:
        attachment_id = attachment.get("id")
        if attachment_id:
            attachment_data = download_attachment(attachment_id)
            if attachment_data:
                if is_claude:
                    # Claude expects base64-encoded images
                    import base64
                    image = Image.open(io.BytesIO(attachment_data))
                    # Convert to bytes
                    img_byte_arr = io.BytesIO()
                    image.save(img_byte_arr, format=image.format or 'PNG')
                    img_byte_arr = img_byte_arr.getvalue()

                    image_contents.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": f"image/{(image.format or 'png').lower()}",
                            "data": base64.b64encode(img_byte_arr).decode('utf-8')
                        }
                    })
                else:
                    # Gemini uses PIL Image objects
                    image = Image.open(io.BytesIO(attachment_data))
                    message_components.append(image)

    if message_components or image_contents:
        try:
            if is_claude:
                # Handle Claude API
                chat = user.get_or_create_chat_session()

                # Build the message content
                claude_message_content = []
                if image_contents:
                    claude_message_content.extend(image_contents)
                if content:
                    claude_message_content.append({"type": "text", "text": content})

                # For group chats, use shared history; for DMs, use user-specific history
                if user.group_id:
                    # Initialize shared group history if needed
                    if user.group_id not in group_histories:
                        group_histories[user.group_id] = []

                    # Add user message to shared group history
                    group_histories[user.group_id].append({
                        "role": "user",
                        "content": claude_message_content
                    })

                    # Trim shared history
                    if len(group_histories[user.group_id]) > config.MAX_HISTORY_MESSAGES:
                        group_histories[user.group_id] = group_histories[user.group_id][-config.MAX_HISTORY_MESSAGES:]
                        print(f"DEBUG - Trimmed shared group history to last {config.MAX_HISTORY_MESSAGES} messages")

                    # Use shared history for this conversation
                    conversation_history = group_histories[user.group_id]
                else:
                    # For DMs, use individual history
                    user.claude_history.append({
                        "role": "user",
                        "content": claude_message_content
                    })

                    # Trim individual history
                    if len(user.claude_history) > config.MAX_HISTORY_MESSAGES:
                        user.claude_history = user.claude_history[-config.MAX_HISTORY_MESSAGES:]
                        print(f"DEBUG - Trimmed history to last {config.MAX_HISTORY_MESSAGES} messages")

                    conversation_history = user.claude_history

                # If we shouldn't respond (not mentioned in group), just add to history and return
                if not should_respond:
                    print(f"DEBUG - Message added to history but not responding (not mentioned)")
                    return

                # Build system prompt - add group chat context if needed
                if user.group_id:
                    # Extract clean model name for identity
                    clean_model_name = '-'.join(model_name.split('-')[:-1]) if model_name.split('-')[-1].isdigit() else model_name

                    if user.current_system_instruction:
                        system_prompt = f"{user.current_system_instruction}\n\nNote: You are [{clean_model_name}]. You are in a group chat with users and other AIs. Messages are prefixed with [username/AI name] to indicate the participant."
                    else:
                        system_prompt = f"You are [{clean_model_name}]. You are in a group chat with users and other AIs. Messages are prefixed with [username/AI name] to indicate the participant."
                else:
                    system_prompt = user.current_system_instruction if user.current_system_instruction else None

                # Debug: Print what we're sending to Claude
                print(f"DEBUG - System prompt: {system_prompt}")
                print(f"DEBUG - Messages being sent: {conversation_history}")

                # Make API call with conversation history
                api_params = {
                    "model": model_name,
                    "max_tokens": 4096,
                    "messages": conversation_history
                }
                if system_prompt:
                    api_params["system"] = system_prompt

                response = anthropic_client.messages.create(**api_params)

                print(f"DEBUG - Claude's raw response: {response.content[0].text}")

                ai_response = response.content[0].text

                # Strip any [prefix]: that Claude might have added despite instructions
                import re
                ai_response = re.sub(r'^\[.*?\]:\s*', '', ai_response).strip()

                print(f"DEBUG - After stripping prefix: {ai_response}")

                # For group chats, add model name prefix to history (helps track which model said what)
                if user.group_id:
                    # Extract clean model name without date suffix
                    clean_model_name = '-'.join(model_name.split('-')[:-1]) if model_name.split('-')[-1].isdigit() else model_name
                    history_response = f"[{clean_model_name}]: {ai_response}"
                else:
                    history_response = ai_response

                # Add assistant response to history
                if user.group_id:
                    # Add to shared group history
                    group_histories[user.group_id].append({
                        "role": "assistant",
                        "content": history_response
                    })
                else:
                    # Add to individual history
                    user.claude_history.append({
                        "role": "assistant",
                        "content": history_response
                    })

            else:
                # Handle Gemini API (original code)
                chat = user.get_or_create_chat_session()
                response = chat.send_message(message_components)
                ai_response = response.text

        except Exception as e:
            print(f"Error generating AI response: {e}")
            ai_response = "Sorry, I couldn't generate a response at this time."

        # Send the clean response (without prefix) to the user
        user.send_message(ai_response)
    else:
        user.send_message("I received your message, but it seems to be empty.")


def process_message(message: Dict, bot_phone: str = None):
    if "envelope" not in message or "dataMessage" not in message["envelope"]:
        return

    # Use bot_phone if provided, otherwise fall back to config
    if bot_phone is None:
        bot_phone = config.SIGNAL_PHONE_NUMBER

    sender = message["envelope"]["source"]
    sender_uuid = message["envelope"].get("sourceUuid", "")
    sender_name = message["envelope"].get("sourceName", "")  # This might have the profile name
    content = message["envelope"]["dataMessage"].get("message", "") or ""
    timestamp = datetime.fromtimestamp(message["envelope"]["timestamp"] / 1000.0)
    attachments = message["envelope"]["dataMessage"].get("attachments", [])
    mentions = message["envelope"]["dataMessage"].get("mentions", [])

    # Check if this is a group message
    group_info = message["envelope"]["dataMessage"].get("groupInfo")
    group_id = None
    if group_info and "groupId" in group_info:
        # Convert internal group ID to proper Signal API group ID
        internal_group_id = group_info["groupId"]
        group_id = get_group_id_from_internal(internal_group_id, bot_phone)
        display_sender = sender_name if sender_name else sender
        print(f"Received GROUP message from {display_sender} ({sender_uuid[:8]}...) in {group_id[:30]}... at {timestamp}: {content}")
        print(f"DEBUG - Mentions: {mentions}")

        # In group chats, only respond if the bot is mentioned
        bot_mentioned = False
        if mentions:
            # Get this bot's UUID for comparison
            bot_uuid = get_bot_uuid(bot_phone)
            print(f"DEBUG - Bot UUID for {bot_phone}: {bot_uuid}")

            # Check if any mention is for the bot (by UUID or phone number)
            for mention in mentions:
                # Mentions can have 'uuid' or 'number' field
                mention_uuid = mention.get("uuid")
                mention_number = mention.get("number")
                print(f"DEBUG - Checking mention: uuid={mention_uuid}, number={mention_number}")

                # Check if the mention matches this bot's phone number
                if mention_number == bot_phone:
                    bot_mentioned = True
                    print(f"DEBUG - Bot was mentioned by phone number!")
                    break

                # Check if the mention matches this bot's UUID
                if bot_uuid and mention_uuid == bot_uuid:
                    bot_mentioned = True
                    print(f"DEBUG - Bot was mentioned by UUID!")
                    break

        # Store these for later privacy check (after user creation)
        is_group_chat = True
    else:
        display_sender = sender_name if sender_name else sender
        print(f"Received message from {display_sender} ({sender}) at {timestamp}: {content}")
        is_group_chat = False
        bot_mentioned = False

    # Handle empty messages (e.g., image-only messages)
    if not content and not attachments:
        return

    # Clean content: Remove object replacement character (￼) that Signal adds for @mentions
    # and strip whitespace
    content = content.replace('\ufffc', '').strip()

    if not content and not attachments:
        return

    # Parse command if there's text content
    if content:
        parts = content.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""
    else:
        # No text, but has attachments - treat as AI message
        command = ""
        args = ""

    # Create or get user object
    user = get_or_create_user(sender, group_id=group_id, bot_phone=bot_phone)

    # Apply privacy filtering for group chats
    if is_group_chat:
        is_command = content.startswith("!")

        # Check if message should be stored in history based on user's privacy mode
        if user.privacy_mode == "opt-in":
            # Opt-in mode: Only store if prefixed with "." OR bot is mentioned
            store_in_history = content.startswith(".") or bot_mentioned
            # Only respond if bot is mentioned (this includes commands)
            should_respond = bot_mentioned

            if not store_in_history:
                print(f"DEBUG - [OPT-IN MODE] Message not prefixed with '.' and not mentioned, ignoring")
                return

            # If message starts with ".", remove the prefix for processing
            if content.startswith("."):
                content = content[1:].lstrip()  # Remove "." and any following spaces
                print(f"DEBUG - [OPT-IN MODE] Opt-in message (started with '.'), storing in history")
        else:
            # Opt-out mode: Store all messages UNLESS prefixed with "."
            if content.startswith("."):
                # User explicitly opted out of this message
                print(f"DEBUG - [OPT-OUT MODE] Message prefixed with '.', ignoring")
                return

            # Store all other messages (commands, mentions, and regular messages)
            store_in_history = True
            # Only respond if bot is mentioned (this includes commands)
            should_respond = bot_mentioned
            print(f"DEBUG - [OPT-OUT MODE] Storing message in history")
    else:
        # DMs always respond
        should_respond = True

    if command == "!help":
        user.send_message(get_help_message(user.privacy_mode))
    elif command == "!cp":
        handle_change_prompt_cmd(user, args)
    elif command == "!cm":
        handle_change_model_cmd(user, args)
    elif command == "!cup":
        handle_custom_prompt_cmd(user, args)
    elif command == "!im" and user.trusted:
        handle_generate_image_cmd(user, args)
    elif command == "!is":
        handle_image_size_cmd(user, args)
    elif command == "!privacy":
        handle_privacy_cmd(user, args)
    else:
        handle_ai_message(user, content, attachments, sender_name=sender_name, should_respond=should_respond)
