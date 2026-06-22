# KTX/SRT Sniper

취소표가 풀렸을 때 자동으로 **예약만** 잡는 KTX/SRT 스나이퍼입니다. 결제는 자동화하지 않습니다. 예약 성공 알림의 구입기한 전에 코레일 또는 SRT 앱/웹에서 직접 결제하세요.

## 준비

```bash
python3.11 -m pip install korail2-ncard pycryptodome
python3.11 -m pip install SRTrain
cd /Users/jenny/Desktop/gai/ktx-sniper
cp config.example.json config.json
```

`config.json`에서 날짜, 출발/도착, 감시할 열차번호를 수정합니다.

코레일 계정은 환경변수로 넣는 것을 권장합니다.

```bash
export KSKILL_KTX_ID='코레일아이디'
export KSKILL_KTX_PASSWORD='코레일비밀번호'
export KSKILL_SRT_ID='SRT아이디'
export KSKILL_SRT_PASSWORD='SRT비밀번호'
```

텔레그램 알림이 필요하면 아래 환경변수를 넣거나 `config.json`의 `telegram`에 채웁니다.

```bash
export KTX_SNIPER_TELEGRAM_TOKEN='bot-token'
export KTX_SNIPER_TELEGRAM_CHAT_ID='chat-id'
```

## 로컬 UI 실행

터미널 없이 쓰려면 로컬 웹앱을 실행하세요.

```bash
cd /Users/jenny/Desktop/gai/ktx-sniper
python3.11 app.py
```

브라우저에서 엽니다.

```text
http://127.0.0.1:8765
```

UI에서 할 수 있는 일:

- KTX/SRT 탭 전환
- 코레일 계정 저장 및 로그인 테스트
- SRT 계정 저장 및 로그인 테스트
- 날짜/시간/구간으로 열차 조회
- 조회 결과에서 감시할 열차 선택
- 일반실/특실 우선순위 설정
- 조회 간격 최소/최대값 조절
- 스나이핑 시작/중지/삭제
- 텔레그램 봇 토큰/Chat ID 저장 및 테스트
- Mac 잠자기 방지 토글 (`caffeinate` 사용)

계정과 텔레그램 정보는 `settings.local.json`에 저장되며 파일 권한은 `0600`으로 제한됩니다. 공용 컴퓨터에서는 사용 후 삭제하세요.

## CLI 실행

한 번만 조회:

```bash
python3.11 ktx_sniper.py --config config.json --once
```

계속 감시:

```bash
python3.11 ktx_sniper.py --config config.json
```

백그라운드 실행:

```bash
nohup python3.11 ktx_sniper.py --config config.json > ktx-sniper.log 2>&1 &
```

중지:

```bash
pkill -f '/Users/jenny/Desktop/gai/ktx-sniper/ktx_sniper.py'
```

## 설정 팁

- `seat_option`
  - `general-first`: 일반실 우선, 없으면 특실
  - `special-first`: 특실 우선, 없으면 일반실
  - `general-only`: 일반실만
  - `special-only`: 특실만
- `train_type`
  - 보통 KTX/KTX-산천만 볼 때는 `ktx`
  - ITX/무궁화까지 포함하려면 `all`
- `interval_min`, `interval_max`
  - 너무 촘촘한 조회는 피하세요. 기본값은 25~40초 랜덤입니다.
