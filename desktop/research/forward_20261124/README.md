# 2026년 11월 23일 한국시간 마감 연구 장부

이 폴더는 OKX 공개 시장자료로 재현한 모의 장부다. 날짜는 11월 23일 00시 이상, 24일 00시 미만이다. 계좌별 최초 독립일의 시작 순자산은 150 USDT다. 다음 날짜는 각 계좌의 실제 모의 마감액과 남은 보유분을 승계한다. 일별 +5%와 +10%를 모두 포함해 평가한다. 미검증 잔액은 해소될 때까지 다음 날에도 미검증으로 이어간다.

## 어떤 날짜를 검증한 것인가

- 11월 22일까지 확정된 두 꼬리·EMA20 반응·거래량 스캘핑 조건과 11월 22일에 동결한 비용·시간·청산 조합에는 11월 23일이 첫 온전한 사후 관측일이다. 비용은 수수료와 슬리피지 각각 편도 5bp, 기본 스트레스는 편도 슬리피지 10bp다. 개별 체결 손익에 계약승수와 실제 펀딩을 적용했다.
- 11월 23일에 사전등록한 종목별 속도·고정 ±1%·기존 청산·추세 방향 비교에서 첫 독립일은 11월 24일이다. 이번 파일의 해당 관측은 설명용으로만 분류한다. 연구 통과에는 각 단독 계좌와 공유 계좌에서 60일 연속 목표를 충족하는 등 사전등록한 모든 요건을 적용한다.
- 11월 23일자 공개 패키지 PC 3.3.1의 마감봉 후보는 당시 배포 파일의 함수로 별도 재생했다. 이 분기의 자료에는 완성된 봉을 받는 지연, 계좌 대사, 당시 호가 잔량 및 사용자 PC의 설치 시각이 없다. 개인 실거래, PC 2.15 모의 관찰과 PC 2.5.0의 과거 장부는 각각 별도다. 13개 폐기 시간표는 연구 실행에서 제외했다.
- 연구 기준 계좌에는 3 USDT 유보, 3자리, 3~5배, 건당 위험 0.5%와 전체 위험 2%를 사용한다. PC 3.3.1 패키지에 들어 있는 5배·8자리 정책은 별도 비교 대상이다. 수량 증가를 타점 개선으로 세지 않는다.

## 자료 및 재현

`run.json`에 날짜별 관측 범위, 최신 배포의 커밋·SHA-256, 확인된 장부 및 미검증 항목을 기록했다. `market.json`, `execution.json`, `evidence.json`에는 분할 ZIP의 순서와 SHA-256이 들어 있다. `restore.py`는 해시를 확인하고 원래 파일명으로 복원한다. `research-source.zip`은 이번 날짜의 실행 코드다.

저장소의 루트에서 아래처럼 격리된 디렉터리를 준비한다. 입력된 날짜는 코드 안의 세션 날짜와 일치해야 한다. 이후 날짜는 같은 계좌의 마감 상태를 승계하는 별도 실행으로 기록한다.

```bash
mkdir -p /tmp/okx-forward-20261124
git worktree add --detach /tmp/okx-forward-20261124/repo 5db7882cbb75ab5560732026e8470cfd990b1831
snapshot="$PWD/desktop/research/forward_20261124"
cd /tmp/okx-forward-20261124
cp -r repo/desktop/research/forward_20261123 study
unzip -q "$snapshot/research-source.zip"
python "$snapshot/restore.py" "$snapshot" .
mkdir -p arrays day/result day/paths day/ticks day/pc290 day/diagnostics frozen latest pc290ref lib
unzip -q repo/desktop/releases/okx_pc_r21600.zip -d frozen
unzip -q repo/desktop/releases/okx_pc_r30301.zip -d latest
unzip -q repo/desktop/releases/okx_pc_r20900.zip -d pc290ref
python prepare.py
python study/check.py day/cache
bash run_day.sh
python evidence.py
python wick_day.py
python wick_compare.py
python wick_accounts.py
python timing_alternatives.py
python paired_timing_ledger.py
python exact_markouts.py
python current_observe.py
python intrabar_range.py
python check_inputs.py
python fill_development.py
```

모의 체결에는 시간순 체결 ID를 사용하고 조회한 분의 시고저종과 체결수량 합계를 공식 원본 1분봉과 대조한다. 보호선에 닿지 않을 것이 모든 체결 순서에서 확실한 완료 분만 건너뛴다. 5·15·30분 방향 변화는 관측치다. 기본 스캘핑, 추세 눌림과 반전 규칙은 각각 사전등록한 보유시간을 적용한다. 15분봉 PC 2.9 비교는 별도로 당일 23:59 청산을 적용한다. 연구상의 손익은 실제 사용자의 체결을 의미하지 않는다.

## 시점과 비교 범위

11월 23일 23:43:45 KST에 게시된 PC 3.3.1은 이날 종료 시점에 확인 가능한 버전이다. 연구 중인 11월 24일 00:44:48 KST에 별도로 게시된 PC 3.3.3도 고정 커밋과 ZIP 해시를 확인했다. 두 배포 사이의 파일 변경 목록은 `release_observations.json`에 있다. 11월 23일 모형에는 장중 배포·개인 설정·거래소 호가의 전체 변경 이력을 대입할 수 없어 실제 주문 수를 확정할 수 없다.

`next_protocol.json`은 11월 25일 이후의 새 실험이다. 지정 시간의 첫 재시험 신호가 나올 때, 직전 15초 중 두 개 이상의 5초 구간에서 같은 방향 체결대금 비율과 해당 종목의 체결 빈도가 함께 상승했는지 확인한다. 매일 전액을 이월하고 미체결일을 포함한다. `development_check.json`은 이미 조사한 11월 22일에 동일 체결 사건을 대조한 자료다. 과거에 확인한 기회 집합 안에서만 비교하므로 새 규칙의 전체 체결 빈도를 추정하는 데 사용하지 않는다. 다음 구간의 정상·빠른 흐름 비교에서는 실제 5분봉 고저폭을 사용한 속도와 이전에 고정한 진폭(true range) 기준을 별도 보관한다.

다음 날짜를 재생할 때 `OKX_KST_DAY`, `OKX_PRIOR_CACHE`, `OKX_PREVIOUS_ACCOUNT_STATE`로 대상 날짜·직전 일자의 원본 봉·동일 실험의 직전 계좌 상태를 지정한다. 전일 입력이나 이월 보유분의 정리가 필요한 경우 해당 계좌 결과는 미검증 처리한다. 관련 날짜를 먼저 보완하고 이어서 재생한다.

신호별 5·15·30분 가격 변화는 `day/exact_markouts.json`의 각 시각까지 마지막 공개 체결로 확인한다. 거래가 드문 구간은 마지막 체결의 시각과 ID도 함께 기록한다. 체결 경로에 든 `markouts_pct`는 직전 완료 1분봉 종가를 사용한 근삿값이다.
