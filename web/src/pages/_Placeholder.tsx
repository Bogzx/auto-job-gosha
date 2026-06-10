// Temporary stub used while screens are being built out task-by-task.
export function Placeholder({ title }: { title: string }) {
  return (
    <div className="flex flex-col items-center gap-2 py-24 text-center">
      <h1 className="headline text-3xl">{title}</h1>
      <p className="font-mono text-xs text-ink-faint">under construction</p>
    </div>
  )
}
