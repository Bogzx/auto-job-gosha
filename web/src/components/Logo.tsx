export function Logo({ size = 'md' }: { size?: 'md' | 'lg' }) {
  return (
    <span className="inline-flex items-center gap-2 select-none">
      <img
        src="/gosha.jpg"
        alt=""
        aria-hidden
        className={`rounded-full border border-ink object-cover ${
          size === 'lg' ? 'h-9 w-9' : 'h-7 w-7'
        }`}
      />
      <span className={`headline ${size === 'lg' ? 'text-2xl' : 'text-lg'}`}>
        GOSHA<span className="text-go">.</span>jobs
      </span>
    </span>
  )
}
