import io
import os
from datetime import datetime
from typing import Dict
from PIL import Image
import requests
import google.generativeai as genai
import anthropic
import boto3
import json as json_module
import fal_client
import config
from config import *
from user import User

genai.configure(api_key=os.environ["GOOGLE_AI_STUDIO_API"])
anthropic_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Initialize Bedrock client (will only be used if AWS credentials are present)
bedrock_client = None
if os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"):
    bedrock_client = boto3.client(
        service_name='bedrock-runtime',
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY")
    )

users = {}
bot_uuid_cache = {}  # Cache for bot phone -> UUID mapping
group_histories = {}  # Shared conversation history for group chats: {group_id: [messages]}
user_name_to_phone = {}  # Cache for mapping display names to phone numbers

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

def detect_mentions_in_text(text, group_id=None):
    """
    Detect bot names and user names in text and return mentions array.
    Returns: (modified_text, mentions_array)

    mentions_array format: [{"start": int, "length": int, "author": "phone_number"}, ...]
    where start and length are in UTF-16 code units
    """
    if not text or not group_id:
        return text, []

    mentions = []
    modified_text = text
    offset = 0  # Track offset as we replace text with mention characters

    # Build a list of names to search for:
    # 1. Bot names from config
    bot_name_to_phone = {}
    for bot in config.BOT_INSTANCES:
        bot_name_to_phone[bot["name"]] = bot["phone"]

    # 2. User names from cache (populated when we see messages)
    # Combine both dictionaries
    name_to_phone = {**bot_name_to_phone, **user_name_to_phone}

    # Sort names by length (longest first) to avoid partial matches
    sorted_names = sorted(name_to_phone.keys(), key=len, reverse=True)

    for name in sorted_names:
        phone = name_to_phone[name]

        # Find all occurrences of this name
        search_pos = 0
        while True:
            pos = modified_text.find(name, search_pos)
            if pos == -1:
                break

            # Check if this is a word boundary (not in middle of another word)
            # Simple heuristic: check character before and after
            before_ok = pos == 0 or modified_text[pos-1] in ' \n\t,.:;!?@'
            after_ok = pos + len(name) >= len(modified_text) or modified_text[pos + len(name)] in ' \n\t,.:;!?'

            if before_ok and after_ok:
                # Calculate UTF-16 position (for proper Signal mention indexing)
                utf16_start = len(modified_text[:pos].encode('utf-16-le')) // 2

                # Replace the name with Signal's object replacement character
                replacement = '\ufffc'  # Object replacement character
                modified_text = modified_text[:pos] + replacement + modified_text[pos + len(name):]

                # Add mention as object (not string) with fields: start, length, author
                # Length is always 1 because we're replacing with single character
                print(f"DEBUG - Creating mention for '{name}' -> phone: {phone}")
                mentions.append({
                    "start": utf16_start,
                    "length": 1,
                    "author": phone
                })

                # Continue search after this replacement
                search_pos = pos + 1
            else:
                search_pos = pos + 1

    return modified_text, mentions

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
    is_bedrock = model_name.startswith("bedrock-")
    is_claude = model_name.startswith("claude-") or is_bedrock

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

                    # Build list of other bots in the chat
                    other_bots = [bot["name"] for bot in config.BOT_INSTANCES if bot["phone"] != user.bot_phone]

                    # Build list of known users from the name cache
                    known_users = [name for name in user_name_to_phone.keys() if name not in [bot["name"] for bot in config.BOT_INSTANCES]]

                    # Create participant list
                    participants = []
                    if other_bots:
                        participants.append(f"Other bots: {', '.join(other_bots)}")
                    if known_users:
                        participants.append(f"Users: {', '.join(known_users)}")

                    participants_text = ". ".join(participants) if participants else "other participants"

                    group_context = f"""You are [{clean_model_name}]. 
                    You are in a group chat with users and other AI bots. 
                    Messages are prefixed with [participant] to indicate the participant. 
                    Be parsimonious, if you wish to directly address another participant (which will notify them), 
                    mention their name in your response. {participants_text}.
                    """

                    if user.current_system_instruction:
                        system_prompt = f"{user.current_system_instruction}\n\n{group_context}"
                    else:
                        system_prompt = group_context
                else:
                    system_prompt = user.current_system_instruction if user.current_system_instruction else None

                # Debug: Print what we're sending to Claude/Bedrock
                print(f"DEBUG - System prompt: {system_prompt}")
                print(f"DEBUG - Messages being sent: {conversation_history}")

                # Make API call with conversation history
                if is_bedrock:
                    # Use AWS Bedrock
                    if not bedrock_client:
                        raise Exception("AWS Bedrock credentials not configured. Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env")

                    # Convert model name to Bedrock format
                    # Claude 3.5 Sonnet v2 (20241022) requires cross-region inference profile
                    # bedrock-claude-3-5-sonnet-20241022 -> us.anthropic.claude-3-5-sonnet-20241022-v2:0
                    # All other models use direct model IDs
                    # bedrock-claude-3-haiku-20240307 -> anthropic.claude-3-haiku-20240307-v1:0
                    base_model = model_name.replace("bedrock-", "")

                    # Claude 3.5 Sonnet October 2024 uses inference profile with v2:0
                    if "claude-3-5-sonnet-20241022" in model_name:
                        bedrock_model_id = f"us.anthropic.{base_model}-v2:0"
                    else:
                        # All other models use direct model ID with v1:0
                        bedrock_model_id = f"anthropic.{base_model}-v1:0"

                    # Prepare Bedrock request body
                    bedrock_body = {
                        "anthropic_version": "bedrock-2023-05-31",
                        "max_tokens": 4096,
                        "messages": conversation_history
                    }
                    if system_prompt:
                        bedrock_body["system"] = system_prompt

                    print(f"DEBUG - Calling Bedrock with model: {bedrock_model_id}")

                    bedrock_response = bedrock_client.invoke_model(
                        modelId=bedrock_model_id,
                        body=json_module.dumps(bedrock_body)
                    )

                    response_body = json_module.loads(bedrock_response['body'].read())
                    print(f"DEBUG - Bedrock raw response: {response_body}")

                    ai_response = response_body['content'][0]['text']
                else:
                    # Use direct Anthropic API
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

        # Detect mentions in the response (for group chats only)
        if user.group_id:
            modified_response, mention_array = detect_mentions_in_text(ai_response, user.group_id)
            if mention_array:
                print(f"DEBUG - Detected mentions in response: {mention_array}")
                print(f"DEBUG - Original: {ai_response}")
                print(f"DEBUG - Modified: {modified_response}")
            user.send_message(modified_response, mentions=mention_array if mention_array else None)
        else:
            # DMs don't need mention detection
            user.send_message(ai_response)
    else:
        user.send_message("I received your message, but it seems to be empty.")


def process_message(message: Dict, bot_phone: str = None):
    if "envelope" not in message:
        print(f"DEBUG - [{bot_phone}] Message missing envelope, skipping")
        return
    if "dataMessage" not in message["envelope"]:
        # Could be a receipt, typing indicator, or other non-data message
        print(f"DEBUG - [{bot_phone}] Message has no dataMessage (likely receipt/typing indicator), skipping")
        return

    # Use bot_phone if provided, otherwise fall back to config
    if bot_phone is None:
        bot_phone = config.SIGNAL_PHONE_NUMBER

    sender = message["envelope"]["source"]
    sender_number = message["envelope"].get("sourceNumber")  # Phone number if available
    sender_uuid = message["envelope"].get("sourceUuid", "")
    sender_name = message["envelope"].get("sourceName", "")  # This might have the profile name
    content = message["envelope"]["dataMessage"].get("message", "") or ""
    timestamp = datetime.fromtimestamp(message["envelope"]["timestamp"] / 1000.0)
    attachments = message["envelope"]["dataMessage"].get("attachments", [])
    mentions = message["envelope"]["dataMessage"].get("mentions", [])
    quote = message["envelope"]["dataMessage"].get("quote")  # Check if this is a reply/quote

    # Log entry to process_message to track which bot is handling this
    print(f"DEBUG - [{bot_phone}] process_message() starting for sender {sender} (number: {sender_number}) at {timestamp}")

    # Cache sender name for mention detection (if we have a name)
    # Prefer sourceNumber over source (which might be UUID)
    sender_phone = sender_number if sender_number else (sender if sender.startswith('+') else None)

    if sender_name and sender_phone:
        user_name_to_phone[sender_name] = sender_phone
        print(f"DEBUG - Cached name '{sender_name}' -> phone: {sender_phone}")

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

        # In group chats, only respond if the bot is mentioned OR quoted
        bot_mentioned = False

        # Check if message is quoting/replying to the bot
        if quote:
            bot_uuid = get_bot_uuid(bot_phone)
            quote_author = quote.get("author")
            quote_author_uuid = quote.get("authorUuid")

            print(f"DEBUG - Message is a reply to: author={quote_author}, uuid={quote_author_uuid}")

            # Check if the quoted message is from this bot
            if quote_author == bot_phone or (bot_uuid and quote_author_uuid == bot_uuid):
                bot_mentioned = True
                print(f"DEBUG - Bot was quoted/replied to!")

        # Check for @mentions
        if mentions and not bot_mentioned:
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
