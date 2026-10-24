/**
 * useTauriDragDrop — Tauri native drag-drop for editor media.
 *
 * WebKitGTK (the desktop webview) doesn't deliver HTML5 file drops, so the
 * frontend receives absolute file *paths* via Tauri's onDragDropEvent instead.
 * This composable owns the listener + unmount cleanup and drives the caller's
 * `isDragging` overlay flag; dropped paths are handled by the caller (upload
 * policy differs per editor).
 *
 * In the browser build this is a no-op (isDragging stays driven by the HTML5
 * drag handlers the editor also registers).
 */
import { onUnmounted, ref } from 'vue'
import type { Event as TauriEvent } from '@tauri-apps/api/event'
import type { DragDropEvent } from '@tauri-apps/api/webview'
import { isTauri } from '../api/client'

export function useTauriDragDrop() {
  const isDragging = ref(false)
  let unlisten: (() => void) | null = null

  /** Register the drag-drop listener; call once from onMounted. The listener
   *  is removed automatically on component unmount. */
  async function register(onPaths: (paths: string[]) => void): Promise<void> {
    if (!isTauri) return
    try {
      const { getCurrentWebview } = await import('@tauri-apps/api/webview')
      const handler = (event: TauriEvent<DragDropEvent>) => {
        const p = event.payload
        if (p.type === 'enter' || p.type === 'over') isDragging.value = true
        else if (p.type === 'leave') isDragging.value = false
        else if (p.type === 'drop') {
          isDragging.value = false
          onPaths(p.paths)
        }
      }
      unlisten = await getCurrentWebview().onDragDropEvent(handler)
    } catch (e) {
      console.warn('Tauri drag-drop unavailable', e)
    }
  }

  onUnmounted(() => {
    unlisten?.()
    unlisten = null
  })

  return { isDragging, register }
}
