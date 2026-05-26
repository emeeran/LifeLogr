# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: tests/settings.spec.ts >> Settings UI verification >> Features tab: TTS voice selector, notifications, plugins
- Location: tests/settings.spec.ts:110:3

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('text=Voice')
Expected: visible
Error: strict mode violation: locator('text=Voice') resolved to 3 elements:
    1) <p class="text-[10px] text-text-muted mt-0.5">Text-to-speech voice settings</p> aka getByText('Text-to-speech voice settings')
    2) <span class="text-[12px] text-text-secondary flex-1">Voice</span> aka getByText('Voice', { exact: true })
    3) <option disabled value="">Loading voices...</option> aka locator('section').filter({ hasText: 'Read AloudText-to-speech' }).getByRole('combobox')

Call log:
  - Expect "toBeVisible" with timeout 5000ms
  - waiting for locator('text=Voice')

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
          - button "Data" [ref=e98] [cursor=pointer]:
            - img [ref=e99]
            - text: Data
          - button "Features" [active] [ref=e101] [cursor=pointer]:
            - img [ref=e102]
            - text: Features
          - button "About" [ref=e105] [cursor=pointer]:
            - img [ref=e106]
            - text: About
        - generic [ref=e108]:
          - generic [ref=e109]:
            - generic [ref=e110]:
              - generic [ref=e111]:
                - heading "Read Aloud" [level=3] [ref=e112]:
                  - img [ref=e113]
                  - text: Read Aloud
                - paragraph [ref=e117]: Text-to-speech voice settings
              - button "Reset" [ref=e119] [cursor=pointer]
            - generic [ref=e120]:
              - generic [ref=e121]:
                - img [ref=e122]
                - generic [ref=e126]: Voice
                - combobox [disabled] [ref=e127] [cursor=pointer]:
                  - option "Loading voices..." [disabled]
              - generic [ref=e128]:
                - generic [ref=e129]: Speed (1.0x)
                - slider [ref=e130]: "1"
              - generic [ref=e131]:
                - generic [ref=e132]: Volume (100%)
                - slider [ref=e133]: "100"
          - generic [ref=e134]:
            - generic [ref=e136]:
              - heading "Notifications" [level=3] [ref=e137]:
                - img [ref=e138]
                - text: Notifications
              - paragraph [ref=e141]: Writing reminders and alerts
            - generic [ref=e142]:
              - generic [ref=e143]:
                - textbox "Reminder title *" [ref=e144]
                - generic [ref=e145]:
                  - textbox "Message (optional)" [ref=e146]
                  - textbox [ref=e147]
                - generic [ref=e148]:
                  - combobox [ref=e149] [cursor=pointer]:
                    - option "Every day" [selected]
                    - option "Weekdays"
                    - option "Weekends"
                  - button "Add" [disabled] [ref=e150] [cursor=pointer]
              - generic [ref=e151]:
                - img [ref=e152]
                - paragraph [ref=e155]: No reminders set.
                - paragraph [ref=e156]: Create one above to get writing prompts.
          - generic [ref=e157]:
            - generic [ref=e159]:
              - heading "Plugins" [level=3] [ref=e160]:
                - img [ref=e161]
                - text: Plugins
              - paragraph [ref=e165]: Extend DailyByte with plugins
            - generic [ref=e166]:
              - generic [ref=e167]:
                - img [ref=e168]
                - paragraph [ref=e172]: Plugin Marketplace
                - paragraph [ref=e173]: Browse and install community plugins — coming soon.
              - generic [ref=e174]:
                - paragraph [ref=e175]: Install manually
                - generic [ref=e176]:
                  - textbox "Name *" [ref=e177]
                  - textbox "module:function *" [ref=e178]
                - generic [ref=e179]:
                  - textbox "Version" [ref=e180]
                  - button "Install" [disabled] [ref=e181] [cursor=pointer]:
                    - img [ref=e182]
                    - text: Install
              - generic [ref=e183]:
                - img [ref=e184]
                - paragraph [ref=e188]: No plugins installed.
                - paragraph [ref=e189]: Install one manually above or wait for the marketplace.
  - generic [ref=e193]:
    - generic [ref=e194]:
      - textbox "Title" [ref=e195]
      - textbox [ref=e196]: 2026-05-26
      - button "New entry" [ref=e197] [cursor=pointer]:
        - img [ref=e198]
      - generic [ref=e199]:
        - button "Fullscreen" [ref=e200] [cursor=pointer]:
          - img [ref=e201]
        - button [ref=e206] [cursor=pointer]:
          - img [ref=e207]
    - generic [ref=e210]:
      - generic [ref=e211]:
        - combobox [ref=e212] [cursor=pointer]:
          - option "System" [selected]
          - option "Segoe UI"
          - option "Inter"
          - option "Roboto"
          - option "Lora"
          - option "Merriweather"
          - option "JetBrains Mono"
          - option "Monospace"
        - combobox [ref=e213] [cursor=pointer]:
          - option "12px"
          - option "13px"
          - option "14px" [selected]
          - option "15px"
          - option "16px"
          - option "18px"
          - option "20px"
          - option "22px"
          - option "24px"
        - button "Undo (Ctrl+Z)" [disabled] [ref=e214] [cursor=pointer]:
          - img [ref=e215]
        - button "Redo (Ctrl+Y)" [disabled] [ref=e218] [cursor=pointer]:
          - img [ref=e219]
        - button "Bold (Ctrl+B)" [ref=e222] [cursor=pointer]:
          - img [ref=e223]
        - button "Italic (Ctrl+I)" [ref=e225] [cursor=pointer]:
          - img [ref=e226]
        - button "Strikethrough (Ctrl+U)" [ref=e228] [cursor=pointer]:
          - img [ref=e229]
        - button "Inline code (Ctrl+K)" [ref=e232] [cursor=pointer]:
          - img [ref=e233]
        - button "Code block" [ref=e236] [cursor=pointer]:
          - img [ref=e237]
        - button "Link" [ref=e239] [cursor=pointer]:
          - img [ref=e240]
        - button "Image" [ref=e243] [cursor=pointer]:
          - img [ref=e244]
        - button "Insert Emoji" [ref=e248] [cursor=pointer]:
          - img [ref=e249]
        - button "Focus Mode" [ref=e252] [cursor=pointer]:
          - img [ref=e253]
        - button "Typewriter Mode" [ref=e259] [cursor=pointer]:
          - img [ref=e260]
        - button "Find & Replace (Ctrl+F)" [ref=e262] [cursor=pointer]:
          - img [ref=e263]
      - generic [ref=e266]:
        - button "Heading 1" [ref=e267] [cursor=pointer]:
          - img [ref=e268]
        - button "Heading 2" [ref=e270] [cursor=pointer]:
          - img [ref=e271]
        - button "Bullet list" [ref=e274] [cursor=pointer]:
          - img [ref=e275]
        - button "Numbered list" [ref=e276] [cursor=pointer]:
          - img [ref=e277]
        - button "Blockquote" [ref=e280] [cursor=pointer]:
          - img [ref=e281]
        - button "Align left" [ref=e285] [cursor=pointer]:
          - img [ref=e286]
        - button "Align center" [ref=e287] [cursor=pointer]:
          - img [ref=e288]
        - button "Align right" [ref=e289] [cursor=pointer]:
          - img [ref=e290]
        - button "Align justify" [ref=e291] [cursor=pointer]:
          - img [ref=e292]
        - button "Highlight" [ref=e294] [cursor=pointer]:
          - img [ref=e295]
        - button "Checkbox" [ref=e299] [cursor=pointer]:
          - img [ref=e300]
        - button "Table" [ref=e303] [cursor=pointer]:
          - img [ref=e304]
        - button "Horizontal rule" [ref=e306] [cursor=pointer]:
          - img [ref=e307]
    - textbox "Write your thoughts..." [ref=e311]
    - generic [ref=e312]:
      - generic [ref=e313]:
        - generic [ref=e314]:
          - img [ref=e315]
          - text: 0 words
        - generic [ref=e316]: 0 chars
        - generic [ref=e317]: 0 lines
        - generic [ref=e318]: 0 paragraphs
        - generic [ref=e319]:
          - img [ref=e320]
          - text: 1 min read
      - generic [ref=e323]:
        - button [ref=e324] [cursor=pointer]:
          - img [ref=e325]
        - button [ref=e327] [cursor=pointer]:
          - img [ref=e328]
        - button "Tags" [ref=e331] [cursor=pointer]:
          - img [ref=e332]
        - button "Use template" [ref=e335] [cursor=pointer]:
          - img [ref=e336]
        - button "AI Smart Actions" [ref=e341] [cursor=pointer]:
          - img [ref=e342]
        - button "Version History" [ref=e345] [cursor=pointer]:
          - img [ref=e346]
        - button [ref=e351] [cursor=pointer]:
          - img [ref=e352]
        - button "Voice Recording" [ref=e355] [cursor=pointer]:
          - img [ref=e356]
        - button "Attach files" [ref=e359] [cursor=pointer]:
          - img [ref=e361]
        - button "Read aloud" [disabled] [ref=e363] [cursor=pointer]:
          - img [ref=e364]
        - button "Save" [ref=e368] [cursor=pointer]
```

# Test source

```ts
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
> 120 |     await expect(page.locator('text=Voice')).toBeVisible()
      |                                              ^ Error: expect(locator).toBeVisible() failed
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
  183 |     expect(hasFocusRing).toBeTruthy()
  184 |   })
  185 | })
  186 | 
```