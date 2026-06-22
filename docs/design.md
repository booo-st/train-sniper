# 디자인

## 컨셉

"Korean rail local console" — 철도 느낌의 클래식한 serif 타이포그래피 + 격자 배경.  
모바일에서도 읽기 쉽게 반응형 레이아웃.

## 색상

| 변수 | 값 | 용도 |
|------|----|------|
| `--ink` | `#171713` | 기본 텍스트 |
| `--paper` | `#f5f1e6` | 배경 |
| `--panel` | `#fffaf0` | 카드/패널 배경 |
| `--line` | `#25251f` | 테두리 |
| `--rail` | `#0d5c63` | 주요 액션 (버튼, 링크) |
| `--signal` | `#d94b2b` | 경고, eyebrow 레이블 |
| `--green` | `#1f7a4d` | 성공 상태 |

## 타이포그래피

- 폰트: `ui-serif, Georgia, "Apple SD Gothic Neo", "Noto Serif KR", serif`
- `h1`: `clamp(42px, 7vw, 92px)` — 헤더 큰 제목
- `.eyebrow`: 13px, 대문자, letter-spacing, signal 색상

## 레이아웃

- 메인: CSS Grid (`grid-template-columns: repeat(3, 1fr)`) — 1050px 이하에서 1열로 전환
- 패널: 테두리 2px solid + `box-shadow: 0 14px 0 rgba(...)` (뒤로 밀린 느낌)

## 컴포넌트

### 로그인 페이지 (`login.html`)
- 화면 중앙 단일 카드
- 비밀번호 입력 + "입장" 버튼
- 오류 메시지 인라인 표시

### 계정 패널
- 프로필 드롭다운 + "적용" 버튼 (config.json에 프로필이 있을 때만 표시)
- 구분선 아래 수동 ID/비밀번호 입력 폼

### 상태 표시
- `.status-pill.ok` (초록) / `.status-pill.warn` (주황)
- 헤더 우측 상단: 계정 상태 / 텔레그램 상태

### 작업 카드
- 실행 중: ok 상태 pill
- 완료: `job-card success` 클래스
- 로그 박스: 최근 20줄 표시
