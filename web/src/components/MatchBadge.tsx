import { matchPercent } from '../lib/format'

/** The hero metric: how well a job fits the user's CV. */
export function MatchBadge({ score, size = 'sm' }: { score: number | null; size?: 'sm' | 'lg' }) {
  const percent = matchPercent(score)
  if (percent == null) return null

  const tone =
    percent >= 75
      ? 'bg-go text-white border-moss'
      : percent >= 50
        ? 'bg-amber-soft text-amber border-amber'
        : 'bg-paper-warm text-ink-faint border-rule'

  return (
    <span
      className={`inline-flex items-center rounded-md border font-mono font-bold ${tone} ${
        size === 'lg' ? 'px-2.5 py-1 text-sm' : 'px-1.5 py-0.5 text-xs'
      }`}
      title="How well this job matches your CV"
    >
      {percent}%
    </span>
  )
}
