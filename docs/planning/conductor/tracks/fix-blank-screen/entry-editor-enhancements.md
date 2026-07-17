# Entry Editor Enhancements Task List

## 1. Formatting & Richness (Phase 1)
- [x] **Refactor Toolbar UI:** Reorganize the current two-row toolbar to accommodate new buttons cleanly (e.g., grouping related actions or adding dropdowns for less common tools).
- [x] **Text Alignment:**
  - [x] Add alignment icons (AlignLeft, Center, AlignRight, Justify) to the toolbar.
  - [x] Implement formatting functions to wrap selected text in `<div style="text-align: left|center|right|justify">...</div>`.
  - [x] Update `activeFormats` logic to detect existing alignment tags.
- [x] **Emoji Picker:**
  - [x] Introduce an emoji picker component (e.g., using `emoji-mart-vue` or native OS picker).
  - [x] Add an emoji button to the toolbar to toggle the picker.
  - [x] Implement insertion logic at the current cursor position.
- [x] **Highlighter Support:**
  - [x] Add a highlighter button to the toolbar.
  - [x] Implement a formatting function to wrap text in `<mark>...</mark>`.
  - [x] Update `activeFormats` logic to detect `<mark>`.

## 2. Writing Productivity (UX)
- [x] **Focus Mode:**
  - [x] Add a "Focus Mode" toggle button.
  - [x] Implement state logic to hide the main app sidebar, secondary panels, and non-essential editor headers when active.
- [x] **Typewriter Mode:**
  - [x] Add a "Typewriter Mode" toggle button.
  - [x] Implement scroll synchronization logic on the textarea to keep the cursor centered vertically.
- [x] **Context Menu:**
  - [x] Implement a custom right-click context menu on the textarea.
  - [x] Populate the menu with quick actions: Copy, Paste, Format (Bold/Italic), and AI actions (Grammar Check, Rewrite).

## 3. Advanced AI Workflows (Phase 2)
- [x] **Smart Actions Toolbar Menu:**
  - [x] Create a dropdown menu in the main toolbar for "Smart Actions" (Implemented as Left Sidebar).
  - [x] Move "Grammar Check", "Spell Check", "Rewrite", and "Continue Writing" from AiDrawerPanel.vue to this new menu.
  - [x] Wire up the API calls directly to the editor text state (applied to selection only).
- [x] **OCR Integration for Images:**
  - [x] Update MediaViewer.vue or the attachment list in EntryEditor.vue to include an "Extract Text (OCR)" button for image files.
  - [x] Implement frontend handler to call the backend OCR endpoint.
  - [x] Append the extracted text to the entry body.

## 4. Security & Data Integrity (Phase 3)
- [x] **Selection Encryption:**
  - [x] Add an "Encrypt Selection" button to the toolbar or context menu.
  - [x] Implement logic to take selected text, call the `/api/v1/encryption/encrypt-selection` endpoint, and replace the text with `<!--ENC{base64}-->`.
  - [x] Update the Markdown preview to parse `<!--ENC{...}-->` tags and render a "Decrypt to view" placeholder or button.
  - [x] Implement logic to call `/api/v1/encryption/decrypt-selection` when the placeholder is interacted with.
- [x] **Auto-save for New Entries (Drafts):**
  - [x] Update the `saveTimer` logic to trigger even when `isNew.value` is true.
  - [x] On the first auto-save, silently convert the "new" entry to a persisted entry in the background.
