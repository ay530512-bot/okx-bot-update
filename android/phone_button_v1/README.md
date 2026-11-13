# 폰 모바일 업데이트 v1 (host-v8)

host-v7 공개 시세 복구 v1 사용자를 위한 일회성 전환입니다. Q2X 원본 파일, 진입/청산 규칙, SL, API 키, 텔레그램 설정을 변경하지 않습니다.

## 사용

1. 모바일 화면에서 신규 진입 중지. 보유/미체결/조건주문이 0일 때 설치합니다. 설치기는 자동 청산/취소하지 않습니다.
2. `android/phone_button_setup.py`를 고정 커밋에서 받아 Termux/Termius에서 한 번 실행합니다.
3. 화면 새로고침 후 `모바일 업데이트 v1` 확인. 실거래 시작은 사용자가 직접 확인합니다.
4. 이후 활동·설정 → **폰 새 버전 확인** → 변경 내용 확인 → **확인한 새 버전 설치**.

확인은 운용 중 가능하며 설치는 중지·계정 상태 검증 후만 가능합니다. 업데이트 중 원격 연결이 잠시 끊깁니다. 신규 진입은 자동 재개하지 않습니다. 실행기 교체는 정상 종료만 사용합니다. 새 실행기 준비 실패 시 기존 실행기 복원을 시도하며, 종료 확인 실패 시 중복 실행하지 않습니다.

## 배포 채널

`main/android/phone_latest.json`은 PC 업데이트와 별도입니다. format은 `okx-phone-release-1`, version은 증가하는 정수, from_versions는 지원하는 출발 버전 배열입니다. commit은 설치기 파일이 있는 40자리 고정 커밋, installer는 android 하위 Python 경로, sha256/bytes는 해당 파일 원본 기준, notes는 한국어 변경 내용입니다. 리다이렉트/다운그레이드/호환되지 않는 출발 버전/파일 불일치는 거부합니다.

향후 배포 절차: 다음 host 버전을 별도 경로에 준비하고 현재 host 파일 핀·서비스 버전·부팅 마커를 갱신합니다. 기존 계정 검증/중지/복원 트랜잭션을 유지하고 테스트합니다. `phone_update.CURRENT`와 빌더 대상 경로도 올립니다. 소스+설치기 커밋을 먼저 게시한 뒤 그 커밋/해시/크기를 가리키는 manifest를 별도 커밋으로 게시합니다. PC ZIP 또는 연구 ZIP을 이 채널로 배포하지 않습니다. 현재 릴리스는 host 어댑터 전용이며 코어 변경은 별도 검증된 마이그레이션이 필요합니다.

TLS로 접근한 사용자 GitHub 저장소를 배포 신뢰 기준으로 사용합니다. SHA256은 파일 일치 검증이며 독립 전자서명은 아닙니다. 앱 인증·Origin 검사를 그대로 사용하고, 설치 확인은 세션 소유자에 묶여 10분 만료/1회 사용입니다. 자동 정기 다운로드나 매매 API 호출은 버전 확인에 포함되지 않습니다.

## 재현 검사

```
PYTHONPATH=android/phone_button_v1 python -m unittest discover -s android/phone_button_v1 -p test_phone_update.py -v
PYTHONPATH=android/phone_button_v1 python -m unittest discover -s android/phone_button_v1 -p test_button_upgrade.py -v
OKX_TEST_CORE=/path/to/verified/runtime-q2x PYTHONPATH=android/phone_button_v1 python -m unittest discover -s android/phone_button_v1 -p test_phone_mobile_integration.py -v
python android/phone_button_v1/build_phone_button.py
```

설치기 빌드는 재현 가능합니다. 실제 Android 재시작·실거래 주문 검증은 로컬 모의검사에 포함되지 않습니다. 설치 전에는 폰에 적용되지 않습니다. `phone_update_result.json` 및 `phone-update-cache/last-install.log`가 설치 상태 기록입니다. 이 파일들은 개인 폰에만 저장하며 GitHub에 올리지 않습니다.
