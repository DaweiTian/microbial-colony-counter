import { Beaker, Microscope } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { apiHealth } from './api/client'
import { Badge, Toast, useToast } from './components/ui'
import { BatchPage } from './features/batch/BatchPage'
import { CountPage } from './features/count/CountPage'
import { defaultCountParams, type CountParams } from './types'

export default function App() {
  const [tab, setTab] = useState<'count' | 'batch'>('count')
  const [health, setHealth] = useState<'checking' | 'ok' | 'down'>('checking')
  const [countParams, setCountParams] = useState<CountParams>(defaultCountParams)
  const [paramsEpoch, setParamsEpoch] = useState(0)
  const { msg, show } = useToast()

  useEffect(() => {
    let cancelled = false
    apiHealth()
      .then(() => {
        if (!cancelled) setHealth('ok')
      })
      .catch(() => {
        if (!cancelled) setHealth('down')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const applyParamsToCount = useCallback((p: CountParams) => {
    setCountParams(p)
    setParamsEpoch((n) => n + 1)
    setTab('count')
  }, [])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-line bg-surface px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-white">
            <Microscope size={18} />
          </div>
          <div>
            <div className="text-[15px] font-semibold leading-tight">微生物菌落计数器</div>
            <div className="text-[12px] text-muted">现代实验室工作台</div>
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
        <Badge tone={health === 'ok' ? 'accent' : health === 'down' ? 'warn' : 'default'}>
          API {health === 'ok' ? '已连接' : health === 'down' ? '未连接' : '…'}
        </Badge>
      </header>

      <main className="min-h-0 flex-1 overflow-auto p-4">
        {tab === 'count' ? (
          <CountPage key={paramsEpoch} initialParams={countParams} />
        ) : (
          <BatchPage applyParamsToCount={applyParamsToCount} toast={show} />
        )}
      </main>

      <Toast message={msg} />
    </div>
  )
}
