import { isTauri } from '../api/client'

export interface SaveFilter {
  name: string
  extensions: string[]
}

export interface SaveOptions {
  defaultName: string
  filters?: SaveFilter[]
}

/** Reduce a builder URL to the backend-relative path+query the desktop
 *  shell's save_url_as command expects (it talks to the sidecar directly). */
function backendPathQuery(url: string): string {
  if (url.startsWith('/')) return url
  const parsed = new URL(url)
  return `${parsed.pathname}${parsed.search}`
}

/**
 * Stream a backend GET straight to a file chosen via the native Save dialog,
 * without pulling the bytes through the webview — a ~200MB export pushed
 * through WebKitGTK's IPC amplifies into multi-GB renderer memory and the
 * kernel kills the app. Falls back to fetch + <a download> when not in Tauri.
 *
 * @returns true if saved, false if the user cancelled the dialog
 */
export async function saveUrlAs(url: string, options: SaveOptions): Promise<boolean> {
  if (isTauri) {
    const { invoke } = await import('@tauri-apps/api/core')
    return invoke<boolean>('save_url_as', {
      pathQuery: backendPathQuery(url),
      defaultName: options.defaultName,
      filters: options.filters ?? null,
    })
  }

  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  const blob = await resp.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = options.defaultName
  a.click()
  URL.revokeObjectURL(a.href)
  return true
}

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
        ? [
            {
              name: 'Files',
              extensions: options.accept
                .split(',')
                .map((e) => e.replace(/^\./, '')),
            },
          ]
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

/**
 * Open a native file picker and return the picked path itself (Tauri only).
 * Unlike `pickFile`, no bytes cross the webview IPC — pair with
 * `uploadFileAs` so large uploads stream from disk in the Rust shell instead
 * of amplifying into multi-GB renderer memory (see save_url_as / upload_file_as).
 * Returns null in browser (browsers cannot hand out paths) or on cancel.
 */
export async function pickPath(options?: {
  accept?: string
}): Promise<string | null> {
  if (!isTauri) return null

  const { open } = await import('@tauri-apps/plugin-dialog')
  const selected = await open({
    multiple: false,
    filters: options?.accept
      ? [
          {
            name: 'Files',
            extensions: options.accept
              .split(',')
              .map((e) => e.replace(/^\./, '')),
          },
        ]
      : undefined,
  })
  if (!selected || Array.isArray(selected)) return null
  return selected
}

/**
 * Stream the file at `path` straight from disk to a backend multipart
 * endpoint via the desktop shell's `upload_file_as` command — the bytes never
 * enter the webview. Returns the backend's response body as text (rejects
 * with the body excerpt on a non-2xx).
 */
export async function uploadFileAs(
  path: string,
  pathQuery: string,
  fieldName = 'file',
): Promise<string> {
  const { invoke } = await import('@tauri-apps/api/core')
  return invoke<string>('upload_file_as', {
    filePath: path,
    pathQuery,
    fieldName,
  })
}

/**
 * Pick a file natively and stream-upload it to a multipart endpoint,
 * returning the parsed JSON response. Returns null when the user cancels
 * (or in browser, where callers keep their own pickFile/FormData flow).
 */
export async function pickAndUploadJson<T>(
  pathQuery: string,
  accept: string,
  fieldName = 'file',
): Promise<T | null> {
  const path = await pickPath({ accept })
  if (!path) return null
  return JSON.parse(await uploadFileAs(path, pathQuery, fieldName)) as T
}
