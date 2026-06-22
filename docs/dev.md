# 개발 환경 및 실행

## 요구사항

- Python 3.11
- macOS (잠자기 방지 기능이 `caffeinate` 의존)

## 설치

```bash
python3.11 -m pip install korail2-ncard pycryptodome SRTrain
```

## 설정 파일

### `config.json` (직접 편집)
```json
{
  "ui_password": "접속비밀번호",
  "ktx_profiles": [
    { "name": "표시이름", "id": "코레일아이디", "password": "비번" }
  ],
  "srt_profiles": [
    { "name": "표시이름", "id": "SRT아이디", "password": "비번" }
  ]
}
```
`config.example.json` 참고.

### `settings.local.json` (앱이 자동 관리)
- 활성 계정, 텔레그램 설정, 잠자기 방지 상태 저장
- 파일 권한 600 (owner read/write only) 자동 설정

## 로컬 실행

```bash
cd /Users/jenny/Desktop/gai/ktx-sniper
python3.11 app.py
# → http://127.0.0.1:8765
```

## 외부 접근 (ngrok)

```bash
# 최초 1회
ngrok config add-authtoken <토큰>  # dashboard.ngrok.com에서 발급

# 매번 실행
ngrok http 8765
# → https://xxxx.ngrok-free.app 로 외부 접근 가능
```

무료 플랜은 ngrok 재시작마다 URL이 바뀜.

## 환경 변수 (선택)

| 변수 | 설명 |
|------|------|
| `KTX_SNIPER_PASSWORD` | UI 비밀번호 (config.json의 `ui_password` 대체) |
| `KSKILL_KTX_ID` | 코레일 아이디 |
| `KSKILL_KTX_PASSWORD` | 코레일 비밀번호 |
| `KSKILL_SRT_ID` | SRT 아이디 |
| `KSKILL_SRT_PASSWORD` | SRT 비밀번호 |
| `KTX_SNIPER_TELEGRAM_TOKEN` | 텔레그램 봇 토큰 |
| `KTX_SNIPER_TELEGRAM_CHAT_ID` | 텔레그램 chat ID |

## 잠자기 방지

앱 UI의 "Mac 전원" 패널에서 토글 → 내부적으로 `caffeinate -dimsu` 프로세스 실행.  
Mac Studio는 뚜껑 닫힘 문제 없음.
