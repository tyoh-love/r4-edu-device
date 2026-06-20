# R4 Swarm — 개발 로드맵 (Phase / Wave / Task)

전체 설계 근거: [`docs/README.md`](./docs/README.md). 이 파일은 실행 분해 + 진행 현황.

## Phases (10단계)

| Phase | 목표 | 상태 |
|---|---|---|
| **P1 — Who's-Stuck 그리드 e2e** | 시뮬레이터→브로커→백엔드→Vue 그리드 | ✅ 완료 (main 머지) |
| **P2 — 오케스트레이션** | 그룹 추상 · push_activity · freeze/resume · 페이싱 · 그룹 뷰 | 진행 |
| **P3 — 형성평가** | activity/question 모델 · 문항별 마스터리 · group mastery · 마스터리 뷰 | 예정 |
| **P4 — 비문해 UX/피드백 루프** | 즉시 피드백(빛/소리) · 아이콘/오디오 콘텐츠 모델 · 교사 넛지 효과 | 예정 |
| **P5 — 실제 R4 펌웨어** | Arduino 스케치(WiFiS3+ArduinoMqttClient) · 계약 구현 · 빌드 노트 | 예정 (병렬) |
| **P6 — 보안/PIPA** | per-device 인증+ACL · 대시보드/API RBAC · 접속기록 · 아동↔좌석 분리 | 예정 |
| **P7 — 콘텐츠 저작** | 활동/퀴즈 저작 API · 콘텐츠 스키마/저장 · 저작 UI | 예정 |
| **P8 — 영속화/리포트** | DB(세션/답안) · 교사·부모 리포트 · CSV export | 예정 |
| **P9 — 멀티클래스/레지스트리** | 반/교실 · 디바이스 등록(enrollment) · 세션 라이프사이클 | 예정 |
| **P10 — 패키징/배포** | 풀스택 docker-compose · 원커맨드 배포 · 운영 런북 | 예정 |

각 Phase는 **구현 → 검증(가능 시 e2e) → 커밋 → main ff-merge**로 진행.

---

## Wave/Task 패턴 (모든 Phase 공통)
- **Wave A · 계약/백엔드/시뮬레이터** — `server/`, `sim/`, `infra/`, `firmware/`
- **Wave B · 프론트** — `frontend/` (서브에이전트 위임 가능)
- **Wave C · 통합/검증** — `verify_e2e.py` 확장, 스크린샷, 커밋/머지

## 완료 기준 (전체 DoD)
- `uv run python run_dev.py`로 broker+backend+sim 기동, 대시보드 동작 유지.
- 각 Phase 후 `verify_e2e.py` 그린 유지(검증 가능 항목).
- P5 펌웨어는 하드웨어 부재로 소스+빌드노트까지(컴파일 검증은 arduino-cli 있을 때).

## 진행 로그
- P1 ✅ 8/8 e2e 통과, main 머지(ab012b9).
