import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../api/client'
import type { AdminStats, ScrapeHealth, UsageDay } from '../api/types'
import { useMe } from '../hooks/useMe'
import { sourceLabel, timeAgo } from '../lib/format'

const INK = '#1c1a15'
const GO = '#0e9f5b'
const AMBER = '#d97817'

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="card-press p-4">
      <p className="font-mono text-[11px] tracking-wider text-ink-faint uppercase">{label}</p>
      <p className="headline mt-1 text-3xl">{value.toLocaleString()}</p>
    </div>
  )
}

export default function Admin() {
  const { me } = useMe()
  const stats = useQuery({
    queryKey: ['admin', 'stats'],
    queryFn: () => api.get<AdminStats>('/admin/stats'),
    enabled: !!me?.is_admin,
  })
  const usage = useQuery({
    queryKey: ['admin', 'usage'],
    queryFn: () => api.get<{ days: UsageDay[] }>('/admin/usage?days=30'),
    enabled: !!me?.is_admin,
  })
  const health = useQuery({
    queryKey: ['admin', 'health'],
    queryFn: () => api.get<ScrapeHealth>('/admin/scrape-health'),
    enabled: !!me?.is_admin,
  })

  if (!me?.is_admin) {
    return (
      <p className="py-20 text-center font-mono text-xs text-ink-faint">
        admin only
      </p>
    )
  }

  if (stats.isLoading || usage.isLoading) {
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="animate-spin text-ink-faint" aria-label="Loading" />
      </div>
    )
  }

  const days = (usage.data?.days ?? []).map((day) => ({
    ...day,
    label: day.date.slice(5),
  }))

  return (
    <div className="space-y-8">
      <h1 className="headline text-3xl">
        Mission control<span className="text-go">.</span>
      </h1>

      {stats.data && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard label="Users" value={stats.data.total_users} />
          <StatCard label="Active jobs" value={stats.data.active_jobs} />
          <StatCard label="Active searches" value={stats.data.active_subscriptions} />
          <StatCard label="Applications" value={stats.data.total_applications} />
        </div>
      )}

      <section className="card-press p-4">
        <h2 className="headline mb-4 text-xl">Daily activity — last 30 days</h2>
        <div className="h-64">
          <ResponsiveContainer>
            <LineChart data={days} margin={{ top: 4, right: 8, left: -22, bottom: 0 }}>
              <CartesianGrid stroke="#d8d2c2" strokeDasharray="2 4" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 10, fontFamily: 'monospace' }} interval={4} />
              <YAxis tick={{ fontSize: 10, fontFamily: 'monospace' }} allowDecimals={false} />
              <Tooltip
                contentStyle={{
                  border: `1px solid ${INK}`,
                  borderRadius: 8,
                  background: '#fdfcf8',
                  fontSize: 12,
                }}
              />
              <Line type="monotone" dataKey="pageviews" stroke={INK} strokeWidth={2} dot={false} name="Pageviews" />
              <Line type="monotone" dataKey="active_users" stroke={GO} strokeWidth={2} dot={false} name="Active users" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      <div className="grid gap-4 md:grid-cols-2">
        <section className="card-press p-4">
          <h2 className="headline mb-4 text-xl">Signups &amp; applies</h2>
          <div className="h-52">
            <ResponsiveContainer>
              <BarChart data={days} margin={{ top: 4, right: 8, left: -22, bottom: 0 }}>
                <CartesianGrid stroke="#d8d2c2" strokeDasharray="2 4" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 10, fontFamily: 'monospace' }} interval={6} />
                <YAxis tick={{ fontSize: 10, fontFamily: 'monospace' }} allowDecimals={false} />
                <Tooltip
                  contentStyle={{
                    border: `1px solid ${INK}`,
                    borderRadius: 8,
                    background: '#fdfcf8',
                    fontSize: 12,
                  }}
                />
                <Bar dataKey="signups" fill={GO} name="Signups" radius={[3, 3, 0, 0]} />
                <Bar dataKey="applies" fill={AMBER} name="Applies" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="card-press p-4">
          <h2 className="headline mb-4 text-xl">Scrape health</h2>
          {health.data && (
            <>
              <p className="mb-3 text-sm text-ink-soft">
                Last job discovered:{' '}
                <strong className="font-mono text-xs">
                  {health.data.last_job_discovered_at
                    ? timeAgo(health.data.last_job_discovered_at)
                    : 'never'}
                </strong>
              </p>
              <ul className="space-y-1.5">
                {Object.entries(health.data.jobs_by_source).map(([source, count]) => (
                  <li key={source} className="flex items-center justify-between text-sm">
                    <span>{sourceLabel(source)}</span>
                    <span className="font-mono text-xs font-bold">{count}</span>
                  </li>
                ))}
                {Object.keys(health.data.jobs_by_source).length === 0 && (
                  <li className="font-mono text-xs text-ink-faint">no active jobs yet</li>
                )}
              </ul>
            </>
          )}
        </section>
      </div>
    </div>
  )
}
