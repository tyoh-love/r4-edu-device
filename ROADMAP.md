# R4 Swarm — 개발 로드맵 (Phase / Wave / Task)

전체 설계 근거: [`docs/README.md`](./docs/README.md). 이 파일은 실행 분해.

## Phases (전체)

| Phase | 목표 | 상태 |
|---|---|---|
| **P1 — Who's-Stuck 그리드 e2e** | 시뮬레이터→브로커→백엔드→Vue 그리드. 하드웨어 없이 랩톱에서 동작 | **진행 중** |
| P2 — 오케스트레이션 명령 | push_activity · freeze/resume · 그룹 · feedback/hint 넛지 | 예정 |
| P3 — 형성평가 | answer 파이프라인 · 마스터리 뷰 · 활동 저작 | 예정 |
| P4 — 비문해 UX/피드백 루프 | 펌웨어 LED/소리 · 오디오/아이콘 콘텐츠 | 예정 |
| P5 — 실제 R4 펌웨어 | 시뮬레이터 → 실보드 · 프로비저닝 · NTP · MQTT5 will-delay · ACL | 예정 |
| P6 — 보안/PIPA | RBAC · 접속기록 · 보관/파기 · 아동↔좌석 분리 저장소 | 예정 |

---

## Phase 1 — Waves & Tasks

### Wave 0 — 계약 & 스캐폴드 (선행, 나머지를 블록)
- **T0.1** 레포 구조 + 툴링(uv / vite)
- **T0.2** MQTT/WS 계약 모듈 — 토픽·페이로드·state enum (단일 진실 소스) → `server/contract.py`, `docs/API.md`

### Wave 1 — 병렬 빌드 (계약에 맞춰 3트랙)
- **Track A · 백엔드** (`server/`)
  - T1.1 aiomqtt 인제스트 루프
  - T1.2 디바이스 스토어 + **stuck 자동 파생**(idle_ms 임계 + 무응답 타이머) + offline(LWT)
  - T1.3 마스터리 집계(answer → rate)
  - T1.4 FastAPI REST 스냅샷 + **WebSocket 푸시** + `/api/cmd`(MQTT publish)
- **Track B · 시뮬레이터** (`sim/`)
  - T1.5 N대 보드 시뮬레이터 — 현실적 상태 전이(working→stuck→help→done) + answer
- **Track C · 프론트** (`frontend/`)
  - T1.6 Vue3 그리드(색 타일 · help/stuck 강조 · 정렬)
  - T1.7 WS 클라이언트 · 마스터리 바 · 상세 패널 · 명령 버튼
- **Track D · 인프라** (`infra/`)
  - T1.8 docker-compose Mosquitto(운영) + amqtt dev 브로커(무의존 dev) + ACL/passwd 예시

### Wave 2 — 통합 & 검증 (선행 순차)
- **T2.1** dev 러너: 한 명령으로 broker+backend+sim 기동 (`run_dev.py`)
- **T2.2** e2e 실행 검증: WS가 올바른 state 방출 · stuck 파생 · help 최우선
- **T2.3** 프론트 빌드 + Playwright 스크린샷 검증
- **T2.4** README 퀵스타트

---

## Phase 1 완료 기준 (DoD)
- `uv run python run_dev.py` 한 줄로 broker+backend+sim 기동.
- 대시보드(`/`)에서 N개 타일이 실시간 색 변화, help=빨강 최우선, stuck=황색 자동 판정.
- 하단 정답률(마스터리) 실시간 갱신.
- 타일 클릭 → 상세 + 개별 명령(MQTT publish 왕복).
- Playwright 스크린샷으로 렌더 확인.
