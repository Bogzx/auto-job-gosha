import { LogOut, ShieldCheck } from 'lucide-react'
import { DiscordHelp } from '../components/DiscordHelp'
import { useLogout, useMe } from '../hooks/useMe'

export default function Profile() {
  const { me } = useMe()
  const logout = useLogout()

  if (!me) return null

  return (
    <div className="mx-auto max-w-md">
      <h1 className="headline mb-6 text-3xl">
        Profile<span className="text-go">.</span>
      </h1>

      <div className="card-press p-5">
        <div className="flex items-center gap-4">
          {me.avatar_url ? (
            <img
              src={me.avatar_url}
              alt=""
              className="h-16 w-16 rounded-full border-2 border-ink"
            />
          ) : (
            <span className="headline flex h-16 w-16 items-center justify-center rounded-full border-2 border-ink bg-paper-warm text-2xl">
              {(me.username ?? '?')[0]?.toUpperCase()}
            </span>
          )}
          <div>
            <p className="headline text-xl">{me.username ?? 'Anonymous'}</p>
            <p className="font-mono text-xs text-ink-faint">
              discord #{me.discord_id}
            </p>
          </div>
        </div>

        <dl className="rule-dotted mt-4 space-y-2 pt-4 text-sm">
          <div className="flex justify-between">
            <dt className="text-ink-soft">Plan</dt>
            <dd className="chip border-moss bg-go-soft font-bold text-moss uppercase">
              {me.tier}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-soft">Discord alerts</dt>
            <dd className={`font-mono text-xs font-bold ${me.in_guild ? 'text-go' : 'text-amber'}`}>
              {me.in_guild ? 'CONNECTED' : 'NOT CONNECTED'}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-soft">CV on file</dt>
            <dd className={`font-mono text-xs font-bold ${me.has_cv ? 'text-go' : 'text-amber'}`}>
              {me.has_cv ? 'YES' : 'NO'}
            </dd>
          </div>
          {me.is_admin && (
            <div className="flex justify-between">
              <dt className="text-ink-soft">Role</dt>
              <dd className="flex items-center gap-1 font-mono text-xs font-bold text-sky">
                <ShieldCheck size={13} aria-hidden /> ADMIN
              </dd>
            </div>
          )}
        </dl>
      </div>

      <div className="mt-4">
        <DiscordHelp compact={me.in_guild} />
      </div>

      <button type="button" className="btn-quiet mt-4 w-full" onClick={() => void logout()}>
        <LogOut size={15} aria-hidden />
        Sign out
      </button>

      <p className="rule-dotted mt-8 pt-4 text-center font-mono text-[11px] leading-relaxed text-ink-faint">
        Your data: Discord id, CV text, saved searches, and job interactions.
        Delete your CV any time from the CV page. Made by{' '}
        <a
          className="underline"
          href="https://bogdantruta.com"
          target="_blank"
          rel="noopener noreferrer"
        >
          Bogdan Truta
        </a>
      </p>
    </div>
  )
}
