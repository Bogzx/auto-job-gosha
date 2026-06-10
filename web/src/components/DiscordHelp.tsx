import { MessageCircle } from 'lucide-react'
import { DISCORD_INVITE } from '../lib/constants'

/** Join-server call-to-action with DM troubleshooting, shown when the bot
 *  can't reach the user (or as general onboarding help). */
export function DiscordHelp({ compact = false }: { compact?: boolean }) {
  return (
    <div className="card-press border-amber bg-amber-soft p-4">
      <p className="flex items-start gap-2 text-sm font-medium">
        <MessageCircle size={18} className="mt-0.5 shrink-0 text-amber" aria-hidden />
        <span>
          <strong>Get job alerts in your Discord DMs.</strong>{' '}
          Signing in adds you to our server automatically — but if that
          didn't work, join here:{' '}
          <a
            href={DISCORD_INVITE}
            target="_blank"
            rel="noopener noreferrer"
            className="font-semibold text-sky underline"
          >
            Join the GOSHA Discord →
          </a>
        </span>
      </p>
      {!compact && (
        <details className="mt-2 ml-7 text-sm text-ink-soft">
          <summary className="cursor-pointer font-semibold select-none">
            Not receiving DMs? Two quick checks
          </summary>
          <ol className="mt-2 list-decimal space-y-1 pl-5">
            <li>
              In Discord, <strong>right-click the GOSHA server icon</strong>{' '}
              (long-press on mobile) → <strong>Privacy Settings</strong> →
              turn on <strong>Direct Messages</strong>.
            </li>
            <li>
              In <strong>User Settings → Privacy &amp; Safety</strong>, make
              sure direct messages from server members are allowed.
            </li>
          </ol>
        </details>
      )}
    </div>
  )
}
