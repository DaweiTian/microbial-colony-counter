import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Minus, Square, X, Copy } from 'lucide-react'

type TauriWindow = {
  minimize: () => Promise<void>
  toggleMaximize: () => Promise<void>
  maximize: () => Promise<void>
  unmaximize: () => Promise<void>
  close: () => Promise<void>
  isMaximized: () => Promise<boolean>
  listen: (event: string, handler: () => void) => Promise<() => void>
}

export function isTauriEnv(): boolean {
  if (typeof window === 'undefined') return false
  const w = window as unknown as {
    __TAURI__?: unknown
    __TAURI_INTERNALS__?: unknown
  }
  return Boolean(w.__TAURI__ || w.__TAURI_INTERNALS__)
}

function getTauriWindow(): TauriWindow | null {
  if (!isTauriEnv()) return null
  const w = window as unknown as {
    __TAURI__?: {
      window?: { getCurrentWindow: () => TauriWindow }
    }
    __TAURI_INTERNALS__?: {
      invoke?: unknown
    }
  }
  const fromGlobal = w.__TAURI__?.window?.getCurrentWindow
  if (typeof fromGlobal === 'function') {
    return fromGlobal()
  }
  return null
}

/**
 * Windows 自绘标题栏控件（最小化 / 最大化 / 关闭）。
 * 仅在 Tauri 桌面壳内渲染；浏览器环境返回 null。
 */
export function WindowControls() {
  const [maximized, setMaximized] = useState(false)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const win = getTauriWindow()
    if (!win) return
    setReady(true)
    let cancelled = false
    let unlisten: (() => void) | null = null

    void win.isMaximized().then((v) => {
      if (!cancelled) setMaximized(v)
    })
    void win.listen('tauri://resize', () => {
      void win.isMaximized().then((v) => {
        if (!cancelled) setMaximized(v)
      })
    }).then((fn) => {
      unlisten = fn
    })

    return () => {
      cancelled = true
      unlisten?.()
    }
  }, [])

  const onMin = useCallback(async () => {
    await getTauriWindow()?.minimize()
  }, [])
  const onMax = useCallback(async () => {
    await getTauriWindow()?.toggleMaximize()
  }, [])
  const onClose = useCallback(async () => {
    await getTauriWindow()?.close()
  }, [])

  if (!ready) return null

  return (
    <div className="win-controls">
      <button type="button" className="win-btn" aria-label="最小化" onClick={() => void onMin()}>
        <Minus size={14} strokeWidth={2} />
      </button>
      <button type="button" className="win-btn" aria-label={maximized ? '还原' : '最大化'} onClick={() => void onMax()}>
        {maximized ? <Copy size={12} strokeWidth={2} /> : <Square size={12} strokeWidth={2} />}
      </button>
      <button type="button" className="win-btn win-btn-close" aria-label="关闭" onClick={() => void onClose()}>
        <X size={15} strokeWidth={2} />
      </button>
    </div>
  )
}

/**
 * 顶栏外壳：整条可拖拽（data-tauri-drag-region）。
 * 交互控件不要加该属性（属性存在即生效，false 也会渲染成字符串）。
 */
export function DragBar({
  children,
  className = '',
  onDoubleClick,
}: {
  children: ReactNode
  className?: string
  onDoubleClick?: () => void
}) {
  const isTauri = isTauriEnv()
  return (
    <header
      className={`app-titlebar ${className}`.trim()}
      data-tauri-drag-region={isTauri ? true : undefined}
      onDoubleClick={isTauri ? onDoubleClick : undefined}
    >
      {children}
    </header>
  )
}

export function useToggleMaximizeOnDoubleclick() {
  return useCallback(() => {
    void getTauriWindow()?.toggleMaximize()
  }, [])
}
