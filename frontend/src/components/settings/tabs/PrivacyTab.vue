<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  Shield,
  Sparkles,
  Cloud,
  Scissors,
  ScanText,
  Volume2,
  CheckCircle2,
  AlertTriangle,
} from 'lucide-vue-next'
import SettingsSection from '../shared/SettingsSection.vue'
import SkeletonCard from '../shared/SkeletonCard.vue'
import {
  getEgressReport,
  type EgressReport,
  type EgressSurface,
} from '../../../api/system'
import { errMsg } from '../../../utils/errorMessage.ts'

// A surface row in the report. `leavesDevice` is the truth that drives the badge.
const report = ref<EgressReport | null>(null)
const loading = ref(true)
const errorMsg = ref('')

// Keys this tab renders with a bespoke card (icon + copy). Anything else the
// backend adds to the report — read_aloud today, whatever next — renders through
// the generic card below instead of being invisible / mislabelled here.
const BESPOKE_KEYS = ['cloud_ai', 'cloud_backup', 'web_clip', 'ocr', 'embeddings']
const EXTRA_LABELS: Record<string, string> = {
  read_aloud: 'Read aloud (text-to-speech)',
}
function extraLabel(key: string): string {
  return (
    EXTRA_LABELS[key] ??
    key.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())
  )
}
/** Surfaces the backend reports that this tab has no bespoke card for. */
const extraSurfaces = computed(() => {
  const r = report.value
  if (!r) return []
  return Object.entries(r)
    .filter(
      ([key, value]) =>
        !BESPOKE_KEYS.includes(key) &&
        !!value &&
        typeof value === 'object' &&
        'note' in (value as object),
    )
    .map(([key, value]) => ({
      key,
      label: extraLabel(key),
      surface: value as EgressSurface,
    }))
})

onMounted(async () => {
  try {
    report.value = await getEgressReport()
  } catch (e: unknown) {
    errorMsg.value = errMsg(e)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <SettingsSection
    title="What leaves your machine"
    :icon="Shield"
    description="LifeLogr is privacy-first and local-first by default. Every surface in this report can send data off your device, and none are on unless you turn them on — the list is whatever your build's backend reports."
    setting-key="What leaves your machine"
  >
    <template v-if="loading"><SkeletonCard :lines="5" /></template>
    <template v-else-if="report">
      <!-- AI tools -->
      <div
        class="mb-2 rounded-md border p-2.5"
        :class="
          report.cloud_ai.leaves_device
            ? 'border-amber-500/40 bg-amber-500/5'
            : 'border-border bg-surface-hover'
        "
      >
        <div class="mb-1 flex items-center gap-1.5">
          <Sparkles :size="13" class="text-text-secondary" />
          <span class="text-[12px] font-medium text-text-primary"
            >AI tools</span
          >
          <span
            v-if="report.cloud_ai.leaves_device"
            class="ml-auto inline-flex items-center gap-1 rounded bg-amber-500/15 px-1.5 py-px text-[9px] font-medium text-amber-300"
          >
            <AlertTriangle :size="10" /> leaves device
          </span>
          <span
            v-else
            class="ml-auto inline-flex items-center gap-1 rounded bg-green-500/15 px-1.5 py-px text-[9px] font-medium text-green-300"
          >
            <CheckCircle2 :size="10" /> on-device
          </span>
        </div>
        <p class="text-[11px] leading-snug text-text-muted">
          {{ report.cloud_ai.note }}
        </p>
      </div>

      <!-- Cloud backup -->
      <div
        class="mb-2 rounded-md border p-2.5"
        :class="
          report.cloud_backup.scheduled
            ? 'border-amber-500/40 bg-amber-500/5'
            : 'border-border bg-surface-hover'
        "
      >
        <div class="mb-1 flex items-center gap-1.5">
          <Cloud :size="13" class="text-text-secondary" />
          <span class="text-[12px] font-medium text-text-primary"
            >Cloud backup</span
          >
          <span
            v-if="report.cloud_backup.scheduled"
            class="ml-auto inline-flex items-center gap-1 rounded bg-amber-500/15 px-1.5 py-px text-[9px] font-medium text-amber-300"
          >
            <AlertTriangle :size="10" /> uploads when scheduled
          </span>
          <span
            v-else
            class="ml-auto inline-flex items-center gap-1 rounded bg-green-500/15 px-1.5 py-px text-[9px] font-medium text-green-300"
          >
            <CheckCircle2 :size="10" /> off
          </span>
        </div>
        <p class="text-[11px] leading-snug text-text-muted">
          {{ report.cloud_backup.note }}
        </p>
        <div
          v-if="report.cloud_backup.configured.length"
          class="mt-1.5 flex flex-wrap gap-1"
        >
          <span
            v-for="c in report.cloud_backup.configured"
            :key="c.provider"
            class="rounded bg-surface px-1.5 py-0.5 text-[10px] text-text-secondary"
            >{{ c.label }}</span
          >
        </div>
      </div>

      <!-- Web clip -->
      <div class="mb-2 rounded-md border border-border bg-surface-hover p-2.5">
        <div class="mb-1 flex items-center gap-1.5">
          <Scissors :size="13" class="text-text-secondary" />
          <span class="text-[12px] font-medium text-text-primary"
            >Web clip</span
          >
          <span
            class="ml-auto inline-flex items-center gap-1 rounded bg-green-500/15 px-1.5 py-px text-[9px] font-medium text-green-300"
          >
            <CheckCircle2 :size="10" /> journal stays local
          </span>
        </div>
        <p class="text-[11px] leading-snug text-text-muted">
          {{ report.web_clip.note }}
        </p>
      </div>

      <!-- OCR -->
      <div class="mb-2 rounded-md border border-border bg-surface-hover p-2.5">
        <div class="mb-1 flex items-center gap-1.5">
          <ScanText :size="13" class="text-text-secondary" />
          <span class="text-[12px] font-medium text-text-primary"
            >OCR (image text)</span
          >
          <span
            class="ml-auto inline-flex items-center gap-1 rounded bg-green-500/15 px-1.5 py-px text-[9px] font-medium text-green-300"
          >
            <CheckCircle2 :size="10" /> on-device · {{ report.ocr.engine }}
          </span>
        </div>
        <p class="text-[11px] leading-snug text-text-muted">
          {{ report.ocr.note }}
        </p>
      </div>

      <!-- Read aloud (rendered when the backend report includes it) -->
      <div
        v-if="report.read_aloud"
        class="rounded-md border p-2.5"
        :class="
          report.read_aloud.leaves_device
            ? 'border-amber-500/40 bg-amber-500/5'
            : 'border-border bg-surface-hover'
        "
      >
        <div class="mb-1 flex items-center gap-1.5">
          <Volume2 :size="13" class="text-text-secondary" />
          <span class="text-[12px] font-medium text-text-primary"
            >Read aloud (text-to-speech)</span
          >
          <span
            v-if="report.read_aloud.leaves_device"
            class="ml-auto inline-flex items-center gap-1 rounded bg-amber-500/15 px-1.5 py-px text-[9px] font-medium text-amber-300"
          >
            <AlertTriangle :size="10" /> leaves device
          </span>
          <span
            v-else
            class="ml-auto inline-flex items-center gap-1 rounded bg-green-500/15 px-1.5 py-px text-[9px] font-medium text-green-300"
          >
            <CheckCircle2 :size="10" /> on-device
          </span>
        </div>
        <p class="text-[11px] leading-snug text-text-muted">
          {{ report.read_aloud.note }}
        </p>
      </div>

      <!-- Any other surface the backend reports (rendered generically) -->
      <div
        v-for="extra in extraSurfaces"
        :key="extra.key"
        class="rounded-md border p-2.5"
        :class="
          extra.surface.leaves_device
            ? 'border-amber-500/40 bg-amber-500/5'
            : 'border-border bg-surface-hover'
        "
      >
        <div class="mb-1 flex items-center gap-1.5">
          <Shield :size="13" class="text-text-secondary" />
          <span class="text-[12px] font-medium text-text-primary">{{
            extra.label
          }}</span>
          <span
            v-if="extra.surface.leaves_device"
            class="ml-auto inline-flex items-center gap-1 rounded bg-amber-500/15 px-1.5 py-px text-[9px] font-medium text-amber-300"
          >
            <AlertTriangle :size="10" /> leaves device
          </span>
          <span
            v-else
            class="ml-auto inline-flex items-center gap-1 rounded bg-green-500/15 px-1.5 py-px text-[9px] font-medium text-green-300"
          >
            <CheckCircle2 :size="10" /> on-device
          </span>
        </div>
        <p class="text-[11px] leading-snug text-text-muted">
          {{ extra.surface.note }}
        </p>
      </div>

      <!-- Embeddings -->
      <div
        class="rounded-md border p-2.5"
        :class="
          report.embeddings.leaves_device
            ? 'border-amber-500/40 bg-amber-500/5'
            : 'border-border bg-surface-hover'
        "
      >
        <div class="mb-1 flex items-center gap-1.5">
          <Sparkles :size="13" class="text-text-secondary" />
          <span class="text-[12px] font-medium text-text-primary"
            >Embeddings (semantic search)</span
          >
          <span
            v-if="report.embeddings.leaves_device"
            class="ml-auto inline-flex items-center gap-1 rounded bg-amber-500/15 px-1.5 py-px text-[9px] font-medium text-amber-300"
          >
            <AlertTriangle :size="10" /> leaves device
          </span>
          <span
            v-else
            class="ml-auto inline-flex items-center gap-1 rounded bg-green-500/15 px-1.5 py-px text-[9px] font-medium text-green-300"
          >
            <CheckCircle2 :size="10" /> on-device
          </span>
        </div>
        <p class="text-[11px] leading-snug text-text-muted">
          {{ report.embeddings.note }}
        </p>
      </div>

      <p
        class="mt-3 flex items-start gap-1.5 text-[10.5px] leading-snug text-text-muted"
      >
        <Shield :size="12" class="mt-px shrink-0" />
        Encrypted entries and notes are AES-256-GCM protected and never indexed
        for search while encrypted. Your
        <code class="text-text-secondary">.secret_key</code> never leaves this
        machine — keep it safe.
      </p>
    </template>
    <div v-else class="flex items-center gap-1.5 text-[11px] text-red-400">
      <AlertTriangle :size="12" /> Could not load the privacy report:
      {{ errorMsg }}
    </div>
  </SettingsSection>
</template>
