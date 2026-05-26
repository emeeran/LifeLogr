# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: tests/settings.spec.ts >> Settings UI verification >> Data tab: sections, descriptions, skeleton loading
- Location: tests/settings.spec.ts:77:3

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('text=Storage')
Expected: visible
Error: strict mode violation: locator('text=Storage') resolved to 2 elements:
    1) <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1.5">…</h3> aka getByRole('heading', { name: 'Storage' })
    2) <p class="text-[10px] text-text-muted mt-0.5">Sync your journal to cloud storage</p> aka getByText('Sync your journal to cloud')

Call log:
  - Expect "toBeVisible" with timeout 5000ms
  - waiting for locator('text=Storage')

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
      - link "Settings" [ref=e65] [cursor=pointer]:
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
          - button "Data" [active] [ref=e98] [cursor=pointer]:
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
            - generic [ref=e111]:
              - heading "Storage" [level=3] [ref=e112]:
                - img [ref=e113]
                - text: Storage
              - paragraph [ref=e115]: Disk usage and entry statistics
            - generic [ref=e117]:
              - generic [ref=e118]:
                - generic [ref=e119]: Database
                - generic [ref=e120]: 1.8 MB
              - generic [ref=e121]:
                - generic [ref=e122]: Entries
                - generic [ref=e123]: "1373"
              - generic [ref=e124]:
                - generic [ref=e125]: Media files
                - generic [ref=e126]: 7 (0 B)
              - generic [ref=e127]:
                - generic [ref=e128]: Total
                - generic [ref=e129]: 1.8 MB
          - generic [ref=e130]:
            - generic [ref=e132]:
              - heading "Import / Export" [level=3] [ref=e133]:
                - img [ref=e134]
                - text: Import / Export
              - paragraph [ref=e138]: Bring entries in or export your journal
            - generic [ref=e139]:
              - generic [ref=e141]:
                - img [ref=e142]
                - generic [ref=e145]: Import entries
                - button "Import file" [ref=e146] [cursor=pointer]
              - generic [ref=e148]:
                - img [ref=e149]
                - generic [ref=e152]: Remove duplicates
                - button "Deduplicate" [ref=e153] [cursor=pointer]
              - generic [ref=e154]:
                - generic [ref=e155]:
                  - img [ref=e156]
                  - generic [ref=e159]: Export
                  - generic [ref=e160] [cursor=pointer]:
                    - radio "All" [checked] [ref=e161]
                    - text: All
                  - generic [ref=e162] [cursor=pointer]:
                    - radio "Range" [ref=e163]
                    - text: Range
                - generic [ref=e164]:
                  - button "ZIP" [ref=e165] [cursor=pointer]
                  - button "Diarium" [ref=e166] [cursor=pointer]
                  - button "HTML" [ref=e167] [cursor=pointer]
                  - button "PDF" [ref=e168] [cursor=pointer]
          - generic [ref=e169]:
            - generic [ref=e171]:
              - heading "Backup" [level=3] [ref=e172]:
                - img [ref=e173]
                - text: Backup
              - paragraph [ref=e177]: Local archive and scheduled backups
            - generic [ref=e178]:
              - generic [ref=e180]:
                - img [ref=e181]
                - generic [ref=e183]: Local archive
                - generic [ref=e184]:
                  - button "Backup" [ref=e185] [cursor=pointer]:
                    - img [ref=e186]
                    - text: Backup
                  - button "Restore" [ref=e189] [cursor=pointer]
              - generic [ref=e191]:
                - checkbox [ref=e192]
                - generic [ref=e193]: Auto backup (local)
          - generic [ref=e194]:
            - generic [ref=e195]:
              - generic [ref=e196]:
                - heading "Cloud" [level=3] [ref=e197]:
                  - img [ref=e198]
                  - text: Cloud
                - paragraph [ref=e200]: Sync your journal to cloud storage
              - button "Add" [ref=e202] [cursor=pointer]:
                - img [ref=e203]
                - text: Add
            - generic [ref=e205]:
              - generic [ref=e206]:
                - generic [ref=e207]: webdav
                - button [ref=e208] [cursor=pointer]:
                  - img [ref=e209]
              - generic [ref=e212]:
                - button "Test" [ref=e213] [cursor=pointer]
                - button "Backup" [ref=e214] [cursor=pointer]
                - button "Restore" [ref=e215] [cursor=pointer]
          - generic [ref=e216]:
            - generic [ref=e218]:
              - heading "Sync" [level=3] [ref=e219]:
                - img [ref=e220]
                - text: Sync
              - paragraph [ref=e225]: Manage data synchronization queue
            - generic [ref=e226]:
              - generic [ref=e227]:
                - generic [ref=e228]: idle
                - generic [ref=e229]: 0 pending
                - generic [ref=e230]: 5/11/2026
              - generic [ref=e231]:
                - button "Push" [ref=e232] [cursor=pointer]
                - button "Pull" [ref=e233] [cursor=pointer]
                - button "Flush" [ref=e234] [cursor=pointer]:
                  - img [ref=e235]
                  - text: Flush
  - generic [ref=e243]:
    - generic [ref=e244]:
      - textbox "Title" [ref=e245]
      - textbox [ref=e246]: 2026-05-26
      - button "New entry" [ref=e247] [cursor=pointer]:
        - img [ref=e248]
      - generic [ref=e249]:
        - button "Fullscreen" [ref=e250] [cursor=pointer]:
          - img [ref=e251]
        - button [ref=e256] [cursor=pointer]:
          - img [ref=e257]
    - generic [ref=e260]:
      - generic [ref=e261]:
        - combobox [ref=e262] [cursor=pointer]:
          - option "System" [selected]
          - option "Segoe UI"
          - option "Inter"
          - option "Roboto"
          - option "Lora"
          - option "Merriweather"
          - option "JetBrains Mono"
          - option "Monospace"
        - combobox [ref=e263] [cursor=pointer]:
          - option "12px"
          - option "13px"
          - option "14px" [selected]
          - option "15px"
          - option "16px"
          - option "18px"
          - option "20px"
          - option "22px"
          - option "24px"
        - button "Undo (Ctrl+Z)" [disabled] [ref=e264] [cursor=pointer]:
          - img [ref=e265]
        - button "Redo (Ctrl+Y)" [disabled] [ref=e268] [cursor=pointer]:
          - img [ref=e269]
        - button "Bold (Ctrl+B)" [ref=e272] [cursor=pointer]:
          - img [ref=e273]
        - button "Italic (Ctrl+I)" [ref=e275] [cursor=pointer]:
          - img [ref=e276]
        - button "Strikethrough (Ctrl+U)" [ref=e278] [cursor=pointer]:
          - img [ref=e279]
        - button "Inline code (Ctrl+K)" [ref=e282] [cursor=pointer]:
          - img [ref=e283]
        - button "Code block" [ref=e286] [cursor=pointer]:
          - img [ref=e287]
        - button "Link" [ref=e289] [cursor=pointer]:
          - img [ref=e290]
        - button "Image" [ref=e293] [cursor=pointer]:
          - img [ref=e294]
        - button "Insert Emoji" [ref=e298] [cursor=pointer]:
          - img [ref=e299]
        - button "Focus Mode" [ref=e302] [cursor=pointer]:
          - img [ref=e303]
        - button "Typewriter Mode" [ref=e309] [cursor=pointer]:
          - img [ref=e310]
        - button "Find & Replace (Ctrl+F)" [ref=e312] [cursor=pointer]:
          - img [ref=e313]
      - generic [ref=e316]:
        - button "Heading 1" [ref=e317] [cursor=pointer]:
          - img [ref=e318]
        - button "Heading 2" [ref=e320] [cursor=pointer]:
          - img [ref=e321]
        - button "Bullet list" [ref=e324] [cursor=pointer]:
          - img [ref=e325]
        - button "Numbered list" [ref=e326] [cursor=pointer]:
          - img [ref=e327]
        - button "Blockquote" [ref=e330] [cursor=pointer]:
          - img [ref=e331]
        - button "Align left" [ref=e335] [cursor=pointer]:
          - img [ref=e336]
        - button "Align center" [ref=e337] [cursor=pointer]:
          - img [ref=e338]
        - button "Align right" [ref=e339] [cursor=pointer]:
          - img [ref=e340]
        - button "Align justify" [ref=e341] [cursor=pointer]:
          - img [ref=e342]
        - button "Highlight" [ref=e344] [cursor=pointer]:
          - img [ref=e345]
        - button "Checkbox" [ref=e349] [cursor=pointer]:
          - img [ref=e350]
        - button "Table" [ref=e353] [cursor=pointer]:
          - img [ref=e354]
        - button "Horizontal rule" [ref=e356] [cursor=pointer]:
          - img [ref=e357]
    - textbox "Write your thoughts..." [ref=e361]
    - generic [ref=e362]:
      - generic [ref=e363]:
        - generic [ref=e364]:
          - img [ref=e365]
          - text: 0 words
        - generic [ref=e366]: 0 chars
        - generic [ref=e367]: 0 lines
        - generic [ref=e368]: 0 paragraphs
        - generic [ref=e369]:
          - img [ref=e370]
          - text: 1 min read
      - generic [ref=e373]:
        - button [ref=e374] [cursor=pointer]:
          - img [ref=e375]
        - button [ref=e377] [cursor=pointer]:
          - img [ref=e378]
        - button "Tags" [ref=e381] [cursor=pointer]:
          - img [ref=e382]
        - button "Use template" [ref=e385] [cursor=pointer]:
          - img [ref=e386]
        - button "AI Smart Actions" [ref=e391] [cursor=pointer]:
          - img [ref=e392]
        - button "Version History" [ref=e395] [cursor=pointer]:
          - img [ref=e396]
        - button [ref=e401] [cursor=pointer]:
          - img [ref=e402]
        - button "Voice Recording" [ref=e405] [cursor=pointer]:
          - img [ref=e406]
        - button "Attach files" [ref=e409] [cursor=pointer]:
          - img [ref=e411]
        - button "Read aloud" [disabled] [ref=e413] [cursor=pointer]:
          - img [ref=e414]
        - button "Save" [ref=e418] [cursor=pointer]
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
  39  |     await page.locator('text=AI').click()
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
> 82  |     await expect(page.locator('text=Storage')).toBeVisible()
      |                                                ^ Error: expect(locator).toBeVisible() failed
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
  140 |     await expect(page.locator('text=About')).toBeVisible()
  141 |     await expect(page.locator('text=App information and credits')).toBeVisible()
  142 |     await expect(page.locator('text=DailyByte')).toBeVisible()
  143 | 
  144 |     // Links
  145 |     await expect(page.locator('text=GitHub')).toBeVisible()
  146 |     await expect(page.locator('text=Report Issue')).toBeVisible()
  147 |     await expect(page.locator('text=License')).toBeVisible()
  148 | 
  149 |     // Danger zone
  150 |     await expect(page.locator('text=Reset Database')).toBeVisible()
  151 |   })
  152 | 
  153 |   // ── CSS: settings-select class ──
  154 |   test('CSS utility classes applied to selects and inputs', async ({ page }) => {
  155 |     await page.locator('text=General').click()
  156 |     await page.waitForTimeout(500)
  157 | 
  158 |     // Check that selects have the settings-select class
  159 |     const styledSelects = page.locator('select.settings-select')
  160 |     await expect(styledSelects.count()).resolves.toBeGreaterThanOrEqual(2)
  161 | 
  162 |     // Check that inputs have the settings-input class
  163 |     const styledInputs = page.locator('input.settings-input')
  164 |     await expect(styledInputs.count()).resolves.toBeGreaterThanOrEqual(1)
  165 |   })
  166 | 
  167 |   // ── Keyboard navigation ──
  168 |   test('Focus rings on tab navigation', async ({ page }) => {
  169 |     await page.locator('text=General').click()
  170 |     await page.waitForTimeout(500)
  171 | 
  172 |     // Tab to first interactive element and check focus outline
  173 |     await page.keyboard.press('Tab')
  174 | 
  175 |     // Get the focused element's computed outline style
  176 |     const hasFocusRing = await page.evaluate(() => {
  177 |       const el = document.activeElement
  178 |       if (!el) return false
  179 |       const style = window.getComputedStyle(el)
  180 |       return style.outlineWidth !== '0px' || style.outlineStyle !== 'none'
  181 |     })
  182 |     // Focus ring should be visible (applied by global CSS)
```