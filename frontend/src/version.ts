/** 由 vite.config.ts 从 package.json 注入，与安装包版本保持一致 */
declare const __APP_VERSION__: string

export const APP_VERSION: string =
  typeof __APP_VERSION__ === 'string' ? __APP_VERSION__ : '0.0.0'
