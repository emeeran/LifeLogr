# Track Plan: Fix Blank Screen & Critical Bugs

This track addresses the runtime crash causing the "blank screen" and several other critical bugs identified in the frontend application.

## 🏁 Objectives
- Resolve the `marked` library runtime crash.
- Fix CSS syntax errors in `main.css`.
- Ensure file uploads work correctly in `client.ts`.
- Fix the calendar month fetching logic in the editor.

## 🛠 Implementation Tasks

### 1. Fix `marked` library usage
The app currently calls `marked()` as a function, which throws a `TypeError` in modern versions of the library where `marked` is an object.
- [x] Update `frontend/src/components/entry/EntryDetail.vue` to use `marked.parse()`.
- [x] Update `frontend/src/components/entry/EntryEditor.vue` to use `marked.parse()`.

### 2. Correct CSS Syntax
The `:global()` selector is invalid in plain CSS and belongs to CSS Modules. (Note: Verified `:global()` is used in Vue SFC scoped styles, which is valid. No changes needed in `main.css`).

### 3. Refactor API Client for `FormData`
The `request` function erroneously sets `Content-Type: application/json` even for multipart form data.
- [x] Update `frontend/src/api/client.ts` to skip setting the JSON content type when the request body is `FormData`.

### 4. Fix Calendar Month logic
The editor currently subtracts 1 from the month when refreshing the calendar, which is incorrect as both frontend and backend use 1-based months.
- [x] Update `frontend/src/components/entry/EntryEditor.vue` to pass the correct month to `fetchCalendarMonth` in `save`, `close`, and `handleDelete` functions.

## 🧪 Verification Plan
- **Manual Verification:**
    - Reload the app and ensure the blank screen is gone and the calendar loads.
    - Open an entry and ensure markdown renders correctly.
    - Toggle dark mode and ensure the logo visibility transitions correctly.
    - Save an entry and ensure the calendar refreshes the correct month.
- **Automated Tests:**
    - N/A (Frontend testing environment not fully configured in this session).
