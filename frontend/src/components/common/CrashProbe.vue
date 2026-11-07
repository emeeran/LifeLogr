<script setup lang="ts">
// BLANK-8 test hook: rendered in place of the routed view when the URL carries
// ?crash=1, so the Playwright suite can prove a throwing view lands on the
// ErrorBoundary (message + Reload + Copy details) instead of blanking the
// panel. No navigation links here — only the explicit query parameter, which
// nothing in the app ever sets.
throw new Error('CrashProbe: deliberate test crash')
</script>
