/**
 * Single source of truth for the editor's AI tools.
 *
 * Every consumer — the AI drawer, the right-click context menu, and the
 * useAiTools composable — iterates `AI_TOOLS`. The menu presents the folded
 * 8-tool contract set (spec.md §10 AI4): rewrite-style operations are one
 * "Rewrite" tool with a mode parameter, and summarize/key-points/actions fold
 * into one "Summarize" tool with a mode parameter. `define` is dropped from
 * the menu (its backend endpoint remains).
 *
 * Adding a tool is a data change here (plus its backend prompt builder for
 * `/ai/tool/<id>` tools).
 */
import type { Component } from 'vue'
import {
  FileText,
  Heading,
  Languages,
  Maximize2,
  Minimize2,
  PenLine,
  Type,
  Wand2,
} from 'lucide-vue-next'
import { useEntriesStore } from '../stores/entries'

export type ToolKind = 'grammar'

export interface AiToolParam {
  /** UI key for the parameter (mode | language). */
  name: string
  /** Request-body field the parameter value is sent under. */
  bodyKey: string
  options: readonly string[]
  default: string
}

export interface AiToolDef {
  /** Stable id; also the tool "mode" passed between components. */
  id: string
  /** Short label for buttons / menu items. */
  label: string
  /** lucide-vue-next icon component. */
  icon: Component
  /** API endpoint relative to the client base. */
  endpoint: string
  /** Response field holding the result text. */
  resultField: string
  /** Optional single parameter rendered as pills. */
  param?: AiToolParam
  /** 'grammar' surfaces the suggestions list alongside corrected_text. */
  kind?: ToolKind
}

/** Tool mode is a tool id (kept loose so the registry can grow). */
export type AiToolMode = string

const LANGUAGE_OPTIONS = [
  'Spanish',
  'French',
  'German',
  'Italian',
  'Portuguese',
  'Japanese',
  'Chinese',
  'Hindi',
  'Arabic',
  'English',
] as const

export const AI_TOOLS: readonly AiToolDef[] = [
  {
    id: 'grammar',
    label: 'Grammar',
    icon: Type,
    endpoint: '/ai/grammar-check',
    resultField: 'corrected_text',
    kind: 'grammar',
  },
  {
    id: 'rewrite',
    label: 'Rewrite',
    icon: Wand2,
    endpoint: '/ai/tool/rewrite',
    resultField: 'result',
    param: {
      name: 'mode',
      bodyKey: 'param',
      options: ['as-is', 'polish', 'clarity', 'simplify', 'formal', 'casual'],
      default: 'as-is',
    },
  },
  {
    id: 'summarize',
    label: 'Summarize',
    icon: FileText,
    endpoint: '/ai/tool/summarize',
    resultField: 'result',
    param: {
      name: 'mode',
      bodyKey: 'param',
      options: ['sentences', 'bullets', 'actions'],
      default: 'sentences',
    },
  },
  {
    id: 'expand',
    label: 'Expand',
    icon: Maximize2,
    endpoint: '/ai/tool/expand',
    resultField: 'result',
  },
  {
    id: 'shorten',
    label: 'Shorten',
    icon: Minimize2,
    endpoint: '/ai/tool/shorten',
    resultField: 'result',
  },
  {
    id: 'title',
    label: 'Title',
    icon: Heading,
    endpoint: '/ai/tool/title',
    resultField: 'result',
  },
  {
    id: 'translate',
    label: 'Translate',
    icon: Languages,
    endpoint: '/ai/tool/translate',
    resultField: 'result',
    param: {
      name: 'language',
      bodyKey: 'param',
      options: LANGUAGE_OPTIONS,
      default: 'Spanish',
    },
  },
  {
    id: 'continue',
    label: 'Continue',
    icon: PenLine,
    endpoint: '/ai/continue-writing',
    resultField: 'continuation',
  },
]

export const AI_TOOL_BY_ID: Record<string, AiToolDef> = Object.fromEntries(
  AI_TOOLS.map((t) => [t.id, t]),
)

// ── Request enrichment shared by every AI caller ─────────────────────────

/**
 * Backend maximum accepted selection length (chars) — mirrors
 * `MAX_TOOL_TEXT_CHARS` in backend/app/services/ai_tool_registry.py. Longer
 * selections are truncated and the truncation MUST be surfaced (spec AI3).
 */
export const AI_MAX_TEXT_CHARS = 4000

export interface AiTruncation {
  sent: number
  total: number
}

/** Truncate an over-long selection and describe what was cut (spec AI3). */
export function truncateForAi(text: string): {
  text: string
  truncation: AiTruncation | null
} {
  if (text.length <= AI_MAX_TEXT_CHARS) return { text, truncation: null }
  return {
    text: text.slice(0, AI_MAX_TEXT_CHARS),
    truncation: { sent: AI_MAX_TEXT_CHARS, total: text.length },
  }
}

/** Metadata of the currently open entry, sent in the AI system channel. */
export interface AiEntryContext {
  date: string | null
  title: string | null
  mood: string | null
  tags: string[]
}

/** Read the entry context from the currently open journal entry, if any. */
export function currentEntryContext(): AiEntryContext | null {
  const entry = useEntriesStore().currentEntry
  if (!entry) return null
  return {
    date: entry.entry_date ?? null,
    title: entry.title ?? null,
    mood: entry.mood ?? null,
    tags: (entry.tags ?? []).map((t) => t.name),
  }
}
