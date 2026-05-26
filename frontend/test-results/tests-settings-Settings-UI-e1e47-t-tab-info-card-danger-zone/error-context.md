# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: tests/settings.spec.ts >> Settings UI verification >> About tab: info card, danger zone
- Location: tests/settings.spec.ts:136:3

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('text=About')
Expected: visible
Error: strict mode violation: locator('text=About') resolved to 2 elements:
    1) <button data-v-ee475729="" class="w-full flex items-center gap-2 px-2.5 py-2 rounded-md text-[12px] font-medium cursor-pointer transition-colors bg-accent/15 text-accent">…</button> aka getByRole('button', { name: 'About' })
    2) <h3 class="text-[11px] font-medium text-text-muted uppercase tracking-wide flex items-center gap-1.5">…</h3> aka getByRole('heading', { name: 'About' })

Call log:
  - Expect "toBeVisible" with timeout 5000ms
  - waiting for locator('text=About')

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
          - button "Features" [ref=e101] [cursor=pointer]:
            - img [ref=e102]
            - text: Features
          - button "About" [active] [ref=e105] [cursor=pointer]:
            - img [ref=e106]
            - text: About
        - generic [ref=e108]:
          - generic [ref=e109]:
            - generic [ref=e111]:
              - heading "About" [level=3] [ref=e112]:
                - img [ref=e113]
                - text: About
              - paragraph [ref=e115]: App information and credits
            - generic [ref=e117]:
              - generic [ref=e118]: Diarilinux
              - generic [ref=e119]: Version 0.1.0
              - generic [ref=e120]: Privacy-first, offline-first journaling for Linux
              - generic [ref=e121]:
                - img [ref=e122]
                - text: Dedicated to my son Tariq Al Fayad
              - generic [ref=e124]:
                - link "GitHub" [ref=e125] [cursor=pointer]:
                  - /url: https://github.com/diarilinux/diarilinux
                - link "Report Issue" [ref=e126] [cursor=pointer]:
                  - /url: https://github.com/diarilinux/diarilinux/issues
                - link "License" [ref=e127] [cursor=pointer]:
                  - /url: https://github.com/diarilinux/diarilinux/blob/main/LICENSE
          - generic [ref=e130]:
            - generic [ref=e131]:
              - generic [ref=e132]: Reset Database
              - generic [ref=e133]: Delete all entries, tags, and media.
            - button "Reset" [ref=e134] [cursor=pointer]
  - generic [ref=e138]:
    - generic [ref=e139]:
      - textbox "Title" [ref=e140]
      - textbox [ref=e141]: 2026-05-26
      - button "New entry" [ref=e142] [cursor=pointer]:
        - img [ref=e143]
      - generic [ref=e144]:
        - button "Fullscreen" [ref=e145] [cursor=pointer]:
          - img [ref=e146]
        - button [ref=e151] [cursor=pointer]:
          - img [ref=e152]
    - generic [ref=e155]:
      - generic [ref=e156]:
        - combobox [ref=e157] [cursor=pointer]:
          - option "System" [selected]
          - option "Segoe UI"
          - option "Inter"
          - option "Roboto"
          - option "Lora"
          - option "Merriweather"
          - option "JetBrains Mono"
          - option "Monospace"
        - combobox [ref=e158] [cursor=pointer]:
          - option "12px"
          - option "13px"
          - option "14px" [selected]
          - option "15px"
          - option "16px"
          - option "18px"
          - option "20px"
          - option "22px"
          - option "24px"
        - button "Undo (Ctrl+Z)" [disabled] [ref=e159] [cursor=pointer]:
          - img [ref=e160]
        - button "Redo (Ctrl+Y)" [disabled] [ref=e163] [cursor=pointer]:
          - img [ref=e164]
        - button "Bold (Ctrl+B)" [ref=e167] [cursor=pointer]:
          - img [ref=e168]
        - button "Italic (Ctrl+I)" [ref=e170] [cursor=pointer]:
          - img [ref=e171]
        - button "Strikethrough (Ctrl+U)" [ref=e173] [cursor=pointer]:
          - img [ref=e174]
        - button "Inline code (Ctrl+K)" [ref=e177] [cursor=pointer]:
          - img [ref=e178]
        - button "Code block" [ref=e181] [cursor=pointer]:
          - img [ref=e182]
        - button "Link" [ref=e184] [cursor=pointer]:
          - img [ref=e185]
        - button "Image" [ref=e188] [cursor=pointer]:
          - img [ref=e189]
        - button "Insert Emoji" [ref=e193] [cursor=pointer]:
          - img [ref=e194]
        - button "Focus Mode" [ref=e197] [cursor=pointer]:
          - img [ref=e198]
        - button "Typewriter Mode" [ref=e204] [cursor=pointer]:
          - img [ref=e205]
        - button "Find & Replace (Ctrl+F)" [ref=e207] [cursor=pointer]:
          - img [ref=e208]
      - generic [ref=e211]:
        - button "Heading 1" [ref=e212] [cursor=pointer]:
          - img [ref=e213]
        - button "Heading 2" [ref=e215] [cursor=pointer]:
          - img [ref=e216]
        - button "Bullet list" [ref=e219] [cursor=pointer]:
          - img [ref=e220]
        - button "Numbered list" [ref=e221] [cursor=pointer]:
          - img [ref=e222]
        - button "Blockquote" [ref=e225] [cursor=pointer]:
          - img [ref=e226]
        - button "Align left" [ref=e230] [cursor=pointer]:
          - img [ref=e231]
        - button "Align center" [ref=e232] [cursor=pointer]:
          - img [ref=e233]
        - button "Align right" [ref=e234] [cursor=pointer]:
          - img [ref=e235]
        - button "Align justify" [ref=e236] [cursor=pointer]:
          - img [ref=e237]
        - button "Highlight" [ref=e239] [cursor=pointer]:
          - img [ref=e240]
        - button "Checkbox" [ref=e244] [cursor=pointer]:
          - img [ref=e245]
        - button "Table" [ref=e248] [cursor=pointer]:
          - img [ref=e249]
        - button "Horizontal rule" [ref=e251] [cursor=pointer]:
          - img [ref=e252]
    - textbox "Write your thoughts..." [ref=e256]
    - generic [ref=e257]:
      - generic [ref=e258]:
        - generic [ref=e259]:
          - img [ref=e260]
          - text: 0 words
        - generic [ref=e261]: 0 chars
        - generic [ref=e262]: 0 lines
        - generic [ref=e263]: 0 paragraphs
        - generic [ref=e264]:
          - img [ref=e265]
          - text: 1 min read
      - generic [ref=e268]:
        - button [ref=e269] [cursor=pointer]:
          - img [ref=e270]
        - button [ref=e272] [cursor=pointer]:
          - img [ref=e273]
        - button "Tags" [ref=e276] [cursor=pointer]:
          - img [ref=e277]
        - button "Use template" [ref=e280] [cursor=pointer]:
          - img [ref=e281]
        - button "AI Smart Actions" [ref=e286] [cursor=pointer]:
          - img [ref=e287]
        - button "Version History" [ref=e290] [cursor=pointer]:
          - img [ref=e291]
        - button [ref=e296] [cursor=pointer]:
          - img [ref=e297]
        - button "Voice Recording" [ref=e300] [cursor=pointer]:
          - img [ref=e301]
        - button "Attach files" [ref=e304] [cursor=pointer]:
          - img [ref=e306]
        - button "Read aloud" [disabled] [ref=e308] [cursor=pointer]:
          - img [ref=e309]
        - button "Save" [ref=e313] [cursor=pointer]
```

# Test source

```ts
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
> 140 |     await expect(page.locator('text=About')).toBeVisible()
      |                                              ^ Error: expect(locator).toBeVisible() failed
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