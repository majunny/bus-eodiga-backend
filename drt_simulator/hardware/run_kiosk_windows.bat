@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0\..\.."

if not exist ".venv\Scripts\python.exe" (
  echo [오류] 먼저 drt_simulator\hardware\install_windows.bat를 실행하세요.
  pause
  exit /b 1
)
if not exist "env.kiosk" (
  echo [오류] env.kiosk 파일이 없습니다. env.kiosk.example을 복사해 이름을 env.kiosk로 바꾸고 키를 입력하세요.
  pause
  exit /b 1
)

for /f "usebackq eol=# tokens=1,* delims==" %%A in ("env.kiosk") do set "%%A=%%B"
if not defined BUS_EODIGA_KIOSK_KEY (
  echo [오류] env.kiosk의 BUS_EODIGA_KIOSK_KEY 값을 입력하세요.
  pause
  exit /b 1
)

set "PYTHONPATH=%CD%\drt_simulator"
".venv\Scripts\python.exe" -m hardware.modi_station_kiosk
if errorlevel 1 (
  echo.
  echo [오류] 키오스크가 종료됐습니다. 위 오류 화면을 사진으로 보내 주세요.
  pause
)
