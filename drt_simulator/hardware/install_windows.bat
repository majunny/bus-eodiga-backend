@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0\..\.."

where py >nul 2>nul
if errorlevel 1 (
  echo [오류] Python이 없습니다. https://www.python.org/downloads/ 에서 Python 3.11을 설치하세요.
  echo 설치할 때 "Add python.exe to PATH"를 체크해야 합니다.
  pause
  exit /b 1
)

echo [1/2] 가상환경을 만듭니다...
if not exist ".venv\Scripts\python.exe" py -3.11 -m venv .venv
if errorlevel 1 goto :failed

echo [2/2] 필요한 패키지를 설치합니다...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -r drt_simulator\hardware\requirements-kiosk.txt
if errorlevel 1 goto :failed

echo.
echo 설치가 완료됐습니다. env.kiosk 파일에 전달받은 키를 넣고 run_kiosk_windows.bat를 실행하세요.
pause
exit /b 0

:failed
echo.
echo [오류] 설치에 실패했습니다. 위 오류 화면을 사진으로 보내 주세요.
pause
exit /b 1
