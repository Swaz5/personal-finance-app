import { useRef, useState } from 'react'
import type { DayPoint } from '../types'
import { formatCents, formatShort } from '../types'

/** The signature element (BUILD_PLAN.md section 7): 90-day forward cash
 * projection with the emergency floor as a hard horizontal rule, the
 * lowest point called out directly, and a crosshair+tooltip on hover. */
export function TroughChart({
  daily,
  floorCents,
  troughDay,
}: {
  daily: DayPoint[]
  floorCents: number
  troughDay: string
}) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  if (daily.length < 2) return <p className="text-ink-dim text-sm">Not enough data yet.</p>

  const width = 900
  const height = 260
  const padL = 8
  const padR = 8
  const padT = 12
  const padB = 8

  const values = daily.map((d) => d.balance_cents)
  const min = Math.min(...values, floorCents)
  const max = Math.max(...values)
  const range = max - min || 1

  const xFor = (i: number) => padL + (i / (daily.length - 1)) * (width - padL - padR)
  const yFor = (cents: number) => height - padB - ((cents - min) / range) * (height - padT - padB)

  const coords = daily.map((d, i) => [xFor(i), yFor(d.balance_cents)] as const)
  const pathD = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const areaD = `${pathD} L${coords[coords.length - 1][0].toFixed(1)},${height - padB} L${coords[0][0].toFixed(1)},${height - padB} Z`

  const troughIdx = daily.findIndex((d) => d.day === troughDay)
  const floorY = yFor(floorCents)
  const belowFloor = daily.some((d) => d.balance_cents < floorCents)
  const lineColor = belowFloor ? 'var(--color-negative)' : 'var(--color-positive)'

  function handleMove(e: React.PointerEvent<SVGSVGElement>) {
    const svg = svgRef.current
    if (!svg) return
    const rect = svg.getBoundingClientRect()
    const relX = ((e.clientX - rect.left) / rect.width) * width
    const idx = Math.round(((relX - padL) / (width - padL - padR)) * (daily.length - 1))
    setHoverIdx(Math.max(0, Math.min(daily.length - 1, idx)))
  }

  const hover = hoverIdx !== null ? daily[hoverIdx] : null
  const hoverX = hoverIdx !== null ? xFor(hoverIdx) : 0
  const tooltipLeft = hoverX > width - 160

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${height}`}
        className="w-full h-64 cursor-crosshair"
        onPointerMove={handleMove}
        onPointerLeave={() => setHoverIdx(null)}
      >
        <line x1={padL} x2={width - padR} y1={floorY} y2={floorY} stroke="var(--color-line)" strokeWidth={1} strokeDasharray="4 3" />
        <text x={width - padR} y={floorY - 6} textAnchor="end" fill="var(--color-ink-dim)" fontSize={11}>
          emergency floor {formatShort(floorCents)}
        </text>

        <path d={areaD} fill={lineColor} opacity={0.1} />
        <path d={pathD} fill="none" stroke={lineColor} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

        {troughIdx >= 0 && (
          <g>
            <circle cx={coords[troughIdx][0]} cy={coords[troughIdx][1]} r={4} fill={lineColor} stroke="var(--color-panel)" strokeWidth={2} />
            <text
              x={coords[troughIdx][0]}
              y={coords[troughIdx][1] - 10}
              textAnchor={troughIdx > daily.length / 2 ? 'end' : 'start'}
              fill="var(--color-ink)"
              fontSize={11}
            >
              lowest: {formatShort(daily[troughIdx].balance_cents)} on {daily[troughIdx].day}
            </text>
          </g>
        )}

        {hover && (
          <g>
            <line x1={hoverX} x2={hoverX} y1={padT} y2={height - padB} stroke="var(--color-line)" strokeWidth={1} />
            <circle cx={hoverX} cy={yFor(hover.balance_cents)} r={4} fill="var(--color-ink)" stroke="var(--color-panel)" strokeWidth={2} />
          </g>
        )}
      </svg>
      {hover && (
        <div
          className="absolute top-0 bg-panel border border-line rounded px-2 py-1 text-xs pointer-events-none"
          style={{ left: tooltipLeft ? undefined : `${(hoverX / width) * 100}%`, right: tooltipLeft ? `${100 - (hoverX / width) * 100}%` : undefined }}
        >
          <div className="text-ink-dim">{hover.day}</div>
          <div className="text-ink font-mono">{formatCents(hover.balance_cents)}</div>
        </div>
      )}
    </div>
  )
}
