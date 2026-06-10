// Small formatting helpers shared across screens.

export function timeAgo(iso: string | null): string {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const seconds = Math.max(0, (Date.now() - then) / 1000)
  if (seconds < 3600) return 'just now'
  const hours = Math.floor(seconds / 3600)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days === 1) return 'yesterday'
  if (days < 30) return `${days}d ago`
  const months = Math.floor(days / 30)
  return months === 1 ? '1mo ago' : `${months}mo ago`
}

export function formatSalary(
  min: number | null,
  max: number | null,
  currency: string | null,
): string | null {
  if (min == null && max == null) return null
  const cur = currency ?? ''
  const fmt = (n: number) =>
    n >= 10000 ? `${Math.round(n / 1000)}k` : `${Math.round(n)}`
  if (min != null && max != null && min !== max) return `${fmt(min)}–${fmt(max)} ${cur}`.trim()
  return `${fmt((min ?? max)!)} ${cur}`.trim()
}

export function matchPercent(score: number | null): number | null {
  if (score == null) return null
  return Math.round(Math.min(1, Math.max(0, score)) * 100)
}

export const SOURCE_LABELS: Record<string, string> = {
  indeed: 'Indeed',
  linkedin: 'LinkedIn',
  glassdoor: 'Glassdoor',
  ejobs: 'eJobs',
  bestjobs: 'BestJobs',
  hipo: 'Hipo',
  remoteok: 'RemoteOK',
}

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source.charAt(0).toUpperCase() + source.slice(1)
}
