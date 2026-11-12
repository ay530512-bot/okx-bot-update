# 폴드3 / Termux 사전 점검

## 최신: 집 폰 실행기 4 · Android Taildrop 종료 오류 수정

계정 연결을 마친 사용자는 [PHONE_HOME_KO.md](PHONE_HOME_KO.md)의 `phone_home_setup.py`를 사용합니다. 기존 설정을 재사용하여 비공개 원격 주소와 백그라운드 조회를 준비합니다. 실거래 이전은 별도 명시적 절차이며, 실제 기기의 외부 접속·장시간·거래 보호 복구는 아직 확인해야 합니다. 아래 내용과 `PHONE_HOST_KO.md`는 이전 단계 기록입니다.

## 폰 내부 계정 연결 화면 (phone_account.py)

`phone_account.py`는 **조회 전용** 후속 단계입니다. 아직 실거래 실행기나 PC 이전 완료판이 아닙니다. `build_phone_account_bundle.py`로 Q2X 고정 ZIP, 준비 스크립트, 이 화면, 사용자 설정 원본을 묶은 개인용 `OKX_PHONE_SETUP.py`를 생성합니다. 생성된 개인용 파일은 이 공개 저장소에 올리지 않습니다. API 키는 번들에 포함하지 않으며 브라우저로 폰에서 직접 입력합니다.

설치 파일을 폴드3 Download 폴더에 저장한 뒤 Termux에서 `termux-setup-storage` 실행 및 권한 허용 후 `python ~/storage/downloads/OKX_PHONE_SETUP.py`를 실행합니다. 코드가 화면에 나타나면 폴드3 Chrome으로 `http://127.0.0.1:8767`에 접속해 그 코드를 입력합니다. 접속 코드는 30분간 유효하며 로그인 화면의 세션은 2시간입니다. 다시 켜려면 `python ~/okx-phone/phone_account.py`를 사용합니다.

- 사용자 설정 원본은 재직렬화 없이 바이트 그대로 `~/okx-phone/strategy_config.json`에 보관합니다. 이미 다른 파일이 있으면 덮어쓰지 않습니다.
- API 정보는 Termux 내부 `~/okx-phone/phone_credentials.json`에 0600 권한으로 저장됩니다. 서버는 127.0.0.1만 바인딩합니다. 다른 폰/PC에서 직접 열 수 있는 주소가 아닙니다.
- 로그인 후 API 정보 저장과 계정 조회만 가능합니다. API 요청 계층과 HTTP 전송 계층에서 GET 경로 허용 목록을 강제합니다. 주문·취소·계정 설정 변경 경로 및 리디렉션을 차단합니다.
- Q2X RuleEngine/AccountStream/Telegram을 생성하거나 PC 기록을 가져오지 않습니다. 계정 모드가 다르면 표시만 하며 자동 수정하지 않습니다. 잔고/포지션/주문 수 조회는 거래 활성화나 PC 종료 허가가 아닙니다.
- 상태 기록 `account-check.json`에는 잔고·계정 ID·API 비밀정보·원문 오류를 넣지 않습니다. PC 실제 운용 상태와 기기 독점 운용은 이 단계에서 확인할 수 없습니다.
- 아직 미완료: 실제 기기의 계정 연결 결과, 폰 매매 실행부 및 보호주문/복구, 외부 모바일 접근, PC 전환, 화면 꺼짐·장시간 운영. 따라서 기존 PC 프로그램을 유지해야 합니다.

검사: 조회 화면 15개 테스트와 기존 준비 단계 19개, 총 34개 통과. 실제 Q2X 전송 클래스를 사용한 모의 계정 응답으로 GET 9회만 호출됨을 확인했습니다. 사용자 설정은 Q2X 검사에서 수정되지 않았고 개인 번들의 설치/재설치/변경 파일 거부를 확인했습니다. Linux x86_64 검사이며 실제 Android 개인 계정 조회 성공을 의미하지 않습니다.

근거: [Termux 공식 명령 안내](https://github.com/termux/termux-tools/blob/master/doc/termux.1.md.in), [공식 저장공간 연결 스크립트](https://github.com/termux/termux-tools/blob/master/scripts/termux-setup-storage.in).

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
# 폰 실행기 추가

계정 조회 이후의 실행기와 PC 전환 절차는 [PHONE_HOST_KO.md](PHONE_HOST_KO.md)를 확인하세요. 기본 조회 모드, 명시적인 최초 전환, 기존 폰 기록으로 재실행을 구분합니다. PC용 프로그램 업데이트가 아니며 실제 폴드3의 장시간/실거래 검증은 별도입니다.

