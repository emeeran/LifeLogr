// ESLint flat config. Deliberately pragmatic: catches real defects (unused
// vars, unsanitized HTML, leaking loops) without fighting the existing style.
// Style/formatting stays with prettier-if-ever-added; nothing here enforces
// quote/comma taste.
import pluginVue from 'eslint-plugin-vue'
import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'

export default defineConfigWithVueTs(
  {
    ignores: ['dist/**', 'node_modules/**', 'coverage/**', 'test-results/**', 'playwright-report/**'],
  },
  pluginVue.configs['flat/recommended'],
  vueTsConfigs.recommended,
  {
    files: ['**/*.vue', '**/*.ts'],
    rules: {
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrors: 'none' },
      ],
      // The codebase uses this shape throughout; not worth a mass reformat.
      'vue/multi-word-component-names': 'off',
      // Pure style — the codebase predates it and churn helps no one.
      'vue/attributes-order': 'off',
      'vue/max-attributes-per-line': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/html-self-closing': 'off',
      'vue/html-indent': 'off',
      'vue/html-closing-bracket-newline': 'off',
      'vue/first-attribute-linebreak': 'off',
      'vue/attribute-hyphenation': 'off',
      'vue/component-name-in-template-casing': 'off',
      // v-html is always paired with DOMPurify here; the shared
      // renderMarkdown() util is the enforced pattern going forward.
      'vue/no-v-html': 'warn',
    },
  },
  {
    files: ['src/**/*.test.ts', 'tests/**/*.ts'],
    rules: {
      '@typescript-eslint/no-non-null-assertion': 'off',
    },
  },
)
