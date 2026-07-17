/**
 * Single source of truth for the editor's AI tools.
 *
 * Every consumer — the AI drawer, the right-click context menu, and the
 * useAiTools composable — iterates `AI_TOOLS`. Adding a tool is now a data
 * change here (plus its backend prompt builder for `/ai/tool/<id>` tools).
 */
import type { Component } from 'vue'
import {
  ArrowRightLeft,
  Baby,
  BookOpen,
  CheckSquare,
  Eye,
  FileText,
  Gem,
  Heading,
  Languages,
  ListChecks,
  ListTree,
  Maximize2,
  MessageCircle,
  Minimize2,
  Type,
  Wand2,
} from 'lucide-vue-next'

export type ToolKind = 'grammar'

export interface AiToolParam {
  /** UI key for the parameter (tone | voice | language). */
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

export type AiToneStyle =
  | 'formal'
  | 'casual'
  | 'friendly'
  | 'professional'
  | 'emphatic'
  | 'humorous'
  | 'poetic'

export const AI_TONE_OPTIONS: readonly AiToneStyle[] = [
  'formal',
  'casual',
  'friendly',
  'professional',
  'emphatic',
  'humorous',
  'poetic',
]

/** Tool mode is a tool id (kept loose so the registry can grow). */
export type AiToolMode = string

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
    endpoint: '/ai/rewrite',
    resultField: 'rewritten_text',
    param: { name: 'tone', bodyKey: 'style', options: AI_TONE_OPTIONS, default: 'formal' },
  },
  {
    id: 'expand',
    label: 'Expand',
    icon: Maximize2,
    endpoint: '/ai/expand',
    resultField: 'expanded_text',
  },
  {
    id: 'tone',
    label: 'Tone',
    icon: MessageCircle,
    endpoint: '/ai/change-tone',
    resultField: 'changed_text',
    param: { name: 'tone', bodyKey: 'tone', options: AI_TONE_OPTIONS, default: 'formal' },
  },
  {
    id: 'define',
    label: 'Define',
    icon: BookOpen,
    endpoint: '/ai/define-text',
    resultField: 'definition',
  },
  {
    id: 'voice',
    label: 'Voice',
    icon: ArrowRightLeft,
    endpoint: '/ai/change-voice',
    resultField: 'changed_text',
    param: { name: 'voice', bodyKey: 'voice', options: ['active', 'passive'], default: 'active' },
  },
  {
    id: 'clarity',
    label: 'Clarity',
    icon: Eye,
    endpoint: '/ai/rewrite-for-clarity',
    resultField: 'rewritten_text',
  },
  {
    id: 'summarize',
    label: 'Summarize',
    icon: FileText,
    endpoint: '/ai/tool/summarize',
    resultField: 'result',
  },
  {
    id: 'key-points',
    label: 'Key Points',
    icon: ListChecks,
    endpoint: '/ai/tool/key-points',
    resultField: 'result',
  },
  {
    id: 'action-items',
    label: 'Actions',
    icon: CheckSquare,
    endpoint: '/ai/tool/action-items',
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
    id: 'simplify',
    label: 'Simplify',
    icon: Baby,
    endpoint: '/ai/tool/simplify',
    resultField: 'result',
  },
  {
    id: 'polish',
    label: 'Polish',
    icon: Gem,
    endpoint: '/ai/tool/polish',
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
      options: ['Spanish', 'French', 'German', 'Italian', 'Portuguese', 'Japanese', 'Chinese', 'Hindi', 'Arabic', 'English'],
      default: 'Spanish',
    },
  },
  {
    id: 'add-structure',
    label: 'Structure',
    icon: ListTree,
    endpoint: '/ai/tool/add-structure',
    resultField: 'result',
  },
  {
    id: 'title',
    label: 'Title',
    icon: Heading,
    endpoint: '/ai/tool/title',
    resultField: 'result',
  },
]

export const AI_TOOL_BY_ID: Record<string, AiToolDef> = Object.fromEntries(
  AI_TOOLS.map((t) => [t.id, t]),
)
