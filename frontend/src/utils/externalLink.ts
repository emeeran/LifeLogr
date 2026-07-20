import { isTauri } from '../api/client'

const EXTERNAL_SCHEMES = ['http:', 'https:', 'mailto:', 'tel:']

/** True if a URL should be handed to the OS (web/mail/tel) rather than the app. */
export function isExternalHref(href: string): boolean {
  if (!href) return false
  try {
    const u = new URL(href, window.location.href)
    return EXTERNAL_SCHEMES.includes(u.protocol)
  } catch {
    return false
  }
}

/**
 * Open an external URL in the system default browser / mail / tel handler.
 * In Tauri this goes through the shell plugin; in a plain browser it opens a
 * new tab. Only http(s)/mailto/tel are ever dispatched — anything else is a
 * no-op, so internal/relative links are never hijacked.
 */
export async function openExternal(href: string): Promise<void> {
  if (!isExternalHref(href)) return
  if (isTauri) {
    try {
      const { open } = await import('@tauri-apps/plugin-shell')
      await open(href)
    } catch (e) {
      console.error('[openExternal] shell open failed', e)
    }
  } else {
    window.open(href, '_blank', 'noopener,noreferrer')
  }
}

/**
 * Document-level delegated click handler: any `<a href>` pointing at an
 * external scheme is opened by the OS instead of navigating the webview.
 * Internal/relative links (vue-router) are left untouched. Returns a cleanup.
 *
 * Links inside the email `<iframe sandbox>` live in a separate document and
 * can't be caught here — those are wired separately via postMessage in
 * EmailView (see the iframe `srcdoc` script + window message listener).
 */
export function installExternalLinkInterceptor(): () => void {
  const onClick = (e: MouseEvent) => {
    const target = e.target as Element | null
    const a = target?.closest?.('a[href]') as HTMLAnchorElement | null
    if (!a) return
    const href = a.getAttribute('href') || ''
    if (!isExternalHref(href)) return
    e.preventDefault()
    void openExternal(href)
  }
  // Capture phase so we intercept before default navigation / router handling.
  document.addEventListener('click', onClick, true)
  return () => document.removeEventListener('click', onClick, true)
}
