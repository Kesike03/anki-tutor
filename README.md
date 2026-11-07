# Anki Tutor

Anki Tutor adds an AI chat panel to Anki's review window. Each card can have multiple persistent conversations, so you can ask questions, keep reviewing, and return to a particular discussion later. The panel uses your own API credentials and supports four provider protocols.

## Features

- **Card-aware conversations:** The front, back, deck and template, scheduling settings, and complete review log can be included in the assistant's context. Choose which fields to share before starting a conversation. Message timestamps can also be included as hidden context for the model; they are never shown in the chat UI.
- **Study home:** In Anki's main window the assistant shows due/new/learning counts, 30-day retention, leeches, today's review signal, recent conversations, and a focus summary. It is a launch point for collection chat, weak-area analysis, history, and Browser batch work.
- **Collection-level chat:** Ask about decks, cards, review data, or study strategy without opening a card. The assistant uses read-only queries first and must specify a card or deck before proposing a write. Collection conversations are stored separately from card conversations and are included in history export/import.
- **Weak-area analysis:** A local, read-only report combines review history, lapses, ease, leech status, recent Again ratings, and FSRS memory data. It groups weak decks/tags and shows a compact card table. It never changes scheduling or review order.
- **Image input:** Local PNG, JPEG, GIF, and WebP images on the selected card sides can be sent to vision-capable models. Repeated images are attached only once.
- **Message attachments:** Attach images, PDFs, and UTF-8 text/code files to a question with the plus button, drag-and-drop, or clipboard paste. Pasted file URLs/paths are detected and converted to attachments. PDFs are supported in Responses, Claude, and Gemini modes.
- **Edit, copy, and regenerate:** User messages can be edited and resent. Assistant replies can be copied or regenerated; versions are kept as branches, and switching a branch also restores its follow-up conversation.
- **Agent workflow:** The tutor can query Anki data, propose changes, inspect the results, and continue for a limited number of steps until the request is complete. After applying changes it reviews the outcome before giving its final answer.
- **Anki editing tools:** Ask the tutor to create, edit, or delete cards, search or inspect cards, read deck statistics, or adjust a deck's shared review options. Changes are applied through native collection operations.
- **Batch field fill:** In the Browser, select any number of notes and choose **Anki Tutor > Fill fields with AI**. Pick a note type, reusable recipe, prompt template, and output-to-field mapping. The add-on validates structured JSON, shows a before/after preview, and writes only the fields you explicitly apply.
- **Conversation authoring:** Turn the current conversation into study notes, generate cards from it, or save a single assistant reply into a card field. Notes and cards are editable drafts; card generation uses the selected note type's real fields and supports Basic, Cloze, and custom note types.
- **Review-first writes:** Every authoring workflow shows a preview and keeps a snapshot of the previous values. Agent edits, field updates, added cards, and conversation authoring all support **Undo last write**.
- **Meta-learning focus:** The home focus summary and weak-area report emphasize retrieval practice, error analysis, self-explanation, and interleaving. They deliberately do not prescribe a card-by-card review order; Anki's scheduler remains authoritative.
- **Source grounding:** Card generation asks the model for a short source quote, rejects unknown fields and duplicate cards, validates cloze deletions, and sanitizes generated HTML. Conversation notes are explicitly labelled as AI-generated and should be reviewed before saving.
- **Permission control:** By default every change requires confirmation. Settings can optionally grant the AI direct-write permission; the current permission mode and other safe settings are injected into the model's hidden context.
- **Multiple conversations per card:** Switch discussions or start a new one using the controls above the chat. Saved conversations are covered when you return to a card; reveal or select a discussion to continue.
- **Readable answers:** Markdown is rendered by a bundled parser. MathJax uses Anki's own bundled resources and accepts `\(...\)`, `\[...\]`, `$...$`, and `$$...$$` formulas.
- **Read aloud:** Every assistant reply has a play button backed by QtTextToSpeech and the system's local voices. Speech is optional, stops when the chat context changes, and never uses the network. Voice, speed, and volume are configurable in the Speech tab, along with optional skipping of code blocks and formulas.
- **Token usage:** Settings has a dedicated Token usage tab with date ranges, per-model totals, daily totals, recent requests, and CSV export. Assistant messages show their token count below the reply. Chat and authoring requests are recorded locally in the Anki profile.
- **History management:** Browse conversations grouped by card, search them, preview messages, delete a conversation or a card's history, clear the entire profile history, and export/import a portable JSON backup. Re-importing the same backup skips duplicates. Opening a conversation from history loads that card's conversation and opens the card in the Browser without changing the panel's docked or floating state. While reviewing, a **Back to current card** button returns from another card or collection conversation to the reviewed card.
- **Comfortable interface:** Open settings in a separate window, choose a font size from 11–22 px, and keep the panel readable at any width. The chat text, controls, and settings window scale together.
- **Unobtrusive interface:** The right-hand panel can be resized, docked, floated into a roomy chat window, or closed. Its colors follow Anki's light and dark themes. A button in the floating panel docks it back on the right.
- **Flexible providers:** OpenAI-compatible Chat Completions, OpenAI-compatible Responses, Anthropic Claude Messages, and Google Gemini. The host, path, model ID, and system prompt are editable.
- **Six interface languages:** Follows Anki's interface language by default when available (English, Japanese, Simplified Chinese, Spanish, French, and German). You can choose a language manually.

## Installation

Anki 24.06 or newer with Qt 6 is required. Download [the latest `.ankiaddon` release](https://github.com/Kesike03/anki-tutor/releases/latest/download/anki-tutor.ankiaddon), then in Anki choose **Tools > Add-ons > Install from file** and restart Anki. To update, install the newer file the same way and restart; Anki preserves the add-on's `user_files` directory.

You can also build the package from this repository with `python scripts/package.py` and install the resulting `dist/anki-tutor.ankiaddon`. No separate Python packages are required inside Anki.

## Getting Started

1. Open Anki. The tutor's **Study home** appears on the right with collection stats and quick actions. Open a card in the review screen to switch to the card-specific tutor. If the panel is closed, enable **Anki Tutor** from Anki's View menu.
2. Open the settings window. The settings are split into **Connection**, **Tutor**, **Speech**, and **Token usage** tabs. Select an API mode, enter your API key and model ID, confirm the host and path, and choose a comfortable font size. The defaults are shown below; replace them for compatible third-party providers.
3. Adjust the system prompt and the context checkboxes as needed. The default card prompt asks for concise, conversational answers and mnemonic-card edits rather than dictionary-style completeness. The front, back, images, deck/template, scheduling data, and review history are selected by default.
4. Ask a question. **Enter** sends it; **Shift+Enter** adds a new line. Requests run in the background, so you can continue studying while the response arrives. Use the conversation selector to return to another discussion on the same card; the plus button starts a new one. Use the paperclip/plus control to attach files.
5. Hover under a user message to edit and resend it, or under an assistant reply to copy, save to a field, or regenerate it. When more than one version exists, use the arrow buttons to switch that message and its following context.
6. Use **Notes** or **Cards** above the chat to turn the conversation into an editable draft. In the Browser, select notes and use **Anki Tutor > Fill fields with AI** for batch work. Review the preview and apply only the rows you want.

| API mode | Default host | Default path | Example model ID |
| --- | --- | --- | --- |
| OpenAI Chat Completions | `https://api.openai.com/v1` | `/chat/completions` | `gpt-4.1-mini` |
| OpenAI Responses | `https://api.openai.com/v1` | `/responses` | `gpt-4.1-mini` |
| Claude Messages | `https://api.anthropic.com` | `/v1/messages` | `claude-sonnet-4-5` |
| Google Gemini | `https://generativelanguage.googleapis.com` | `/v1beta/models/{model}:generateContent` | `gemini-2.5-flash` |

The host may be a base URL or a full endpoint that already ends with the configured path. Switching modes updates fields that still contain their previous defaults; custom values remain untouched. Availability of individual model IDs depends on the provider and your account.

## Authoring and Safety

Batch fill and conversation authoring follow the same rules:

- The model receives only the selected note fields or the current conversation plus card context.
- Generated fields are parsed as JSON, checked against the real note type, and sanitized before they enter the collection.
- Nothing is written until you press **Apply selected** or **Save**.
- The preview lets you edit generated values, inspect warnings and source quotes, and apply fields individually.
- **Undo last write** restores the previous field values. For newly added cards it removes them; for deleted cards it recreates the note but cannot restore review scheduling.

Recipes are stored in the add-on configuration and can be exported/imported as JSON from the batch fill window. They are not sent to the AI provider.

## Conversations and Data

The system prompt, selected card text and metadata, and attached images are captured when you first send a message in a conversation. Changing the prompt or context checkboxes affects **new conversations only**. Start a new discussion on the card to use updated context. **Clear chat** deletes the selected conversation after confirmation. You can change the API connection or model for an existing conversation. Failed requests keep the user message and offer **Retry**.

Images are sent as encoded data, not as links to your Anki media directory. Remote image URLs, SVGs, and missing local files are not uploaded. Attachments and card images share a combined 20 MB limit; resize or deselect files that exceed it. Supported message attachments are PNG/JPEG/GIF/WebP images, PDF documents, and UTF-8 text or common code files. A text-only model may reject attachments; turn off **Card images** or use a model that accepts the file type.

Anki edit requests are parsed from a separate structured block and shown in a confirmation dialog. The tutor can add Basic cards, edit fields on existing notes, delete selected cards, and change a normal deck preset's new/review/lapse limits and desired retention. It cannot create note types or decks, access arbitrary files, or run shell commands. Changes are executed one at a time through the safe write layer, which snapshots old values and exposes **Undo last write** in the panel. Deleting a card cannot restore its scheduling state, so use the confirmation dialog carefully.

Nothing is sent to an AI provider until you submit a question. The selected context and conversation are sent to the configured API host; provider policies and charges are determined by that provider. Chats and captured image data live in profile-specific SQLite files under `user_files/`. Existing single-conversation histories are migrated automatically on update. The API key and preferences are saved as **plain text** in Anki's local add-on `meta.json`. Neither the chats nor the key are included in Anki collection sync or collection exports; use **Chat history > Export** to back up chats as JSON and **Import** to merge a backup. The JSON file includes conversations, context, and images, but never your API key. Protect both the Anki profile directory and exported backups accordingly.

Agent requests include a compact hidden settings summary (context selections, API mode/model, interface language, and whether direct-write permission is enabled) so the model knows what it is allowed to see and do. API keys, host URLs, and API paths are never included in that summary. Settings changes take effect on the next request.

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
