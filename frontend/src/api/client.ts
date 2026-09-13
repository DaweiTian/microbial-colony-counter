import type {
  BatchRunResult,
  CalibrateResult,
  CountParams,
  CountResponse,
} from '../types'

/** Browser same-origin by default; Tauri packaged page needs absolute API. */
function detectTauri(): boolean {
  if (typeof window === 'undefined') return false
  const w = window as unknown as {
    __TAURI__?: unknown
    __TAURI_INTERNALS__?: unknown
  }
  return Boolean(w.__TAURI__ || w.__TAURI_INTERNALS__)
}

const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ||
  (detectTauri() ? 'http://127.0.0.1:8000' : '')

function apiUrl(path: string) {
  return `${API_BASE}${path}`
}

async function parseError(res: Response): Promise<string> {
  try {
    const data = await res.json()
    return data.detail || data.message || res.statusText
  } catch {
    return res.statusText || `HTTP ${res.status}`
  }
}

function paramsToForm(
  params: CountParams,
  roiType: string | null,
  roiData: string | null,
) {
  const fd = new FormData()
  fd.append('thresh_method', params.thresh_method)
  fd.append('thresh_val', String(params.thresh_val))
  fd.append('adaptive_block_size', String(params.adaptive_block_size))
  fd.append('adaptive_c', String(params.adaptive_c))
  fd.append('blur_ksize', String(params.blur_ksize))
  fd.append('min_area', String(params.min_area))
  fd.append('max_area', String(params.max_area))
  fd.append('min_distance_from_edge', String(params.min_distance_from_edge))
  fd.append('detect_petri_dish', String(params.detect_petri_dish))
  fd.append('use_watershed', String(params.use_watershed))
  fd.append('min_circularity', String(params.min_circularity))
  if (roiType && roiType !== 'none' && roiData) {
    fd.append('roi_type', roiType)
    fd.append('roi_data', roiData)
  }
  return fd
}

export async function apiCount(
  image: File,
  params: CountParams,
  roiType: string | null,
  roiData: string | null,
): Promise<CountResponse> {
  const fd = paramsToForm(params, roiType, roiData)
  fd.append('image', image)
  const res = await fetch(apiUrl('/api/v1/count'), { method: 'POST', body: fd })
  if (!res.ok) throw new Error(await parseError(res))
  return res.json()
}

export async function apiCountSmart(image: File): Promise<CountResponse> {
  const fd = new FormData()
  fd.append('image', image)
  const res = await fetch(apiUrl('/api/v1/count_smart'), {
    method: 'POST',
    body: fd,
  })
  if (!res.ok) throw new Error(await parseError(res))
  return res.json()
}

export async function apiHealth(): Promise<{ status: string }> {
  const res = await fetch(apiUrl('/health'))
  if (!res.ok) throw new Error(await parseError(res))
  return res.json()
}

export async function apiAddRefs(files: File[]): Promise<{
  refs: Array<{
    id: string
    name: string
    width: number
    height: number
    thumb_base64: string
  }>
}> {
  const fd = new FormData()
  for (const f of files) fd.append('images', f)
  const res = await fetch(apiUrl('/api/v1/batch/refs'), {
    method: 'POST',
    body: fd,
  })
  if (!res.ok) throw new Error(await parseError(res))
  return res.json()
}

export async function apiUpdateRef(
  id: string,
  body: {
    total_gt?: number | null
    points?: Array<{ x: number; y: number }>
  },
): Promise<{
  id: string
  name: string
  total_gt: number | null
  points: Array<{ x: number; y: number }>
}> {
  const res = await fetch(apiUrl(`/api/v1/batch/refs/${id}`), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await parseError(res))
  return res.json()
}

export async function apiCalibrate(
  refs: Array<{
    id: string
    total_gt: number | null
    points: Array<{ x: number; y: number }>
  }>,
  options?: { max_evals?: number; time_limit_sec?: number },
): Promise<CalibrateResult> {
  const res = await fetch(apiUrl('/api/v1/batch/calibrate'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      refs,
      max_evals: options?.max_evals ?? 40,
      time_limit_sec: options?.time_limit_sec ?? 60,
    }),
  })
  if (!res.ok) throw new Error(await parseError(res))
  return res.json()
}

export async function apiBatchRun(
  files: File[],
  params: Record<string, unknown>,
): Promise<BatchRunResult> {
  const fd = new FormData()
  for (const f of files) fd.append('images', f)
  fd.append('params', JSON.stringify(params))
  const res = await fetch(apiUrl('/api/v1/batch/run'), {
    method: 'POST',
    body: fd,
  })
  if (!res.ok) throw new Error(await parseError(res))
  return res.json()
}

export function downloadText(
  filename: string,
  content: string,
  mime = 'text/plain',
) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function downloadDataUrl(filename: string, dataUrl: string) {
  const a = document.createElement('a')
  a.href = dataUrl
  a.download = filename
  a.click()
}

export function resultsToCsv(
  items: Array<{ name: string; count: number; error?: string | null }>,
) {
  const header = 'name,count,error'
  const rows = items.map((r) =>
    [r.name, r.count, r.error ? `"${String(r.error).replace(/"/g, '""')}"` : ''].join(
      ',',
    ),
  )
  return [header, ...rows].join('\n')
}
