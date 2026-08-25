/** Message from an unknown catch value — the app-wide way to show `e` to the user. */
export function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}
