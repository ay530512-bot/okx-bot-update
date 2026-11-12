# 폴드3 / Termux 사전 점검

## 실행 환경 준비 (phone_prepare.py)

첫 기초점검 이후 `phone_prepare.py`를 Termux Python으로 실행합니다. 기존 Q2X 공개 배포 파일을 고정 커밋에서 내려받아 SHA-256을 확인하고 `~/okx-phone-stage/q2x-source`에 보관합니다. 기존 파일이 다르면 덮어쓰지 않습니다. Windows 배치 파일은 실행하지 않습니다.

필수 Python 패키지 requests 2.34.2, python-dotenv 1.2.4, websocket-client 1.9.2를 PyPI에서 설치합니다. Tk를 불러오지 않고 원래 `okx_v5`, `okx_stream`, `okx_mobile` 모듈을 import한 뒤 원래 공개 `MarketStream`만 60초간 실행합니다. 계좌/RuleEngine/개인 WebSocket/텔레그램은 생성하지 않습니다. AAVE의 ticker, books5, mark-price가 각각 2회 이상 갱신되고 마지막 조회가 10초 이내이며, 연결된 후 단절이 없고 검사 간격이 5초 이하일 때 짧은 공개 연결 점검 통과로 표시합니다. 거래용 지연 기준이나 24시간 안정성 보증이 아닙니다.

실행 결과는 `~/okx-phone-stage/runtime-check.json`에 저장됩니다. 이 파일은 **실거래용 Android 실행기나 업데이트가 아닙니다.** 아직 필요한 작업: 사용자 PC의 최신 `strategy_config.json` 확인/이관, 로컬 비밀키 입력, headless 운용 화면 및 외부 연결, PC와 폰 중 한 곳만 주문하도록 전환, 보호 관리/복구/장시간 기기 검증. 이 단계에서 PC 프로그램을 종료할 필요는 없습니다.

2026-11-13 KST 사용자가 보낸 첫 점검 화면에서는 공개 API 정상, 180.172초 실행, 최대 간격 1.024초가 확인되었습니다. 화면 꺼짐 여부는 스크립트가 자동 측정하지 않습니다. 기기 모델은 사용자가 폴드3로 알려주었습니다.

의존성 배포 출처: [Requests](https://pypi.org/project/requests/), [python-dotenv](https://pypi.org/project/python-dotenv/), [websocket-client](https://pypi.org/project/websocket-client/). 설치/모듈 import 테스트는 Linux x86_64 Python 3.12에서 수행했으며 실제 Android 결과는 사용자 기기에서 확인해야 합니다.

## 첫 기초점검 (phone_check.py)

`phone_check.py`는 Python 표준 라이브러리만 사용하는 기초 점검입니다. 매매 프로그램 설치판이 아닙니다.

- 현재 데스크톱 코드와 같은 OKX 공개 서버의 시간 및 AAVE 15분봉을 HTTPS GET으로 확인합니다.
- 기본 180초 동안 1초 간격 실행을 기록합니다. 5초를 초과하는 간격이 있으면 추가 확인으로 표시합니다. 이는 사전 점검용 기준이며 주문 지연 허용 기준이 아닙니다.
- 화면을 끄는 동작은 사용자가 수행해야 합니다. 이 스크립트는 화면 상태를 측정하지 않습니다.
- 결과는 `~/okx-phone-check/result.json`, 직전 결과는 `previous-result.json`에 저장합니다. 앱 강제 종료 시 `running` 상태가 남을 수 있습니다.
- API 키, 계좌, 주문, 텔레그램, 기존 프로그램 파일을 사용하지 않습니다. IP 주소/기기 일련번호는 수집하지 않습니다.

Termux에서 `termux-wake-lock`을 실행하고 이 스크립트를 실행하세요. "화면을 꺼주세요"가 나오면 3분간 끈 뒤 결과를 확인하세요. 점검 후 wake lock은 `termux-wake-unlock`으로 해제할 수 있습니다.

짧은 점검 통과는 24시간 안정성을 입증하지 않습니다. HTTP만 점검하며 WebSocket, 인증, 주문 및 보호주문, 프로세스 복구, 외부 모바일 접속은 미검증입니다. 현재 Windows/Tk 실행부와 업데이트 재시작 경로는 Android 전용 실행부로 이식해야 합니다. 폰 실거래 이전과 검증 전까지 이 파일만으로 PC를 대체할 수 없습니다.

## 개발 검증

`python -m unittest discover -s android -v`

테스트는 모의 응답으로 동작하며 실제 폴드3나 OKX 연결 성공을 대신하지 않습니다. 이 폴더만 수정하면 기존 `release-input/**` 기반 데스크톱 배포를 시작하지 않습니다.
