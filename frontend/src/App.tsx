import { Beaker, Microscope } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { apiHealth } from './api/client'
import { Badge, Toast, useToast } from './components/ui'
import { ThemeProvider, ThemeToggleButton } from './components/ThemeProvider'
import {
  DragBar,
  WindowControls,
  isTauriEnv,
  useToggleMaximizeOnDoubleclick,
} from './components/TitleBar'
import { BatchPage } from './features/batch/BatchPage'
import { CountPage } from './features/count/CountPage'
import { defaultCountParams, type CountParams } from './types'
import { APP_VERSION } from './version'

function Shell() {
  const [tab, setTab] = useState<'count' | 'batch'>('count')
  const [health, setHealth] = useState<'checking' | 'ok' | 'down'>('checking')
  const [countParams, setCountParams] = useState<CountParams>(defaultCountParams)
  const [appliedParams, setAppliedParams] = useState<CountParams | null>(null)
  const { msg, show } = useToast()
  const toggleMaximize = useToggleMaximizeOnDoubleclick()
  const isDesktop = isTauriEnv()

  useEffect(() => {
    let cancelled = false
    let tries = 0
    let timer: number | null = null

    const poll = () => {
      apiHealth()
        .then(() => {
          if (!cancelled) setHealth('ok')
        })
        .catch(() => {
          if (cancelled) return
          tries += 1
          if (tries < 90) {
            setHealth('checking')
            timer = window.setTimeout(poll, 1000)
          } else {
            setHealth('down')
          }
        })
    }
    poll()
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
  }, [])

  const applyParamsToCount = useCallback((p: CountParams) => {
    setCountParams(p)
    setAppliedParams(p)
    setTab('count')
  }, [])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <DragBar className="!h-[52px]" onDoubleClick={toggleMaximize}>
        <div className="flex min-w-0 items-center gap-3" data-tauri-drag-region={isDesktop ? true : undefined}>
          <div
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] bg-primary text-white"
            data-tauri-drag-region={isDesktop ? true : undefined}
          >
            <Microscope size={16} />
          </div>
          <div className="min-w-0" data-tauri-drag-region={isDesktop ? true : undefined}>
            <div
              className="flex items-center gap-2"
              data-tauri-drag-region={isDesktop ? true : undefined}
            >
              <span
                className="truncate text-[14px] font-semibold leading-tight"
                data-tauri-drag-region={isDesktop ? true : undefined}
              >
                微生物菌落计数器
              </span>
              <span
                className="inline-flex shrink-0 items-center rounded-full bg-accent-soft px-1.5 py-0.5 font-mono text-[10px] font-semibold text-accent"
                title={`当前版本 v${APP_VERSION}`}
                data-tauri-drag-region={isDesktop ? true : undefined}
              >
                v{APP_VERSION}
              </span>
            </div>
            <div
              className="truncate text-[11px] text-muted"
              data-tauri-drag-region={isDesktop ? true : undefined}
            >
              现代实验室工作台
            </div>
          </div>
        </div>

        <nav className="flex items-center gap-1 rounded-[10px] bg-bg p-1">
          <button
            className={`btn !border-0 !px-3 !py-2 !text-[13px] ${tab === 'count' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setTab('count')}
          >
            单图计数
          </button>
          <button
            className={`btn !border-0 !px-3 !py-2 !text-[13px] ${tab === 'batch' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setTab('batch')}
          >
            <Beaker size={14} /> 批次标定
          </button>
        </nav>

        <div className="drag-spacer" data-tauri-drag-region={isDesktop ? true : undefined} />

        <div className="flex shrink-0 items-center gap-2 pr-1">
          <Badge tone={health === 'ok' ? 'accent' : health === 'down' ? 'warn' : 'default'}>
            API {health === 'ok' ? '已连接' : health === 'down' ? '未连接' : '启动中…'}
          </Badge>
          <ThemeToggleButton />
        </div>

        {isDesktop ? <WindowControls /> : null}
      </DragBar>

      {health !== 'ok' && (
        <div className="border-b border-line bg-warn-soft px-4 py-2 text-[13px] text-warn">
          {health === 'checking'
            ? '正在启动本地计数服务，请稍候…'
            : '本地服务未运行。请确认后端已启动，或重新打开桌面应用。'}
        </div>
      )}

      <main className="min-h-0 flex-1 overflow-hidden p-3">
        {tab === 'count' ? (
          <CountPage
            initialParams={countParams}
            appliedParams={appliedParams}
            onAppliedParamsConsumed={() => setAppliedParams(null)}
          />
        ) : (
          <div className="h-full overflow-auto">
            <BatchPage applyParamsToCount={applyParamsToCount} toast={show} />
          </div>
        )}
      </main>

      <Toast message={msg} />
    </div>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <Shell />
    </ThemeProvider>
  )
}
