import { isTauri } from '../api/client'

/**
 * True only for an ABSOLUTE http(s)/mailto/tel URL — i.e. one to hand to the OS
 * rather than the app. Relative paths ("/settings"), anchors ("#"), and
 * query-only links are in-app and must be left to the router.
 *
 * Do NOT resolve via `new URL(href, window.location.href)`: that turns every
 * router-link ("/email" → "http://host/email") into an "external" http URL,
 * and the capture-phase interceptor then `preventDefault()`s the click — which
 * makes vue-router's RouterLink bail (it skips when `event.defaultPrevented`),
 * breaking all in-app nav. (In Tauri the origin is `tauri://`, so the bug was
 * latent there; in the web/dev origin it breaks navigation outright.)
 */
export function isExternalHref(href: string): boolean {
  return /^(https?:|mailto:|tel:)/i.test(href ?? '')
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
