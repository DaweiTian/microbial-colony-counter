import { useCallback, useEffect, useRef, useState } from 'react'
import { Maximize2, ZoomIn, ZoomOut } from 'lucide-react'

type Props = {
  src: string
  /** 原图像素宽高，用于点位百分比定位 */
  width: number
  height: number
  points?: Array<{ x: number; y: number }>
  onPick?: (x: number, y: number) => void
  pickEnabled?: boolean
  className?: string
}

/**
 * 批次标定用图：默认 contain 自适应容器，支持滚轮/按钮缩放与拖拽平移。
 * 点击坐标始终映射回原图像素，与缩放无关。
 */
export function FitZoomImage({
  src,
  width,
  height,
  points = [],
  onPick,
  pickEnabled = false,
  className = '',
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [box, setBox] = useState({ w: 0, h: 0 })
  /** 1 = 适配容器；>1 放大 */
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const panRef = useRef<{ startX: number; startY: number; ox: number; oy: number } | null>(null)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const measure = () => setBox({ w: el.clientWidth, h: el.clientHeight })
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // 换图时回到适配
  useEffect(() => {
    setZoom(1)
    setPan({ x: 0, y: 0 })
  }, [src, width, height])

  const fitScale =
    width > 0 && height > 0 && box.w > 0 && box.h > 0
      ? Math.min(box.w / width, box.h / height)
      : 0
  const baseW = fitScale > 0 ? Math.max(1, Math.floor(width * fitScale)) : 0
  const baseH = fitScale > 0 ? Math.max(1, Math.floor(height * fitScale)) : 0
  const drawW = Math.floor(baseW * zoom)
  const drawH = Math.floor(baseH * zoom)
  const overflow = zoom > 1.02

  const clampPan = useCallback(
    (p: { x: number; y: number }) => {
      if (!overflow || !box.w || !box.h) return { x: 0, y: 0 }
      const maxX = Math.max(0, (drawW - box.w) / 2)
      const maxY = Math.max(0, (drawH - box.h) / 2)
      return {
        x: Math.max(-maxX, Math.min(maxX, p.x)),
        y: Math.max(-maxY, Math.min(maxY, p.y)),
      }
    },
    [overflow, box.w, box.h, drawW, drawH],
  )

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    const next = Math.min(4, Math.max(1, zoom * (e.deltaY > 0 ? 0.9 : 1.1)))
    setZoom(next)
    if (next <= 1.02) setPan({ x: 0, y: 0 })
  }

  const onPointerDown = (e: React.PointerEvent) => {
    const img = e.currentTarget.querySelector('img')
    // 点选模式：任意缩放级别都可加点（用 img 显示矩形映射回原图）
    if (pickEnabled && onPick && img) {
      const rect = img.getBoundingClientRect()
      if (rect.width <= 0 || rect.height <= 0) return
      const x = ((e.clientX - rect.left) / rect.width) * width
      const y = ((e.clientY - rect.top) / rect.height) * height
      if (x >= 0 && y >= 0 && x <= width && y <= height) {
        onPick(Math.round(x), Math.round(y))
      }
      return
    }
    // 非点选且放大时：拖拽平移
    if (!overflow) return
    ;(e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId)
    panRef.current = { startX: e.clientX, startY: e.clientY, ox: pan.x, oy: pan.y }
  }

  const onPointerMove = (e: React.PointerEvent) => {
    if (!panRef.current) return
    const dx = e.clientX - panRef.current.startX
    const dy = e.clientY - panRef.current.startY
    setPan(clampPan({ x: panRef.current.ox + dx, y: panRef.current.oy + dy }))
  }

  const onPointerUp = () => {
    panRef.current = null
  }

  return (
    <div className={`flex h-full min-h-0 flex-col ${className}`}>
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          className="btn btn-ghost !px-2 !py-1.5 !text-[12px]"
          onClick={() => setZoom((z) => Math.max(1, z / 1.25))}
          disabled={zoom <= 1}
          title="缩小"
        >
          <ZoomOut size={14} /> 缩小
        </button>
        <span className="min-w-[3.5rem] text-center font-mono text-[12px] text-muted">
          {Math.round(zoom * 100)}%
        </span>
        <button
          type="button"
          className="btn btn-ghost !px-2 !py-1.5 !text-[12px]"
          onClick={() => setZoom((z) => Math.min(4, z * 1.25))}
          title="放大"
        >
          <ZoomIn size={14} /> 放大
        </button>
        <button
          type="button"
          className="btn btn-ghost !px-2 !py-1.5 !text-[12px]"
          onClick={() => {
            setZoom(1)
            setPan({ x: 0, y: 0 })
          }}
          title="适应窗口"
        >
          <Maximize2 size={14} /> 适配
        </button>
        {overflow ? (
          <span className="text-[11px] text-muted">
            {pickEnabled ? '点击图片加点 · 关闭点选后可拖拽平移' : '拖拽平移 · 滚轮缩放'}
          </span>
        ) : pickEnabled ? (
          <span className="text-[11px] text-muted">点击图片加点</span>
        ) : null}
      </div>

      <div
        ref={wrapRef}
        className={`stage-bg relative min-h-0 flex-1 overflow-hidden rounded-lg ${
          pickEnabled ? 'cursor-crosshair' : overflow ? 'cursor-grab' : ''
        }`}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {baseW > 0 && (
          <div
            className="absolute left-1/2 top-1/2"
            style={{
              width: drawW,
              height: drawH,
              transform: `translate(-50%, -50%) translate(${pan.x}px, ${pan.y}px)`,
            }}
          >
            <img
              src={src}
              alt=""
              className="pointer-events-none block h-full w-full select-none rounded-lg"
              draggable={false}
            />
            {points.map((p, i) => (
              <span
                key={i}
                className="pointer-events-none absolute h-3 w-3 rounded-full border-2 border-white bg-primary shadow"
                style={{
                  left: `${(p.x / width) * 100}%`,
                  top: `${(p.y / height) * 100}%`,
                  // 随缩放同比例变大；适配时 zoom=1 恢复原始显示大小
                  transform: `translate(-50%, -50%) scale(${zoom})`,
                }}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
