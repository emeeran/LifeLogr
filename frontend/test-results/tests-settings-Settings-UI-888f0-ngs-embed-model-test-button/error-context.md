# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: tests/settings.spec.ts >> Settings UI verification >> AI tab: connection settings, embed model, test button
- Location: tests/settings.spec.ts:38:3

# Error details

```
Error: locator.click: Error: strict mode violation: locator('text=AI') resolved to 3 elements:
    1) <span data-v-7ade5772="" class="text-sm font-bold text-sidebar-text tracking-tight leading-tight">DailyByte</span> aka getByText('DailyByte')
    2) <button data-v-ee475729="" class="w-full flex items-center gap-2 px-2.5 py-2 rounded-md text-[12px] font-medium cursor-pointer transition-colors text-text-secondary hover:bg-surface-hover hover:text-text-primary">…</button> aka getByRole('button', { name: 'AI', exact: true })
    3) <option data-v-6047ee6b="" value="'JetBrains Mono', monospace">JetBrains Mono</option> aka getByRole('combobox').nth(4)

Call log:
  - waiting for locator('text=AI')

```

# Page snapshot

```yaml
- generic [ref=e3]:
  - navigation [ref=e4]:
    - generic [ref=e5]:
      - button "DailyByte" [ref=e6] [cursor=pointer]
      - generic [ref=e7]:
        - generic [ref=e8]: DailyByte
        - generic [ref=e9]: Your Day in Media & Minutes
    - generic [ref=e10]:
      - link "Calendar" [ref=e11] [cursor=pointer]:
        - /url: /
        - img [ref=e12]
        - generic [ref=e14]: Calendar
      - link "Timeline" [ref=e15] [cursor=pointer]:
        - /url: /timeline
        - img [ref=e16]
        - generic [ref=e19]: Timeline
      - link "Search" [ref=e20] [cursor=pointer]:
        - /url: /search
        - img [ref=e21]
        - generic [ref=e24]: Search
      - link "Analytics" [ref=e25] [cursor=pointer]:
        - /url: /analytics
        - img [ref=e26]
        - generic [ref=e28]: Analytics
      - link "Digest" [ref=e29] [cursor=pointer]:
        - /url: /digest
        - img [ref=e30]
        - generic [ref=e32]: Digest
      - link "Map" [ref=e33] [cursor=pointer]:
        - /url: /map
        - img [ref=e34]
        - generic [ref=e37]: Map
      - link "Reminders" [ref=e38] [cursor=pointer]:
        - /url: /reminders
        - img [ref=e39]
        - generic [ref=e42]: Reminders
      - link "On this day" [ref=e43] [cursor=pointer]:
        - /url: /on-this-day
        - img [ref=e44]
        - generic [ref=e49]: On this day
    - button "Toggle Scribble Pad" [ref=e51] [cursor=pointer]:
      - img [ref=e52]
      - generic [ref=e55]: Scribble
    - generic [ref=e56]:
      - button "Switch to light mode" [ref=e57] [cursor=pointer]:
        - img [ref=e58]
        - generic [ref=e64]: Light
      - link "Settings" [active] [ref=e65] [cursor=pointer]:
        - /url: /settings
        - img [ref=e66]
        - generic [ref=e69]: Settings
      - button "Collapse sidebar" [ref=e70] [cursor=pointer]:
        - img [ref=e71]
        - generic [ref=e74]: Collapse
  - main [ref=e75]:
    - generic [ref=e76]:
      - heading "Settings" [level=2] [ref=e78]
      - generic [ref=e79]:
        - navigation [ref=e80]:
          - generic [ref=e82]:
            - img [ref=e83]
            - textbox "Search..." [ref=e86]
          - button "General" [ref=e87] [cursor=pointer]:
            - img [ref=e88]
            - text: General
          - button "AI" [ref=e89] [cursor=pointer]:
            - img [ref=e90]
            - text: AI
          - button "Data" [ref=e98] [cursor=pointer]:
            - img [ref=e99]
            - text: Data
          - button "Features" [ref=e101] [cursor=pointer]:
            - img [ref=e102]
            - text: Features
          - button "About" [ref=e105] [cursor=pointer]:
            - img [ref=e106]
            - text: About
        - generic [ref=e108]:
          - generic [ref=e109]:
            - generic [ref=e110]:
              - generic [ref=e111]:
                - heading "Appearance" [level=3] [ref=e112]:
                  - img [ref=e113]
                  - text: Appearance
                - paragraph [ref=e119]: Customize the look and feel
              - button "Reset" [ref=e121] [cursor=pointer]
            - generic [ref=e122]:
              - generic [ref=e123]:
                - generic [ref=e124]: Dark mode
                - switch [checked] [ref=e125] [cursor=pointer]
              - generic [ref=e126]:
                - img [ref=e127]
                - generic [ref=e129]: Font family
                - combobox [ref=e130] [cursor=pointer]:
                  - option "System UI" [selected]
                  - option "Georgia (Serif)"
                  - option "Merriweather"
                  - option "Noto Serif"
                  - option "Monospace"
              - generic [ref=e131]:
                - img [ref=e132]
                - generic [ref=e134]: Font size (14px)
                - slider [ref=e135]: "14"
          - generic [ref=e136]:
            - generic [ref=e137]:
              - generic [ref=e138]:
                - heading "Editor & Writing" [level=3] [ref=e139]:
                  - img [ref=e140]
                  - text: Editor & Writing
                - paragraph [ref=e141]: Writing behavior, search, and preferences
              - button "Reset" [ref=e143] [cursor=pointer]
            - generic [ref=e144]:
              - generic [ref=e145]:
                - img [ref=e146]
                - generic [ref=e149]: Auto-save (2s)
                - slider [ref=e150]: "2"
              - generic [ref=e151]:
                - img [ref=e152]
                - generic [ref=e155]: OCR language
                - combobox [ref=e156] [cursor=pointer]:
                  - option "English" [selected]
                  - option "French"
                  - option "German"
                  - option "Spanish"
                  - option "Portuguese"
                  - option "Italian"
                  - option "Dutch"
                  - option "Polish"
                  - option "Russian"
                  - option "Japanese"
                  - option "Chinese (Simplified)"
                  - option "Arabic"
                  - option "Hindi"
              - generic [ref=e157]:
                - img [ref=e158]
                - generic [ref=e160]: Default title
                - textbox "e.g. Daily Journal" [ref=e161]
              - generic [ref=e162]:
                - generic [ref=e163]:
                  - img [ref=e164]
                  - generic [ref=e167]: Search mode
                  - combobox [ref=e168] [cursor=pointer]:
                    - option "Hybrid" [selected]
                    - option "Keyword"
                    - option "Semantic"
                - paragraph [ref=e169]: Combines keyword and semantic search for best results.
              - generic [ref=e170]:
                - generic [ref=e171]:
                  - generic [ref=e172]: Auto-tag location
                  - switch [ref=e173] [cursor=pointer]
                - generic [ref=e174]:
                  - img [ref=e175]
                  - generic [ref=e179]: Default template
                  - combobox [ref=e180] [cursor=pointer]:
                    - option "None" [selected]
          - generic [ref=e181]:
            - button "Keyboard Shortcuts" [ref=e182] [cursor=pointer]:
              - img [ref=e183]
              - text: Keyboard Shortcuts
              - img [ref=e185]
            - generic [ref=e189]:
              - generic [ref=e190]:
                - generic [ref=e191]: Open search palette
                - generic [ref=e192]: Ctrl + K
              - generic [ref=e193]:
                - generic [ref=e194]: Save entry
                - generic [ref=e195]: Ctrl + S
              - generic [ref=e196]:
                - generic [ref=e197]: Bold text
                - generic [ref=e198]: Ctrl + B
              - generic [ref=e199]:
                - generic [ref=e200]: Italic text
                - generic [ref=e201]: Ctrl + I
              - generic [ref=e202]:
                - generic [ref=e203]: Strikethrough
                - generic [ref=e204]: Ctrl + Shift + X
              - generic [ref=e205]:
                - generic [ref=e206]: Remove formatting
                - generic [ref=e207]: Ctrl + \
              - generic [ref=e208]:
                - generic [ref=e209]: Undo
                - generic [ref=e210]: Ctrl + Z
              - generic [ref=e211]:
                - generic [ref=e212]: Redo
                - generic [ref=e213]: Ctrl + Shift + Z
              - generic [ref=e214]:
                - generic [ref=e215]: Find in entry
                - generic [ref=e216]: Ctrl + F
              - generic [ref=e217]:
                - generic [ref=e218]: Close panel / dialog
                - generic [ref=e219]: Escape
  - generic [ref=e223]:
    - generic [ref=e224]:
      - textbox "Title" [ref=e225]
      - textbox [ref=e226]: 2026-05-26
      - button "New entry" [ref=e227] [cursor=pointer]:
        - img [ref=e228]
      - generic [ref=e229]:
        - button "Fullscreen" [ref=e230] [cursor=pointer]:
          - img [ref=e231]
        - button [ref=e236] [cursor=pointer]:
          - img [ref=e237]
    - generic [ref=e240]:
      - generic [ref=e241]:
        - combobox [ref=e242] [cursor=pointer]:
          - option "System" [selected]
          - option "Segoe UI"
          - option "Inter"
          - option "Roboto"
          - option "Lora"
          - option "Merriweather"
          - option "JetBrains Mono"
          - option "Monospace"
        - combobox [ref=e243] [cursor=pointer]:
          - option "12px"
          - option "13px"
          - option "14px" [selected]
          - option "15px"
          - option "16px"
          - option "18px"
          - option "20px"
          - option "22px"
          - option "24px"
        - button "Undo (Ctrl+Z)" [disabled] [ref=e244] [cursor=pointer]:
          - img [ref=e245]
        - button "Redo (Ctrl+Y)" [disabled] [ref=e248] [cursor=pointer]:
          - img [ref=e249]
        - button "Bold (Ctrl+B)" [ref=e252] [cursor=pointer]:
          - img [ref=e253]
        - button "Italic (Ctrl+I)" [ref=e255] [cursor=pointer]:
          - img [ref=e256]
        - button "Strikethrough (Ctrl+U)" [ref=e258] [cursor=pointer]:
          - img [ref=e259]
        - button "Inline code (Ctrl+K)" [ref=e262] [cursor=pointer]:
          - img [ref=e263]
        - button "Code block" [ref=e266] [cursor=pointer]:
          - img [ref=e267]
        - button "Link" [ref=e269] [cursor=pointer]:
          - img [ref=e270]
        - button "Image" [ref=e273] [cursor=pointer]:
          - img [ref=e274]
        - button "Insert Emoji" [ref=e278] [cursor=pointer]:
          - img [ref=e279]
        - button "Focus Mode" [ref=e282] [cursor=pointer]:
          - img [ref=e283]
        - button "Typewriter Mode" [ref=e289] [cursor=pointer]:
          - img [ref=e290]
        - button "Find & Replace (Ctrl+F)" [ref=e292] [cursor=pointer]:
          - img [ref=e293]
      - generic [ref=e296]:
        - button "Heading 1" [ref=e297] [cursor=pointer]:
          - img [ref=e298]
        - button "Heading 2" [ref=e300] [cursor=pointer]:
          - img [ref=e301]
        - button "Bullet list" [ref=e304] [cursor=pointer]:
          - img [ref=e305]
        - button "Numbered list" [ref=e306] [cursor=pointer]:
          - img [ref=e307]
        - button "Blockquote" [ref=e310] [cursor=pointer]:
          - img [ref=e311]
        - button "Align left" [ref=e315] [cursor=pointer]:
          - img [ref=e316]
        - button "Align center" [ref=e317] [cursor=pointer]:
          - img [ref=e318]
        - button "Align right" [ref=e319] [cursor=pointer]:
          - img [ref=e320]
        - button "Align justify" [ref=e321] [cursor=pointer]:
          - img [ref=e322]
        - button "Highlight" [ref=e324] [cursor=pointer]:
          - img [ref=e325]
        - button "Checkbox" [ref=e329] [cursor=pointer]:
          - img [ref=e330]
        - button "Table" [ref=e333] [cursor=pointer]:
          - img [ref=e334]
        - button "Horizontal rule" [ref=e336] [cursor=pointer]:
          - img [ref=e337]
    - textbox "Write your thoughts..." [ref=e341]
    - generic [ref=e342]:
      - generic [ref=e343]:
        - generic [ref=e344]:
          - img [ref=e345]
          - text: 0 words
        - generic [ref=e346]: 0 chars
        - generic [ref=e347]: 0 lines
        - generic [ref=e348]: 0 paragraphs
        - generic [ref=e349]:
          - img [ref=e350]
          - text: 1 min read
      - generic [ref=e353]:
        - button [ref=e354] [cursor=pointer]:
          - img [ref=e355]
        - button [ref=e357] [cursor=pointer]:
          - img [ref=e358]
        - button "Tags" [ref=e361] [cursor=pointer]:
          - img [ref=e362]
        - button "Use template" [ref=e365] [cursor=pointer]:
          - img [ref=e366]
        - button "AI Smart Actions" [ref=e371] [cursor=pointer]:
          - img [ref=e372]
        - button "Version History" [ref=e375] [cursor=pointer]:
          - img [ref=e376]
        - button [ref=e381] [cursor=pointer]:
          - img [ref=e382]
        - button "Voice Recording" [ref=e385] [cursor=pointer]:
          - img [ref=e386]
        - button "Attach files" [ref=e389] [cursor=pointer]:
          - img [ref=e391]
        - button "Read aloud" [disabled] [ref=e393] [cursor=pointer]:
          - img [ref=e394]
        - button "Save" [ref=e398] [cursor=pointer]
```

# Test source

```ts
  1   | import { test, expect } from '@playwright/test'
  2   | 
  3   | test.describe('Settings UI verification', () => {
  4   |   test.beforeEach(async ({ page }) => {
  5   |     await page.goto('/')
  6   |     // Navigate to settings - click the settings icon/link in the sidebar
  7   |     await page.locator('text=Settings').first().click()
  8   |     await page.waitForTimeout(500)
  9   |   })
  10  | 
  11  |   // ── General Tab ──
  12  |   test('General tab: toggle switches render, descriptions visible', async ({ page }) => {
  13  |     // Should be on General tab by default
  14  |     await expect(page.locator('text=Appearance')).toBeVisible()
  15  |     await expect(page.locator('text=Customize the look and feel')).toBeVisible()
  16  | 
  17  |     // Toggle switches: should use role="switch", not raw checkboxes in the UI
  18  |     const darkModeToggle = page.locator('role=switch[name=/dark/i], [role="switch"]').first()
  19  |     await expect(darkModeToggle).toBeVisible()
  20  | 
  21  |     // Editor section has description
  22  |     await expect(page.locator('text=Editor & Writing')).toBeVisible()
  23  |     await expect(page.locator('text=Writing behavior, search, and preferences')).toBeVisible()
  24  | 
  25  |     // Keyboard shortcuts accordion (collapsed by default)
  26  |     await expect(page.locator('text=Keyboard Shortcuts')).toBeVisible()
  27  |     // Shortcuts should be collapsed - the kbd elements should NOT be visible
  28  |     await expect(page.locator('kbd')).toHaveCount(0)
  29  | 
  30  |     // Click to expand
  31  |     await page.locator('text=Keyboard Shortcuts').click()
  32  |     await page.waitForTimeout(300)
  33  |     // Now kbd elements should appear
  34  |     await expect(page.locator('kbd').first()).toBeVisible()
  35  |   })
  36  | 
  37  |   // ── AI Tab ──
  38  |   test('AI tab: connection settings, embed model, test button', async ({ page }) => {
> 39  |     await page.locator('text=AI').click()
      |                                   ^ Error: locator.click: Error: strict mode violation: locator('text=AI') resolved to 3 elements:
  40  |     await page.waitForTimeout(800)
  41  | 
  42  |     // Section header + description
  43  |     await expect(page.locator('text=AI Configuration')).toBeVisible()
  44  |     await expect(page.locator('text=Local AI model and feature settings')).toBeVisible()
  45  | 
  46  |     // Connection sub-section
  47  |     await expect(page.locator('text=Connection')).toBeVisible()
  48  |     await expect(page.locator('text=Ollama URL')).toBeVisible()
  49  | 
  50  |     // Ollama URL input
  51  |     const urlInput = page.locator('input[placeholder="http://localhost:11434"]')
  52  |     await expect(urlInput).toBeVisible()
  53  | 
  54  |     // Test Connection button
  55  |     await expect(page.locator('text=Test Connection')).toBeVisible()
  56  | 
  57  |     // Models sub-section
  58  |     await expect(page.locator('text=Models')).toBeVisible()
  59  |     await expect(page.locator('text=Chat model')).toBeVisible()
  60  |     await expect(page.locator('text=Embedding model')).toBeVisible()
  61  | 
  62  |     // Embed model input with datalist
  63  |     const embedInput = page.locator('input[placeholder="nomic-embed-text"]')
  64  |     await expect(embedInput).toBeVisible()
  65  | 
  66  |     // Feature toggles as toggle switches
  67  |     await expect(page.locator('text=Features')).toBeVisible()
  68  |     const toggles = page.locator('[role="switch"]')
  69  |     await expect(toggles.count()).resolves.toBeGreaterThanOrEqual(6)
  70  | 
  71  |     // Themes & Insights accordion (collapsed)
  72  |     await expect(page.locator('text=Themes & Insights')).toBeVisible()
  73  |     await expect(page.locator('text=Discover patterns in your journaling')).toBeVisible()
  74  |   })
  75  | 
  76  |   // ── Data Tab ──
  77  |   test('Data tab: sections, descriptions, skeleton loading', async ({ page }) => {
  78  |     await page.locator('text=Data').click()
  79  |     await page.waitForTimeout(800)
  80  | 
  81  |     // Storage section
  82  |     await expect(page.locator('text=Storage')).toBeVisible()
  83  |     await expect(page.locator('text=Disk usage and entry statistics')).toBeVisible()
  84  | 
  85  |     // Import / Export section
  86  |     await expect(page.locator('text=Import / Export')).toBeVisible()
  87  |     await expect(page.locator('text=Bring entries in or export your journal')).toBeVisible()
  88  | 
  89  |     // Backup section
  90  |     await expect(page.locator('text=Backup')).toBeVisible()
  91  |     await expect(page.locator('text=Local archive and scheduled backups')).toBeVisible()
  92  | 
  93  |     // Cloud section with description
  94  |     await expect(page.locator('text=Cloud')).toBeVisible()
  95  |     await expect(page.locator('text=Sync your journal to cloud storage')).toBeVisible()
  96  | 
  97  |     // Sync section
  98  |     await expect(page.locator('text=Sync')).toBeVisible()
  99  |     await expect(page.locator('text=Manage data synchronization queue')).toBeVisible()
  100 | 
  101 |     // Cloud empty state (if no configs)
  102 |     const emptyState = page.locator('text=No cloud backups configured')
  103 |     if (await emptyState.isVisible()) {
  104 |       // Should have a hint below
  105 |       await expect(page.locator('text=Click Add to connect a cloud provider')).toBeVisible()
  106 |     }
  107 |   })
  108 | 
  109 |   // ── Features Tab ──
  110 |   test('Features tab: TTS voice selector, notifications, plugins', async ({ page }) => {
  111 |     await page.locator('text=Features').click()
  112 |     await page.waitForTimeout(800)
  113 | 
  114 |     // Read Aloud section
  115 |     await expect(page.locator('text=Read Aloud')).toBeVisible()
  116 |     await expect(page.locator('text=Text-to-speech voice settings')).toBeVisible()
  117 | 
  118 |     // Voice select - should have optgroups
  119 |     const voiceSelect = page.locator('select').filter({ hasText: '' }).first()
  120 |     await expect(page.locator('text=Voice')).toBeVisible()
  121 | 
  122 |     // Speed and Volume sliders
  123 |     await expect(page.locator('text=/Speed/')).toBeVisible()
  124 |     await expect(page.locator('text=/Volume/')).toBeVisible()
  125 | 
  126 |     // Notifications section
  127 |     await expect(page.locator('text=Notifications')).toBeVisible()
  128 |     await expect(page.locator('text=Writing reminders and alerts')).toBeVisible()
  129 | 
  130 |     // Plugins section
  131 |     await expect(page.locator('text=Plugins')).toBeVisible()
  132 |     await expect(page.locator('text=Extend DailyByte with plugins')).toBeVisible()
  133 |   })
  134 | 
  135 |   // ── About Tab ──
  136 |   test('About tab: info card, danger zone', async ({ page }) => {
  137 |     await page.locator('text=About').click()
  138 |     await page.waitForTimeout(500)
  139 | 
```