export function Logo({ size = 'md' }: { size?: 'md' | 'lg' }) {
  return (
    <span className="inline-flex items-baseline gap-1.5 select-none">
      <span
        className={`headline text-paper bg-moss rounded-md inline-flex items-center justify-center ${
          size === 'lg' ? 'w-9 h-9 text-2xl' : 'w-7 h-7 text-lg'
        }`}
        aria-hidden
      >
        G
      </span>
      <span className={`headline ${size === 'lg' ? 'text-2xl' : 'text-lg'}`}>
        GOSHA<span className="text-go">.</span>jobs
      </span>
    </span>
  )
}
