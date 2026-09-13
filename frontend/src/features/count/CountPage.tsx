import {
  Calculator,
  Download,
  History,
  ImageDown,
  Sparkles,
  Trash2,
  Upload,
  Zap,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { apiCount, apiCountSmart, downloadDataUrl } from '../../api/client'
import {
  Badge,
  Card,
  EmptyState,
  SectionTitle,
  SliderField,
  Spinner,
  SwitchField,
} from '../../components/ui'
import {
  defaultCountParams,
  type CountParams,
  type CountResponse,
  type HistoryItem,
  type RoiMode,
  type RoiShape,
} from '../../types'
import { RoiCanvas, nudgeShape, scaleShape, shapeToRoi } from './RoiCanvas'

const HISTORY_KEY = 'colony-counter-history-v1'

function isDefaultParams(p: CountParams) {
  return JSON.stringify(p) === JSON.stringify(defaultCountParams)
}

function loadHistory(): HistoryItem[] {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
  } catch {
    return []
  }
}

function saveHistory(items: HistoryItem[]) {
  const slim = items.slice(0, 20)
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(slim))
  } catch {
    // 配额不足时去掉缩略图再试
    try {
      localStorage.setItem(
        HISTORY_KEY,
        JSON.stringify(slim.map((h) => ({ ...h, thumb: null }))),
      )
    } catch {
      try {
        localStorage.removeItem(HISTORY_KEY)
      } catch {
        /* ignore */
      }
    }
  }
}

export function CountPage({
  initialParams,
  appliedParams,
  onAppliedParamsConsumed,
}: {
  initialParams?: CountParams
  appliedParams?: CountParams | null
  onAppliedParamsConsumed?: () => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [imgSrc, setImgSrc] = useState<string | null>(null)
  const [imageEl, setImageEl] = useState<HTMLImageElement | null>(null)
  const [params, setParams] = useState<CountParams>(initialParams ?? defaultCountParams)
  const [roiMode, setRoiMode] = useState<RoiMode>('none')
  const [roiShape, setRoiShape] = useState<RoiShape | null>(null)
  const [result, setResult] = useState<CountResponse | null>(null)
  const [loading, setLoading] = useState<'count' | 'smart' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<'source' | 'processed' | 'binary'>('source')
  const [autoPreview, setAutoPreview] = useState(false)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [history, setHistory] = useState<HistoryItem[]>(() => loadHistory())
  const [modalSrc, setModalSrc] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<number | null>(null)

  useEffect(() => {
    if (appliedParams) {
      setParams(appliedParams)
      onAppliedParamsConsumed?.()
    }
  }, [appliedParams, onAppliedParamsConsumed])

  const acceptFile = useCallback((f: File) => {
    if (!f.type.startsWith('image/') && f.size > 0) {
      // 仍允许无 MIME 的粘贴，但拒绝明显非图
      if (f.type && !f.type.startsWith('image/')) {
        setError('请选择图片文件')
        return
      }
    }
    if (f.size > 15 * 1024 * 1024) {
      setError('图片过大（上限 15MB）')
      return
    }
    setFile(f)
    setResult(null)
    setError(null)
    setRoiShape(null)
    setView('source')
    const reader = new FileReader()
    reader.onload = () => {
      const src = String(reader.result)
      setImgSrc(src)
      const img = new Image()
      img.onload = () => setImageEl(img)
      img.src = src
    }
    reader.readAsDataURL(f)
  }, [])

  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const item = Array.from(e.clipboardData?.items || []).find((i) => i.type.startsWith('image/'))
      if (item) {
        const f = item.getAsFile()
        if (f) acceptFile(f)
      }
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [acceptFile])

  const setParam = <K extends keyof CountParams>(key: K, value: CountParams[K]) => {
    setParams((p) => ({ ...p, [key]: value }))
  }

  const runCount = async () => {
    if (!file) return
    setLoading('count')
    setError(null)
    try {
      const roi = shapeToRoi(roiShape)
      const data = await apiCount(file, params, roi?.type || null, roi?.data || null)
      setResult(data)
      setView('processed')
      const item: HistoryItem = {
        id: crypto.randomUUID(),
        name: file.name,
        count: data.count,
        timeMs: Math.round(data.processing_ms || 0),
        strategy: null,
        createdAt: Date.now(),
        thumb: data.processed_image_base64
          ? `data:image/jpeg;base64,${data.processed_image_base64}`
          : null,
      }
      setHistory((h) => {
        const next = [item, ...h].slice(0, 20)
        return next
      })
      saveHistory([item, ...history].slice(0, 20))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(null)
    }
  }

  const runSmart = async () => {
    if (!file) return
    setLoading('smart')
    setError(null)
    try {
      const data = await apiCountSmart(file)
      setResult(data)
      setView('processed')
      const item: HistoryItem = {
        id: crypto.randomUUID(),
        name: file.name,
        count: data.count,
        timeMs: Math.round(data.processing_ms || 0),
        strategy: data.strategy,
        createdAt: Date.now(),
        thumb: data.processed_image_base64
          ? `data:image/jpeg;base64,${data.processed_image_base64}`
          : null,
      }
      setHistory((h) => {
        const next = [item, ...h].slice(0, 20)
        return next
      })
      saveHistory([item, ...history].slice(0, 20))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(null)
    }
  }

  // ROI arrow-key nudge
  useEffect(() => {
    if (roiMode === 'none' || !roiShape) return
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.tagName === 'SELECT' ||
          target.isContentEditable)
      ) {
        return
      }
      const step = e.shiftKey ? 10 : 2
      if (e.key === 'ArrowLeft') {
        e.preventDefault()
        setRoiShape((s) => nudgeShape(s, -step, 0))
      } else if (e.key === 'ArrowRight') {
        e.preventDefault()
        setRoiShape((s) => nudgeShape(s, step, 0))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setRoiShape((s) => nudgeShape(s, 0, -step))
      } else if (e.key === 'ArrowDown') {
        e.preventDefault()
        setRoiShape((s) => nudgeShape(s, 0, step))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [roiMode, roiShape])

  // debounce auto preview
  useEffect(() => {
    if (!autoPreview || !file) return
    if (debounceRef.current) window.clearTimeout(debounceRef.current)
    debounceRef.current = window.setTimeout(() => {
      if (loading) return
      void runCount()
    }, 400)
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, roiShape, autoPreview, file])

  const stageSrc = useMemo(() => {
    if (view === 'processed' && result?.processed_image_base64) {
      return `data:image/jpeg;base64,${result.processed_image_base64}`
    }
    if (view === 'binary' && result?.binary_image_base64) {
      return `data:image/jpeg;base64,${result.binary_image_base64}`
    }
    return imgSrc
  }, [view, result, imgSrc])

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    const f = e.dataTransfer.files?.[0]
    if (f) acceptFile(f)
  }

  return (
    <div className="grid h-full min-h-0 gap-4 xl:grid-cols-[260px_minmax(0,1fr)_320px] lg:grid-cols-[minmax(0,1fr)_320px] grid-cols-1">
      {/* Left rail */}
      <div className="flex min-h-0 flex-col gap-3 overflow-y-auto xl:order-1 order-1">
        <Card className="!p-3">
          <button className="btn btn-primary w-full" onClick={() => fileInputRef.current?.click()}>
            <Upload size={15} /> 选择 / 换图
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) acceptFile(f)
              e.target.value = ''
            }}
          />
          <p className="mt-2 text-[12px] leading-relaxed text-muted">
            支持拖拽到中间舞台，或 Ctrl+V 粘贴剪贴板图片。
          </p>
        </Card>

        <Card className="!p-3">
          <SectionTitle>ROI 模式</SectionTitle>
          <div className="grid grid-cols-3 gap-1.5">
            {(
              [
                ['none', '全图'],
                ['rectangle', '矩形'],
                ['circle', '圆形'],
              ] as const
            ).map(([m, label]) => (
              <button
                key={m}
                className={`btn ${roiMode === m ? 'btn-primary' : 'btn-ghost'} !px-2 !py-2 !text-[12px]`}
                onClick={() => {
                  setRoiMode(m)
                  if (m === 'none') setRoiShape(null)
                  if (m !== 'none') setParam('detect_petri_dish', false)
                }}
              >
                {label}
              </button>
            ))}
          </div>
          {roiMode !== 'none' && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              <button className="btn btn-ghost !px-2 !py-1.5 !text-[12px]" onClick={() => setRoiShape((s) => scaleShape(s, 1.05))}>
                放大
              </button>
              <button className="btn btn-ghost !px-2 !py-1.5 !text-[12px]" onClick={() => setRoiShape((s) => scaleShape(s, 0.95))}>
                缩小
              </button>
              <button className="btn btn-ghost !px-2 !py-1.5 !text-[12px]" onClick={() => setRoiShape(null)}>
                <Trash2 size={13} /> 清除
              </button>
              <button className="btn btn-ghost !px-2 !py-1.5 !text-[12px]" onClick={() => setParam('detect_petri_dish', false)}>
                关闭皿检测
              </button>
            </div>
          )}
        </Card>

        <Card className="min-h-0 flex-1 !p-3">
          <SectionTitle>
            <span className="inline-flex items-center gap-1.5">
              <History size={14} /> 历史
            </span>
          </SectionTitle>
          <div className="space-y-2">
            {history.length === 0 && (
              <div className="text-[12px] text-muted">暂无记录</div>
            )}
            {history.map((h) => (
              <button
                key={h.id}
                type="button"
                className="flex w-full items-center gap-2 rounded-lg border border-line p-2 text-left hover:bg-slate-50"
                title="仅恢复记录信息，原图需重新上传"
                onClick={() =>
                  window.alert(
                    `历史：${h.name}\n计数：${h.count}\n耗时：${h.timeMs}ms${h.strategy ? `\n策略：${h.strategy}` : ''}\n（原图未缓存，请重新上传）`,
                  )
                }
              >
                {h.thumb ? (
                  <img src={h.thumb} alt="" className="h-10 w-10 rounded object-cover" />
                ) : (
                  <div className="flex h-10 w-10 items-center justify-center rounded bg-slate-100 text-[11px] text-muted">
                    img
                  </div>
                )}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[12px] font-medium">{h.name}</div>
                  <div className="font-mono text-[11px] text-muted">
                    {h.count} 个 · {h.timeMs}ms {h.strategy ? `· ${h.strategy}` : ''}
                  </div>
                </div>
              </button>
            ))}
          </div>
          {history.length > 0 && (
            <button
              className="btn btn-danger mt-2 w-full !py-1.5 !text-[12px]"
              onClick={() => {
                setHistory([])
                saveHistory([])
              }}
            >
              清空历史
            </button>
          )}
        </Card>
      </div>

      {/* Stage */}
      <div
        className="flex min-h-[360px] min-w-0 flex-col gap-3 xl:order-2 order-2"
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
      >
        <Card className="flex min-h-0 flex-1 flex-col !p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div className="flex gap-1">
              {(
                [
                  ['source', '原图'],
                  ['processed', '结果'],
                  ['binary', '二值'],
                ] as const
              ).map(([k, label]) => (
                <button
                  key={k}
                  className={`btn !px-2.5 !py-1.5 !text-[12px] ${view === k ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => setView(k)}
                  disabled={k !== 'source' && !result}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              {result?.strategy ? <Badge tone="accent">{result.strategy}</Badge> : null}
              {file ? <Badge>{file.name}</Badge> : null}
            </div>
          </div>
          {!imgSrc ? (
            <div
              className="flex flex-1 items-center justify-center rounded-lg border border-dashed border-line bg-white/50"
              onClick={() => fileInputRef.current?.click()}
            >
              <EmptyState
                icon={<Upload size={28} />}
                title="上传培养皿照片"
                desc="点击选择，或把图片拖到这里；也可 Ctrl+V 粘贴。"
              />
            </div>
          ) : (
            <div className="min-h-0 flex-1 overflow-auto">
              <RoiCanvas
                imageEl={imageEl}
                mode={roiMode}
                shape={roiShape}
                onChange={setRoiShape}
                overlaySrc={stageSrc}
              />
            </div>
          )}
        </Card>
      </div>

      {/* Right panel */}
      <div className="flex min-h-0 flex-col gap-3 overflow-y-auto xl:order-3 order-3">
        <Card className="!p-4">
          <SectionTitle>参数</SectionTitle>
          <div className="space-y-3">
            <div>
              <span className="field-label">二值化方法</span>
              <select
                className="w-full rounded-[8px] border border-line bg-white px-2 py-2 text-[13px]"
                value={params.thresh_method}
                onChange={(e) => setParam('thresh_method', e.target.value as 'adaptive' | 'manual')}
              >
                <option value="adaptive">自适应阈值</option>
                <option value="manual">手动阈值</option>
              </select>
            </div>
            {params.thresh_method === 'manual' ? (
              <SliderField
                label="手动阈值"
                value={params.thresh_val}
                min={0}
                max={255}
                onChange={(v) => setParam('thresh_val', v)}
              />
            ) : (
              <>
                <SliderField
                  label="自适应块大小"
                  value={params.adaptive_block_size}
                  min={3}
                  max={31}
                  step={2}
                  onChange={(v) => setParam('adaptive_block_size', v)}
                />
                <SliderField
                  label="自适应 C"
                  value={params.adaptive_c}
                  min={-5}
                  max={5}
                  onChange={(v) => setParam('adaptive_c', v)}
                />
              </>
            )}
            <SliderField
              label="高斯模糊核"
              value={params.blur_ksize}
              min={3}
              max={15}
              step={2}
              onChange={(v) => setParam('blur_ksize', v)}
            />
            <div className="grid grid-cols-2 gap-3">
              <SliderField
                label="最小面积"
                value={params.min_area}
                min={10}
                max={1000}
                step={10}
                onChange={(v) => setParam('min_area', v)}
              />
              <SliderField
                label="最大面积"
                value={params.max_area}
                min={1000}
                max={50000}
                step={100}
                onChange={(v) => setParam('max_area', v)}
              />
            </div>
            <SliderField
              label="最小边缘距离"
              value={params.min_distance_from_edge}
              min={0}
              max={200}
              onChange={(v) => setParam('min_distance_from_edge', v)}
            />
            <SliderField
              label="最小圆度"
              value={params.min_circularity}
              min={0}
              max={0.9}
              step={0.05}
              onChange={(v) => setParam('min_circularity', v)}
              format={(v) => v.toFixed(2)}
            />
            <SwitchField
              label="自动检测培养皿"
              hint={roiMode !== 'none' ? '已选 ROI 时会自动关闭皿检测' : undefined}
              checked={params.detect_petri_dish}
              onChange={(v) => setParam('detect_petri_dish', v)}
            />
            <SwitchField
              label="分水岭分离粘连"
              hint="可能导致过分割"
              checked={params.use_watershed}
              onChange={(v) => setParam('use_watershed', v)}
            />
            <SwitchField
              label="参数改动自动预览"
              hint="防抖 400ms 触发经典计数"
              checked={autoPreview}
              onChange={setAutoPreview}
            />
          </div>
        </Card>

        <Card className="!p-4">
          <div className="grid gap-2">
            <button
              className="btn btn-primary w-full"
              disabled={!file || loading !== null}
              onClick={() => void runCount()}
            >
              <Calculator size={15} />
              {loading === 'count' ? '计数中…' : '开始计数'}
            </button>
            <button
              className="btn btn-accent w-full"
              disabled={!file || loading !== null}
              onClick={() => void runSmart()}
            >
              <Zap size={15} />
              {loading === 'smart' ? '智能分析中…' : '一键智能'}
            </button>
            <button
              className="btn btn-ghost w-full"
              disabled={isDefaultParams(params)}
              onClick={() => setParams(defaultCountParams)}
            >
              <Sparkles size={15} /> 恢复默认参数
            </button>
          </div>
          {loading && (
            <div className="mt-3">
              <Spinner label={loading === 'smart' ? '智能计数运行中…' : '经典计数运行中…'} />
            </div>
          )}
          {error && (
            <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-danger">
              {error}
            </div>
          )}
        </Card>

        {result && (
          <Card className="fade-in-up !p-4">
            <SectionTitle>结果</SectionTitle>
            <div className="flex items-end justify-between">
              <div>
                <div className="text-[12px] text-muted">菌落总数</div>
                <div key={result.count} className="count-pop font-mono text-[36px] font-bold leading-none text-primary">
                  {result.count}
                </div>
              </div>
              <div className="text-right">
                <div className="text-[12px] text-muted">耗时</div>
                <div className="font-mono text-[16px]">
                  {Math.round(result.processing_ms || 0)}ms
                </div>
              </div>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {result.strategy ? <Badge tone="accent">策略 {result.strategy}</Badge> : null}
              {result.petri_detected ? <Badge tone="primary">已检出培养皿</Badge> : null}
              {result.detector ? <Badge>{result.detector}</Badge> : null}
            </div>

            {result.candidates && result.candidates.length > 0 && (
              <div className="mt-3">
                <div className="mb-1 text-[12px] font-medium text-muted">候选策略对比</div>
                <div className="space-y-1">
                  {result.candidates.map((c, i) => {
                    const score = c.score ?? 0
                    const maxScore = Math.max(...result.candidates!.map((x) => x.score || 0), 1)
                    const active = c.strategy === result.strategy
                    return (
                      <div
                        key={`${c.strategy}-${i}`}
                        className={`rounded-lg border px-2 py-1.5 ${active ? 'border-accent bg-accent-soft' : 'border-line'}`}
                      >
                        <div className="flex items-center justify-between text-[12px]">
                          <span className="font-mono">{c.strategy || '—'}</span>
                          <span className="font-mono">
                            {c.count ?? '—'} · {(c.score ?? 0).toFixed(2)}
                          </span>
                        </div>
                        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
                          <div
                            className={`h-full rounded-full ${active ? 'bg-accent' : 'bg-primary/60'}`}
                            style={{ width: `${Math.max(4, (score / maxScore) * 100)}%` }}
                          />
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {result.colony_details?.length > 0 && (
              <div className="mt-3">
                <button
                  className="btn btn-ghost w-full !text-[12px]"
                  onClick={() => setDetailsOpen((v) => !v)}
                >
                  {detailsOpen ? '收起' : '展开'}菌落详情（{result.colony_details.length}）
                </button>
                {detailsOpen && (
                  <div className="mt-2 max-h-56 overflow-auto rounded-lg border border-line">
                    <table className="w-full text-[12px]">
                      <thead className="sticky top-0 bg-slate-50 text-muted">
                        <tr>
                          <th className="px-2 py-1.5 text-left">#</th>
                          <th className="px-2 py-1.5 text-right">X</th>
                          <th className="px-2 py-1.5 text-right">Y</th>
                          <th className="px-2 py-1.5 text-right">面积</th>
                          <th className="px-2 py-1.5 text-right">圆度</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.colony_details.slice(0, 200).map((d) => (
                          <tr key={d.id} className="border-t border-line">
                            <td className="px-2 py-1 font-mono">{d.id}</td>
                            <td className="px-2 py-1 text-right font-mono">{d.x}</td>
                            <td className="px-2 py-1 text-right font-mono">{d.y}</td>
                            <td className="px-2 py-1 text-right font-mono">{d.area}</td>
                            <td className="px-2 py-1 text-right font-mono">
                              {d.circularity != null ? d.circularity.toFixed(2) : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            <div className="mt-3 grid grid-cols-2 gap-2">
              {result.processed_image_base64 && (
                <button
                  className="btn btn-ghost !text-[12px]"
                  onClick={() => downloadDataUrl('colony-result.jpg', `data:image/jpeg;base64,${result.processed_image_base64}`)}
                >
                  <ImageDown size={14} /> 下载结果图
                </button>
              )}
              <button
                className="btn btn-ghost !text-[12px]"
                onClick={() =>
                  setModalSrc(
                    view === 'binary' && result.binary_image_base64
                      ? `data:image/jpeg;base64,${result.binary_image_base64}`
                      : result.processed_image_base64
                        ? `data:image/jpeg;base64,${result.processed_image_base64}`
                        : imgSrc,
                  )
                }
              >
                <Download size={14} /> 查看大图
              </button>
            </div>
          </Card>
        )}
      </div>

      {modalSrc && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="结果预览"
          className="fixed inset-0 z-40 flex items-center justify-center bg-black/80 p-6"
          onClick={() => setModalSrc(null)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setModalSrc(null)
          }}
          tabIndex={-1}
          ref={(el) => {
            if (el) el.focus()
          }}
        >
          <img src={modalSrc} alt="preview" className="max-h-full max-w-full rounded-lg" />
        </div>
      )}
    </div>
  )
}
