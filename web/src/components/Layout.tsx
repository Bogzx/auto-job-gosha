import type { ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import {
  BarChart3,
  FileText,
  KanbanSquare,
  Newspaper,
  SearchCheck,
  UserRound,
} from 'lucide-react'
import { useMe } from '../hooks/useMe'
import { Logo } from './Logo'

const NAV_ITEMS = [
  { to: '/feed', label: 'Feed', icon: Newspaper },
  { to: '/tracker', label: 'Tracker', icon: KanbanSquare },
  { to: '/searches', label: 'Searches', icon: SearchCheck },
  { to: '/cv', label: 'CV', icon: FileText },
]

/** App chrome: top nav on desktop, bottom tab bar on mobile. */
export function Layout({ children }: { children: ReactNode }) {
  const { me } = useMe()

  return (
    <div className="min-h-dvh pb-20 md:pb-0">
      {/* ── Desktop top bar ── */}
      <header className="sticky top-0 z-40 border-b border-ink bg-paper/95 backdrop-blur-sm">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-4 px-4">
          <Link to="/feed" aria-label="GOSHA Jobs home">
            <Logo />
          </Link>

          <nav className="hidden items-center gap-1 md:flex" aria-label="Main">
            {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-semibold transition-colors ${
                    isActive
                      ? 'bg-moss text-paper'
                      : 'text-ink-soft hover:bg-paper-warm hover:text-ink'
                  }`
                }
              >
                <Icon size={15} strokeWidth={2.25} aria-hidden />
                {label}
              </NavLink>
            ))}
            {me?.is_admin && (
              <NavLink
                to="/admin"
                className={({ isActive }) =>
                  `inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-semibold transition-colors ${
                    isActive
                      ? 'bg-moss text-paper'
                      : 'text-ink-soft hover:bg-paper-warm hover:text-ink'
                  }`
                }
              >
                <BarChart3 size={15} strokeWidth={2.25} aria-hidden />
                Admin
              </NavLink>
            )}
          </nav>

          <Link
            to="/profile"
            className="flex items-center gap-2 rounded-full border border-rule p-0.5 pr-3 transition-colors hover:border-ink"
            aria-label="Profile"
          >
            {me?.avatar_url ? (
              <img
                src={me.avatar_url}
                alt=""
                className="h-7 w-7 rounded-full border border-rule"
              />
            ) : (
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-paper-warm">
                <UserRound size={15} aria-hidden />
              </span>
            )}
            <span className="hidden max-w-28 truncate font-mono text-xs sm:block">
              {me?.username ?? '…'}
            </span>
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>

      {/* ── Mobile bottom tabs ── */}
      <nav
        className="fixed inset-x-0 bottom-0 z-40 border-t border-ink bg-card pb-[env(safe-area-inset-bottom)] md:hidden"
        aria-label="Main"
      >
        <div className="grid grid-cols-4">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex flex-col items-center gap-0.5 py-2.5 font-mono text-[10px] font-medium tracking-wide ${
                  isActive ? 'text-go' : 'text-ink-faint'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  <Icon size={20} strokeWidth={isActive ? 2.5 : 2} aria-hidden />
                  {label.toUpperCase()}
                </>
              )}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  )
}
