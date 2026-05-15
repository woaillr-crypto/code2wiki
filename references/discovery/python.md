# Python 项目发现规则

> 通用规则见 [`_common.md`](./_common.md)。本文件补充 Django / FastAPI / Flask / SQLAlchemy / Celery 项目的语言特定模式。

## 首要扫描文件

- 构建：`pyproject.toml`、`requirements.txt`、`requirements/*.txt`、`setup.py`、`Pipfile`
- 配置：`settings.py`（Django）、`*.env`、`config/*.yml`、`alembic.ini`
- 入口：FastAPI app/router、Django `urls.py`、Flask blueprints、`manage.py`
- 模型：SQLAlchemy declarative base、Django Model、Alembic migrations
- 异步：Celery `tasks.py`、`celery.py`、APScheduler 配置

## 路由识别

| 框架 | 形态 | 角色 |
| --- | --- | --- |
| FastAPI | `@app.get("/...")` / `@router.post("/...")` | controller |
| Django | `path("/...", view)` / `re_path` | controller |
| Flask | `@app.route("/...")` / `@bp.route("/...")` | controller |
| Starlette / aiohttp | `Route(...)` 注册 | controller |

FastAPI 的 `APIRouter(prefix="/api/order")` 会自动拼接到所有方法路径前。

## 业务逻辑层信号

- 类后缀：`*Service`、`*UseCase`、`*Manager`
- 函数装饰器：`@async_session`、`@inject`
- 目录：`services/`、`use_cases/`、`domain/`
- `class Service:` 内部为多个 async 方法的写法是典型业务编排

## 数据模型识别

- SQLAlchemy：`class X(Base):` + `__tablename__ = "..."`
- Django：`class X(models.Model):` + `class Meta: db_table = "..."`
- Pydantic：`class XSchema(BaseModel):` — 通常归为 `dto` 角色
- Dataclasses：作为 DTO/值对象出现

## 异步 / 调度信号

- Celery：`@shared_task` / `@app.task` / `Celery(...)` 配置中的 `task_routes`
- APScheduler：`@scheduler.scheduled_job(trigger, ...)`
- RQ / Dramatiq：`@job()`、`@actor()`
- asyncio 协程：`async def` + `loop.create_task` / `asyncio.create_task`

## Python 风险信号

- `@transaction.atomic` / `with transaction.atomic():`
- `async with session.begin():`（SQLAlchemy）
- `threading.Lock` / `asyncio.Lock` / `redis.lock`
- `cache.get` / `cache.set` / `@lru_cache`
- 幂等关键字：`idempotency_key`、`unique_together`、`UniqueConstraint`
- `httpx`/`requests` 调用嵌套在事务上下文里

## 已知限制（regex 模式）

- 不解析动态路由（如运行时调用 `app.add_api_route(...)`）
- Pydantic 的 `Field(...)` 元数据不会被结构化抽取
- Celery `task_routes` 配置式注册不在文件层抽取——需要 AI 富化时人工补充
- ~~Django Class-Based View（`class OrderListView(ListAPIView):`）识别成 `service`~~ ✅ Phase 1.3 已修复：`_is_django_cbv` 提取所有 `class X(Bases):` 的基类，与 `DJANGO_CBV_BASE_CLASSES`（Django 内置 + DRF 全套，共 30+ 个）求交集，命中则 role=`controller`。CBV 的 class_name（如 `RefundListView`）在 domain 推断前剥离 `(List|Detail|Create|Update|Delete|Retrieve|Destroy|ReadOnly|Generic|Model|...)*<View|ViewSet|APIView>` 后缀，确保 domain 是业务名（`refund`）而不是 `refund-list-view`。36 条单测覆盖。

## Phase 1 修复说明

- **Django CBV**：fixture `tests/fixtures/python/app/refund/` 包含 `RefundListView(ListAPIView)`、`RefundDetailView(RetrieveAPIView)`、`RefundApproveView(APIView)` 三个 CBV，全部识别为 controller，归入 `refund` 域。

## 推荐 AI 富化补强

- 把 `services/` 里的方法签名翻译成业务流程（每个方法一句话）
- 把 ORM 模型的字段含义解读出来（如 `status` 的合法状态）
- 列出 Celery 任务的触发场景与下游影响
