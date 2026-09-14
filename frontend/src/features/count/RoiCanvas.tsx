import { useCallback, useEffect, useRef, useState } from 'react'
import type { RoiMode, RoiShape } from '../../types'

type Props = {
  imageEl: HTMLImageElement | null
  mode: RoiMode
  shape: RoiShape | null
  onChange: (shape: RoiShape | null) => void
  overlay?: 'processed' | 'binary' | null
  overlaySrc?: string | null
}

type DragMode = null | 'draw' | 'move'

function clampRect(s: Extract<RoiShape, { type: 'rectangle' }>, cw: number, ch: number) {
  s.w = Math.min(Math.max(s.w, 12), cw)
  s.h = Math.min(Math.max(s.h, 12), ch)
  s.x = Math.max(0, Math.min(s.x, cw - s.w))
  s.y = Math.max(0, Math.min(s.y, ch - s.h))
}

function clampCircle(s: Extract<RoiShape, { type: 'circle' }>, cw: number, ch: number) {
  const maxR = Math.max(8, Math.min(cw, ch) / 2)
  s.r = Math.min(Math.max(s.r, 8), maxR)
  s.cx = Math.max(s.r, Math.min(s.cx, cw - s.r))
  s.cy = Math.max(s.r, Math.min(s.cy, ch - s.r))
}

export function RoiCanvas({ imageEl, mode, shape, onChange, overlaySrc }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<DragMode>(null)
  const startRef = useRef<{ x: number; y: number } | null>(null)
  const offsetRef = useRef<{ x: number; y: number } | null>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  const [box, setBox] = useState({ w: 0, h: 0 })

  // 容器尺寸观察：图片按 contain 自适应，避免超大图撑出滚动条
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const measure = () => {
      setBox({ w: el.clientWidth, h: el.clientHeight })
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const nw = imageEl?.naturalWidth || imageEl?.width || 0
  const nh = imageEl?.naturalHeight || imageEl?.height || 0
  const fitScale =
    nw > 0 && nh > 0 && box.w > 0 && box.h > 0
      ? Math.min(box.w / nw, box.h / nh, 1)
      : 0
  const displayW = fitScale > 0 ? Math.max(1, Math.floor(nw * fitScale)) : 0
  const displayH = fitScale > 0 ? Math.max(1, Math.floor(nh * fitScale)) : 0

  const redraw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas || !imageEl) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    // 逻辑分辨率仍用原图，显示由 CSS 缩放，ROI 坐标体系不变
    canvas.width = imageEl.naturalWidth || imageEl.width
    canvas.height = imageEl.naturalHeight || imageEl.height
    setSize({ w: canvas.width, h: canvas.height })
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    if (!shape) return
    ctx.strokeStyle = '#22c55e'
    ctx.lineWidth = Math.max(2, canvas.width / 400)
    if (shape.type === 'rectangle') {
      ctx.strokeRect(shape.x, shape.y, shape.w, shape.h)
    } else {
      ctx.beginPath()
      ctx.arc(shape.cx, shape.cy, shape.r, 0, Math.PI * 2)
      ctx.stroke()
    }
  }, [imageEl, shape])

  useEffect(() => {
    redraw()
  }, [redraw])

  useEffect(() => {
    if (imageEl) redraw()
  }, [imageEl, redraw])

  const pointInShape = (pos: { x: number; y: number }, s: RoiShape) => {
    if (s.type === 'rectangle') {
      return pos.x >= s.x && pos.x <= s.x + s.w && pos.y >= s.y && pos.y <= s.y + s.h
    }
    const dx = pos.x - s.cx
    const dy = pos.y - s.cy
    return dx * dx + dy * dy <= s.r * s.r
  }

  const onDown = (clientX: number, clientY: number) => {
    if (mode === 'none') return
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const scaleX = canvas.width / rect.width
    const scaleY = canvas.height / rect.height
    const pos = { x: (clientX - rect.left) * scaleX, y: (clientY - rect.top) * scaleY }
    if (shape && pointInShape(pos, shape)) {
      dragRef.current = 'move'
      offsetRef.current =
        shape.type === 'rectangle'
          ? { x: pos.x - shape.x, y: pos.y - shape.y }
          : { x: pos.x - shape.cx, y: pos.y - shape.cy }
    } else {
      dragRef.current = 'draw'
      startRef.current = pos
      const next: RoiShape =
        mode === 'rectangle'
          ? { type: 'rectangle', x: pos.x, y: pos.y, w: 12, h: 12 }
          : { type: 'circle', cx: pos.x, cy: pos.y, r: 8 }
      onChange(next)
    }
  }

  const onMove = (clientX: number, clientY: number) => {
    if (!dragRef.current) return
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const scaleX = canvas.width / rect.width
    const scaleY = canvas.height / rect.height
    const pos = { x: (clientX - rect.left) * scaleX, y: (clientY - rect.top) * scaleY }
    if (dragRef.current === 'draw' && startRef.current) {
      const s = startRef.current
      if (mode === 'rectangle') {
        const next: RoiShape = {
          type: 'rectangle',
          x: Math.min(s.x, pos.x),
          y: Math.min(s.y, pos.y),
          w: Math.abs(pos.x - s.x),
          h: Math.abs(pos.y - s.y),
        }
        clampRect(next, canvas.width, canvas.height)
        onChange(next)
      } else {
        const next: RoiShape = {
          type: 'circle',
          cx: s.x,
          cy: s.y,
          r: Math.hypot(pos.x - s.x, pos.y - s.y),
        }
        clampCircle(next, canvas.width, canvas.height)
        onChange(next)
      }
    } else if (dragRef.current === 'move' && shape && offsetRef.current) {
      if (shape.type === 'rectangle') {
        const next: RoiShape = {
          type: 'rectangle',
          x: pos.x - offsetRef.current.x,
          y: pos.y - offsetRef.current.y,
          w: shape.w,
          h: shape.h,
        }
        clampRect(next, canvas.width, canvas.height)
        onChange(next)
      } else {
        const next: RoiShape = {
          type: 'circle',
          cx: pos.x - offsetRef.current.x,
          cy: pos.y - offsetRef.current.y,
          r: shape.r,
        }
        clampCircle(next, canvas.width, canvas.height)
        onChange(next)
      }
    }
  }

  const onUp = () => {
    dragRef.current = null
    startRef.current = null
    offsetRef.current = null
  }

  return (
    <div
      ref={wrapRef}
      className="stage-bg relative flex h-full w-full items-center justify-center overflow-hidden rounded-lg"
    >
      {displayW > 0 && (
        <div className="relative" style={{ width: displayW, height: displayH }}>
          <img
            src={overlaySrc || imageEl?.src || ''}
            alt="stage"
            className="block h-full w-full select-none"
            draggable={false}
          />
          <canvas
            ref={canvasRef}
            className="absolute inset-0 h-full w-full cursor-crosshair touch-none"
            style={{ display: size.w ? 'block' : 'none' }}
            onMouseDown={(e) => onDown(e.clientX, e.clientY)}
            onMouseMove={(e) => onMove(e.clientX, e.clientY)}
            onMouseUp={onUp}
            onMouseLeave={onUp}
            onTouchStart={(e) => {
              if (e.touches[0]) onDown(e.touches[0].clientX, e.touches[0].clientY)
            }}
            onTouchMove={(e) => {
              if (e.touches[0]) onMove(e.touches[0].clientX, e.touches[0].clientY)
            }}
            onTouchEnd={onUp}
          />
        </div>
      )}
    </div>
  )
}

export function nudgeShape(shape: RoiShape | null, dx: number, dy: number): RoiShape | null {
  if (!shape) return null
  if (shape.type === 'rectangle') {
    return { ...shape, x: shape.x + dx, y: shape.y + dy }
  }
  return { ...shape, cx: shape.cx + dx, cy: shape.cy + dy }
}

export function scaleShape(shape: RoiShape | null, factor: number): RoiShape | null {
  if (!shape) return null
  if (shape.type === 'rectangle') {
    const cx = shape.x + shape.w / 2
    const cy = shape.y + shape.h / 2
    const w = Math.max(12, shape.w * factor)
    const h = Math.max(12, shape.h * factor)
    return { type: 'rectangle', x: cx - w / 2, y: cy - h / 2, w, h }
  }
  return { ...shape, r: Math.max(8, shape.r * factor) }
}

export function shapeToRoi(shape: RoiShape | null): { type: string; data: string } | null {
  if (!shape) return null
  if (shape.type === 'rectangle') {
    return {
      type: 'rectangle',
      data: [
        Math.round(shape.x),
        Math.round(shape.y),
        Math.round(shape.w),
        Math.round(shape.h),
      ].join(','),
    }
  }
  return {
    type: 'circle',
    data: [Math.round(shape.cx), Math.round(shape.cy), Math.round(shape.r)].join(','),
  }
}
