/** Coerce a caught value (typically `unknown`) into a displayable string. */
export function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}
