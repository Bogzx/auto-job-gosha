// Discord sign-in that opens the app when installed.
//
// The hard constraint: mobile browsers only allow custom-scheme navigation
// (discord://) when it happens SYNCHRONOUSLY inside a user gesture. Any
// `await` before navigating breaks the gesture chain and Chrome silently
// blocks the app link. So the OAuth URLs (and the CSRF state cookie) are
// prefetched on page load, and the click handler navigates immediately.
//
// Per platform:
//  - Android Chrome: intent:// URL with a built-in browser_fallback_url —
//    Chrome opens the app if installed, else loads the fallback. No timers.
//  - iOS / desktop: discord:// attempt + timed fallback to the web flow,
//    canceled when the app steals focus.

const LOGIN_PATH = '/api/v1/auth/discord/login'
// State cookie lives 10 min; refresh the prefetched URLs well within that.
const REFRESH_MS = 8 * 60 * 1000

interface LoginUrls {
  web_url: string
  app_url: string
}

let cached: LoginUrls | null = null
let refreshTimer: number | undefined

async function fetchUrls(): Promise<LoginUrls | null> {
  try {
    const resp = await fetch(`${LOGIN_PATH}?format=json`, { credentials: 'include' })
    if (!resp.ok) return null
    return (await resp.json()) as LoginUrls
  } catch {
    return null
  }
}

/** Call on page load so the click handler can navigate synchronously. */
export function prefetchLogin(): void {
  void fetchUrls().then((urls) => {
    cached = urls
  })
  if (refreshTimer === undefined) {
    refreshTimer = window.setInterval(() => {
      void fetchUrls().then((urls) => {
        if (urls) cached = urls
      })
    }, REFRESH_MS)
  }
}

function androidIntentUrl(appUrl: string, webUrl: string): string {
  // discord://-/oauth2/authorize?x=y  ->
  // intent://-/oauth2/authorize?x=y#Intent;scheme=discord;package=com.discord;...
  const withoutScheme = appUrl.replace(/^discord:\/\//, '')
  return (
    `intent://${withoutScheme}` +
    `#Intent;scheme=discord;package=com.discord;` +
    `S.browser_fallback_url=${encodeURIComponent(webUrl)};end`
  )
}

/** Synchronous within the click gesture — required for app deep links. */
export function signInWithDiscord(): void {
  const urls = cached
  if (!urls) {
    // Prefetch hasn't landed (or failed) — plain browser flow always works.
    window.location.href = LOGIN_PATH
    return
  }

  const ua = navigator.userAgent
  if (/android/i.test(ua)) {
    window.location.href = androidIntentUrl(urls.app_url, urls.web_url)
    return
  }

  // iOS + desktop: try the app scheme, fall back to the web flow unless
  // the app visibly took over.
  const fallback = window.setTimeout(() => {
    window.location.href = urls.web_url
  }, 1600)
  const cancel = () => window.clearTimeout(fallback)
  document.addEventListener(
    'visibilitychange',
    () => {
      if (document.hidden) cancel()
    },
    { once: true },
  )
  window.addEventListener('pagehide', cancel, { once: true })
  window.addEventListener('blur', cancel, { once: true })

  window.location.href = urls.app_url
}
