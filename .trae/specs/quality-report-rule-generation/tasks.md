# 质量报告规则代际一致性 - 实施计划

## Task 1: 规则代际数据模型、指纹与解析服务
- **Status**: `completed`
- **Priority**: high
- **Depends On**: None
- **Completion Evidence**:
  - 迁移 [0014_quality_rules_generation.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/migrations/0014_quality_rules_generation.py) 经 makemigrations 自动生成，SQLite SQL 渲染确认含 `rules_version` 列、generation 表、描述符唯一约束与 fingerprint 索引（.tmp_shim/out0014.sql）；迁移依赖 0013。
  - [generation.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/generation.py) 实现指纹（sha256，sort_keys 规范载荷）、source/inherit 描述符解析、get_or_create 幂等、is_rules_generation_current、bump_rules_version（F 表达式原子自增并同步 updated_date）。
  - ORM 冒烟（SQLite 内存库 + 最小桩环境）3 个用例通过：继承任务/项目指纹相同且 source 指向项目设置；自定义内容（启用一条基础要求）指纹不同；bump 后继承任务与项目同新指纹、独立任务代际不变；bump 单调（连续两次 1→3）、空更新返回 0、get_or_create 幂等。
  - py_compile 通过。完整 datumaro 环境下的正式测试在 Task 7 补齐。
- **Description**:
  - 在 [models.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/models.py) 为 `QualitySettings` 增加单调版本字段 `rules_version`（PositiveBigIntegerField，default=1）。
  - 新增 `QualityRulesGeneration` 模型：scope 自有设置 FK（task/project 二选一，带与 QualitySettings 一致的互斥 check）、`own_rules_version`、`inherit`、source 设置 FK（related_name 区分）、`source_rules_version`、`fingerprint`（db 索引）、`created_date`；唯一约束 `(scope_settings, own_rules_version, inherit, source_settings, source_rules_version)`；提供 `__str__`/organization 解析辅助。
  - 新增代际解析服务（建议 `generation.py`）：规范化有效规则（复用 `resolve_effective_requirements`，字段排序/名称/sort_order/启用/过滤/阈值等全量参数）+ 设置标量（job_filter、max_validations_per_job）生成确定性 sha256 指纹；为 Task/Project 解析“当前有效代际描述符”（source settings：任务按 inherit 与 project 解析，项目为自身），以 get_or_create 语义幂等返回 `QualityRulesGeneration`；提供 `bump_rules_version(settings)`（`F("rules_version") + 1` 原子更新，去重同事务多次调用）。
  - 编写迁移 0014：新字段/新表/约束；存量设置 version=1；不回填报告。
- **Acceptance Criteria Addressed**: AC-1, AC-2, AC-13
- **Test Requirements**:
  - `rule` TR-1.1: 对项目设置、继承任务、自定义任务分别解析描述符，source settings/version/inherit 正确；重复解析返回同一 id；证据：单元测试断言。
  - `rule` TR-1.2: 同项目继承任务与项目指纹相同；等价内容的不同项目设置指纹相同；任意要求字段/顺序/启用状态/filter/job_filter/max_validations_per_job 差异均导致指纹不同；证据：指纹单元测试。
  - `rule` TR-1.3: `bump_rules_version` 同事务多次调用只 +1，并发调用不丢增量（模拟并发 update 或 SQL 层论证）；证据：单元测试。
  - `rule` TR-1.4: `manage.py migrate` 在空库与含 quality_control 存量数据的库上成功（SQLite 测试设置）；证据：迁移检查与测试运行。
- **Notes**: 指纹 JSON 序列化固定分隔符/键顺序/浮点表示，避免 Python hash 随机化影响。

## Task 2: 规则/设置/继承变更路径的版本自增强
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1
- **Completion Evidence**:
  - [serializers.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/serializers.py)：要求 create/update 走 `_touch_settings`→`bump_rules_version`；settings PATCH/PUT 检测 job_filter/inherit/max_validations_per_job 变化与 requirements 全量替换，仅在实际变化时 bump 一次；bulk create 事务末 bump；[views.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/views.py) perform_destroy bump；[models.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/models.py) ensure_base 创建基础要求时 bump；[signals.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/signals.py) post_init 跟踪 task project_id、post_save 在任务跨项目移动时 bump 且每次保存同步跟踪值。
  - 离线 SQLite 桩环境 7 个测试全绿：单条要求新增/更新/删除各 bump 一次；设置标量变化 bump、无变化不 bump；bulk 批量只 bump 一次；任务跨项目移动 bump、重复保存不 bump；bump 对设置/任务创建初始版本（基础要求写入）语义正确。
- **Description**:
  - 在 [serializers.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/serializers.py) 收口所有版本推进：QualityRequirementSerializer 的 create/update（保留 touch_settings 上下文语义，单条接口在要求增改后 bump 一次）、QualitySettingsSerializer.update（标量字段变化与 `_sync_requirements` 全量替换完成后 bump 一次；无变化不 bump）、QualityRequirementBulkCreateSerializer.create（事务末尾 bump 一次）、`QualityRequirementViewSet.perform_destroy`（删除后 bump）。
  - 在 [signals.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/signals.py)（或 engine 信号挂载处）增加 Task.project_id 变化后的任务设置 bump（post_save 追踪 loaded project_id）；无设置时跳过。
  - `ensure_base_quality_requirements` 初始创建基础要求的场景不 bump（设置 version 初始即 1，且代际按需解析）；确认其显式 `touch()` 调用点语义不被破坏。
- **Acceptance Criteria Addressed**: AC-1
- **Test Requirements**:
  - `rule` TR-2.1: 经 REST 更新/新增/删除/bulk 创建要求、PATCH settings（含 requirements 全量替换）、切换 inherit/job_filter/max_validations 后，重新解析代际得到新版本；未改变字段的保存不产生新版本；证据：REST/单元测试。
  - `rule` TR-2.2: 任务移入/移出项目后，其任务设置 version 自增且新代际 source 指向新项目设置；证据：信号单元/REST 测试。
  - `rule` TR-2.3: 单次复合写操作（bulk、settings+requirements 替换）只 bump 一次；证据：版本号断言。

## Task 3: 报告族模型、发布闸与任务计算器重写
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1
- **Completion Evidence**:
  - [0015_quality_report_family_generation.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/migrations/0015_quality_report_family_generation.py) 增加 generation FK（PROTECT）、status 与 task/job/project 三个部分唯一约束；SQLite SQL 渲染确认为 `CREATE UNIQUE INDEX ... WHERE status = 'current'`（.tmp_shim/out0015.sql）。
  - [report_families.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/report_families.py)：StaleGenerationError、TaskReportSnapshot、publish_task_report_family（FOR UPDATE 锁任务与作业行→校验绑定代际/指纹→校验 target/gt/作业/受派者时间戳→幂等复用→整族 supersede→同族 current 写入冲突）；current 查询辅助。
  - [quality_calculators.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/quality_calculators.py)：compute_report 接受 generation_id，最多 2 次有界重算、持续过期废弃并返回既有 current；快照事务与聚合分离；_save_reports 移除，冲突/子报告全部由发布服务统一写。
  - 离线 SQLite 2 个发布服务测试通过：代际过期/任务或 GT 时间戳过期均抛 StaleGenerationError；完全相同快照幂等不新增行（共 2 行）；数据变化发布新 current 族且任务根与作业子报告整体 superseded（各状态计数正确）。
  - py_compile 通过；PostgreSQL FOR UPDATE 行为留待 CI 验证。
- **Description**:
  - `QualityReport` 增加 `generation` FK（nullable，PROTECT，related_name）与 `status`（CharField choices current/superseded，null=legacy）；编写迁移 0015，含 PostgreSQL 部分唯一约束（task_id/job_id/project_id 各一个 current；Django `UniqueConstraint(condition=Q(status="current"))`）；验证 SQLite 测试库同样成立。
  - 新增报告族发布服务（建议 `report_families.py`）：在 atomic 内对目标行 `select_for_update`（任务行 + GT job 行；项目在 Task 4）→重新解析当前代际与当前时间戳→判定 stale（代际/继承指纹不符 或 target/gt/assignee 时间戳变化）→定义 `StaleGenerationError`；幂等命中（同代际且全部时间戳相等的 current 族）直接返回该族；否则旧 current 族（任务根+作业子报告）整体置 superseded，新族（根+子报告+冲突）置 current 并写同一 generation，任务根 `created_date` 晚于旧族。
  - 重写 [quality_calculators.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/quality_calculators.py) `TaskQualityCalculator.compute_report(task, *, generation_id=None)`：接受绑定代际；快照事务内额外记录 target/job/gt/assignee 时间戳与代际快照；`_save_reports` 改走发布服务；实现最多 2 次重算的有界循环（stale 时重新解析最新代际重算，attempt 日志 slogger），持续 stale 则废弃不写库并返回已存在 current 族（无则 None）；GT 作业消失维持 None；保持返回任务报告对象的契约（幂等时返回既有族）。
  - 作业子报告 status/代际随族统一；冲突仅随新族写入，废弃路径不产生孤儿冲突。
- **Acceptance Criteria Addressed**: AC-4, AC-5, AC-7, AC-9, AC-13, AC-14, NFR-1, NFR-3
- **Test Requirements**:
  - `rule` TR-3.1: 注入过期 generation_id 调用 compute_report：不写入绑定代际 current 行，重算后 current 族属于最新代际；连续两次 stale（模拟重算期间再变更，attempt 上限 2）后无新增行且返回既有 current id/None；slogger 有过期/重算/废弃记录；证据：计算器测试与日志断言。
  - `rule` TR-3.2: 快照后修改任务/GT 标注或受派者：旧时间戳不发布，重算后新族时间戳为最新；GT 删除返回 None；证据：计算器测试。
  - `rule` TR-3.3: 同代际同时间戳并发/重复调用只产生一个 current 任务族与一套作业子报告/冲突，返回 id 相同；不同数据时间戳产生新 current 族且旧族（含作业子报告）全部 superseded；证据：并发集成测试与库记录断言。
  - `rule` TR-3.4: 部分唯一约束在两数据库后端生效；status 为空的历史行不参与唯一约束；证据：迁移/SQL 断言。
  - `rubric` TR-3.5: 发布闸/族服务单一权威、计算器无旁路保存路径；scale 1-5；anchors 1=保存逻辑散落多路径，3=存在集中服务但仍有旁路，5=全部写库路径唯一收口；threshold >= 4；证据：代码评审。

## Task 4: 项目计算器的同代际聚合与确定性内联重算
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 3
- **Completion Evidence**:
  - [quality_calculators.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/quality_calculators.py) `ProjectQualityCalculator` 重写：任务 current 族按 status+指纹匹配+task/GT/各作业/受派者时间戳新鲜度复用；缺失或失配按任务当前代际内联 `TaskQualityCalculator.compute_report(generation_id=...)`；项目发布有界重算循环（2 次），持续过期废弃并返回既有 current。
  - [report_families.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/report_families.py) 增 `publish_project_report_family`：项目行 FOR UPDATE→代际一致→项目时间戳→选中任务族仍 current/同指纹→时间戳+子族集合幂等复用→仅项目根 supersede→同族连接；`ProjectReportSnapshot`。
  - QualityReport 增加 `parameters` 便捷属性；作业集合集合运算兼容 JSON 反序列化的列表。
  - 离线 2 个项目冒烟通过：项目复用/幂等（二次计算同一 id）、项目时间戳过期抛 StaleGenerationError、规则变更后新任务族被聚合并使旧项目根 superseded（任务族状态独立）。连同前面套件共 11 个离线测试全绿。
- **Description**:
  - 重写 `ProjectQualityCalculator.compute_report(project, *, generation_id=None)`：入队绑定项目代际；以“status=current + 指纹==项目代际指纹 + target/gt 时间戳最新”替代/收紧 `is_task_report_relevant`（custom 任务用其自身代际指纹判定）；项目行 select_for_update 后发布。
  - 对缺失/失配任务以 `TaskQualityCalculator().compute_report(task, generation_id=...)` 内联重算：继承任务传项目代际 id，custom 任务传其自身当前代际 id；内联结果与独立任务 worker 竞争时由 Task 3 的行锁/唯一约束幂等收敛。
  - 项目发布前若任一子任务族在聚合过程中变为 stale（代际/时间戳复核失败），整批不发布，按有界循环（2 次）以最新项目代际重算整个项目报告；持续过期则废弃并返回既有 current 项目报告（无则 None）。
  - `_compute_project_report` 只聚合同指纹 current 任务族；custom/inherited 桶、completed 统计语义保持；项目报告 children 仅连接被聚合/连接的同代际族；无 GT 任务维持 not_configured 口径。
- **Acceptance Criteria Addressed**: AC-6, AC-8, AC-14
- **Test Requirements**:
  - `rule` TR-4.1: 项目规则修改后触发项目计算：旧代际任务报告不进入聚合，相关任务在项目代际下被内联重算（断言绑定 generation_id 传递正确），项目汇总各字段仅来自同指纹 current 族；证据：扩展 `test_can_reuse_relevant_task_reports_in_project_report` 风格的 REST/计算器测试。
  - `rule` TR-4.2: 部分任务无报告/报告数据过期/自定义设置任务：分别确定性重算或进入 custom 桶；children 连接完整；证据：项目计算器测试。
  - `rule` TR-4.3: 内联重算与独立任务 worker 并发后仅一个 current 任务族被项目报告引用；证据：并发测试断言。
  - `rule` TR-4.4: 聚合期间子族失配触发整批废弃重算（attempt 上限 2），不落混合项目报告；证据：计算器测试。

## Task 5: 报告请求入队绑定代际
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1
- **Completion Evidence**:
  - [queue_manager.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/queue_manager.py) 在 setup_new_job 入队前解析当前代际并把 `generation_id` 作为作业回调 kwargs；QualityRequestId 增加 generation_id（不进 rq_id 字符串）；两个 worker 回调透传 generation_id；校验与确定性 rq_id 语义保持。py_compile 通过；端到端入队/kwargs 在 Task 7 的 REST 流程中覆盖。
- **Description**:
  - [queue_manager.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/queue_manager.py)：`QualityReportQueueManager` 在 validate/enqueue 流程中于事务内解析目标当前代际并持久化；`init_callback_with_params` 将 `generation_id` 传入 `check_task_quality`/`check_project_quality`；`check_*_quality` 透传代际 id 给计算器。
  - 保持确定性 RQ job id 与 409/在途语义；代际行 PROTECT 不影响作业生命周期。
  - 旧版 `rq_id` 状态查询与 FINISHED 返回 report id 的废弃端点适配：计算器幂等/废弃返回的 id 经该路径仍能取回报告或维持“无报告”语义。
- **Acceptance Criteria Addressed**: AC-3, AC-12
- **Test Requirements**:
  - `rule` TR-5.1: POST 入队作业 kwargs/meta 可检验到 generation_id；在途重复 POST 仍 409 同 rq_id；作业终态后规则已变的新 POST 绑定新代际；证据：REST 测试（RQ mock/测试队列）。
  - `rule` TR-5.2: 无 GT、非 2D 等既有校验与权限拒绝路径不回归；证据：现有 POST 用例通过。

## Task 6: 报告/冲突 API 序列化、过滤与 OpenAPI
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 3, Task 4
- **Completion Evidence**:
  - [serializers.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/serializers.py) 报告序列化新增只读 `status`（null→"legacy"）与 `generation_id`；列表查询新增可重复 `status=current|superseded|legacy`。
  - [views.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/views.py)：列表按 status OR 过滤（legacy=status__isnull）；冲突列表在无 report_id 的 job/task/project 作用域下仅返回 current 族（project 经 current 项目根的 parents 关系），显式 report_id 行为不变；OpenAPI 增加 status 参数。
  - 离线冒烟通过：current/legacy 序列化值、generation_id、查询参数校验与 ORM 状态过滤断言。py_compile 通过。
- **Description**:
  - `QualityReportSerializer` 增加只读 `status`（legacy 行输出 `"legacy"`）、`generation_id`；`QualityReportListQuerySerializer` 增加可选 `status`（current/superseded，多值/单值校验）并在 viewset queryset 生效（可索引列，不使用 JSON 正则）；`include_legacy` 语义保持。
  - `QualityConflictsViewSet`：无 report_id 的 task/project 维度过滤限制为 current 族（job：report__status=current；task/project：沿 parents 链且根 status=current）；显式 report_id 路径行为不变。
  - [schema.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/schema.py) 与 drf-spectacular 输出同步新字段/参数；data/confusion/matrix action 的报告门控保持（has_current_data_format）；矩阵下载与 JSON data 不限制报告 status（显式历史下载保留）。
- **Acceptance Criteria Addressed**: AC-9, AC-10, AC-12, NFR-2, NFR-5
- **Test Requirements**:
  - `rule` TR-6.1: 列表默认包含 current+superseded+legacy（受 include_legacy 控制 legacy）；`status=current` 仅返回当前族；序列化字段齐全；证据：REST 测试。
  - `rule` TR-6.2: 冲突端点按 task/project 仅得 current 族冲突、按 report_id 精确返回该族冲突；矩阵 ZIP/CSV/JSON 与 data 下载在 current 与 superseded 显式报告上均可用、legacy 矩阵仍 404 而 data 可下载；证据：REST 测试。
  - `rule` TR-6.3: OpenAPI schema 生成成功且含新字段/参数；证据：schema 生成检查/测试。

## Task 7: 后端测试套件补齐与回归
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2, Task 5, Task 6
- **Completion Evidence**:
  - 新增应用级测试 [test_rule_generations.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/tests/test_rule_generations.py)（继承/指纹/幂等/bump/跨项目移动/序列化器新增要求/is_current，7 用例）与 [test_report_families.py](file:///f:/swe/092308/project-01/cvat/apps/quality_control/tests/test_report_families.py)（任务/项目发布闸：代际过期、target/GT 时间戳过期、幂等、整族 supersede、项目子族集合变化拒绝，5 用例），py_compile 通过，CI 以 manage.py test cvat.apps + PostgreSQL 运行。
  - REST 新增 TestQualityReportGenerations 4 用例到 [test_quality_control.py](file:///f:/swe/092308/project-01/tests/python/rest_api/test_quality_control.py)：status/generation 字段与 status 过滤；无变化手动重算幂等；规则变更后新请求绑定新代际；标注变化后新 current 族/旧族 superseded/任务冲突仅列 current/历史 report_id 可读。py_compile 通过，CI 随 pytest tests/python 运行。
  - 本地离线桩环境（SQLite，无 datumaro/scipy）12 个临时用例全绿，覆盖发布服务核心 ORM 行为；完整 datumaro 匹配路径与 REST 流程依赖 CI 镜像。
- **Description**:
  - 扩展 [test_quality_control.py](file:///f:/swe/092308/tests/python/rest_api/test_quality_control.py)：代际绑定入队、状态/过滤、过期不落库的端到端行为（通过测试 RQ 同步执行或直接 manager 调用）、并发幂等、项目同代际聚合、手动无变化幂等与数据变化新增、历史/legacy 兼容、权限矩阵全量回归。
  - 在 quality_control/tests 下为 generation 服务、发布闸/族转换增加单元测试；复用现有 quality_reports fixture 与 RQ 等待工具。
  - 运行 quality_control 全部 Django 测试与 rest_api quality 相关测试（SQLite 配置），修复回归。
- **Acceptance Criteria Addressed**: AC-1~AC-13 的后端证据汇总
- **Test Requirements**:
  - `rule` TR-7.1: 新增测试可稳定复现“排队后改规则旧 worker 不污染当前结果”与“项目混合快照”两个原始问题场景，并断言修复后行为；证据：测试通过输出。
  - `rule` TR-7.2: `pytest tests/python/rest_api/test_quality_control.py tests/python/rest_api/test_quality_requirements.py` 与 quality_control 应用测试全绿；证据：命令输出。
  - `rubric` TR-7.3: 测试覆盖关键竞态/并发与兼容回归，断言基于数据库可观察状态而非实现细节；scale 1-5；anchors 1=仅快乐路径，3=覆盖主场景但缺并发，5=含并发、过期、兼容；threshold >= 4；证据：测试清单评审。

## Task 8: cvat-core 报告代际字段与 current 过滤
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 6
- **Description**:
  - 更新 [server-response-types.ts](file:///f:/swe/092308/project-01/cvat-core/src/quality/server-response-types.ts) 的 SerializedQualityReportData（status、generation_id）与 reports filter 类型；[server-proxy.ts](file:///f:/swe/092308/project-01/cvat-core/src/server-proxy.ts) `getQualityReports` 透传 status；[quality-report.ts](file:///f:/swe/092308/project-01/cvat-core/src/quality/quality-report.ts) 暴露 `status`/`generationId`。
  - 如 SDK Python 有报告 filter 模型（cvat_sdk api_client），同步增加可选 status 字段（生成代码模型按仓库现有生成流程处理；若生成产物不入库则仅改手写层并记录）。
- **Acceptance Criteria Addressed**: AC-11, AC-12, NFR-5
- **Test Requirements**:
  - `rule` TR-8.1: tsc 编译与 eslint 通过，新字段端到端可从 /quality/reports 响应反序列化；证据：构建输出。
  - `rule` TR-8.2: 不传 status 时调用行为与现状一致（历史仍可取）；证据：类型检查与现有前端调用点审查。

## Task 9: cvat-ui 当前报告选择路径适配
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 8
- **Description**:
  - [annotation-actions.ts](file:///f:/swe/092308/project-01/cvat-ui/src/actions/annotation-actions.ts) 作业质量加载改为 `{ jobID, target: 'job', status: 'current' }`，无 current 报告时维持后续空冲突行为。
  - 质量管理页（quality-control-page 及其数据来源：Task/Project 模型 reports 封装或页面内加载处）显式按 status=current 拉取任务/项目当前报告；历史列表若有展示仍取全量。
  - 全仓审计其余 `quality.reports(`/`analytics.quality.conflicts(` 调用点，确保“当前结果”消费方使用 current 过滤；cvat-ui tsc/eslint/prettier 通过。
- **Acceptance Criteria Addressed**: AC-10, AC-11
- **Test Requirements**:
  - `rule` TR-9.1: 构造同时含 superseded（id 更大）与 current 报告的数据场景，标注页与质量管理页取到的均为 current 报告 id 及其冲突/矩阵；证据：代码走查 + 可运行处的组件/集成验证。
  - `rule` TR-9.2: cvat-ui 生产构建（tsc/webpack）与 lint 通过；证据：构建日志。

## Task 10: 变更记录与最终集成验证
- **Status**: `pending`
- **Priority**: low
- **Depends On**: Task 7, Task 9
- **Description**:
  - 按仓库 changelog.d（scriv）约定添加变更片段，说明质量报告代际一致性与新增 API 字段。
  - 全量运行后端质量相关测试、前端 cvat-core/cvat-ui 构建与 lint；修复发现；整理迁移在 PostgreSQL 方言下的 DDL 审查（部分索引/FK PROTECT）。
- **Acceptance Criteria Addressed**: AC-13, AC-14, NFR-1~NFR-5
- **Test Requirements**:
  - `rule` TR-10.1: 后端子集测试与前端 typecheck/build 均通过；证据：命令输出汇总。
  - `rubric` TR-10.2: 端到端一致性（入队绑定→计算→发布闸→同代际聚合→读取/下载/UI）闭环无缺口；scale 1-5；anchors 1=链路有断点，3=主链路通但存在读取面遗漏，5=全链路一致；threshold >= 4；证据：独立评审。
