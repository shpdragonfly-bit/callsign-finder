@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [Call Sign 데이터 업데이트] 인터넷 연결 상태에서 실행하세요.
where py >nul 2>nul && (py -3 updater\update.py %*) || (python updater\update.py %*)
echo.
echo 완료되면 web\index.html 을 브라우저로 여세요.
pause
