@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [비행준비 서버 설정] 업로드 비밀키 만들기 → 서버 주소 저장 → 30분마다 자동 업로드 등록
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\fp_sync.ps1" -Setup
if errorlevel 1 (
  echo.
  echo 설정 또는 첫 업로드가 끝나지 않았습니다. 위 메시지를 확인하세요.
  pause
  exit /b 1
)
schtasks /Create /F /SC MINUTE /MO 30 /TN "FLT Assist 비행준비 업로드" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%~dp0tools\fp_sync.ps1\"" >nul
if errorlevel 1 (echo 자동 실행 등록에 실패했습니다. 이 파일을 마우스 오른쪽 → 관리자 권한으로 실행해 보세요.) else (echo 30분마다 자동 업로드를 등록했습니다. 기록: private\fp_sync.log)
pause
