import io
import os
from datetime import datetime
from typing import Dict
from PIL import Image
import requests
import google.generativeai as genai
import anthropic
import fal_client
from config import *
from user import User

genai.configure(api_key=os.environ["GOOGLE_AI_STUDIO_API"])
anthropic_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

users = {}
HELP_MESSAGE = f"""
Available commands
- !help: Show this help message
- !cp [prompt_name]: Change system prompt: {', '.join(SYSTEM_INSTRUCTIONS.keys())}
- !cm <model_number>: Change AI model {', '.join(VALID_MODELS)}
- !cup <custom_prompt_number>: Set a custom system prompt
- !im <prompt>: Generate an image
- !is <size_numer>: Change image size {', '.join(IMAGE_SIZES.keys())}
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


def get_group_id_from_internal(internal_id: str):
    """Convert internal group ID to the proper Signal API group ID"""
    url = f"{HTTP_BASE_URL}/v1/groups/{SIGNAL_PHONE_NUMBER}"
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


def get_or_create_user(sender, group_id=None):
    # Create unique key: use group_id if it's a group chat, otherwise use sender phone number
    user_key = group_id if group_id else sender

    if user_key not in users:
        users[user_key] = User(sender, DEFAULT_SYSTEM_INSTRUCTION, DEFAULT_MODEL, group_id=group_id)
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


def handle_ai_message(user, content, attachments, sender_name=None):
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

                # Add user message to history
                user.claude_history.append({
                    "role": "user",
                    "content": claude_message_content
                })

                # Build system prompt - add group chat context if needed
                if user.group_id:
                    if user.current_system_instruction:
                        system_prompt = f"{user.current_system_instruction}\n\nNote: You are in a group chat. User messages are prefixed with [username] to indicate who is speaking. Do not include any prefix in your own responses."
                    else:
                        system_prompt = "You are in a group chat. User messages are prefixed with [username] to indicate who is speaking. Do not include any prefix in your own responses."
                else:
                    system_prompt = user.current_system_instruction if user.current_system_instruction else None

                # Debug: Print what we're sending to Claude
                print(f"DEBUG - System prompt: {system_prompt}")
                print(f"DEBUG - Messages being sent: {user.claude_history}")

                # Make API call with conversation history
                api_params = {
                    "model": model_name,
                    "max_tokens": 4096,
                    "messages": user.claude_history
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

                # Add assistant response to history (with model prefix for group chats)
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


def process_message(message: Dict):
    if "envelope" not in message or "dataMessage" not in message["envelope"]:
        return

    sender = message["envelope"]["source"]
    sender_uuid = message["envelope"].get("sourceUuid", "")
    sender_name = message["envelope"].get("sourceName", "")  # This might have the profile name
    content = message["envelope"]["dataMessage"].get("message", "") or ""
    timestamp = datetime.fromtimestamp(message["envelope"]["timestamp"] / 1000.0)
    attachments = message["envelope"]["dataMessage"].get("attachments", [])

    # Check if this is a group message
    group_info = message["envelope"]["dataMessage"].get("groupInfo")
    group_id = None
    if group_info and "groupId" in group_info:
        # Convert internal group ID to proper Signal API group ID
        internal_group_id = group_info["groupId"]
        group_id = get_group_id_from_internal(internal_group_id)
        display_sender = sender_name if sender_name else sender
        print(f"Received GROUP message from {display_sender} ({sender_uuid[:8]}...) in {group_id[:30]}... at {timestamp}: {content}")
    else:
        display_sender = sender_name if sender_name else sender
        print(f"Received message from {display_sender} ({sender}) at {timestamp}: {content}")

    # Handle empty messages (e.g., image-only messages)
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

    user = get_or_create_user(sender, group_id=group_id)

    if command == "!help":
        user.send_message(HELP_MESSAGE)
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
    else:
        handle_ai_message(user, content, attachments, sender_name=sender_name)
