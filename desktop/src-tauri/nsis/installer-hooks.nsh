; Tauri NSIS 钩子：安装前强制结束主程序与 Python sidecar，避免文件被占用
!macro NSIS_HOOK_PREINSTALL
  DetailPrint "正在关闭运行中的微生物菌落计数器..."
  nsExec::ExecToLog 'taskkill /IM "colony-backend.exe" /F'
  Pop $0
  nsExec::ExecToLog 'taskkill /IM "colony-counter-desktop.exe" /F'
  Pop $0
  ; 旧版可能的其他映像名
  nsExec::ExecToLog 'taskkill /IM "微生物菌落计数器.exe" /F'
  Pop $0
  Sleep 800
!macroend
