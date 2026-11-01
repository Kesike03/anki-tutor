# Anki Tutor

Anki Tutor adds a small AI chat panel to Anki's review window. Each card has its own persistent conversation, so you can ask a question, keep reviewing, and pick up where you left off when that card appears again. The panel uses your own API credentials and supports four provider protocols.

## Features

- **Card-aware conversations:** The front, back, deck and template, scheduling settings, and complete review log can be included in the assistant's context. Choose which fields to share before starting a conversation.
- **Image input:** Local PNG, JPEG, GIF, and WebP images on the selected card sides can be sent to vision-capable models. Repeated images are attached only once.
- **One chat per card:** Messages are stored locally for each Anki profile and card. Existing conversations are covered when you return to a card; reveal them or send a new question to continue.
- **Unobtrusive interface:** The right-hand panel can be resized, floated, or closed. Its colors follow Anki's light and dark themes. A button in the floating panel docks it back on the right.
- **Flexible providers:** OpenAI-compatible Chat Completions, OpenAI-compatible Responses, Anthropic Claude Messages, and Google Gemini. The host, path, model ID, and system prompt are editable.
- **Six interface languages:** English by default, plus Japanese, Simplified Chinese, Spanish, French, and German.

## Installation

Anki 24.06 or newer with Qt 6 is required. Download [the latest `.ankiaddon` release](https://github.com/Kesike03/anki-tutor/releases/latest/download/anki-tutor.ankiaddon), then in Anki choose **Tools > Add-ons > Install from file** and restart Anki. To update, install the newer file the same way and restart; Anki preserves the add-on's `user_files` directory.

You can also build the package from this repository with `python scripts/package.py` and install the resulting `dist/anki-tutor.ankiaddon`. No separate Python packages are required inside Anki.

## Getting Started

1. Open a card in Anki's review screen. The tutor appears on the right. If you closed it, enable **Anki Tutor** from Anki's View menu.
2. Open the panel settings. Select an API mode, enter your API key and model ID, and confirm the host and path. The defaults are shown below; replace them for compatible third-party providers.
3. Adjust the system prompt and the context checkboxes as needed. The front, back, images, deck/template, scheduling data, and review history are selected by default.
4. Ask a question. **Enter** sends it; **Shift+Enter** adds a new line. Requests run in the background, so you can continue studying while the response arrives.

| API mode | Default host | Default path | Example model ID |
| --- | --- | --- | --- |
| OpenAI Chat Completions | `https://api.openai.com/v1` | `/chat/completions` | `gpt-4.1-mini` |
| OpenAI Responses | `https://api.openai.com/v1` | `/responses` | `gpt-4.1-mini` |
| Claude Messages | `https://api.anthropic.com` | `/v1/messages` | `claude-sonnet-4-5` |
| Google Gemini | `https://generativelanguage.googleapis.com` | `/v1beta/models/{model}:generateContent` | `gemini-2.5-flash` |

The host may be a base URL or a full endpoint that already ends with the configured path. Switching modes updates fields that still contain their previous defaults; custom values remain untouched. Availability of individual model IDs depends on the provider and your account.

## Conversations and Data

The system prompt, selected card text and metadata, and attached images are captured when you first send a message for a card. Changing the prompt or context checkboxes affects **new conversations only**. To start over on the current card, use **Clear chat** and confirm the deletion. You can change the API connection or model for an existing conversation. Failed requests keep the user message and offer **Retry**.

Images are sent as encoded data, not as links to your Anki media directory. Remote image URLs, SVGs, and missing local files are not uploaded. Images over a combined 20 MB must be resized or deselected. A text-only model may reject image input; turn off **Card images** before starting a new chat in that case.

Nothing is sent to an AI provider until you submit a question. The selected context and conversation are sent to the configured API host; provider policies and charges are determined by that provider. Chats and captured image data live in profile-specific SQLite files under `user_files/`. The API key and preferences are saved as **plain text** in Anki's local add-on `meta.json`. Neither the chats nor the key are included in Anki collection sync or collection exports. Protect your Anki profile directory accordingly.

## Development

Run the standard-library tests from the repository root:

```sh
python -m unittest discover -s tests -v
python scripts/package.py
python -m zipfile -t dist/anki-tutor.ankiaddon
```

The protocol, context, storage, and translation tests need only Python. An optional offscreen Qt smoke test also runs when PyQt6 is installed; it exercises panel docking and a local HTTP response without launching Anki. The installable archive is built from `scripts/package.py` and published as a GitHub release asset. Report defects and suggestions in [GitHub Issues](https://github.com/Kesike03/anki-tutor/issues).

## License

Anki Tutor is licensed under the [GNU Affero General Public License version 3](LICENSE) (AGPL-3.0-only). This project is not affiliated with or endorsed by Anki, OpenAI, Anthropic, or Google.
