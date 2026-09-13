export type ColonyDetail = {
  id: number
  x: number
  y: number
  area: number
  circularity?: number | null
}

export type SmartCandidate = {
  strategy?: string
  count?: number
  score?: number
  error?: string | null
}

export type CountResponse = {
  count: number
  quality_score?: number | null
  warnings: string[]
  binary_image_base64?: string | null
  processed_image_base64?: string | null
  petri_circle?: [number, number, number] | null
  processing_ms?: number | null
  colony_details: ColonyDetail[]
  strategy?: string | null
  detector?: string | null
  smart?: boolean | null
  petri_detected?: boolean | null
  candidates?: SmartCandidate[] | null
}

export type CountParams = {
  thresh_method: 'adaptive' | 'manual'
  thresh_val: number
  adaptive_block_size: number
  adaptive_c: number
  blur_ksize: number
  min_area: number
  max_area: number
  min_distance_from_edge: number
  detect_petri_dish: boolean
  use_watershed: boolean
  min_circularity: number
}

export const defaultCountParams: CountParams = {
  thresh_method: 'adaptive',
  thresh_val: 100,
  adaptive_block_size: 11,
  adaptive_c: 2,
  blur_ksize: 7,
  min_area: 50,
  max_area: 5000,
  min_distance_from_edge: 20,
  detect_petri_dish: false,
  use_watershed: false,
  min_circularity: 0,
}

export type RoiMode = 'none' | 'rectangle' | 'circle'

export type RoiShape =
  | { type: 'rectangle'; x: number; y: number; w: number; h: number }
  | { type: 'circle'; cx: number; cy: number; r: number }

export type HistoryItem = {
  id: string
  name: string
  count: number
  timeMs: number
  strategy?: string | null
  createdAt: number
  thumb?: string | null
}

export type RefPlate = {
  id: string
  name: string
  thumb: string
  width: number
  height: number
  totalGt: number | null
  points: { x: number; y: number }[]
}

export type BatchImage = {
  id: string
  name: string
  file: File
}

export type CalibrateResult = {
  success: boolean
  message?: string
  params?: Record<string, unknown>
  fit_error?: number
  evals?: number
  elapsed_ms?: number
  n_refs?: number
  warnings?: string[]
  plate_results?: Array<Record<string, unknown>>
}

export type BatchRunItem = {
  name: string
  count: number
  error?: string | null
  processed_image_base64?: string | null
}

export type BatchRunResult = {
  items: BatchRunItem[]
  elapsed_ms?: number
}
