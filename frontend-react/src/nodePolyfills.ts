// epubjs's dependency chain (jszip, core-js) assumes it's running under
// Node or a bundler that shims Node globals (webpack does this
// automatically; Vite doesn't) — without these, importing epubjs throws
// "process is not defined" at module-eval time and the whole entry fails to
// mount. Minimal shims only (Buffer + a nextTick-ish process), not the full
// node-stdlib polyfill suite, which drags in an unrelated crypto stack.
// Ported 1:1 from frontend/src/nodePolyfills.js — imported only by the
// reader entry (src/reader-main.tsx), the only place epubjs is used.
import { Buffer } from 'buffer'

declare global {
  interface Window {
    Buffer?: typeof Buffer
    process?: { env: Record<string, string>; nextTick: (fn: (...args: unknown[]) => void, ...args: unknown[]) => void }
  }
}

window.Buffer = window.Buffer || Buffer
window.process = window.process || { env: {}, nextTick: (fn, ...args) => setTimeout(() => fn(...args), 0) }
