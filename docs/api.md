# API

표준 라이브러리 `http.server` 기반. 모든 요청/응답은 JSON (UTF-8).  
`ui_password` 설정 시 로그인 엔드포인트 제외 전체 인증 필요.

## 인증

- **방식**: 쿠키 기반 세션 (`ktx_session`)
- **로그인**: `POST /api/login` → `Set-Cookie: ktx_session=<token>`
- **미인증 GET**: 302 → `/login` 리다이렉트
- **미인증 POST**: 401 JSON 응답

## GET 엔드포인트

| 경로 | 설명 |
|------|------|
| `GET /` | 메인 UI (`static/index.html`) |
| `GET /login` | 로그인 페이지 (`static/login.html`) |
| `GET /api/state` | 전체 상태 (설정, 잠자기 방지 여부, 작업 목록) |
| `GET /api/profiles?service=ktx\|srt` | `config.json`에서 계정 프로필 목록 (비밀번호 제외) |

### `GET /api/state` 응답
```json
{
  "ok": true,
  "settings": {
    "accounts": { "ktx": { "id": "...", "has_password": true }, "srt": { ... } },
    "telegram": { "has_token": true, "chat_id": "..." },
    "sleep": { "prevent": false }
  },
  "sleep_prevented": false,
  "jobs": [ /* Job 객체 배열 */ ]
}
```

### `GET /api/profiles?service=ktx` 응답
```json
{
  "ok": true,
  "profiles": [
    { "name": "쟁", "id": "1666563106", "has_password": true }
  ]
}
```

## POST 엔드포인트

| 경로 | 설명 |
|------|------|
| `POST /api/login` | 비밀번호 인증, 세션 쿠키 발급 |
| `POST /api/profiles/apply` | 프로필을 활성 계정으로 적용 |
| `POST /api/account` | 계정 ID/비밀번호 수동 저장 |
| `POST /api/account/test` | 저장된 계정으로 로그인 테스트 |
| `POST /api/telegram` | 텔레그램 토큰/chat_id 저장 |
| `POST /api/telegram/test` | 텔레그램 테스트 메시지 전송 |
| `POST /api/sleep` | 잠자기 방지 on/off (`caffeinate`) |
| `POST /api/search` | 열차 조회 |
| `POST /api/jobs` | 스나이핑 작업 생성 |
| `POST /api/jobs/:id/start` | 작업 시작 |
| `POST /api/jobs/:id/stop` | 작업 중지 |
| `POST /api/jobs/:id/delete` | 작업 삭제 |

### `POST /api/login`
```json
// 요청
{ "password": "..." }
// 응답 (성공)
{ "ok": true }  // + Set-Cookie 헤더
```

### `POST /api/profiles/apply`
```json
// 요청
{ "service": "ktx", "name": "쟁" }
// 응답
{ "ok": true, "settings": { ... } }
```

### `POST /api/search`
```json
// 요청
{
  "service": "ktx",
  "dep": "대전", "arr": "서울",
  "date": "2026-06-20", "time": "09:00",
  "train_type": "ktx",
  "adults": 1,
  "include_waiting": false
}
```

### `POST /api/jobs`
```json
// 요청
{
  "service": "ktx",
  "name": "대전→서울 오전",
  "dep": "대전", "arr": "서울",
  "date": "2026-06-20", "time": "09:00",
  "train_numbers": ["012", "014"],
  "train_type": "ktx",
  "seat_option": "special-first",
  "interval_min": 25, "interval_max": 40,
  "adults": 1, "children": 0, "seniors": 0, "toddlers": 0,
  "include_waiting": false
}
```
