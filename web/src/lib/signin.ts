// Sign-in entry point: try the Discord app first (mobile AND desktop both
// register the discord:// protocol), fall back to the browser OAuth flow
// when the app doesn't take over within a moment.
//
// The JSON fetch sets the CSRF state cookie in this browser, so the
// callback lands back here with a matching state either way.

const LOGIN_PATH = '/api/v1/auth/discord/login'

export async function signInWithDiscord(): Promise<void> {
  try {
    const resp = await fetch(`${LOGIN_PATH}?format=json`, { credentials: 'include' })
    const { web_url, app_url } = (await resp.json()) as {
      web_url: string
      app_url: string
    }

    const fallback = window.setTimeout(() => {
      window.location.href = web_url
    }, 1600)

    const cancelFallback = () => window.clearTimeout(fallback)
    // App taking over backgrounds the tab (mobile) or steals focus (desktop)
    document.addEventListener(
      'visibilitychange',
      () => {
        if (document.hidden) cancelFallback()
      },
      { once: true },
    )
    window.addEventListener('blur', cancelFallback, { once: true })

    window.location.href = app_url
  } catch {
    window.location.href = LOGIN_PATH
  }
}
