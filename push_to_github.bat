@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo 推送到 GitHub（安全模式：不 force、不 add -A）
echo ==========================================
echo.

where git >nul 2>nul
if %errorlevel% neq 0 (
    echo 错误: 未找到 git 命令，请先安装 Git。
    pause
    exit /b 1
)

git remote get-url origin >nul 2>nul
if %errorlevel% neq 0 (
    echo 未配置 origin，请先手动添加：
    echo   git remote add origin https://github.com/OWNER/REPO.git
    pause
    exit /b 1
)

echo [1/2] 显示待提交变更：
git status --short
echo.
echo 请确认没有误选文件后，手动执行：
echo   git add -p
echo   git commit -m "your message"
echo   git push origin HEAD
echo.
echo 本脚本已移除 git add -A / commit --force / push --force，避免误推密钥与历史改写。
echo.
pause
