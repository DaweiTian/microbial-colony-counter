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
  (detectTauri() ? 'http://127.0.0.1:18085' : '')

function apiUrl(path: string) {
  return `${API_BASE}${path}`
}

async function parseError(res: Response): Promise<string> {
  try {
    const data = await res.json()
    const detail = data.detail ?? data.message
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((d: unknown) =>
          typeof d === 'string'
            ? d
            : typeof d === 'object' && d && 'msg' in d
              ? String((d as { msg: unknown }).msg)
              : JSON.stringify(d),
        )
        .join('; ')
    }
    if (detail != null) return String(detail)
    return res.statusText || `HTTP ${res.status}`
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

function bufferToBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf)
  let binary = ''
  const chunk = 0x8000
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk))
  }
  return btoa(binary)
}

/** 不用 fetch(dataUrl)：Tauri CSP connect-src 不含 data:，会 Failed to fetch */
function dataUrlToBlob(dataUrl: string): Blob {
  const comma = dataUrl.indexOf(',')
  if (comma < 0) throw new Error('无效的 data URL')
  const meta = dataUrl.slice(0, comma)
  const b64 = dataUrl.slice(comma + 1)
  const mime = /data:([^;,]+)/.exec(meta)?.[1] || 'application/octet-stream'
  const bin = atob(b64)
  const arr = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i)
  return new Blob([arr], { type: mime })
}

async function toBlob(data: Blob | string, mime: string): Promise<Blob> {
  if (typeof data === 'string') {
    if (data.startsWith('data:')) return dataUrlToBlob(data)
    return new Blob([data], { type: mime })
  }
  return data
}

/**
 * 弹出系统「另存为」让用户选路径和文件名。
 * mode=dialog 走后端 Windows 保存对话框；取消返回 cancelled。
 */
export async function saveFileWithDialog(
  filename: string,
  data: Blob | string,
  mime = 'application/octet-stream',
): Promise<{ ok: boolean; cancelled?: boolean; path?: string; message: string }> {
  try {
    const blob = await toBlob(data, mime)
    const buf = await blob.arrayBuffer()
    const b64 = bufferToBase64(buf)
    const fd = new FormData()
    fd.append('filename', filename)
    fd.append('content_b64', b64)
    fd.append('mode', 'dialog')
    const res = await fetch(apiUrl('/api/v1/export'), { method: 'POST', body: fd })
    const body = (await res.json().catch(() => ({}))) as {
      ok?: boolean
      cancelled?: boolean
      path?: string
      message?: string
      detail?: string
    }
    if (body.cancelled) {
      return { ok: false, cancelled: true, message: '已取消保存' }
    }
    if (res.ok && body.ok) {
      return { ok: true, path: body.path, message: `已保存到 ${body.path}` }
    }
    return {
      ok: false,
      message: body.detail || body.message || `保存失败 HTTP ${res.status}`,
    }
  } catch (e) {
    return { ok: false, message: e instanceof Error ? e.message : String(e) }
  }
}

/** 直接写入下载目录（无对话框）；失败回退 DOM 下载 */
export async function saveFile(
  filename: string,
  data: Blob | string,
  mime = 'application/octet-stream',
): Promise<{ ok: boolean; path?: string; message: string }> {
  try {
    const blob = await toBlob(data, mime)
    const buf = await blob.arrayBuffer()
    const b64 = bufferToBase64(buf)
    const fd = new FormData()
    fd.append('filename', filename)
    fd.append('content_b64', b64)
    fd.append('mode', 'downloads')
    const res = await fetch(apiUrl('/api/v1/export'), { method: 'POST', body: fd })
    if (res.ok) {
      const data = (await res.json()) as { path?: string; dir?: string; filename?: string }
      return {
        ok: true,
        path: data.path,
        message: `已保存到 ${data.path || data.dir || '下载目录'}`,
      }
    }
    const detail = await parseError(res)
    downloadBlobFallback(blob, filename)
    return { ok: true, message: `已触发浏览器下载（本地保存失败：${detail}）` }
  } catch (e) {
    try {
      const blob = await toBlob(data, mime)
      downloadBlobFallback(blob, filename)
      return { ok: true, message: '已触发浏览器下载' }
    } catch (e2) {
      return { ok: false, message: e2 instanceof Error ? e2.message : String(e2) }
    }
  }
}

function downloadBlobFallback(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.setTimeout(() => URL.revokeObjectURL(url), 15000)
}

export function downloadText(
  filename: string,
  content: string,
  mime = 'text/plain',
) {
  void saveFile(filename, content, mime)
}

export function downloadDataUrl(filename: string, dataUrl: string) {
  void saveFile(filename, dataUrl)
}

function csvEscape(value: string | number): string {
  let s = String(value ?? '')
  // Excel/CSV 公式注入防护
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`
  if (/["\n\r,]/.test(s)) s = `"${s.replace(/"/g, '""')}"`
  return s
}

export function resultsToCsv(
  items: Array<{ name: string; count: number; error?: string | null }>,
) {
  const header = 'name,count,error'
  const rows = items.map((r) =>
    [csvEscape(r.name), csvEscape(r.count), csvEscape(r.error || '')].join(','),
  )
  return [header, ...rows].join('\n')
}
