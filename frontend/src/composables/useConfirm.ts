import { ref } from 'vue'

export interface ConfirmRequest {
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
}

// Module-level singleton: one pending dialog at a time, settled via the
// ConfirmDialogHost mounted in App.vue. Lets any component (or plain
// composable / router guard) await a modal confirmation without owning
// ConfirmDialog boilerplate — spec §9 ED9 bans native window.confirm.
const current = ref<ConfirmRequest | null>(null)
let resolver: ((proceed: boolean) => void) | null = null

export function useConfirm() {
  function confirm(req: ConfirmRequest): Promise<boolean> {
    // Shouldn't happen (requests are awaited before the next one), but a
    // stale unresolved dialog must never wedge the new one.
    if (resolver) resolver(false)
    current.value = req
    return new Promise((r) => {
      resolver = r
    })
  }

  function settle(proceed: boolean) {
    current.value = null
    resolver?.(proceed)
    resolver = null
  }

  return { confirm, current, settle }
}
