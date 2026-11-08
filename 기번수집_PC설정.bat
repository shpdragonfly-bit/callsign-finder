@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [기번 수집 PC 설정] 토큰 확인 - 첫 수집 - 15분마다 자동 실행 등록
set PY=python
where py >nul 2>nul && set PY=py -3
%PY% tools\fleet_pc.py --check
if errorlevel 1 (
  echo.
  echo config\local.env 에 GH_FLEET_TOKEN=토큰 한 줄을 넣고 저장한 뒤 이 파일을 다시 실행하세요.
  notepad config\local.env
  pause
  exit /b 1
)
echo 첫 수집과 올리기를 합니다 (처음에는 1~2분 걸립니다)...
%PY% tools\fleet_pc.py
for /f "delims=" %%i in ('%PY% -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set PYW=%%i
schtasks /Create /F /SC MINUTE /MO 15 /TN "FLT Assist 기번 수집" /TR "\"%PYW%\" \"%~dp0tools\fleet_pc.py\"" >nul
if errorlevel 1 (echo 자동 실행 등록에 실패했습니다. 이 파일을 마우스 오른쪽 - 관리자 권한으로 실행해 보세요.) else (echo 15분마다 자동 수집을 등록했습니다. 기록: private\fleet_pc.log)
pause
