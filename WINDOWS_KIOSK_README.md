# MODI+ 정류장 키오스크 Windows 실행법

1. ZIP을 `다운로드` 같은 짧은 영문 경로에 압축 해제합니다.
2. Python 3.11을 설치합니다. 설치 화면에서 `Add python.exe to PATH`를 체크합니다.
3. `drt_simulator\hardware\install_windows.bat`를 더블클릭합니다.
4. 최상위 폴더의 `env.kiosk.example`을 복사하여 이름을 `env.kiosk`로 바꿉니다.
5. `BUS_EODIGA_KIOSK_KEY=` 오른쪽에 주최자가 별도로 전달한 키를 붙여 넣습니다.
6. 웹캠과 MODI+ 네트워크 모듈을 연결합니다.
7. `drt_simulator\hardware\run_kiosk_windows.bat`를 더블클릭합니다.

`26swbest2.pt`는 ZIP에 포함되어 있으며 옮길 필요가 없습니다. Windows Defender 방화벽 창이 뜨면 Python의 개인 네트워크 통신을 허용합니다. 종료는 카메라 창에서 `q`를 누르거나 명령창에서 `Ctrl+C`를 누릅니다.

실패하면 검은 명령창의 오류가 보이도록 사진을 찍어 전달해 주세요. `env.kiosk` 파일은 비밀키가 들어 있으므로 GitHub나 단체 채팅방에 올리지 않습니다.
