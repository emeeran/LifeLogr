import { isTauri } from '../api/client'

/**
 * Save data to a file chosen by the user via native Save As dialog.
 * Falls back to browser <a download> when not running in Tauri.
 *
 * @returns true if saved, false if user cancelled
 */
export async function saveFile(options: {
  data: Blob | string
  defaultName: string
  filters?: { name: string; extensions: string[] }[]
}): Promise<boolean> {
  const { data, defaultName, filters } = options

  if (isTauri) {
    const { save } = await import('@tauri-apps/plugin-dialog')
    const path = await save({ defaultPath: defaultName, filters })
    if (!path) return false

    let uint8: Uint8Array
    if (typeof data === 'string') {
      uint8 = new TextEncoder().encode(data)
    } else {
      uint8 = new Uint8Array(await data.arrayBuffer())
    }

    const { writeFile } = await import('@tauri-apps/plugin-fs')
    await writeFile(path, uint8)
    return true
  }

  // Browser fallback: create <a download> click
  const blob = typeof data === 'string' ? new Blob([data]) : data
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = defaultName
  a.click()
  URL.revokeObjectURL(url)
  return true
}

/**
 * Open a file chosen by the user via native Open File dialog.
 * Falls back to triggering a hidden <input type="file"> when not in Tauri.
 *
 * @returns File object, or null if user cancelled
 */
export async function pickFile(options?: {
  accept?: string
  multiple?: boolean
}): Promise<File | null> {
  if (isTauri) {
    const { open } = await import('@tauri-apps/plugin-dialog')
    const selected = await open({
      multiple: options?.multiple ?? false,
      filters: options?.accept
        ? [{ name: 'Files', extensions: options.accept.split(',').map(e => e.replace(/^\./, '')) }]
        : undefined,
    })
    if (!selected) return null

    const paths = Array.isArray(selected) ? selected : [selected]
    const first = paths[0]
    if (!first) return null

    const { readFile } = await import('@tauri-apps/plugin-fs')
    const bytes = await readFile(first)
    const name = first.split('/').pop() ?? 'file'
    return new File([bytes], name)
  }

  // Browser fallback: click hidden <input type="file">
  return new Promise<File | null>((resolve) => {
    const input = document.createElement('input')
    input.type = 'file'
    if (options?.accept) input.accept = options.accept
    if (options?.multiple) input.multiple = true
    input.onchange = () => {
      resolve(input.files?.[0] ?? null)
    }
    input.click()
  })
}

/**
 * Open a native folder picker dialog (Tauri only).
 * Returns null in browser (not supported).
 */
export async function pickFolder(): Promise<string | null> {
  if (!isTauri) return null

  const { open } = await import('@tauri-apps/plugin-dialog')
  const selected = await open({ directory: true })
  if (!selected || Array.isArray(selected)) return null
  return selected
}
