# 아키텍처

## 개요

KTX/SRT 취소표를 자동으로 감지해 예약하는 로컬 스나이퍼 도구.  
결제는 자동화하지 않으며, 예약 성공 시 텔레그램으로 알림 → 사용자가 앱에서 직접 결제.

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| 백엔드 | Python 3.11, 표준 라이브러리 (`http.server`, `threading`) |
| KTX 연동 | `korail2-ncard` 라이브러리 |
| SRT 연동 | `SRTrain` 라이브러리 |
| 프론트엔드 | Vanilla JS, HTML, CSS (프레임워크 없음) |
| 알림 | Telegram Bot API |
| 터널링 | ngrok (외부 접근용) |

## 파일 구성

```
ktx-sniper/
├── app.py               # HTTP 서버 + API 라우터 + 스나이핑 워커
├── ktx_sniper.py        # CLI 모드 (웹 UI 없이 직접 실행)
├── config.json          # 사용자 설정 (계정 프로필, UI 비밀번호, 잡 목록)
├── config.example.json  # 설정 예시 템플릿
├── settings.local.json  # 런타임 저장 설정 (활성 계정, 텔레그램 등)
└── static/
    ├── index.html       # 메인 UI
    ├── login.html       # 비밀번호 게이트 페이지
    ├── app.js           # 프론트엔드 로직
    └── styles.css       # 스타일
```

## 주요 구조

### 상태 관리
- `AppState` 클래스가 싱글톤으로 전체 상태 보유
- `SettingsStore`: `settings.local.json` 읽기/쓰기 (락 보호)
- `jobs: dict[str, Job]`: 실행 중인 스나이핑 작업 (in-memory)

### 스나이핑 워커
- 작업당 별도 스레드 (`threading.Thread`)
- `stop_event`로 외부 중지 신호 전달
- 조회 간격: `interval_min`~`interval_max` 사이 랜덤 (초)
- 예약 성공 시 스레드 자동 종료

### 인증 (웹 UI)
- `config.json`의 `ui_password` 또는 환경변수 `KTX_SNIPER_PASSWORD`
- 로그인 성공 시 `ktx_session` 쿠키 발급 (서버 메모리에 토큰 보관)
- 서버 재시작 시 세션 초기화

### 계정 프로필
- `config.json`의 `ktx_profiles` / `srt_profiles` 배열에 여러 계정 사전 정의
- 웹 UI에서 드롭다운으로 선택 → `settings.local.json`에 적용
- 스나이핑 시작 시 계정 ID로 프로필 이름 역매핑 → 텔레그램 알림에 포함
