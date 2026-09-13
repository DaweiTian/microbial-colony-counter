import { Beaker, FlaskConical, Play, Plus, Trash2, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import {
  apiAddRefs,
  apiBatchRun,
  apiCalibrate,
  apiUpdateRef,
  downloadText,
  resultsToCsv,
} from '../../api/client'
import { Badge, Card, EmptyState, SectionTitle, Spinner } from '../../components/ui'
import type {
  BatchImage,
  BatchRunItem,
  CalibrateResult,
  CountParams,
  RefPlate,
} from '../../types'

type Props = {
  applyParamsToCount: (params: CountParams) => void
  toast: (msg: string) => void
}

function paramsFromCalibrate(p: Record<string, unknown> | undefined): CountParams | null {
  if (!p) return null
  const num = (k: string, d: number) => {
    const v = p[k]
    return typeof v === 'number' ? v : d
  }
  const bool = (k: string, d: boolean) => {
    const v = p[k]
    return typeof v === 'boolean' ? v : d
  }
  return {
    thresh_method: p.thresh_method === 'manual' ? 'manual' : 'adaptive',
    thresh_val: num('thresh_val', 100),
    adaptive_block_size: num('adaptive_block_size', 11),
    adaptive_c: num('adaptive_c', 2),
    blur_ksize: num('blur_ksize', 7),
    min_area: num('min_area', 50),
    max_area: num('max_area', 5000),
    min_distance_from_edge: num('min_distance_from_edge', 20),
    detect_petri_dish: bool('detect_petri_dish', false),
    use_watershed: bool('use_watershed', false),
    min_circularity: num('min_circularity', 0),
  }
}

export function BatchPage({ applyParamsToCount, toast }: Props) {
  const [refs, setRefs] = useState<RefPlate[]>([])
  const [activeRefId, setActiveRefId] = useState<string | null>(null)
  const [pointMode, setPointMode] = useState(false)
  const [batch, setBatch] = useState<BatchImage[]>([])
  const [calib, setCalib] = useState<CalibrateResult | null>(null)
  const [calibrating, setCalibrating] = useState(false)
  const [running, setRunning] = useState(false)
  const [runItems, setRunItems] = useState<BatchRunItem[]>([])
  const refInput = useRef<HTMLInputElement>(null)
  const batchInput = useRef<HTMLInputElement>(null)

  const activeRef = refs.find((r) => r.id === activeRefId) || null

  const addRefs = async (files: File[]) => {
    if (files.length === 0) return
    if (refs.length + files.length > 5) {
      toast('参考盘最多 5 块')
      return
    }
    try {
      const data = await apiAddRefs(files)
      const next: RefPlate[] = data.refs.map((r) => ({
        id: r.id,
        name: r.name,
        thumb: `data:image/jpeg;base64,${r.thumb_base64}`,
        width: r.width,
        height: r.height,
        totalGt: null,
        points: [],
      }))
      setRefs((prev) => [...prev, ...next])
      if (next[0]) setActiveRefId(next[0].id)
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e))
    }
  }

  const syncRefToServer = (id: string, body: { total_gt?: number | null; points?: { x: number; y: number }[] }) => {
    void apiUpdateRef(id, body).catch(() => {
      /* 静默失败：标定请求仍会带完整 N/点 */
    })
  }

  const startCalibrate = async () => {
    if (refs.length === 0) {
      toast('请先添加参考盘')
      return
    }
    const payload = refs.map((r) => ({
      id: r.id,
      total_gt: r.totalGt,
      points: r.points,
    }))
    setCalibrating(true)
    setCalib(null)
    try {
      const result = await apiCalibrate(payload, { max_evals: 40, time_limit_sec: 90 })
      setCalib(result)
      if (result.success) toast('标定完成')
      else toast(result.message || '标定失败')
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e))
    } finally {
      setCalibrating(false)
    }
  }

  const startBatch = async () => {
    if (batch.length === 0) {
      toast('请先添加批量图片')
      return
    }
    if (!calib?.success || !calib.params) {
      toast('请先完成标定')
      return
    }
    setRunning(true)
    setRunItems([])
    try {
      const res = await apiBatchRun(
        batch.map((b) => b.file),
        calib.params,
      )
      setRunItems(res.items)
      toast(`批量完成：${res.items.length} 张`)
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="grid h-full min-h-0 gap-4 xl:grid-cols-[280px_minmax(0,1fr)_320px] lg:grid-cols-[minmax(0,1fr)_320px] grid-cols-1">
      {/* refs list */}
      <div className="flex min-h-0 flex-col gap-3 overflow-y-auto">
        <Card className="!p-3">
          <button className="btn btn-primary w-full" onClick={() => refInput.current?.click()}>
            <Plus size={15} /> 添加参考盘（最多 5）
          </button>
          <input
            ref={refInput}
            type="file"
            accept="image/*"
            multiple
            className="hidden"
            onChange={(e) => {
              void addRefs(Array.from(e.target.files || []))
              e.target.value = ''
            }}
          />
        </Card>
        <Card className="min-h-0 flex-1 !p-3">
          <SectionTitle>
            <span className="inline-flex items-center gap-1.5">
              <Beaker size={14} /> 参考盘
            </span>
          </SectionTitle>
          <div className="space-y-2">
            {refs.map((r) => (
              <div
                key={r.id}
                role="button"
                tabIndex={0}
                className={`flex w-full items-center gap-2 rounded-lg border p-2 text-left ${
                  r.id === activeRefId ? 'border-primary bg-primary-soft' : 'border-line'
                }`}
                onClick={() => setActiveRefId(r.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    setActiveRefId(r.id)
                  }
                }}
              >
                <img src={r.thumb} alt="" className="h-10 w-10 rounded object-cover" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[12px] font-medium">{r.name}</div>
                  <div className="font-mono text-[11px] text-muted">
                    N={r.totalGt ?? '—'} · 点 {r.points.length}
                  </div>
                </div>
                <button
                  type="button"
                  aria-label={`删除 ${r.name}`}
                  className="text-muted hover:text-danger"
                  onClick={(e) => {
                    e.stopPropagation()
                    setRefs((prev) => prev.filter((x) => x.id !== r.id))
                    if (activeRefId === r.id) setActiveRefId(null)
                  }}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            {refs.length === 0 && (
              <EmptyState title="尚无参考盘" desc="上传 1–5 张已知人工计数的平板照片" />
            )}
          </div>
        </Card>
      </div>

      {/* canvas + batch list */}
      <div className="flex min-h-0 flex-col gap-3">
        <Card className="flex min-h-[280px] flex-1 flex-col !p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <SectionTitle>参考盘标注</SectionTitle>
            <div className="flex flex-wrap items-center gap-2">
              <button
                className={`btn !text-[12px] ${pointMode ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setPointMode((v) => !v)}
                disabled={!activeRef}
              >
                {pointMode ? '点选中（点击加点）' : '点选模式'}
              </button>
              <button
                className="btn btn-ghost !text-[12px]"
                disabled={!activeRef}
                onClick={() => {
                  if (!activeRefId || !activeRef) return
                  const nextPoints = activeRef.points.slice(0, -1)
                  setRefs((prev) =>
                    prev.map((r) =>
                      r.id === activeRefId ? { ...r, points: nextPoints } : r,
                    ),
                  )
                  syncRefToServer(activeRefId, { points: nextPoints })
                }}
              >
                撤销一点
              </button>
              <button
                className="btn btn-ghost !text-[12px]"
                disabled={!activeRef}
                onClick={() => {
                  if (!activeRefId) return
                  setRefs((prev) =>
                    prev.map((r) => (r.id === activeRefId ? { ...r, points: [] } : r)),
                  )
                  syncRefToServer(activeRefId, { points: [] })
                }}
              >
                清空点
              </button>
              {activeRef && (
                <label className="flex items-center gap-2 text-[12px] text-muted">
                  人工 N
                  <input
                    type="number"
                    min={0}
                    className="w-20 rounded border border-line px-2 py-1 font-mono"
                    value={activeRef.totalGt ?? ''}
                    onChange={(e) => {
                      const v = e.target.value === '' ? null : Number(e.target.value)
                      setRefs((prev) =>
                        prev.map((r) => (r.id === activeRefId ? { ...r, totalGt: v } : r)),
                      )
                      if (activeRefId) syncRefToServer(activeRefId, { total_gt: v })
                    }}
                  />
                </label>
              )}
            </div>
          </div>
          {!activeRef ? (
            <div className="flex flex-1 items-center justify-center rounded-lg border border-dashed border-line">
              <EmptyState title="选择或上传一块参考盘" desc="左侧填人工计数 N；可选点选若干典型菌落作增强" />
            </div>
          ) : (
            <div
              className="relative min-h-0 flex-1 overflow-auto"
              onClick={(e) => {
                if (!pointMode || !activeRef) return
                const target = e.currentTarget.querySelector('img')
                if (!target) return
                const rect = target.getBoundingClientRect()
                const x = ((e.clientX - rect.left) / rect.width) * activeRef.width
                const y = ((e.clientY - rect.top) / rect.height) * activeRef.height
                const nextPoint = { x: Math.round(x), y: Math.round(y) }
                const nextPoints = [...activeRef.points, nextPoint]
                setRefs((prev) =>
                  prev.map((r) =>
                    r.id === activeRefId ? { ...r, points: nextPoints } : r,
                  ),
                )
                if (activeRefId) syncRefToServer(activeRefId, { points: nextPoints })
              }}
            >
              <div className="relative inline-block max-w-full">
                <img src={activeRef.thumb} alt={activeRef.name} className="block max-w-full rounded-lg" />
                {activeRef.points.map((p, i) => (
                  <span
                    key={i}
                    className="pointer-events-none absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-primary shadow"
                    style={{
                      left: `${(p.x / activeRef.width) * 100}%`,
                      top: `${(p.y / activeRef.height) * 100}%`,
                    }}
                  />
                ))}
              </div>
            </div>
          )}
        </Card>

        <Card className="!p-3">
          <div className="mb-2 flex items-center justify-between">
            <SectionTitle>
              <span className="inline-flex items-center gap-1.5">
                <Upload size={14} /> 批量图片
              </span>
            </SectionTitle>
            <button className="btn btn-ghost !text-[12px]" onClick={() => batchInput.current?.click()}>
              添加图片
            </button>
            <input
              ref={batchInput}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={(e) => {
                const files = Array.from(e.target.files || [])
                setBatch((prev) => [
                  ...prev,
                  ...files.map((f) => ({
                    id: crypto.randomUUID(),
                    name: f.name,
                    file: f,
                  })),
                ])
                e.target.value = ''
              }}
            />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {batch.map((b) => (
              <span key={b.id} className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px]">
                {b.name}
              </span>
            ))}
            {batch.length === 0 && <span className="text-[12px] text-muted">未添加</span>}
          </div>
        </Card>
      </div>

      {/* right actions + results */}
      <div className="flex min-h-0 flex-col gap-3 overflow-y-auto">
        <Card className="!p-4">
          <SectionTitle>
            <span className="inline-flex items-center gap-1.5">
              <FlaskConical size={14} /> 标定与批量
            </span>
          </SectionTitle>
          <div className="grid gap-2">
            <button
              className="btn btn-primary w-full"
              disabled={calibrating || refs.length === 0}
              onClick={() => void startCalibrate()}
            >
              {calibrating ? '标定中…' : '开始标定'}
            </button>
            <button
              className="btn btn-accent w-full"
              disabled={running || batch.length === 0 || !calib?.success}
              onClick={() => void startBatch()}
            >
              <Play size={15} />
              {running ? '批量计数中…' : '应用标定参数批量计数'}
            </button>
            {calib?.success && (
              <button
                className="btn btn-ghost w-full"
                onClick={() => {
                  const p = paramsFromCalibrate(calib.params)
                  if (p) {
                    applyParamsToCount(p)
                    toast('已应用到单图参数')
                  }
                }}
              >
                应用到单图
              </button>
            )}
          </div>
          {(calibrating || running) && (
            <div className="mt-3">
              <Spinner label={calibrating ? '参数搜索中…' : '批量处理中…'} />
            </div>
          )}
          {calib && (
            <div className="mt-3 rounded-lg border border-line bg-slate-50 p-3 text-[12px]">
              <div className="flex items-center justify-between">
                <span className="font-medium">标定结果</span>
                <Badge tone={calib.success ? 'accent' : 'warn'}>
                  {calib.success ? '成功' : '失败'}
                </Badge>
              </div>
              {calib.fit_error != null && (
                <div className="mt-1 font-mono text-muted">
                  平均相对误差 {(calib.fit_error * 100).toFixed(1)}%
                  {calib.elapsed_ms ? ` · ${Math.round(calib.elapsed_ms)}ms` : ''}
                </div>
              )}
              {!calib.success && calib.message && (
                <div className="mt-1 text-danger">{calib.message}</div>
              )}
              {calib.success && calib.params && (
                <button
                  className="btn btn-ghost mt-2 w-full !text-[12px]"
                  onClick={() =>
                    downloadText(
                      'calibrated-params.json',
                      JSON.stringify(calib.params, null, 2),
                      'application/json',
                    )
                  }
                >
                  下载参数 JSON
                </button>
              )}
            </div>
          )}
        </Card>

        {runItems.length > 0 && (
          <Card className="fade-in-up !p-4">
            <SectionTitle>批量结果</SectionTitle>
            <div className="mb-2 overflow-auto rounded-lg border border-line">
              <table className="w-full text-[12px]">
                <thead className="bg-slate-50 text-muted">
                  <tr>
                    <th className="px-2 py-1.5 text-left">文件</th>
                    <th className="px-2 py-1.5 text-right">计数</th>
                    <th className="px-2 py-1.5 text-left">错误</th>
                  </tr>
                </thead>
                <tbody>
                  {runItems.map((r, i) => (
                    <tr key={`${r.name}-${i}`} className="border-t border-line">
                      <td className="max-w-[140px] truncate px-2 py-1.5">{r.name}</td>
                      <td className="px-2 py-1.5 text-right font-mono font-semibold text-primary">
                        {r.count}
                      </td>
                      <td className="px-2 py-1.5 text-danger">{r.error || ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button
              className="btn btn-ghost w-full !text-[12px]"
              onClick={() => downloadText('batch-results.csv', resultsToCsv(runItems), 'text/csv')}
            >
              导出 CSV
            </button>
          </Card>
        )}
      </div>
    </div>
  )
}
