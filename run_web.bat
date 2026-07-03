@echo off
REM 本地启动 Web 后台，浏览器打开 http://127.0.0.1:8000
cd /d %~dp0

REM 优先用项目虚拟环境的 Python（Web 依赖装在这里）
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

echo 使用 Python: %PY%
REM 不加 --reload：批量跑文章时若文件被改动，热重载会冲断正在跑的任务
"%PY%" -m uvicorn webapp.app:app --host 127.0.0.1 --port 8000
echo.
echo [服务已退出] 如果上面有红色报错，把它截图发出来。
pause
