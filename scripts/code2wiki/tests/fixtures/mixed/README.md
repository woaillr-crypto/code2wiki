# Mixed-language Monorepo fixture

Verifies the multi-plugin orchestration path:
- Root has no build manifest → auto-detect must kick in.
- `backend-java/` exercises Spring Boot + RocketMQ Producer/Consumer + Feign.
- `frontend-ts/` exercises NestJS + TypeORM + BullMQ.
- Both plugins write to `02_cross_cutting/mq.md` — Phase 4's writer
  registration must merge the two sub-sections (currently they overwrite each
  other, which is exactly the bug we want to expose with this fixture).
