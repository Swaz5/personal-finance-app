import type { CategoryBar } from '../types'
import { formatCents, formatShort } from '../types'

/** Horizontal bars per category, this month vs. the trailing 6-month median
 * (section 7) — no pie charts, no per-category colors (color is semantic
 * only). The median shows as a ghost tick on the same neutral bar. */
export function CategoryBars({ rows }: { rows: CategoryBar[] }) {
  const spend = rows.filter((r) => r.kind !== 'income' && (r.current_cents > 0 || r.median_cents > 0))
  if (spend.length === 0) return <p className="text-ink-dim text-sm">Nothing to compare yet.</p>

  const max = Math.max(...spend.map((r) => Math.max(r.current_cents, r.median_cents)), 1)

  return (
    <div className="space-y-2">
      {spend.map((r) => {
        const barPct = (r.current_cents / max) * 100
        const medianPct = (r.median_cents / max) * 100
        const overMedian = r.median_cents > 0 && r.current_cents > r.median_cents * 1.15
        return (
          <div key={r.category_id} className="flex items-center gap-3 text-sm">
            <span className="w-32 shrink-0 text-ink-dim truncate">{r.category}</span>
            <div className="flex-1 relative h-4 bg-line/40 rounded-sm overflow-visible">
              <div
                className={`h-4 rounded-sm ${overMedian ? 'bg-negative' : 'bg-ink-dim'}`}
                style={{ width: `${Math.max(barPct, r.current_cents > 0 ? 1 : 0)}%` }}
              />
              {r.median_cents > 0 && (
                <div
                  className="absolute top-[-2px] w-[2px] h-5 bg-ink"
                  style={{ left: `${medianPct}%` }}
                  title={`6-month median: ${formatCents(r.median_cents)}`}
                />
              )}
            </div>
            <span className="w-20 shrink-0 text-right font-mono text-ink">{formatShort(r.current_cents)}</span>
          </div>
        )
      })}
      <p className="text-ink-dim text-xs pt-1">
        Bar is this month so far. The vertical tick is your trailing 6-month median for that category.
      </p>
    </div>
  )
}
