# 质量报告规则代际一致性 - 产品需求文档

## Overview
- **Summary**: 为质量报告（Quality Report）计算引入“有效规则代际（rules generation）”及其继承来源的完整绑定：每次报告请求在入队时确定并绑定唯一代际；worker 仅在任务标注、Ground Truth、规则树、继承关系在计算快照与发布时刻均未变化时，才将报告族发布为当前结果；旧代际计算在当前代际下有界确定性重算，仍过期则明确废弃；并发 worker 与重复请求对同一目标只产生一个可作为当前结果的报告族；任务、作业、项目三级汇总、冲突、完成状态与混淆矩阵下载全部引用同一代际；同时保留规则未变化时的手动计算、既有权限、历史报告读取与旧格式兼容。
- **Purpose**: 消除“排队后规则被修改，旧 worker 仍按旧规则完成计算，并在新规则保存后成为列表中最新报告”的竞态；消除项目报告聚合来自不同规则代际任务报告的混合快照。
- **Target Users**: 质量管理员（维护质量设置/质量要求、发起任务/项目报告计算）；标注员与评审员（查看作业质量、冲突、完成状态）；API/SDK 集成方（读取报告、冲突、下载矩阵）。

## Goals
- 每次报告请求绑定一份**完整有效规则代际**及其**继承来源**（自有设置 vs 继承自项目设置），并可在任务/项目之间判定“有效规则是否相同”。
- 计算在数据库一致性快照下进行；发布为“当前结果”前原子校验规则代际、继承来源、目标/GT/受派者数据版本均未变化，杜绝混合快照成为当前结果。
- 旧代际计算不发布为当前结果：在 worker 内按最新代际有界确定性重算；持续过期时明确废弃（不落库）。
- 同一目标的重复请求与并发 worker（含项目 worker 对任务的内联计算）只产生**一个**当前报告族；幂等请求复用该族。
- 项目报告只聚合同代际（规则指纹相同）的当前任务报告族；缺失或过期的任务报告在项目代际下确定性重算。
- 任务/作业/项目报告的汇总、冲突列表、完成状态、矩阵下载均从同一报告族解析。
- 保留：规则未变化（仅数据变化或完全无变化）时的手动计算行为；现有权限模型；历史报告（含已取代族）读取；旧数据格式（legacy）报告的读取与下载兼容。

## Non-Goals
- 不重设计质量要求（QualityRequirement）的规则树继承语义、序列化格式或校验规则本身。
- 不引入跨代际报告的自动合并、diff 展示或 UI 代数管理页面。
- 不对既有历史报告做数据回填/重算（旧报告保持 legacy 可读）。
- 不改变 RQ 队列拓扑、请求 ID 总体方案、OPA/rego 权限策略与组织隔离规则。
- 不实现 GT 作业或标注数据的 MVCC 快照版本化基础设施（沿用 REPEATABLE READ 与 updated_date 时间戳）。
- 不改变报告 JSON 内 ComparisonReport 的统计口径（完成状态、汇总结构保持不变）。

## Background & Context
- 入口：POST `/api/quality/reports` 由 `QualityReportQueueManager`（[queue_manager.py](file:///f:/swe/092308/proj-01/cvat/apps/quality_control/queue_manager.py)）入队，RQ 作业 ID 对同一目标是确定性的（`quality-check-task-<id>` / `quality-check-project-<id>`），在途并发请求返回 409；终态作业被删除后可重新入队。
- 任务 worker `TaskQualityCalculator.compute_report`（[quality_calculators.py](file:///f:/swe/092308/proj-01/cvat/apps/quality_control/quality_calculators.py)）：在 `transaction_with_repeatable_read()` 中加载任务、GT 作业、有效设置、全部要求与标注并计算各作业报告；随后在新事务中保存“任务报告 + 作业报告 + 冲突”。当前保存时**无任何新鲜度/代际校验**，完成越晚的报告 id 越大，即被视为最新。
- 项目 worker `ProjectQualityCalculator.compute_report`：按 `created_date` 取每个任务最新报告，仅以 `target_last_updated >= task.updated_date 且 >= quality_settings.updated_date`（`is_task_report_relevant`）判定可复用；对缺失任务在项目 worker 内**同步内联**调用任务计算器；源码注释已明确“we don't guarantee absolute consistency”。不同任务的报告可能来自不同规则版本，形成混合聚合。
- `QualitySettings`/`QualityRequirement` 变更通过 `settings.save()`/`touch()` 刷新 `updated_date`；要求单条增改、删除、bulk 批量创建、settings PATCH/PUT 的 requirements 全量替换都会 touch 设置；但不存在单调版本号或指纹。
- 读取侧：报告列表默认按 `-id` 排序（前端 cvat-core 取第一条为“当前报告”，见 `cvat-ui/src/actions/annotation-actions.ts` 的 `cvat.analytics.quality.reports({ target: 'job' })`）；冲突默认列表、矩阵下载、data 下载均以报告 id 为索引；legacy 报告通过 `data` 正则与 `include_legacy` 过滤。
- 用户已确认的决策：
  1. **过期计算**：worker 内按最新代际有界确定性重算（最多 2 次），仍过期则废弃且不落库，作业返回已存在的当前报告 id。
  2. **手动幂等**：规则与数据（target/GT/受派者时间戳）均未变化时，重复请求幂等复用唯一当前族；数据变化时仍正常产生新族。
  3. **范围**：前后端一起适配，前端显式以 `status=current` 选择当前报告。

## Functional Requirements

### FR-1：规则代际模型与继承来源
- 系统为每份 `QualitySettings` 维护单调递增的 `rules_version`（初始 1），并在以下任一变更发生时（同一事务内、去重后）自增一次：
  - 设置标量字段变化：`job_filter`、`inherit`、`max_validations_per_job`；
  - 其下任一 `QualityRequirement` 的创建、更新、删除（含单条接口、bulk 批量创建、settings PATCH/PUT 的 requirements 全量替换）；
  - 任务在项目间移动（`Task.project_id` 变化）导致其任务设置的继承来源变化。
- 系统提供 `QualityRulesGeneration` 代际记录，至少包含：自有设置（scope settings）、自有版本、`inherit` 标志、**有效来源设置**（source settings）、来源版本、创建时间，以及对“完整有效规则集”的规范化**指纹 fingerprint**（包含解析继承后的全部有效要求参数与顺序、设置级 job_filter/max_validations_per_job）。
- 同一有效规则内容（含项目设置与其继承任务）必须产生相同指纹；任一规则或继承来源变化产生不同代际。
- 代际记录按 `(scope_settings, own_version, inherit, source_settings, source_version)` 幂等获取或创建（get_or_create 语义），不依赖时间戳比较。

### FR-2：报告请求绑定代际
- POST 创建报告时，队列管理器在同一事务内解析目标当前的完整有效代际（任务含继承来源解析），并将代际 id 作为作业参数绑定；入队响应（rq_id）与该绑定对应。
- RQ 作业 ID 仍按目标确定（保持在途重复请求 409 语义）；终态后重新发起的请求绑定当时最新代际。
- 无 GT 作业的任务等现有校验与报错保持不变。
- worker（任务/项目）从作业参数接收绑定代际 id，而非自行隐式取最新。

### FR-3：计算快照与发布闸
- 任务计算在既有 REPEATABLE READ 快照内一次性读取任务、作业、GT 作业、有效设置、有效要求树与全部标注，并在快照内记录 target/job/GT 的 `updated_date`（含 assignee 时间戳）。
- 报告族落库前，在单个原子事务中对目标行加锁并重新读取当前状态，仅当以下全部成立才允许发布为 current：
  1. 绑定代际仍等于目标当前有效代际（含继承来源一致）；
  2. 快照捕获的任务、GT 作业、各作业、受派者时间戳与当前库一致（GT 作业在调度后被删除时按现有行为返回无报告）；
  3. 不存在同代际、同数据时间戳的当前报告族。
- 任一条件不满足时不得写入新的 current 报告族。

### FR-4：过期代际的有界重算与废弃
- 发布闸判定代际过期（或项目聚合发现子族过期）时，worker 在同一作业内按**当前**代际重新执行完整计算，最多重算 2 次；重算重新捕获快照与绑定代际。
- 重算后仍过期（规则持续被修改）时，明确废弃：不写入任何报告行，作业返回目标已存在的当前报告 id；不存在时返回空（保持现有“无报告”响应语义）。
- 已落库的旧代际报告族在新族发布时被原子标记为 superseded，绝不删除、仍可按历史读取。

### FR-5：唯一当前报告族与并发幂等
- 每个任务、每个作业、每个项目至多存在一个 `status=current` 的报告根/族；新族发布时同族内旧任务报告及其作业子报告在同一事务内整体转为 superseded。
- 同目标并发 worker（含项目 worker 对任务的内联计算与独立任务 worker 竞争）通过目标行 `SELECT ... FOR UPDATE` 串行化发布；重复落库由部分唯一约束兜底，违反时幂等返回已存在的当前族 id，不产生第二个族。
- 规则与数据时间戳均未变化的重复/并发请求幂等复用同一当前族；仅数据变化（标注/GT/受派者）时在同代际内发布新族；规则变化时在当代际发布新族。
- 任务报告与其全部作业子报告、冲突共享同一代际 id，作为单一报告族保存；项目报告与其选用的任务报告族连接。

### FR-6：项目报告的代际一致性
- 项目请求绑定项目设置的当前代际；项目 worker 仅可复用满足以下全部条件的任务报告族：`status=current`、规则指纹与项目绑定代际指纹相同、target/GT 时间戳仍为最新。
- 缺失或不满足条件的已配置任务，由项目 worker 在项目代际（继承任务）或任务自身当前代际（custom 任务）下**确定性内联重算**，内联计算同样遵守 FR-3/FR-5 的发布闸与幂等。
- 项目报告发布前若任一子任务族在聚合期间变为过期，整批不发布并按 FR-4 重算整个项目报告（有界）；项目报告与其汇总的任务/作业统计、完成数、冲突只来自同代际族。
- custom（非继承）任务报告可作为项目报告子项连接（沿用现有 inherited 标记与 custom 桶统计），但不并入同代际指纹聚合口径。

### FR-7：读取、冲突、完成状态与下载引用同一族
- 报告序列化输出新增 `status`（current/superseded；无代际的旧报告为 `legacy`）与代际标识（至少 `generation_id`）。
- 列表/详情默认仍可读取全部报告（历史读取不破坏），新增按 `status` 过滤能力；前端选择“当前报告”时显式使用 current 状态而非取列表第一条。
- 冲突列表在按 task/project 维度无 `report_id` 浏览时，仅解析 current 报告族（任务/项目沿用父子关系下钻）；显式带 `report_id` 时行为与权限不变。
- 完成状态（jobs/tasks completed、requirements completed）继续取自报告 JSON summary，因此天然跟随所读取的报告族。
- `/data`、`/confusion`、`/confusion/matrix` 行为对指定报告 id 保持不变；旧格式报告仍不可下载矩阵（沿用 has_current_data_format 门控），但 JSON 数据下载继续兼容 legacy。

### FR-8：保留的行为
- 规则未变化时手动发起计算仍被允许并返回/生成报告：数据变化→同代际新族；无任何变化→幂等返回当前族。
- 报告、设置、要求、冲突的所有权限（OPA rego 策略、对象级/列表 scope 过滤、rq 状态查询权限）保持不变。
- 历史报告（superseded 与 legacy）可列出、查看、下载 data；`include_legacy`、`parent_id`、target/task/project/job 过滤语义保持。
- 无 GT 任务不支持任务报告、2D 限制、项目空报告等现有校验与响应码保持。
- SDK/前端在无显式 status 参数时的既有调用方式尽量兼容（新增可选字段与可选过滤参数，不破坏旧客户端）。

## Non-Functional Requirements
- **NFR-1 正确性**：在 PostgreSQL（生产）与 SQLite（测试）下均正确；并发安全基于数据库行锁与约束，不依赖仅 Redis/RQ 的进程内锁。
- **NFR-2 性能**：代际解析与指纹计算只在入队、重算、项目聚合时发生；报告列表查询不得全表扫描 JSON 或以正则过滤来判定当前（代际/状态为可索引列）；现有报告列表的 COUNT/WHERE 性能不劣化。
- **NFR-3 可观测性**：过期重算与废弃在服务端日志有明确记录（目标、绑定代际、当前代际、attempt 序号）。
- **NFR-4 迁移安全**：新迁移可在既有大数据量上在线执行；旧报告行无需回填（status/代际为空即 legacy）；新增约束对存量数据成立（部分唯一索引仅约束 current）。
- **NFR-5 兼容**：API 仅新增只读字段与可选查询参数；cvat-sdk Python 与 cvat-core TypeScript 类型同步扩展；不移除任何现有响应字段。

## Constraints
- **Technical**: Django + DRF + PostgreSQL/SQLite；RQ/django-rq 作业模型；datumaro ComparisonReport 序列化保持不变；迁移编号沿用 `cvat/apps/quality_control/migrations/` 现有序列（下一个 0014）。
- **Business**: 不改变质量报告业务语义与权限边界；旧报告长期可读。
- **Dependencies**: `cvat.apps.engine`（Task/Job/TimestampedModel/update 时间戳信号）、`cvat.apps.redis_handler`（AbstractRequestManager）、cvat-core/cvat-ui 报告读取链路。

## Assumptions
- 标注/GT/受派者变更会更新对应 Task/Job 的 `updated_date`（现有 target_last_updated/gt_last_updated 机制已依赖该前提）；标签结构变更经由 Task.updated_date 体现，因此被同一时间戳闸覆盖，不另建标签代际。
- `QualityRequirement` 的任何写操作都经过现有 serializer/view 路径（无旁路批量 SQL 写入要求）。
- 项目 worker 内联任务计算与独立任务 worker 可能并发执行，数据库行锁足以将发布串行化。
- 指纹规范化不需要跨 CVAT 版本稳定（仅需同版本内确定性与相等性），使用规范 JSON + sha256 即可。

## Acceptance Criteria

### AC-1：规则变更产生单调新代际并记录继承来源
- **Type**: `rule`
- **Given**: 一个任务（或项目）已有代际 G1 与有效规则集；管理员通过单条更新、bulk 批量新增、删除要求，或修改 `inherit`/`job_filter`/`max_validations_per_job`，或把任务移入/移出项目
- **When**: 变更成功提交后解析目标当前有效代际
- **Then**: 得到与 G1 不同的新代际 id；其 source settings/source version 反映真实继承来源（继承任务指向项目设置及其新版本，custom 任务指向自身设置）；未发生上述变更时重复解析返回同一代际 id
- **Pass Condition**: 自动化测试覆盖全部变更入口，断言代际 id 单调变化、继承来源字段正确、无变更时代际稳定
- **Evidence**: quality_control 新增单元/REST 测试；代际模型数据与迁移检查

### AC-2：有效规则指纹相等性
- **Type**: `rule`
- **Given**: 同一项目设置 P，以及继承它的任务 T1、T2；另有自定义要求任务 T3 与内容恰好相同的项目设置 P2
- **When**: 分别计算有效规则指纹
- **Then**: P、T1、T2 指纹相同；T1 与 T3 指纹不同；P 与 P2 内容相同时指纹相同；要求参数/顺序/启用状态/继承字段任一不同则指纹不同
- **Pass Condition**: 单元测试对上述组合断言指纹相等/不等
- **Evidence**: 指纹规范化函数的单元测试

### AC-3：请求绑定代际且在途重复请求不重复入队
- **Type**: `rule`
- **Given**: 对任务/项目发起报告创建请求
- **When**: 解析请求并入队；在作业 queued/started 期间再次发起同目标请求
- **Then**: RQ 作业参数携带解析时刻的代际 id；第二次请求返回 409 与同一 rq_id；作业终态后新请求绑定最新代际并产生新作业
- **Pass Condition**: REST 测试断言作业 meta/kwargs 含 generation_id、409 行为不变、终态后可按新代际入队
- **Evidence**: test_quality_control.py 新增/扩展用例

### AC-4：计算期间规则/继承变化不得发布为当前结果
- **Type**: `rule`
- **Given**: 任务 T 的报告作业已绑定 G1 并开始计算；计算期间管理员修改要求树、切换 inherit、或把任务移出项目（产生 G2）
- **When**: worker 到达发布闸
- **Then**: G1 快照报告不写入为 current；worker 按 G2 确定性重算（attempt 记录），并以 G2 发布唯一当前族；若 G2 也在重算期间失效且超过 2 次，则废弃且不新增任何报告行
- **Pass Condition**: 用直接调用计算器（注入过期 generation_id）+ 规则变更钩子的测试，断言无 G1 current 行、最终 current 族属于 G2（或在持续变动场景无新行且作业返回既有 current id）
- **Evidence**: 计算器单元测试与服务端日志断言

### AC-5：计算期间标注/GT/受派者变化不得发布为当前结果
- **Type**: `rule`
- **Given**: 作业已绑定代际并在 REPEATABLE READ 快照中计算；计算期间任务标注、GT 作业标注或作业受派者变化
- **When**: worker 到达发布闸并比对时间戳
- **Then**: 旧快照不发布为 current；按最新状态在同代际下重算并发布新族；GT 作业被删除时维持现有“无报告”返回
- **Pass Condition**: 计算器测试模拟时间戳推进，断言旧时间戳行不落库、新族 target_last_updated/gt_last_updated/assignee_last_updated 与重算快照一致
- **Evidence**: quality_control 计算器测试

### AC-6：并发 worker 与重复请求只产生一个当前报告族
- **Type**: `rule`
- **Given**: 两个执行流同时为同一任务（或项目 worker 内联与独立任务 worker 同时为同一任务）计算同代际同数据报告
- **When**: 两者并发进入发布
- **Then**: 数据库中该任务（及其作业子报告）仅有一个 current 族，另一执行流幂等返回该族 id；无部分冲突行残留；两者返回同一报告 id
- **Pass Condition**: 并发测试（线程/事务交叉）后断言 current 报告计数为 1、冲突行只属于该族、两个返回 id 相等
- **Evidence**: 并发集成测试；部分唯一约束与 FOR UPDATE 发布路径代码审查

### AC-7：完全无变化的重复手动计算幂等
- **Type**: `rule`
- **Given**: 目标已有 current 族 G1 且规则、标注、GT、受派者均无变化
- **When**: 再次（或并发）发起手动计算
- **Then**: 不新增报告行，返回现有 current 族 id；在数据已变化但规则未变化时，正常产生 G1 下的新 current 族且旧族转 superseded
- **Pass Condition**: REST/计算器测试分别覆盖“无变化复用”和“仅数据变化新增”两种情形
- **Evidence**: test_quality_control.py 新增用例

### AC-8：项目报告只聚合同代际当前任务族并确定性重算缺口
- **Type**: `rule`
- **Given**: 项目 P 下任务 A 拥有 G_old 当前报告、任务 B 无报告；项目规则代为 G_project（=继承任务当前指纹）；另有 custom 任务 C
- **When**: 触发项目报告计算
- **When**: A 的旧族不被聚合且 A 在 G_project 下被内联重算，B 同样在 G_project 下计算，C 在其自身代际下计算；任一子族在项目聚合期间失配则整批废弃并重算整个项目
- **Then**: 项目 current 报告的任务/作业汇总、完成数、冲突计数、要求逐项分数仅来自同指纹 current 任务族；custom 任务保持 custom 桶且不并入指纹聚合；子报告连接完整
- **Pass Condition**: 扩展现有 `test_can_reuse_relevant_task_reports_in_project_report` 场景：修改项目规则后不出现 G_old 数字，所有汇总与子族代际一致；内联重算绑定的 generation_id 为项目代际
- **Evidence**: 项目计算器测试 + REST 项目报告测试

### AC-9：族状态转换与历史可读
- **Type**: `rule`
- **Given**: 目标存在 current 族；新族成功发布
- **When**: 发布事务提交
- **Then**: 旧任务根及其作业子报告（含冲突）统一变为 superseded，新族全部为 current；列表仍默认返回两类历史报告（含 legacy 空状态行），详情/data 下载可正常访问旧族；include_legacy/parent_id 过滤不回归
- **Pass Condition**: REST 测试断言状态转换、历史列表/详情/下载对 superseded 与 legacy 均可用
- **Evidence**: test_quality_control.py

### AC-10：冲突与矩阵下载跟随当前族
- **Type**: `rule`
- **Given**: 一个同时拥有 superseded 族与 current 族的任务
- **When**: 不带 report_id 按 task/project 列冲突，或由前端进入作业评审拉取冲突；以及对 current 报告下载 JSON/CSV/ZIP 矩阵
- **Then**: 无 report_id 的冲突列表只返回 current 族（沿父子关系）下的冲突；显式 report_id 仍精确返回该报告族冲突；矩阵下载内容与 current 族 summary 一致；legacy 报告矩阵端点继续 404/不可用而 JSON data 可下载
- **Pass Condition**: REST 测试覆盖两种冲突列入口径与三类下载，断言代际一致性与旧格式门控
- **Evidence**: test_quality_control.py 冲突/下载用例

### AC-11：API/前端端到端使用 current 状态选择报告
- **Type**: `rule`
- **Given**: 目标存在一个 superseded（id 更大但已取代）和一个 current 报告
- **When**: 标注页加载作业质量冲突、质量管理页加载任务/项目报告
- **Then**: 前端通过 `status=current` 过滤取得唯一 current 报告及其冲突/矩阵，任何界面不展示 superseded 族为当前结果
- **Pass Condition**: cvat-core 类型与 server-proxy 支持 status 参数；annotation-actions 与质量管理页数据加载显式传 current；TypeScript/lint/构建通过；手测或集成测试验证取到的报告 id 为 current
- **Evidence**: cvat-core/cvat-ui 代码与静态检查

### AC-12：权限与旧格式行为不回归
- **Type**: `rule`
- **Given**: 现有质量报告权限矩阵（admin/任务受派者/无权限用户、sandbox/org）
- **When**: 执行创建、状态查询、列表、详情、冲突、下载操作
- **Then**: 所有允许/拒绝结果与现状一致；reg/sql 无需变更即生效；legacy 报告继续默认从 UI 列表隐藏但可下载、可 include_legacy 读取
- **Pass Condition**: 现有 TestPostQualityReports/TestListQualityReports/TestGetQualityReportData 等权限与 legacy 用例全部通过
- **Evidence**: tests/python/rest_api/test_quality_control.py 全量相关用例

### AC-13：迁移与双数据库兼容
- **Type**: `rule`
- **Given**: 含既有质量报告/设置/要求的数据库
- **When**: 升级到含代际模型的迁移并在 PostgreSQL 与 SQLite 上运行
- **Then**: 旧报告 status/代际为空并按 legacy 处理；旧设置 rules_version=1；部分唯一索引/约束成功创建；migrate 无数据回填即可完成
- **Pass Condition**: 迁移可正向执行；SQLite 测试配置下全量质量测试通过；检查约束不阻塞存量行
- **Evidence**: 迁移文件与 CI 测试矩阵

### AC-14：实现质量与最小侵入
- **Type**: `rubric`
- **Dimension**: 设计一致性、可维护性与侵入面
- **Scale**: 1-5
- **Anchors**: 1 = 新增机制与现有时间戳/快照/RQ 方案重复或冲突，读取侧散落多套“当前”判定；3 = 机制可用但存在重复实现或绕过闸口的保存路径；5 = 代际解析、发布闸、族状态各有单一权威实现点，calculator/serializer/前端均复用
- **Pass Threshold**: >= 4
- **Evidence**: 独立代码评审

## Open Questions
- 无（三项关键决策已与用户确认：有界重算后废弃、无变化幂等复用、前后端一起改）。
