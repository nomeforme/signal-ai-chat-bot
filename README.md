# Signal AI Chat Bot

This project implements an AI-powered chatbot that integrates with Signal messenger, allowing users to interact with various AI models (Gemini and Flux right now) through Signal messages.

There is a successor project using a signal bot as an MCP (Model Context Protocol) Client here: [https://github.com/piebro/signal-mcp-client](https://github.com/piebro/signal-mcp-client).

## Features

- Interaction with AI models (Gemini and Claude) via Signal messages
- Image generation capabilities (using Flux and LoRAs)
- Session management for continuous conversations
- Command system for changing bot settings

## Prerequisites

1. A dedicated phone number for the Signal bot
2. A device to link the Signal app to the API
3. [uv](https://docs.astral.sh/uv/) - Fast Python package installer
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
4. [podman](https://podman.io/) or Docker for running signal-cli-rest-api
5. [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api) - The startup script will handle this automatically

## Setup and Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/signal-ai-chat.git
   cd signal-ai-chat
   ```

2. Install dependencies using uv:
   ```bash
   uv sync
   ```

3. Configure environment variables:
   ```bash
   # Copy the example environment file
   cp .env.example .env

   # Edit .env with your actual API keys and phone numbers
   nano .env  # or use your preferred editor
   ```

   Required variables in `.env`:
   - `GOOGLE_AI_STUDIO_API` - Your Google AI Studio API key (for Gemini models)
   - `ANTHROPIC_API_KEY` - Your Anthropic API key (for Claude models)
   - `SIGNAL_PHONE_NUMBER` - Your Signal bot phone number
   - `TRUSTED_PHONE_NUMBERS` - Comma-separated list of trusted phone numbers
   - `FAL_KEY` - (Optional) Your Fal.ai API key for image generation
   - `LORA_PATH_TO_URL` - (Optional) JSON mapping of LoRA trigger words to URLs
   - `PROMPT_REPLACE_DICT` - (Optional) JSON dictionary for prompt replacements

4. Run the Signal AI bot:

   **Option A: Using the startup script (recommended)**
   ```bash
   ./start.sh
   ```

   This script will:
   - Check if `uv` is installed
   - Check if `.env` is configured
   - Create virtual environment and sync dependencies with `uv`
   - Start signal-cli-rest-api (if not already running)
   - Start the Python bot

   **Option B: Manual startup**
   ```bash
   uv run python src/main.py
   ```

   The bot will automatically load environment variables from the `.env` file.

5. Stop the bot:
   ```bash
   # Press Ctrl+C to stop the Python bot

   # To stop the signal-cli-rest-api container:
   ./stop.sh
   ```

## Usage

Once the bot is running, you can interact with it via Signal messages. Available commands include:

- `!help`: Show help message with current settings
- `!cp [prompt_name]`: Change system prompt
- `!cm <model_number>`: Change AI model
- `!cup <custom_prompt>`: Set a custom system prompt
- `!im <prompt>`: Generate an image (trusted users only)
- `!is <size_number>`: Change image size
- `!privacy <opt-in|opt-out>`: Change privacy mode for the current chat

### Group Chat Privacy Modes

The bot supports two privacy modes for group chats:

**Opt-In Mode (default - privacy-first):**
- Only stores messages that start with `.` (dot) OR when bot is @mentioned
- Bot only responds when @mentioned or to commands
- All other messages are completely ignored
- Best for privacy-conscious groups

**Opt-Out Mode (convenience-first):**
- Bot sees and stores ALL group messages in conversation history
- Bot only responds when @mentioned or to commands
- Prefix messages with `.` to explicitly exclude them from history
- Best for casual groups where everyone is comfortable with the bot learning context

You can switch modes anytime with `!privacy opt-in` or `!privacy opt-out`. The setting is per-chat (each group and DM has its own privacy mode).

## Configuration

You can customize various settings in the `config.py` file, including:

- Available AI models (Gemini 1.5 Flash/Pro, Claude 3.5 Haiku/Sonnet, Claude 3.7 Sonnet)
- System instructions/personalities
- Image sizes
- Trusted phone numbers
- API endpoints

### Available Models

The bot supports the following AI models:

**Gemini Models:**
- **(1) gemini-1.5-flash-8b** - Fast, lightweight model
- **(2) gemini-1.5-flash-002** - Balanced model
- **(3) gemini-1.5-pro-002** - Advanced model with higher capabilities

**Claude Haiku Models (Fast & Efficient):**
- **(4) claude-3-haiku-20240307** - Claude 3 Haiku
- **(5) claude-3-5-haiku-20241022** - Claude 3.5 Haiku
- **(6) claude-haiku-4-5-20251001** - Claude 4.5 Haiku (Default - Latest Haiku)

**Claude Sonnet Models (Balanced):**
- **(8) claude-3-7-sonnet-20250219** - Claude 3.7 Sonnet
- **(9) claude-sonnet-4-20250514** - Claude Sonnet 4
- **(10) claude-sonnet-4-5-20250929** - Claude Sonnet 4.5 (Recommended for most use cases)

**Claude Opus Models (Most Capable):**
- **(7) claude-3-opus-20240229** - Claude 3 Opus
- **(11) claude-opus-4-20250514** - Claude Opus 4
- **(12) claude-opus-4-1-20250805** - Claude Opus 4.1 (Best for complex reasoning)

Use `!cm <model_number>` to switch between models during a conversation.

## Future Ideas

- [ ] Run on a Raspberry PI Zero 2W
- [ ] Use function calling for the bot with useful functions
- [ ] Use the bot in groupe chats

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## More Projects

More generative art, statistics or other projects of me can be found here: [piebro.github.io](https://piebro.github.io?ref=github.com/piebro/signal-ai-chat-bot).

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
