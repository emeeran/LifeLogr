export type { PlatformProvider } from './platform'
export * from './platform'
export { desktopProvider } from './desktop'
export { FEATURES } from './features'

// Lazy-loaded: mobile provider only imported when on Capacitor
export async function createProvider(): Promise<PlatformProvider> {
  if (import.meta.env.VITE_PLATFORM === 'capacitor') {
    const { mobileProvider } = await import('./mobile')
    return mobileProvider
  }
  const { desktopProvider } = await import('./desktop')
  return desktopProvider
}
