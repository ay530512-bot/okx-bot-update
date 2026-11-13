# 폰 급등·급락 알림 v2: 확정 15분봉 ±10%

2026-11-14 KST 사용자 요청으로 기존 약 5분 ±3% 기준을 교체합니다.

- OKX 거래 중인 암호화폐 선형 USDT 무기한 전체(BTC/ETH/SOL 포함). 비암호화폐 분류, 주식 연동 그룹, 기존 stock_linked_symbols 제외.
- OKX 실제 15분봉의 `(종가 / 시가 - 1) × 100`이 +10% 이상 또는 −10% 이하일 때 알림. 거래소 confirm=1이고 해당 봉이 실제 마감된 경우만 사용합니다.
- 고가/저가 범위, 진행 중인 봉, 레버리지 ROE, 최근 15분의 이동 구간 수익률은 기준이 아닙니다.
- 동일 종목·동일 봉은 한 번만 전송 시도합니다. 다음 15분봉도 ±10%이면 별도 알림 대상입니다. 재시작 뒤에도 중복 방지 기록을 유지합니다.
- 메시지에 종목, 방향, 시가·종가, 변동률, 봉 시작·종료 KST가 표시됩니다.

## 조회 및 전달

최근 완료된 봉을 종목마다 순차 확인합니다. 공개 candles 요청 간 최소 0.5초를 두며, 종목 목록은 시작 시와 1시간마다 조회합니다. 처음 설치할 때도 가장 최근에 마감된 15분봉부터 확인합니다. 15분봉 하나당 종목별 정상 조회 1회, 미확인/일반 오류 시 제한된 추가 재시도가 있습니다.

종목 수·통신 상태에 따라 봉 마감 후 수 분 지연될 수 있습니다. 장애로 다음 봉까지 넘어가면 지난 봉은 소급 알림하지 않으므로 일부 감지가 누락될 수 있습니다. 시세 호출은 기존 봇 호출에 추가되며, 기존 공개 WS 연결 장애를 고치는 기능은 아닙니다.

Telegram은 최대 1분에 한 묶음(20종)을 보내며, 초과분은 다음 묶음으로 보냅니다. 거래소 제한 오류는 지수 대기, Telegram 제한 오류는 retry_after를 적용합니다. 전송 성공 여부를 알 수 없는 네트워크 오류는 중복 방지를 우선하여 같은 알림을 재전송하지 않습니다.

## 설치와 교체

검토한 커밋의 android/phone_move_alerts.py를 내려받아 `python 파일명 --install`을 실행합니다. 이전 추가판이 실행 중이면 **급변 알림 프로세스만** 정상 종료를 기다린 뒤 교체합니다. 종료를 확인하지 못하면 강제 종료하지 않고 설치를 중단합니다. 기존 매매 실행기·계좌/주문/SL·전략 설정은 수정하거나 재시작하지 않습니다.

기존 `~/okx-phone/phone_notifications.json`의 토큰과 대화 ID를 읽어 사용합니다. API 키를 사용하지 않고 매매 모듈도 가져오지 않습니다.

설치 경로는 호환성을 위해 `~/okx-phone/move-alerts-v1/`를 유지합니다. 버전은 `phone-move-alerts-2-15m-10pct`이며 새 기록은 `candle_state.json`입니다. 기존 v1 state.json은 그대로 남습니다. 자동 시작 파일은 `~/.termux/boot/95-okx-move-alerts`입니다. Termux:Boot 설치 후 한 번 열기와 백그라운드 실행 허용이 필요합니다.

시작 알림: `[15분봉 ±10% 알림 연결]`. 설치 완료 메시지만으로 실제 Telegram 수신을 확인한 것은 아닙니다.

상태:

```sh
python ~/okx-phone/move-alerts-v1/phone_move_alerts.py --status
```

알림만 중지:

```sh
python ~/okx-phone/move-alerts-v1/phone_move_alerts.py --stop
```

재개는 설치 파일의 `--install`을 다시 실행합니다. 안드로이드가 Termux를 종료하면 감시가 중단될 수 있으며 실제 폰 장시간 가동은 별도 확인이 필요합니다.

## 검사 및 자료

`python -m unittest -v test_phone_move_alerts.py`로 17개 검사 통과. 양방향 10% 경계, 확정봉/시가종가 계산, 꼬리 제외, 이전·미완성·미래 봉 제외, 재시작 중복 방지, 다음 봉 재알림, API 경로 제한, 기존 파일 보존, 이전 알림 교체, 모의 시간 기반 실행기 통합 검사 등을 포함합니다. 실제 폰 설치·OKX 실시간 수신·Telegram 실전송은 확인하지 못했습니다.

공식 자료 확인: 2026-11-14 KST.
- https://www.okx.com/docs-v5/en/#order-book-trading-market-data-get-candlesticks
- https://core.telegram.org/bots/api#sendmessage
- https://core.telegram.org/bots/api#responseparameters
