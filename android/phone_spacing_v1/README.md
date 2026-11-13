# 화면 여백 v1 · host-v9

최근 활동과 업데이트 영역 사이에 32 CSS px 여백을 추가합니다. 모바일 업데이트 v1(host-v8)에서 버튼으로 설치합니다. 변경 확인 문구는 화면 여백 v1입니다.

원본 매매 코어, 진입/청산/SL/자금/계정 설정 및 공개 시세 복구 코드는 변경하지 않습니다. 설치에는 기존과 동일한 중지·보유/주문 0 검사, 정상 종료, 실패 시 복원 절차가 적용됩니다. 자동 매매 재개는 하지 않습니다.

PYTHONPATH=android/phone_spacing_v1 python -m unittest discover -s android/phone_spacing_v1 -p test_button_upgrade.py -v

고정 코어를 OKX_TEST_CORE로 지정하여 test_phone_mobile_integration.py를 실행할 수 있습니다. 빌더 build_phone_button.py는 결정적으로 phone_spacing_setup.py를 생성합니다. 실제 폴드 적용 확인은 사용자의 업데이트 버튼 설치 후 필요합니다.
