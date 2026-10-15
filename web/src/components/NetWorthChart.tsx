import type { NetWorthPoint } from '../types'

export function NetWorthChart({ points, height = 200 }: { points: NetWorthPoint[]; height?: number }) {
  if (points.length < 2) return <p className="text-ink-dim text-sm">Not enough data yet.</p>

  const width = 900
  const padding = 8
  const values = points.map((p) => p.net_worth_cents)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1

  const coords = points.map((p, i) => {
    const x = padding + (i / (points.length - 1)) * (width - padding * 2)
    const y = height - padding - ((p.net_worth_cents - min) / range) * (height - padding * 2)
    return [x, y] as const
  })
  const pathD = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const areaD = `${pathD} L${coords[coords.length - 1][0].toFixed(1)},${height - padding} L${coords[0][0].toFixed(1)},${height - padding} Z`

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ height }} preserveAspectRatio="none">
      <defs>
        <linearGradient id="nwFade" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--color-positive)" stopOpacity={0.25} />
          <stop offset="100%" stopColor="var(--color-positive)" stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={areaD} fill="url(#nwFade)" />
      <path d={pathD} fill="none" stroke="var(--color-positive)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}
