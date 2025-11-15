import requests
import base64
from datetime import datetime, timedelta
import google.generativeai as genai
import anthropic
import config


class User:
    def __init__(self, phone_number, default_system_instruction, default_model, group_id=None, bot_phone=None):
        self.phone_number = phone_number
        self.group_id = group_id  # None for individual chats, group ID for group chats
        self.bot_phone = bot_phone or config.SIGNAL_PHONE_NUMBER  # Bot's phone number
        self.current_system_instruction = default_system_instruction
        self.current_model = default_model
        self.trusted = phone_number in config.TRUSTED_PHONE_NUMBERS
        self.last_activity = None
        self.chat_session = None
        self.claude_history = []  # Store Claude conversation history
        self.image_size = config.DEFAULT_IMAGE_SIZE
        # Privacy mode: defaults to config value, but can be overridden per user/group
        self.privacy_mode = config.GROUP_PRIVACY_MODE

    def is_session_inactive(self, timeout=config.SESSION_TIMEOUT):
        if self.last_activity is None:
            return True
        return datetime.now() - self.last_activity > timedelta(minutes=timeout)

    def reset_session(self):
        self.chat_session = None
        self.claude_history = []

    def get_or_create_chat_session(self):
        if self.chat_session is None or self.is_session_inactive():
            model_name = self.current_model.split(" ")[1]
            # Check if it's a Claude model
            if model_name.startswith("claude-"):
                # For Claude, we don't create a session object, just reset history
                self.claude_history = []
                self.chat_session = "claude"  # Marker to indicate Claude is active
            else:
                # Gemini models
                if self.current_system_instruction is None:
                    model = genai.GenerativeModel(model_name=model_name)
                else:
                    model = genai.GenerativeModel(
                        model_name=model_name,
                        system_instruction=self.current_system_instruction,
                    )
                self.chat_session = model.start_chat(history=[])
            self.last_activity = datetime.now()
        return self.chat_session

    def set_model(self, model_name):
        self.current_model = model_name
        self.reset_session()

    def set_system_instruction(self, system_instruction):
        self.current_system_instruction = system_instruction
        self.reset_session()

    def set_image_size(self, size):
        self.image_size = size

    def set_privacy_mode(self, mode):
        """Set privacy mode to 'opt-in' or 'opt-out'"""
        if mode in ["opt-in", "opt-out"]:
            self.privacy_mode = mode
            return True
        return False

    def send_message(self, content, attachment=None, mentions=None):
        url = f"{config.HTTP_BASE_URL}/v2/send"

        # If this is a group chat, send to the group; otherwise send to individual
        if self.group_id:
            recipients = [self.group_id]
            recipient_display = f"group {self.group_id[:20]}..."
        else:
            recipients = [self.phone_number]
            recipient_display = self.phone_number

        payload = {
            "number": self.bot_phone,  # Use the bot's phone number
            "recipients": recipients,
        }
        if isinstance(content, str):
            payload["message"] = content
        if attachment:
            encoded = base64.b64encode(attachment).decode("utf-8")
            payload["base64_attachments"] = [encoded]
        if mentions:
            payload["mentions"] = mentions
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            print(f"Message sent successfully to {recipient_display}")
            if mentions:
                print(f"DEBUG - Mentions sent: {mentions}")
        except requests.RequestException as e:
            print(f"Error sending message: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response status: {e.response.status_code}")
                print(f"Response content: {e.response.text}")
            print(f"Payload sent: {payload}")
