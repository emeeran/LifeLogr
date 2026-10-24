/** Message from an unknown catch value — the app-wide way to show `e` to the user.
 *
 *  Handles the shapes we actually produce: `Error` subclasses (incl. the API
 *  client's `ApiError`, whose `.message` is already human-readable), `ErrorEvent`
 *  style objects with a `message` field, and anything else via `String()`.
 *  Never returns `undefined` and never throws, so it is safe inside a catch. */
export function errorMessage(e: unknown): string {
  if (typeof e === 'string') return e
  if (e instanceof Error) return e.message
  if (typeof e === 'object' && e !== null) {
    const msg = (e as { message?: unknown }).message
    if (typeof msg === 'string' && msg) return msg
    try {
      return JSON.stringify(e)
    } catch {
      return String(e)
    }
  }
  return String(e)
}

/** Legacy alias — kept because it is imported in a dozen call sites. */
export const errMsg = errorMessage
