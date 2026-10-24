import { ref, watch, onUnmounted, nextTick } from 'vue'

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * useModalFocus — the a11y boilerplate every app modal needs: `role="dialog"`,
 * `aria-modal`, a Tab focus trap, Esc-to-close and focus restoration.
 *
 * Bind the returned `container` ref to the dialog PANEL (not the backdrop) and
 * wire `onKeydown` on it, then add the `role`/`aria-modal` attributes in the
 * template:
 *
 *   <div ref="modal.container" role="dialog" aria-modal="true"
 *        :aria-label="…" tabindex="-1" @keydown="modal.onKeydown">
 *
 * `active` is a getter for the open flag (a `v-if` condition), `onClose` runs on
 * Esc. Focus is captured on open and restored on close.
 */
export function useModalFocus(
  active: () => boolean,
  onClose?: () => void,
) {
  const container = ref<HTMLElement | null>(null)
  let previouslyFocused: HTMLElement | null = null

  function focusFirst() {
    const root = container.value
    if (!root) return
    const target = root.querySelector<HTMLElement>(FOCUSABLE) ?? root
    target.focus({ preventScroll: true })
  }

  function trapTab(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      onClose?.()
      return
    }
    if (e.key !== 'Tab') return
    const root = container.value
    if (!root) return
    const items = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
      (el) => el.offsetParent !== null || el === document.activeElement,
    )
    if (!items.length) {
      e.preventDefault()
      root.focus()
      return
    }
    const first = items[0]
    const last = items[items.length - 1]
    const current = document.activeElement as HTMLElement | null
    if (e.shiftKey) {
      if (current === first || !root.contains(current)) {
        e.preventDefault()
        last.focus()
      }
    } else if (current === last || !root.contains(current)) {
      e.preventDefault()
      first.focus()
    }
  }

  watch(
    active,
    (open) => {
      if (open) {
        previouslyFocused = document.activeElement as HTMLElement | null
        void nextTick(() => {
          focusFirst()
          container.value?.scrollIntoView?.({ block: 'nearest' })
        })
      } else if (previouslyFocused) {
        previouslyFocused.focus({ preventScroll: true })
        previouslyFocused = null
      }
    },
    // immediate: components that mount already-open (v-if modals) must still
    // capture focus; for closed-at-mount modals the else branch is a no-op.
    { immediate: true },
  )

  onUnmounted(() => {
    // If the component unmounts while open, still hand focus back.
    if (previouslyFocused && document.contains(previouslyFocused)) {
      previouslyFocused.focus({ preventScroll: true })
    }
    previouslyFocused = null
  })

  return { container, onKeydown: trapTab }
}
