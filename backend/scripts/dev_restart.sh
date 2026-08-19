#!/usr/bin/env bash
# 开发环境重启 uvicorn：连 --reload 的 multiprocessing 子进程一起清掉
# （Windows 下孤儿 worker 会继续占端口跑旧代码，导致"改了没生效"的假象）
set -e
cd "$(dirname "$0")/.."

powershell -NoProfile -Command "
\$masters = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object {\$_.CommandLine -like '*uvicorn*'};
foreach (\$m in \$masters) {
  Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object {\$_.ParentProcessId -eq \$m.ProcessId} | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue };
  Stop-Process -Id \$m.ProcessId -Force -ErrorAction SilentlyContinue
}" 2>/dev/null || true
sleep 2

PYTHONUTF8=1 nohup /d/adaconda/envs/SmartBot/python.exe -m uvicorn app.main:app --reload --port 8000 > uvicorn.log 2>&1 &
for i in $(seq 1 10); do
  curl -s -m 2 http://127.0.0.1:8000/api/health >/dev/null 2>&1 && { echo "server up"; exit 0; }
  sleep 1
done
echo "server FAILED to start"; tail -5 uvicorn.log; exit 1
