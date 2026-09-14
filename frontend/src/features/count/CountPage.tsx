import {
  Calculator,
  ChevronLeft,
  ChevronRight,
  Crop,
  Download,
  History,
  ImageDown,
  Pencil,
  Settings2,
  Sparkles,
  Trash2,
  Upload,
  X,
  Zap,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { apiCount, apiCountSmart, saveFileWithDialog } from '../../api/client'
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
import { circleFromShape, cropCircleFromImage } from '../../utils/crop'
import { RoiCanvas, nudgeShape, scaleShape, shapeToRoi } from './RoiCanvas'

const HISTORY_KEY = 'colony-counter-history-v1'

function isDefaultParams(p: CountParams) {
  return JSON.stringify(p) === JSON.stringify(defaultCountParams)
}

/** 历史里保存可回放的计数结果：去掉超大 base64，图片用 thumb 复用。 */
function slimResultForHistory(data: CountResponse): CountResponse {
  return {
    count: data.count,
    quality_score: data.quality_score ?? null,
    warnings: data.warnings || [],
    binary_image_base64: null,
    processed_image_base64: data.processed_image_base64 || null,
    petri_circle: data.petri_circle ?? null,
    processing_ms: data.processing_ms ?? null,
    colony_details: (data.colony_details || []).slice(0, 500),
    strategy: data.strategy ?? null,
    detector: data.detector ?? null,
    smart: data.smart ?? null,
    petri_detected: data.petri_detected ?? null,
    candidates: data.candidates ?? null,
  }
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
  const attempts: Array<(h: HistoryItem) => HistoryItem> = [
    (h) => h,
    (h) => ({ ...h, sourceImage: null }),
    (h) => ({
      ...h,
      sourceImage: null,
      result: h.result ? { ...h.result, processed_image_base64: null, colony_details: [] } : null,
      thumb: null,
    }),
  ]
  for (const strip of attempts) {
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(slim.map(strip)))
      return
    } catch {
      /* try lighter payload */
    }
  }
  try {
    localStorage.removeItem(HISTORY_KEY)
  } catch {
    /* ignore */
  }
}

function historyExportCsv(items: HistoryItem[]): string {
  const esc = (v: string | number | null | undefined) => {
    let s = String(v ?? '')
    if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`
    if (/["\n\r,]/.test(s)) s = `"${s.replace(/"/g, '""')}"`
    return s
  }
  const header = '显示名称,文件名,菌落总数,策略,耗时ms,时间,裁切,警告'
  const rows = items.map((h) => {
    const d = new Date(h.createdAt)
    const ts = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
    const warn = (h.result?.warnings || []).join(' | ')
    return [
      esc(h.label || h.name),
      esc(h.name),
      h.count,
      esc(h.strategy || ''),
      h.timeMs,
      esc(ts),
      h.cropped ? '是' : '否',
      esc(warn),
    ].join(',')
  })
  return [header, ...rows].join('\n')
}

function pushHistory(list: HistoryItem[], item: HistoryItem): HistoryItem[] {
  const next = [item, ...list].slice(0, 20)
  saveHistory(next)
  return next
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
  /** 参数悬浮面板：默认收起，点击后展开 */
  const [paramsOpen, setParamsOpen] = useState(false)
  const [historySelected, setHistorySelected] = useState<Set<string>>(new Set())
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<number | null>(null)

  useEffect(() => {
    if (appliedParams) {
      setParams(appliedParams)
      setParamsOpen(true)
      onAppliedParamsConsumed?.()
    }
  }, [appliedParams, onAppliedParamsConsumed])

  const acceptFile = useCallback((f: File) => {
    if (!f.type.startsWith('image/') && f.size > 0) {
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

  const recordResult = useCallback(
    (
      data: CountResponse,
      name: string,
      strategy: string | null,
      extra?: { cropped?: boolean; label?: string },
    ) => {
      setResult(data)
      setView('processed')
      setDetailsOpen(true)
      const item: HistoryItem = {
        id: crypto.randomUUID(),
        name,
        label: extra?.label || null,
        count: data.count,
        timeMs: Math.round(data.processing_ms || 0),
        strategy,
        createdAt: Date.now(),
        thumb: data.processed_image_base64
          ? `data:image/jpeg;base64,${data.processed_image_base64}`
          : null,
        result: slimResultForHistory(data),
        sourceImage: null,
        cropped: extra?.cropped || false,
      }
      setHistory((h) => pushHistory(h, item))
    },
    [],
  )

  const restoreHistory = useCallback((h: HistoryItem) => {
    setError(null)
    setDetailsOpen(true)
    if (h.result) {
      setResult(h.result)
      setView('processed')
      const src = h.result.processed_image_base64
        ? `data:image/jpeg;base64,${h.result.processed_image_base64}`
        : h.thumb
      if (src) {
        setImgSrc(src)
        const img = new Image()
        img.onload = () => setImageEl(img)
        img.src = src
      }
    } else {
      // 旧版历史无完整结果，仅提示
      window.alert(
        `历史：${h.name}\n计数：${h.count}\n耗时：${h.timeMs}ms${h.strategy ? `\n策略：${h.strategy}` : ''}\n（该条未缓存完整结果，请重新计数）`,
      )
    }
  }, [])

  const runCount = async () => {
    if (!file) return
    setLoading('count')
    setError(null)
    try {
      const roi = shapeToRoi(roiShape)
      const data = await apiCount(file, params, roi?.type || null, roi?.data || null)
      recordResult(data, file.name, null)
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
      recordResult(data, file.name, data.strategy || null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(null)
    }
  }

  /** 圆形 ROI 在原分辨率裁切后计数，避免整图压缩导致边缘糊掉 */
  const applyCropAndRun = async (mode: 'count' | 'smart') => {
    const circle = circleFromShape(roiShape)
    if (!imageEl || !circle) {
      setError('请先选择圆形 ROI 作为培养皿裁切区')
      return
    }
    setLoading(mode)
    setError(null)
    try {
      const crop = await cropCircleFromImage(imageEl, circle)
      // 舞台切换为裁切图，便于核对范围
      setImgSrc(crop.dataUrl)
      const img = new Image()
      img.onload = () => setImageEl(img)
      img.src = crop.dataUrl
      const baseName = file?.name?.replace(/\.[^.]+$/, '') || 'petri'
      const croppedName = `${baseName}-crop.jpg`
      setFile(crop.file)
      setRoiShape(null)
      setRoiMode('none')
      setResult(null)

      const data =
        mode === 'smart'
          ? await apiCountSmart(crop.file)
          : await apiCount(crop.file, params, null, null)
      recordResult(data, croppedName, mode === 'smart' ? data.strategy || null : null, {
        cropped: true,
        label: `${baseName}（皿内裁切）`,
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(null)
    }
  }

  const toggleHistorySelect = (id: string) => {
    setHistorySelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const exportHistory = async (items: HistoryItem[], filename: string) => {
    if (items.length === 0) {
      setError('没有可导出的历史记录')
      return
    }
    const csv = historyExportCsv(items)
    const r = await saveFileWithDialog(filename, '﻿' + csv, 'text/csv;charset=utf-8')
    if (r.cancelled) return
    if (r.ok) setNotice(r.message)
    else setError(r.message)
  }

  const deleteHistoryItem = (id: string) => {
    setHistory((prev) => {
      const next = prev.filter((h) => h.id !== id)
      saveHistory(next)
      return next
    })
    setHistorySelected((prev) => {
      const n = new Set(prev)
      n.delete(id)
      return n
    })
  }

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
    <div className="flex h-full min-h-0 gap-3">
      {/* 左栏：选图 + 历史 */}
      <aside className="side-rail">
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
            支持拖到右侧舞台，或 Ctrl+V 粘贴。
          </p>
          {file ? (
            <div className="mt-2 truncate text-[12px] font-medium text-ink" title={file.name}>
              {file.name}
            </div>
          ) : null}
        </Card>

        <Card className="flex min-h-0 flex-1 flex-col !p-3">
          <SectionTitle>
            <span className="inline-flex items-center gap-1.5">
              <History size={14} /> 历史
            </span>
          </SectionTitle>
          <p className="mb-2 shrink-0 text-[11px] leading-snug text-muted">
            结果保存在本机浏览器 localStorage，不会上传。导出写入系统「下载」目录。
          </p>
          <div className="mb-2 flex shrink-0 flex-wrap gap-1.5">
            <button
              type="button"
              className="btn btn-ghost !px-2 !py-1.5 !text-[12px]"
              disabled={history.length === 0}
              onClick={() =>
                setHistorySelected(
                  historySelected.size === history.length
                    ? new Set()
                    : new Set(history.map((h) => h.id)),
                )
              }
            >
              {historySelected.size === history.length && history.length > 0 ? '取消全选' : '全选'}
            </button>
            <button
              type="button"
              className="btn btn-ghost !px-2 !py-1.5 !text-[12px]"
              disabled={historySelected.size === 0}
              onClick={() =>
                void exportHistory(
                  history.filter((h) => historySelected.has(h.id)),
                  `colony-history-selected.csv`,
                )
              }
            >
              <ImageDown size={13} /> 导出所选
            </button>
            <button
              type="button"
              className="btn btn-ghost !px-2 !py-1.5 !text-[12px]"
              disabled={history.length === 0}
              onClick={() => void exportHistory(history, `colony-history-all.csv`)}
            >
              导出全部
            </button>
            <button
              type="button"
              className="btn btn-ghost !px-2 !py-1.5 !text-[12px]"
              disabled={historySelected.size === 0}
              onClick={() => {
                const ids = historySelected
                setHistory((prev) => {
                  const next = prev.filter((h) => !ids.has(h.id))
                  saveHistory(next)
                  return next
                })
                setHistorySelected(new Set())
              }}
            >
              <Trash2 size={13} /> 删除所选
            </button>
          </div>
          <div className="min-h-0 flex-1 space-y-2 overflow-y-auto overscroll-contain pr-0.5">
            {history.length === 0 && (
              <div className="text-[12px] text-muted">暂无记录</div>
            )}
            {history.map((h) => (
              <div
                key={h.id}
                className={`flex w-full min-w-0 items-start gap-2 overflow-hidden rounded-lg border p-2 ${
                  historySelected.has(h.id) ? 'border-primary bg-primary-soft/40' : 'border-line'
                }`}
              >
                <input
                  type="checkbox"
                  className="mt-2.5 shrink-0"
                  checked={historySelected.has(h.id)}
                  onChange={() => toggleHistorySelect(h.id)}
                  aria-label="选择历史"
                />
                <button
                  type="button"
                  className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden text-left"
                  title="回放该次计数结果"
                  onClick={() => restoreHistory(h)}
                >
                  {h.thumb ? (
                    <img
                      src={h.thumb}
                      alt=""
                      className="h-10 w-10 shrink-0 rounded object-cover"
                    />
                  ) : (
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded bg-subtle text-[11px] text-muted">
                      img
                    </div>
                  )}
                  <div className="min-w-0 flex-1 overflow-hidden">
                    {renamingId === h.id ? (
                      <input
                        className="surface-input !py-1 !text-[12px]"
                        value={renameDraft}
                        autoFocus
                        onChange={(e) => setRenameDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            setHistory((prev) => {
                              const next = prev.map((x) =>
                                x.id === h.id ? { ...x, label: renameDraft.trim() || null } : x,
                              )
                              saveHistory(next)
                              return next
                            })
                            setRenamingId(null)
                          } else if (e.key === 'Escape') {
                            setRenamingId(null)
                          }
                        }}
                      />
                    ) : (
                      <div className="truncate text-[12px] font-medium">
                        {h.label || h.name}
                        {h.cropped ? (
                          <span className="ml-1 text-[10px] text-accent">裁切</span>
                        ) : null}
                      </div>
                    )}
                    <div className="truncate font-mono text-[11px] text-muted">
                      {h.count} 个 · {h.timeMs}ms {h.strategy ? `· ${h.strategy}` : ''}
                    </div>
                  </div>
                </button>
                <div className="flex shrink-0 flex-col gap-1">
                  <button
                    type="button"
                    className="btn btn-ghost !h-7 !w-7 !rounded-md !p-0"
                    title="重命名"
                    onClick={() => {
                      setRenamingId(h.id)
                      setRenameDraft(h.label || h.name)
                    }}
                  >
                    <Pencil size={12} />
                  </button>
                  <button
                    type="button"
                    className="btn btn-danger !h-7 !w-7 !rounded-md !p-0"
                    title="删除此条"
                    onClick={() => deleteHistoryItem(h.id)}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            ))}
          </div>
          {history.length > 0 && (
            <button
              className="btn btn-danger mt-2 w-full shrink-0 !py-1.5 !text-[12px]"
              onClick={() => {
                setHistory([])
                setHistorySelected(new Set())
                saveHistory([])
              }}
            >
              清空历史
            </button>
          )}
        </Card>
      </aside>

      {/* 右侧：舞台 + 悬浮参数 + 底部智能计数 */}
      <div
        className="flex min-h-0 min-w-0 flex-1 flex-col gap-2"
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
      >
        <div className="flex flex-wrap items-center justify-between gap-2 px-1">
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
            {roiMode !== 'none' ? (
              <Badge tone="primary">ROI {roiMode === 'circle' ? '圆形' : '矩形'}</Badge>
            ) : null}
          </div>
        </div>

        <div className="stage-shell">
          {!imgSrc ? (
            <button
              type="button"
              className="flex h-full w-full items-center justify-center bg-elevated/40"
              onClick={() => fileInputRef.current?.click()}
            >
              <EmptyState
                icon={<Upload size={28} />}
                title="上传培养皿照片"
                desc="点击选择，或把图片拖到这里；也可 Ctrl+V 粘贴。"
              />
            </button>
          ) : (
            <div className="h-full w-full overflow-hidden p-3">
              <RoiCanvas
                imageEl={imageEl}
                mode={roiMode}
                shape={roiShape}
                onChange={setRoiShape}
                overlaySrc={stageSrc}
              />
            </div>
          )}

          {/* ROI 快捷条（舞台左上） */}
          {roiMode !== 'none' && (
            <div className="absolute left-3 top-3 z-10 flex flex-wrap gap-1.5 rounded-[10px] border border-line bg-float/95 p-1.5 shadow-lg">
              {(
                [
                  ['none', '全图'],
                  ['rectangle', '矩形'],
                  ['circle', '圆形'],
                ] as const
              ).map(([m, label]) => (
                <button
                  key={m}
                  className={`btn !px-2 !py-1.5 !text-[12px] ${roiMode === m ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => {
                    setRoiMode(m)
                    if (m === 'none') setRoiShape(null)
                    if (m !== 'none') setParam('detect_petri_dish', false)
                  }}
                >
                  {label}
                </button>
              ))}
              <button className="btn btn-ghost !px-2 !py-1.5 !text-[12px]" onClick={() => setRoiShape((s) => scaleShape(s, 1.05))}>
                放大
              </button>
              <button className="btn btn-ghost !px-2 !py-1.5 !text-[12px]" onClick={() => setRoiShape((s) => scaleShape(s, 0.95))}>
                缩小
              </button>
              <button className="btn btn-ghost !px-2 !py-1.5 !text-[12px]" onClick={() => setRoiShape(null)}>
                <Trash2 size={13} /> 清除
              </button>
            </div>
          )}

          {/* 结果悬浮卡 */}
          {result && (
            <div className="result-float fade-in-up">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-[12px] text-muted">菌落总数</div>
                  <div
                    key={result.count}
                    className="count-pop font-mono text-[36px] font-bold leading-none text-primary"
                  >
                    {result.count}
                  </div>
                </div>
                <button
                  type="button"
                  className="btn btn-ghost !h-8 !w-8 !rounded-lg !p-0"
                  aria-label="关闭结果"
                  onClick={() => setResult(null)}
                >
                  <X size={14} />
                </button>
              </div>
              <div className="mt-1 text-[12px] text-muted">
                耗时 <span className="font-mono">{Math.round(result.processing_ms || 0)}ms</span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {result.strategy ? <Badge tone="accent">策略 {result.strategy}</Badge> : null}
                {result.petri_detected ? <Badge tone="primary">已检出培养皿</Badge> : null}
                {result.detector ? <Badge>{result.detector}</Badge> : null}
              </div>

              {result.warnings && result.warnings.length > 0 && (
                <div className="mt-3 rounded-lg border border-warn-line bg-warn-soft px-3 py-2 text-[12px] text-warn">
                  {result.warnings.map((w, i) => (
                    <div key={i}>{w}</div>
                  ))}
                </div>
              )}

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
                          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-subtle">
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
                  <div className="flex items-center justify-between">
                    <button
                      className="btn btn-ghost !text-[12px]"
                      onClick={() => setDetailsOpen((v) => !v)}
                    >
                      {detailsOpen ? '收起' : '展开'}菌落详情（{result.colony_details.length}）
                    </button>
                    <button
                      className="btn btn-ghost !text-[12px]"
                      onClick={() => {
                        const rows = [
                          'id,x,y,area,circularity',
                          ...result.colony_details.map((d) =>
                            [d.id, d.x, d.y, d.area, d.circularity ?? ''].join(','),
                          ),
                        ]
                        void saveFileWithDialog(
                          'colony-details.csv',
                          '﻿' + rows.join('\n'),
                          'text/csv;charset=utf-8',
                        ).then((r) => {
                          if (r.cancelled) return
                          if (r.ok) setNotice(r.message)
                          else setError(r.message)
                        })
                      }}
                    >
                      导出 CSV
                    </button>
                  </div>
                  {detailsOpen && (
                    <div className="mt-2 max-h-48 overflow-auto rounded-lg border border-line">
                      <table className="w-full text-[12px]">
                        <thead className="sticky top-0 bg-subtle text-muted">
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
                    onClick={() => {
                      void saveFileWithDialog(
                        'colony-result.jpg',
                        `data:image/jpeg;base64,${result.processed_image_base64}`,
                      ).then((r) => {
                        if (r.cancelled) return
                        if (r.ok) setNotice(r.message)
                        else setError(r.message)
                      })
                    }}
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
            </div>
          )}

          {/* 参数悬浮面板（默认收起） */}
          {paramsOpen && (
            <div className="params-panel">
              <div className="flex items-center justify-between border-b border-line px-3 py-2">
                <div className="inline-flex items-center gap-1.5 text-[13px] font-semibold">
                  <Settings2 size={14} /> 计数参数
                </div>
                <button
                  type="button"
                  className="btn btn-ghost !h-8 !w-8 !rounded-lg !p-0"
                  aria-label="收起参数"
                  onClick={() => setParamsOpen(false)}
                >
                  <ChevronRight size={16} />
                </button>
              </div>
              <div className="params-panel-body space-y-3">
                <div>
                  <span className="field-label">ROI 模式</span>
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
                </div>

                <div>
                  <span className="field-label">二值化方法</span>
                  <select
                    className="surface-input"
                    value={params.thresh_method}
                    onChange={(e) =>
                      setParam('thresh_method', e.target.value as 'adaptive' | 'manual')
                    }
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
              <div className="border-t border-line p-3">
                <button
                  className="btn btn-primary w-full"
                  disabled={!file || loading !== null}
                  onClick={() => void runCount()}
                  title="严格按当前参数计算"
                >
                  <Calculator size={15} />
                  {loading === 'count' ? '计数中…' : '按参数手动计数'}
                </button>
                <button
                  className="btn btn-ghost mt-2 w-full"
                  disabled={isDefaultParams(params)}
                  onClick={() => setParams(defaultCountParams)}
                >
                  <Sparkles size={15} /> 恢复默认参数
                </button>
              </div>
            </div>
          )}
        </div>

        {/* 底部悬浮操作条 */}
        <div className="dock-bar">
          {!paramsOpen && (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setParamsOpen(true)}
              title="展开计数参数"
            >
              <ChevronLeft size={15} /> 参数
            </button>
          )}
          {roiShape?.type === 'circle' ? (
            <>
              <button
                className="btn btn-primary"
                disabled={!file || loading !== null}
                onClick={() => void applyCropAndRun('smart')}
                title="按圆形 ROI 在原分辨率裁切培养皿，再智能计数，减少整图压缩导致的模糊"
              >
                <Crop size={15} /> 裁切皿内·智能
              </button>
              <button
                className="btn btn-ghost"
                disabled={!file || loading !== null}
                onClick={() => void applyCropAndRun('count')}
                title="裁切后按当前参数计数"
              >
                <Crop size={14} /> 裁切·按参数
              </button>
            </>
          ) : (
            <button
              type="button"
              className="btn btn-ghost"
              disabled={!file}
              onClick={() => {
                setRoiMode('circle')
                setParam('detect_petri_dish', false)
              }}
              title="画圆形裁切区，只保留培养皿内部，可减小体积并保持清晰度"
            >
              <Crop size={15} /> 皿内裁切
            </button>
          )}
          <button
            className="btn btn-accent dock-smart"
            disabled={!file || loading !== null}
            onClick={() => void runSmart()}
            title={file ? '自动估参并多策略选优；整图分析' : '请先选择图片'}
          >
            <Zap size={16} />
            {loading === 'smart' ? '智能分析中…' : '开始计数（智能）'}
          </button>
          {!file && result ? (
            <div className="rounded-[10px] border border-line bg-float px-3 py-2 text-[12px] text-muted">
              历史回放中 · 重新计数请先选图
            </div>
          ) : null}
          {loading === 'count' ? (
            <div className="rounded-[10px] border border-line bg-float px-3 py-2">
              <Spinner label="经典计数中…" />
            </div>
          ) : null}
        </div>

        {(error || notice || loading) && (
          <div className="px-1 pb-1">
            {loading && loading === 'smart' ? (
              <Spinner label="智能计数运行中…" />
            ) : null}
            {notice && (
              <div className="rounded-lg border border-accent bg-accent-soft px-3 py-2 text-[12px] text-accent">
                {notice}
                <button
                  type="button"
                  className="ml-2 underline"
                  onClick={() => setNotice(null)}
                >
                  关闭
                </button>
              </div>
            )}
            {error && (
              <div className="rounded-lg border border-danger-line bg-danger-soft px-3 py-2 text-[12px] text-danger">
                {error}
              </div>
            )}
          </div>
        )}
      </div>

      {modalSrc && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="结果预览"
          className="fixed inset-0 z-40 flex items-center justify-center bg-overlay p-6"
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
