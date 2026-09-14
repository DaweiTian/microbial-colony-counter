import type { RoiShape } from '../types'

export type CropResult = {
  file: File
  width: number
  height: number
  dataUrl: string
}

/**
 * 按圆形 ROI 在原图分辨率上裁切外接正方形，并把圆外背景涂成皿内均色，
 * 减少上传像素、保留皿内清晰度，同时避免角落背景干扰 Otsu/自适应阈值。
 */
export async function cropCircleFromImage(
  image: HTMLImageElement,
  circle: Extract<RoiShape, { type: 'circle' }>,
  opts?: { padRatio?: number; quality?: number; maskOutside?: boolean },
): Promise<CropResult> {
  const padRatio = opts?.padRatio ?? 0.08
  const quality = opts?.quality ?? 0.95
  const maskOutside = opts?.maskOutside !== false
  const nw = image.naturalWidth || image.width
  const nh = image.naturalHeight || image.height
  const pad = circle.r * padRatio
  const half = circle.r + pad
  const x0 = Math.max(0, Math.floor(circle.cx - half))
  const y0 = Math.max(0, Math.floor(circle.cy - half))
  const x1 = Math.min(nw, Math.ceil(circle.cx + half))
  const y1 = Math.min(nh, Math.ceil(circle.cy + half))
  const w = Math.max(1, x1 - x0)
  const h = Math.max(1, y1 - y0)

  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  if (!ctx) throw new Error('无法创建裁切画布')
  ctx.drawImage(image, x0, y0, w, h, 0, 0, w, h)

  if (maskOutside) {
    const cx = circle.cx - x0
    const cy = circle.cy - y0
    const r = circle.r + pad * 0.35
    const imgData = ctx.getImageData(0, 0, w, h)
    const data = imgData.data
    // 取圆内环带均色作为填充，避免纯黑/纯白干扰阈值
    let sr = 0
    let sg = 0
    let sb = 0
    let sn = 0
    const rIn = r * 0.85
    for (let y = 0; y < h; y += 2) {
      for (let x = 0; x < w; x += 2) {
        const dx = x - cx
        const dy = y - cy
        const d2 = dx * dx + dy * dy
        if (d2 >= rIn * rIn && d2 <= r * r) {
          const i = (y * w + x) * 4
          sr += data[i]
          sg += data[i + 1]
          sb += data[i + 2]
          sn++
        }
      }
    }
    const fillR = sn ? Math.round(sr / sn) : 128
    const fillG = sn ? Math.round(sg / sn) : 128
    const fillB = sn ? Math.round(sb / sn) : 128
    const r2 = r * r
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const dx = x - cx
        const dy = y - cy
        if (dx * dx + dy * dy > r2) {
          const i = (y * w + x) * 4
          data[i] = fillR
          data[i + 1] = fillG
          data[i + 2] = fillB
          data[i + 3] = 255
        }
      }
    }
    ctx.putImageData(imgData, 0, 0)
  }

  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error('裁切编码失败'))),
      'image/jpeg',
      quality,
    )
  })
  const dataUrl = canvas.toDataURL('image/jpeg', quality)
  const file = new File([blob], 'petri-crop.jpg', { type: 'image/jpeg' })
  return { file, width: w, height: h, dataUrl }
}

export function circleFromShape(shape: RoiShape | null) {
  return shape && shape.type === 'circle' ? shape : null
}
