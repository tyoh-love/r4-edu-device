# 배포 / 운영 런북 (P10)

## 1. 로컬 dev (의존성 최소, Docker 불필요)
```bash
cd frontend && npm install && npm run build && cd ..
uv run python run_dev.py          # in-process amqtt broker + backend + simulator
open http://localhost:8077
```

## 2. 풀스택 (Docker, 운영 충실)
Mosquitto + 백엔드(대시보드 서빙) + (옵션)시뮬레이터를 한 번에:
```bash
docker compose -f infra/docker-compose.full.yml up --build
open http://localhost:8077
```
- 실제 보드로 운영 시 `simulator` 서비스를 제거하고, 보드의 브로커 주소를 이 호스트의 1883으로 지정(`firmware/config.h`).
- `r4data` 볼륨에 SQLite(답안)·roster·registry가 영속화됨 → 정기 백업 대상.

## 3. 운영 보안 활성화 (PIPA)
기본 dev는 익명/무인증이다. 운영 전 반드시:
1. **교사 인증 ON**: compose `backend.environment`에 `AUTH_REQUIRED=1`, `TEACHERS=ms.kim:<비밀번호>`, `AUTH_SECRET=<랜덤>`. 이후 대시보드는 `/api/login` 토큰 필요, 모든 명령/리포트/로스터 접근이 **접속기록(`data/audit.log`)** 에 남는다.
2. **브로커 per-device 인증 + ACL**: `infra/mosquitto/mosquitto.conf`에서 `allow_anonymous false`, `password_file`/`acl_file` 활성화. 디바이스별 user/pass 발급:
   ```bash
   docker compose -f infra/docker-compose.full.yml exec mosquitto \
     mosquitto_passwd -b /mosquitto/config/passwd r4-0007 <비밀번호>
   ```
   ACL은 `infra/mosquitto/aclfile`(디바이스는 자기 네임스페이스만, 와일드카드 구독 금지).
3. **TLS(서버 인증)**: `mosquitto.conf`의 8883 listener + CA/cert 주석 해제. R4는 서버인증 TLS 지원(클라이언트 인증서 mTLS는 불가 — `docs/README.md §6.5`).
4. **아동 개인정보**: 토픽/페이로드는 좌석·기기 단위만. 아동↔좌석 매핑은 `data/roster.json`(인증·접속기록 하에 `/api/roster`)에만 두고 MQTT에 절대 싣지 않는다. 보관/파기 주기를 정하고 `data/` 백업을 암호화.

## 4. 헬스/모니터링
- 백엔드: `GET /api/state` (스냅샷), WS `/ws`.
- 브로커 생존: `$SYS` 토픽 또는 compose `restart: unless-stopped`.
- 리포트: `GET /api/report/activity?act=color-quiz`, `/api/report/seats`, `/api/report/export.csv`(인증).

## 5. 백업/복구
- 영속 데이터는 전부 `data/`(dev) 또는 `r4data` 볼륨(Docker): `r4swarm.db`, `roster.json`, `registry.json`, `activities.json`, `audit.log`.
- 정기 스냅샷 + 오프사이트 암호화 보관 권장.
