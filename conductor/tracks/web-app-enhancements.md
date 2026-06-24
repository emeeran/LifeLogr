# Track: Web App Enhancements & UI/UX Polish

This track focuses on improving the user experience and visual polish of the LifeLogr web application (Tauri frontend).

## 🏁 Objectives
- Improve editor UX with a more intuitive markdown preview toggle.
- Enhance AI interaction reliability and feedback.
- Add "Empty State" illustrations for better user onboarding.
- Polish the Analytics view with more interactive charts.

## 🛠 Proposed Tasks

### 1. Editor UI/UX Polish
- [ ] **Sticky Toolbar:** Ensure the editor toolbar remains visible when scrolling through long entries.
- [ ] **Split-View Mode:** Add an optional side-by-side preview mode for the editor.
- [ ] **Auto-Focus:** Ensure the editor or title field is focused when opening a new entry.
- [ ] **Passphrase Visibility Toggle:** Add a "show/hide" icon for the passphrase prompt in encryption.

### 2. AI & Smart Actions Enhancements
- [ ] **Refine "Smart Action" Loading States:** Add a progress bar or more detailed status updates for long-running AI tasks (e.g., "Summarizing...", "Analyzing Sentiment...").
- [ ] **Graceful Ollama Offline Handling:** Improve the UI when Ollama is offline — provide clear instructions on how to start it and hide AI buttons to reduce clutter.
- [ ] **Tag Suggestion UX:** Allow clicking suggested tags to add them instantly without opening a separate dropdown.

### 3. Analytics & Visualization
- [ ] **Interactive Heatmap:** Allow clicking a day in the heatmap to jump to that day's entry.
- [ ] **Sentiment Over Time Chart:** Add a line chart to the Analytics view showing valence trends.
- [ ] **Mood Cloud:** Add a word cloud or bubble chart for frequently used mood labels.

### 4. General App Polish
- [ ] **Custom Scrollbars:** Implement consistent, slim scrollbars throughout the app for a more modern look.
- [ ] **Transitions & Animations:** Add subtle transitions for panel opening/closing and view switches.
- [ ] **Empty State Illustrations:** Add stylized SVG illustrations (using CSS shapes/gradients) for empty lists, search results, and "On This Day" when no entries are found.

## 🧪 Verification Plan
- **UI/UX Testing:** Manual verification of all new UI components and interactions.
- **Responsiveness Check:** Ensure enhancements work well in both windowed and fullscreen modes.
- **Error Handling:** Verify that the app remains functional when backend services (like Ollama) are unavailable.
