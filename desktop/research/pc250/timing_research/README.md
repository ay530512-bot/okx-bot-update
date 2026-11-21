# OKX PC 2.5.0 공개 데이터 재검증

같은 디렉터리에 배포 ZIP에서 추출한 `OKX_PC_PACKAGE`와 이 연구 폴더를 놓고 실행합니다. Python, NumPy, pandas가 필요합니다. PC 매매 실행기는 이 연구용 패키지를 사용하지 않습니다. 기간은 한국시간이며 종료일 00시는 제외합니다.

```bash
python timing_research/fetch_public.py --start 2026-09-22 --end 2026-11-21
python timing_research/replay.py --start 2026-09-22 --end 2026-11-21 --out timing_cache/opportunities.pkl
python timing_research/forward_proxy.py --data timing_cache/opportunities.pkl --start 2026-09-22 --end 2026-11-21 --out timing_cache/forward.json
python timing_research/test_release.py
```

`replay.py`의 기초 자료는 OKX의 31종목 1분봉과 정산 펀딩 이력입니다. 15분봉과 1시간봉은 완료된 1분봉을 합쳐 만듭니다. 수수료와 예상 슬리피지는 기본 편도 각각 0.05%입니다. 누락 시각, 종목 수, 체결 수를 확인한 뒤 비교합니다. 과거 호가 잔량과 마크가격 경로에는 차이가 있을 수 있습니다. 실시간 관찰은 실제 관찰 시점의 호가, 거래 봉, 마크가격 봉과 정산 펀딩을 사용합니다. 모의 수익에는 실거래 체결 보장이 없습니다.

`select_rules.py freeze`는 개발 두 구간에서 비용 차감 손익이 모두 양수인 후보 중 규칙별 하나를 고른 뒤 다음 검증 구간을 한 번 사용합니다. `test`는 고정한 선택을 이후 구간에서 평가합니다. `forward_proxy.py`는 설치 직후와 같이 빈 장부에서 시작해 모의거래 결과를 알 수 있는 시점 이후에만 자격을 부여합니다. 공개 과거봉에서는 진입 당시 실제 호가·수신 지연을 재현할 수 없어 근사값을 냅니다. `--report-from`은 앞부분을 모의 관찰로 쓰고 이후의 계좌 성과만 집계합니다. 재검증 날짜에 맞춰 시작일·종료일 인수를 변경할 수 있습니다.

`validation.json`은 2.5.0 배포 당시 고정한 검증 결과입니다. 이후 날짜는 별도 구간으로 기록합니다.
