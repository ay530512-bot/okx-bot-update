# 1.2.3 — 진입 시각 오류, 반복 검증 비용, 수신 대기 처리 수정

2026-11-15 KST. 대상은 1.2.2 / host-v20, 새 실행기는 host-v21입니다.

## 확인한 오류와 수정

1. **검사 시작 시각으로 최신 호가를 검사하던 오류**
   원본 candidate는 전체 종목 검사 전에 now를 한 번 저장했습니다. 이후 MarketStream.read는 이 시각과 수신 호가의 ts를 비교하고 500ms보다 미래이면 거절합니다. 9초 지연을 주고 정상 최신 호가를 넣는 재현 검사에서 원본은 준비 신호를 남긴 채 최종 검사로 넘기지 않았습니다. 수정본은 전체 검사 뒤, 후보별 호가 확인 직전에 시각을 다시 읽어 같은 후보를 최종 검사로 넘깁니다. 500ms 허용치, 시세 신선도, 90초 만료, 최종 REST 재검사, 주문 허용 검사는 그대로입니다.

2. **변경 없는 확정봉의 반복 전체 검증**
   정확한 전체 15m/1H 입력과 확정봉 시간 구간을 키로 삼아 `검증 + 순수 패턴 선택`의 작은 결과만 재사용합니다. 큰 봉 배열을 캐시에 저장하거나 hit 때 깊은 복사하지 않습니다. 정수로 정렬된 봉 시각에서만 시간 구간 정규화가 적용됩니다. 과거봉 수정/거래량/시간봉 입력 변경/시간 구간 변경은 재검사하며, 오류는 캐시하지 않습니다. 양성 후보의 전체 자료, 시세, 유효시간 및 주문 직전 검사는 매번 수행합니다.

3. **공개 시세 수신과 구독**
   websocket-client 1.8.0의 TLS readiness timeout이 None으로 반환되어 연결 종료 예외로 바뀌는 경로를 재현했습니다. 폰에 설치된 라이브러리 버전 및 실제 끊김 원인은 미확인입니다. 공개 소켓 전용 수신 어댑터는 일시적인 TLS/read 대기를 timeout으로 돌려 수신을 계속하고, 실제 0바이트 EOF·종료 프레임은 기존 복구 절차로 보냅니다. 부분 수신 프레임 보존, 실제 EOF, 재구독을 검사했습니다. TLS 인증과 프레임 검증은 유지됩니다.
   구독/heartbeat 점검은 프레임마다 하지 않고 최대 0.25초 간격으로 수행합니다. 모든 시장 프레임은 그대로 처리하며 폐기/축약하지 않습니다. 신규 실행 채널을 먼저 구독하고 기존 채널 제거는 다음 허용 시점에 수행해 삭제 우선으로 인한 추가 10초 대기를 줄입니다. 구독 요청 간격 10초, 재접속 backoff, 시세/계좌 확인 후 진입 복구를 유지합니다.

4. **화면에서 상태 확인**
   활동·설정의 업데이트 카드 아래에 이번 실행 시간, 시세·계좌 상태, 끊김 누계/마지막 시각, 신호 검사 소요시간, 후보별 대기 채널·검사 당시 남은 시간, 탈락 사유를 표시합니다. 이 진단은 기존 자료만 읽고 추가 API 호출이나 주문을 하지 않습니다. 오래된 진단은 지연으로 표시합니다. 연결 상태와 체결 확인을 구분합니다.

## 검사

- Python 검사 60개: 실제 고정 Q2X 코드에 대한 81종목 fixture의 신호 비교/시간 경계/반복 입력/수정된 과거봉, 지연된 검사 후 최신 호가 통과, 오래된·미래·이전 연결 세대 호가 차단, 만료 신호 차단, 수신/복구 22개, 보유분 인계/트랜잭션 22개, 기존 눌림목 크기 규칙 5개, 진단 3개.
- 화면 진단 DOM 상태 검사 3가지. Chromium은 환경 소켓 제한으로 실행 불가하여 실제 브라우저 시각 검사는 미완료.
- 동일한 합성 289종목을 10회 반복: 전체 봉 검증 2890→10회, 준비 신호 1개로 동일. 이 환경의 평균 0.1145→0.0404초. **폰의 실측 속도나 수익 검사가 아닙니다.**
- 공개 WS 실접속도 시도했으나 이 실행 환경의 DNS 접근 실패로 시세 수신을 확인하지 못했습니다. `public_smoke.json`은 그 실패 기록이며 사용자 폰의 기록이 아닙니다.
- 실제 사용자 폰에 대한 접속 권한이 없으므로 장시간 연결 안정화 및 체결은 아직 확인하지 못했습니다. 재현 검사 통과를 무끊김 보장으로 표현하지 않습니다.

## 보존 범위

기존 OR 두꼬리, 눌림목 롱 크기 조절, 자금/손절/익절, 중복 방지, 최종 주문 검사를 보존합니다. 원본 core/config 파일은 덮어쓰지 않습니다. 설치기는 정확한 host-v20 해시를 검증하고 새 디렉터리를 만든 뒤 기존 직렬 안전 인계를 사용합니다. 보유분/보호 주문이 불확실하면 설치를 보류하거나 복구하며 강제 청산하지 않습니다.

## 재현

```
OKX_TEST_CORE=/path/to/pinned/core OKX_TEST_HOST=/path/to/host-v21 python android/phone_v123/test_candidate_fast.py
OKX_TEST_CORE=/path/to/pinned/core OKX_TEST_HOST=/path/to/host-v21 python android/phone_v123/test_entry_clock.py
PYTHONPATH=/path/to/host-v21:/path/to/websocket-client-1.8.0 python android/phone_v123/test_public_ws.py
PYTHONPATH=/path/to/host-v21:android/phone_v118 python -m unittest test_handover test_update_transaction
PYTHONPATH=/path/to/host-v21 python android/phone_v120/test_pullback_size.py
PYTHONPATH=/path/to/host-v21 python android/phone_v123/test_runtime_health.py
node android/phone_v123/test_health_ui.cjs
```

`benchmark_scan.py`는 같은 환경변수로 host-v20/host-v21을 각각 지정해 실행합니다. 원본 ZIP SHA256: `6b2a0a90f02cca914ffc5cc0996555e8c1435b7a61618575ee94ee2ebdc2dad1`.

참고한 1차 자료(확인일 2026-11-15):
- [OKX WebSocket 접속/heartbeat/구독 제한](https://www.okx.com/docs-v5/en/#overview-websocket)
- [websocket-client recv 원문](https://websocket-client.readthedocs.io/en/latest/_modules/websocket/_socket.html)
- 실제 재현에 사용한 websocket-client 1.8.0의 `_socket.recv`와 `_core.WebSocket` 소스. 설치된 사용자 폰의 버전으로 단정하지 않음.
