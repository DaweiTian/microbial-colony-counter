import { cpSync, mkdirSync, existsSync, rmSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(fileURLToPath(import.meta.url))
const dist = join(root, '..', 'dist')
const dest = join(root, '..', '..', 'backend', 'static')

if (!existsSync(dist)) {
  console.error('dist not found; run vite build first')
  process.exit(1)
}

mkdirSync(dest, { recursive: true })
// 清理旧 assets，避免哈希文件堆积
const assets = join(dest, 'assets')
if (existsSync(assets)) rmSync(assets, { recursive: true, force: true })
cpSync(dist, dest, { recursive: true })
console.log(`synced ${dist} -> ${dest}`)
