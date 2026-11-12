# OKX 업데이트 배포

자동 배포: .github/workflows/publish-update.yml

새 버전은 release-input/OKX_PROGRAM_UPDATE.zip 및 release-input/update_manifest.json을 같은 커밋으로 main에 추가/교체합니다. ZIP은 GitHub Git blob API의 base64 인코딩을 사용합니다. 프로그램 버전과 sequence는 이전 정식 릴리스보다 증가해야 합니다.

배포 전에 ZIP SHA256, 개별 파일 해시, 경로, 크기 제한, 필수 파일, release_info 일치 및 Python 문법을 검사합니다. 검사가 성공하면 draft 릴리스를 만들고 두 파일을 업로드한 뒤 GitHub가 반환한 해시를 확인하고 latest로 공개합니다. 실패한 draft는 정식 업데이트로 노출되지 않습니다.

release-input이 없는 초기 실행은 기존 latest 파일을 내려받아 검증만 합니다. 이 초기 검사는 신규 릴리스 업로드 경로 검증과 다릅니다.

동일 버전·sequence·ZIP 해시는 재배포하지 않습니다. 기존 태그의 파일을 덮어쓰지 않습니다. .env, 계정 키, 사용자 상태·설정 파일을 업로드하지 않습니다.

GitHub 릴리스 공개는 사용자 PC의 자동 설치나 실거래 설정 변경을 의미하지 않습니다. 설치는 기존 프로그램의 업데이트 버튼과 포지션/미체결 검사 절차를 따릅니다.
