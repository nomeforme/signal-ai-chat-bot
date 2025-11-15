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

    def _split_message(self, content, max_length=400):
        """Split long messages into chunks to avoid 'see more' in Signal"""
        if not content or len(content) <= max_length:
            return [content] if content else []

        chunks = []
        lines = content.split('\n')
        current_chunk = []
        current_length = 0

        for line in lines:
            line_length = len(line) + 1  # +1 for newline

            # If a single line is longer than max_length, split it by sentences/words
            if line_length > max_length:
                # First, flush current chunk if any
                if current_chunk:
                    chunks.append('\n'.join(current_chunk))
                    current_chunk = []
                    current_length = 0

                # Split long line by sentences
                sentences = line.replace('. ', '.\n').split('\n')
                for sentence in sentences:
                    if len(sentence) > max_length:
                        # If sentence is still too long, split by words
                        words = sentence.split(' ')
                        temp_chunk = []
                        temp_length = 0
                        for word in words:
                            word_length = len(word) + 1
                            if temp_length + word_length > max_length:
                                chunks.append(' '.join(temp_chunk))
                                temp_chunk = [word]
                                temp_length = word_length
                            else:
                                temp_chunk.append(word)
                                temp_length += word_length
                        if temp_chunk:
                            chunks.append(' '.join(temp_chunk))
                    elif current_length + len(sentence) + 1 > max_length:
                        chunks.append('\n'.join(current_chunk))
                        current_chunk = [sentence]
                        current_length = len(sentence)
                    else:
                        current_chunk.append(sentence)
                        current_length += len(sentence) + 1
            elif current_length + line_length > max_length:
                # This line would exceed limit, start new chunk
                chunks.append('\n'.join(current_chunk))
                current_chunk = [line]
                current_length = line_length
            else:
                current_chunk.append(line)
                current_length += line_length

        # Add remaining chunk
        if current_chunk:
            chunks.append('\n'.join(current_chunk))

        return chunks

    def send_message(self, content, attachment=None, mentions=None):
        url = f"{config.HTTP_BASE_URL}/v2/send"

        # If this is a group chat, send to the group; otherwise send to individual
        if self.group_id:
            recipients = [self.group_id]
            recipient_display = f"group {self.group_id[:20]}..."
        else:
            recipients = [self.phone_number]
            recipient_display = self.phone_number

        # Split long messages into multiple chunks
        if isinstance(content, str):
            message_chunks = self._split_message(content)
        else:
            message_chunks = [content] if content else []

        # Send each chunk as a separate message
        for i, chunk in enumerate(message_chunks):
            payload = {
                "number": self.bot_phone,  # Use the bot's phone number
                "recipients": recipients,
                "text_mode": "styled"  # Enable text formatting (bold, italic, monospace, strikethrough)
            }
            if chunk:
                payload["message"] = chunk

            # Only attach file and mentions to the first message
            if i == 0:
                if attachment:
                    encoded = base64.b64encode(attachment).decode("utf-8")
                    payload["base64_attachments"] = [encoded]
                if mentions:
                    payload["mentions"] = mentions

            try:
                response = requests.post(url, json=payload)
                response.raise_for_status()
                if len(message_chunks) > 1:
                    print(f"Message chunk {i+1}/{len(message_chunks)} sent successfully to {recipient_display}")
                else:
                    print(f"Message sent successfully to {recipient_display}")
                if i == 0 and mentions:
                    print(f"DEBUG - Mentions sent: {mentions}")
            except requests.RequestException as e:
                print(f"Error sending message chunk {i+1}: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    print(f"Response status: {e.response.status_code}")
                    print(f"Response content: {e.response.text}")
                print(f"Payload sent: {payload}")
