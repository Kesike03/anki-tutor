# Anki Tutor

Anki Tutor adds an AI chat panel to Anki's review window. Each card can have multiple persistent conversations, so you can ask questions, keep reviewing, and return to a particular discussion later. The panel uses your own API credentials and supports four provider protocols.

## Features

- **Card-aware conversations:** The front, back, deck and template, scheduling settings, and complete review log can be included in the assistant's context. Choose which fields to share before starting a conversation.
- **Image input:** Local PNG, JPEG, GIF, and WebP images on the selected card sides can be sent to vision-capable models. Repeated images are attached only once.
- **Message attachments:** Attach images, PDFs, and UTF-8 text/code files to a question. PDFs are supported in Responses, Claude, and Gemini modes.
- **Edit, copy, and regenerate:** User messages can be edited and resent. Assistant replies can be copied or regenerated; versions are kept as branches, and switching a branch also restores its follow-up conversation.
- **Anki editing tools:** Ask the tutor to create, edit, or delete cards, or adjust a deck's shared review options. It proposes explicit changes and Anki asks for confirmation before applying them through native collection operations.
- **Multiple conversations per card:** Switch discussions or start a new one using the controls above the chat. Saved conversations are covered when you return to a card; reveal or select a discussion to continue.
- **Readable answers:** Markdown is rendered by a bundled parser. MathJax uses Anki's own bundled resources and accepts `\(...\)`, `\[...\]`, `$...$`, and `$$...$$` formulas.
- **History management:** Browse conversations grouped by card, preview messages, delete a conversation or a card's history, clear the entire profile history, and export/import a portable JSON backup. Re-importing the same backup skips duplicates.
- **Unobtrusive interface:** The right-hand panel can be resized, floated, or closed. Its colors follow Anki's light and dark themes. A button in the floating panel docks it back on the right.
- **Flexible providers:** OpenAI-compatible Chat Completions, OpenAI-compatible Responses, Anthropic Claude Messages, and Google Gemini. The host, path, model ID, and system prompt are editable.
- **Six interface languages:** Follows Anki's interface language by default when available (English, Japanese, Simplified Chinese, Spanish, French, and German). You can choose a language manually.

## Installation

Anki 24.06 or newer with Qt 6 is required. Download [the latest `.ankiaddon` release](https://github.com/Kesike03/anki-tutor/releases/latest/download/anki-tutor.ankiaddon), then in Anki choose **Tools > Add-ons > Install from file** and restart Anki. To update, install the newer file the same way and restart; Anki preserves the add-on's `user_files` directory.

You can also build the package from this repository with `python scripts/package.py` and install the resulting `dist/anki-tutor.ankiaddon`. No separate Python packages are required inside Anki.

## Getting Started

1. Open a card in Anki's review screen. The tutor appears on the right. If you closed it, enable **Anki Tutor** from Anki's View menu.
2. Open the panel settings. Select an API mode, enter your API key and model ID, and confirm the host and path. The defaults are shown below; replace them for compatible third-party providers.
3. Adjust the system prompt and the context checkboxes as needed. The front, back, images, deck/template, scheduling data, and review history are selected by default.
4. Ask a question. **Enter** sends it; **Shift+Enter** adds a new line. Requests run in the background, so you can continue studying while the response arrives. Use the conversation selector to return to another discussion on the same card; the plus button starts a new one. Use the paperclip/plus control to attach files.
5. Hover under a user message to edit and resend it, or under an assistant reply to copy or regenerate it. When more than one version exists, use the arrow buttons to switch that message and its following context.

| API mode | Default host | Default path | Example model ID |
| --- | --- | --- | --- |
| OpenAI Chat Completions | `https://api.openai.com/v1` | `/chat/completions` | `gpt-4.1-mini` |
| OpenAI Responses | `https://api.openai.com/v1` | `/responses` | `gpt-4.1-mini` |
| Claude Messages | `https://api.anthropic.com` | `/v1/messages` | `claude-sonnet-4-5` |
| Google Gemini | `https://generativelanguage.googleapis.com` | `/v1beta/models/{model}:generateContent` | `gemini-2.5-flash` |

The host may be a base URL or a full endpoint that already ends with the configured path. Switching modes updates fields that still contain their previous defaults; custom values remain untouched. Availability of individual model IDs depends on the provider and your account.

## Conversations and Data

The system prompt, selected card text and metadata, and attached images are captured when you first send a message in a conversation. Changing the prompt or context checkboxes affects **new conversations only**. Start a new discussion on the card to use updated context. **Clear chat** deletes the selected conversation after confirmation. You can change the API connection or model for an existing conversation. Failed requests keep the user message and offer **Retry**.

Images are sent as encoded data, not as links to your Anki media directory. Remote image URLs, SVGs, and missing local files are not uploaded. Attachments and card images share a combined 20 MB limit; resize or deselect files that exceed it. Supported message attachments are PNG/JPEG/GIF/WebP images, PDF documents, and UTF-8 text or common code files. A text-only model may reject attachments; turn off **Card images** or use a model that accepts the file type.

Anki edit requests are parsed from a separate structured block and shown in a confirmation dialog. The tutor can add Basic cards, edit fields on existing notes, delete selected cards, and change a normal deck preset's new/review/lapse limits and desired retention. It cannot create note types or decks, access arbitrary files, or run shell commands. Changes are executed one at a time through Anki's collection operations and appear in Anki's undo history.

Nothing is sent to an AI provider until you submit a question. The selected context and conversation are sent to the configured API host; provider policies and charges are determined by that provider. Chats and captured image data live in profile-specific SQLite files under `user_files/`. Existing single-conversation histories are migrated automatically on update. The API key and preferences are saved as **plain text** in Anki's local add-on `meta.json`. Neither the chats nor the key are included in Anki collection sync or collection exports; use **Chat history > Export** to back up chats as JSON and **Import** to merge a backup. The JSON file includes conversations, context, and images, but never your API key. Protect both the Anki profile directory and exported backups accordingly.

## Development

Run the standard-library tests from the repository root:

```sh
python -m unittest discover -s tests -v
python scripts/package.py
python -m zipfile -t dist/anki-tutor.ankiaddon
node tests/render_smoke.js
```

The protocol, context, storage, attachment, harness, and translation tests need only Python. An optional offscreen Qt smoke test also runs when PyQt6 is installed; it exercises panel docking and a local HTTP response without launching Anki. The Node smoke test checks Markdown and math token handling. The installable archive includes the MIT-licensed [markdown-it](web/vendor/LICENSE.markdown-it) parser; MathJax comes from Anki. Refresh the pinned parser with `python scripts/vendor.py`. Report defects and suggestions in [GitHub Issues](https://github.com/Kesike03/anki-tutor/issues).

## License

Anki Tutor is licensed under the [GNU Affero General Public License version 3](LICENSE) (AGPL-3.0-only). This project is not affiliated with or endorsed by Anki, OpenAI, Anthropic, or Google.
