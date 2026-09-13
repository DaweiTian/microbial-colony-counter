import { useEffect, useRef, useState, type ReactNode } from 'react'

export function Card({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return <div className={`card p-4 ${className}`}>{children}</div>
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <div className="mb-3 text-[13px] font-semibold tracking-wide text-ink/80">
      {children}
    </div>
  )
}

export function SliderField({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
  format,
}: {
  label: string
  value: number
  min: number
  max: number
  step?: number
  onChange: (v: number) => void
  format?: (v: number) => string
}) {
  return (
    <label className="block">
      <div className="mb-1 flex items-center justify-between">
        <span className="field-label mb-0">{label}</span>
        <span className="font-mono text-[12px] text-ink/70">
          {format ? format(value) : value}
        </span>
      </div>
      <input
        type="range"
        className="w-full"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  )
}

export function SwitchField({
  label,
  checked,
  onChange,
  hint,
}: {
  label: string
  checked: boolean
  onChange: (v: boolean) => void
  hint?: string
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div>
        <div className="text-[13px] font-medium text-ink">{label}</div>
        {hint ? <div className="mt-0.5 text-[12px] text-muted">{hint}</div> : null}
      </div>
      <label className="switch mt-0.5">
        <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
        <span className="switch-track" />
      </label>
    </div>
  )
}

export function Toast({ message }: { message: string | null }) {
  if (!message) return null
  return <div className="toast">{message}</div>
}

export function useToast(timeout = 2800) {
  const [msg, setMsg] = useState<string | null>(null)
  const timer = useRef<number | null>(null)

  const show = (text: string) => {
    setMsg(text)
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setMsg(null), timeout)
  }

  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current)
  }, [])

  return { msg, show }
}

export function EmptyState({
  title,
  desc,
  icon,
}: {
  title: string
  desc?: string
  icon?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-[12px] border border-dashed border-line bg-white/60 px-6 py-10 text-center">
      {icon ? <div className="mb-3 text-muted">{icon}</div> : null}
      <div className="text-[14px] font-semibold text-ink">{title}</div>
      {desc ? <div className="mt-1 max-w-sm text-[12px] leading-relaxed text-muted">{desc}</div> : null}
    </div>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-[13px] text-muted">
      <span
        className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-line border-t-primary"
        aria-hidden
      />
      {label || '处理中…'}
    </div>
  )
}

export function Badge({
  children,
  tone = 'default',
}: {
  children: ReactNode
  tone?: 'default' | 'primary' | 'accent' | 'warn'
}) {
  const tones: Record<string, string> = {
    default: 'bg-slate-100 text-slate-700',
    primary: 'bg-primary-soft text-primary',
    accent: 'bg-accent-soft text-accent',
    warn: 'bg-amber-50 text-warn',
  }
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${tones[tone]}`}>
      {children}
    </span>
  )
}
