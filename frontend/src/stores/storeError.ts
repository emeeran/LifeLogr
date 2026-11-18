import type { Ref } from 'vue'
import { errorMessage } from '../utils/errorMessage'
import { useToastStore } from './toast'

/** Set a store's `error` ref + toast — the one place store failures reach the user. */
export function failStoreError(error: Ref<string | null>, fallback: string, e: unknown) {
  const message = errorMessage(e) || fallback
  error.value = message
  useToastStore().error(`${fallback}: ${message}`)
}
