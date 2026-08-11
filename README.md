# WhoChat

WhoChat 是一个正在开发中的个人聊天 AI 助手。

它的目标不是接管你的社交，而是在你面对老板、客户、同事、朋友或暧昧对象时，帮你更快理解上下文、整理记忆，并给出更合适的回复建议。

项目当前处于 **Phase 0 技术探针 + 主路径可验证阶段**：已经有可运行的 PySide6 主窗口、单行贴边悬浮窗、SQLite 本地数据层、自定义 AI 设置入口、PaddleOCR 首选接入和自动化验证脚本。欢迎关注、讨论和点 Star。

## 想做什么

很多聊天回复并不难，但很消耗注意力：

- 老板发来一句模糊要求，不知道怎么回才显得靠谱。
- 客户追问进度，既要稳住对方，又不能过度承诺。
- 同事沟通反复横跳，需要保持边界。
- 暧昧聊天想自然一点，不想太生硬或太油。
- 朋友日常消息想好好回应，但不想每次都耗很久。

WhoChat 希望做成一个跟随聊天窗口的小助手：

- 识别当前正在聊天的人。
- 读取当前可见聊天上下文。
- 根据聊天对象画像、聊天记忆、用户偏好和分组目标生成回复建议。
- 用户点击建议后复制到剪贴板，再手动粘贴发送。
- 默认不自动发送，不后台遍历联系人，不读取微信数据库。

## 产品原则

- **用户掌控**：AI 只给建议，是否发送由用户决定。
- **低侵入**：优先使用截图和 OCR，不注入、不 Hook、不破解客户端。
- **本地优先**：联系人画像、聊天记忆和配置默认保存在本地。
- **外发可控**：确认联系人不等于允许云端 AI，第三方 Provider 外发需要联系人级授权。
- **可解释**：用户应该知道 AI 是基于哪些上下文和画像生成回复。
- **有人性**：亲密关系默认进入手动回复保护，不鼓励把所有关系都工具化。

## 计划中的能力

### 悬浮小部件

- 跟随当前焦点目标聊天窗口移动、隐藏和显示。
- 单行展示 `应用·昵称（分组） 回复1 回复2 回复3`，尽量贴在窗口外侧不遮挡聊天区。
- 点击真实回复建议即可复制；安全门控阻断时不会提供假建议。
- 用户主动隐藏后不会被轮询自动拉起；非聊天页会立即置灰旧建议。
- 支持贴靠优先位置、透明度、回复数量、暂停和隐藏。

### 聊天识别

- 通过截图和 OCR 获取当前可见聊天内容。
- 区分“我”和“对方”的消息。
- 判断当前页面是否真的是聊天页。
- 遇到公众号、新闻、设置、搜索等页面时暂停生成。
- 支持不同窗口尺寸、多显示器和用户调整过的聊天列表分割线，自动估算只是候选，用户校准优先。

### 聊天对象画像

- 私聊和群聊都是聊天对象，都可以放进同一套分组策略中。
- 平台联系人使用 `APP + 昵称` 作为线索，例如 `微信·小红`、`Telegram·大红`。
- OCR 识别到聊天标题后会立即建立聊天对象并用于本地建议；用户可后续确认、合并、改名或设为忽略。
- 用户可以把多个平台联系人手动链接为同一个真实人，例如把 `微信·小红` 和 `Telegram·大红` 合并到同一个 Person。
- 昵称不是唯一身份；同名可以是不同人，一个人也可以有多个昵称。
- AI 提取的新记忆默认等待用户确认。
- 低置信度 OCR 内容不直接写入长期画像。

### 群聊

群聊会作为独立聊天对象保存和分组。标题里的成员数后缀会被移除，例如 `项目群（12）` 和 `项目群(18)` 会归为同一个群对象，原始标题作为别名保留。群成员会单独记录为成员对象，可以链接到某个好友或跨平台身份，也可以保持未解析状态。系统不会只因为昵称相同就自动认定是同一个人。

### 聊天记录拼接

WhoChat 会尝试把多次截图中的可见消息拼接成持久聊天记录。只有当上下滚动后的页面和已有记录存在可靠重叠时才自动合并；跳页、重复短句、低置信度或边缘截断内容会先作为待确认片段处理。

### 分组策略

分组不是写死的。

系统可以提供一些预设，例如：

- 领导
- 客户
- 同事
- 朋友
- 暧昧或搭讪
- 手动回复保护

但每个用户都可以自定义目标和语气。比如同样是领导，有人想应付，有人想迎合，有人想保持边界，也有人只是想把话说清楚。

### 调试与整理

主窗口计划提供：

- 当前状态面板
- 简洁日志
- 当前聊天记录
- 当前聊天对象画像
- 聊天对象和分组列表
- 聊天对象详情页

这些模块主要用来让用户看清楚：系统现在识别的是谁、看到了什么、为什么生成这样的回复。

## 当前进度

- [x] 初始化项目仓库
- [x] 编写产品需求文档
- [x] 搭建 Python 虚拟环境
- [x] 创建 PySide6 桌面应用骨架
- [x] 创建主窗口信息架构
- [x] 创建悬浮窗原型
- [x] 增加自定义 AI 设置入口
- [x] 支持自定义 AI、隐私和采集设置本地保存
- [x] 设置保存前执行一致性校验，拦截无效云端地址、空模型、空 OCR 语言和无目标应用配置
- [x] API Key 优先保存到 Windows Credential Manager
- [x] 增加设置变更审计，记录 AI、隐私和采集配置差异且不保存密钥
- [x] 增加 SQLite 数据层、迁移和默认分组策略
- [x] 增加联系人、消息、记忆和日志仓储
- [x] 主窗口联系人、分组、诊断页开始接入真实数据源
- [x] 总览页接入真实运行态、联系人画像、聊天记录和记忆，不再展示硬编码示例聊天
- [x] 总览页增加运行链路，解释窗口、页面、联系人、采集、隐私和 AI 的通过/阻断状态
- [x] 总览页增加单行主动作条，从运行链路中提取当前最该处理的问题，减少用户翻表格和日志的成本
- [x] 总览页增加 OCR 状态环节，能看见运行中、完成、跳过、失败和冷却等待
- [x] OCR 状态支持标题快路径：标题已识别时先显示聊天对象，消息区仍读取中时不再混同为普通运行中
- [x] 悬浮窗在标题快路径下会先显示联系人与 OCR 读取中状态，不会被旧建议或 AI 阻断状态覆盖
- [x] 分组策略支持新增、复制和编辑
- [x] 分组策略支持搜索、归档和恢复；归档不会破坏已分配聊天对象
- [x] 聊天对象详情支持选择联动展示画像、聊天记录和记忆
- [x] 联系人可进入确认状态、编辑备注、调整分组和手动回复保护
- [x] 联系人确认、资料编辑和手动回复保护操作会同步刷新列表、详情、总览和悬浮窗状态
- [x] 记忆确认或拒绝后会同步刷新记忆列表、聊天对象详情、总览画像和状态提示
- [x] 联系人可独立控制是否允许将上下文发送给第三方 AI Provider
- [x] 支持联系人别名和手动合并，合并时迁移消息、记忆和 AI 审计
- [x] 支持联系人级数据导出和记录清空，清空时保留联系人资料、别名、备注和分组
- [x] 支持全局数据导出和全局内容清空，清空时保留策略、校准、配置和设置审计
- [x] 全局/联系人导出的生成审计和应用日志会执行最终脱敏，避免密钥、Bearer、手机号等元数据泄漏
- [x] 支持日志、调试样本、截图缓存和校准样本的本地保留期清理
- [x] 回复反馈支持独立保留期，过期记录会在本地清理中从 SQLite 删除
- [x] 增加跨应用身份层模型，支持 `APP + 昵称` 联系人线索手动链接到同一个 Person
- [x] 聊天对象详情增加身份页，支持查看/创建/链接真实身份和维护身份别名
- [x] 增加群成员模型，支持群成员和好友重叠或保持未解析
- [x] 聊天对象详情增加群成员页，支持维护群成员候选、链接真实身份和平台对象
- [x] 增加聊天记录滚动拼接器，基于可见页重叠保守合并上下文
- [x] 采集入库已接入聊天记录拼接器，滚动重复内容不会反复写入
- [x] OCR 可识别明显的居中时间锚点，并在入库时保存 `message_time` 与 `time_source`
- [x] AI 提取记忆支持待确认、确认和拒绝流程
- [x] 增加微信窗口查找探针
- [x] 增加可配置目标应用列表，支持多选启用、新增/删除自定义项、编辑进程名/标题关键词/排除标题和当前焦点窗口优先跟随
- [x] 微信默认排除图片视频预览、设置、转发等非聊天子窗口，避免误触发截图和 PaddleOCR
- [x] 增加前台白名单窗口门控：目标最小化、非前台或被其他前台窗口覆盖时暂停采集，避免截到遮挡窗口内容
- [x] 增加悬浮窗贴靠目标聊天窗口的基础控制器
- [x] 目标窗口缺失、最小化或不可见时隐藏悬浮窗并暂停采集
- [x] 悬浮窗支持贴靠优先位置、透明度和可见回复数量配置，保存后立即应用
- [x] 悬浮窗贴靠移动不再覆盖 OCR/AI 业务状态；贴靠边缘只作为调试信息保留
- [x] 悬浮窗接入真实联系人、分组、风险状态和回复建议；阻断状态下禁用复制按钮
- [x] 增加离屏 UI 验证脚本
- [x] 增加运行态模型、微信适配器几何布局估算和采集门控验证
- [x] 增加区域校准数据表、持久化和诊断页校准入口
- [x] 微信适配器优先使用用户保存的 active 校准布局
- [x] 增加截图覆盖层式区域校准画布，支持拖动区域并保存相对比例
- [x] 增加可替换 OCR 抽象和校准覆盖层 OCR 预览候选框
- [x] 增加 OCR Provider 配置和首选本地 PaddleOCR 适配器
- [x] 切换 OCR Provider 时会先释放旧 OCR 引擎，避免 PaddleOCR daemon 残留
- [x] 增加 OCR 区域归属、页面证据分类和基础消息候选解析
- [x] OCR 基础分类支持私聊/群聊区分，群聊标题会以群聊对象入库
- [x] OCR 页面分类会优先识别设置页、公众号/服务号和文章页，并阻断 AI 回复与入库
- [x] 增加截图-OCR-解析异步采集管线骨架，支持重复截图和旧任务丢弃
- [x] 采集管线优先裁剪右侧内容区送入 OCR，并把图片内坐标映射回窗口布局坐标
- [x] 采集管线拆分标题区快路径和消息区慢路径，标题 OCR 完成后可先识别聊天对象
- [x] 采集管线写入截图 hash、裁剪区域、OCR 状态和页面分类元数据，不保存聊天原文
- [x] 增加自动采集控制器，目标窗口轮询后可按防抖策略自动触发采集
- [x] 增加 PaddleOCR 自动采集稳定性保护：完整主流程结束后冷却、运行中保留一个待处理请求、连续失败熔断和本地诊断日志
- [x] 增加采集结果入库服务，可信聊天页可自动创建可用聊天对象并保存拼接后的新增消息
- [x] 增加 AI 回复生成服务边界、离线候选生成和安全阻断
- [x] 增加 AI 生成审计日志，记录上下文 hash 和风险摘要但不保存密钥或完整聊天文本
- [x] 增加云端 AI 请求治理：冷却时间、相同上下文去重和每日请求上限
- [x] 主窗口回复生成改为后台任务，真实 Provider 慢响应不会阻塞 UI
- [x] 增加 AI Provider 健康状态和失败退避，连续失败后会暂缓云端请求
- [x] 设置页支持查看并手动恢复 AI Provider 健康状态
- [x] 设置页“测试连接”会发起真实轻量 Provider 请求，本地预览/禁用模式不会发起网络请求
- [x] AI Provider 健康状态会本地持久化，重启后仍尊重退避窗口
- [x] Provider 退避过期后会本地转入 recovering，不主动发起网络重试
- [x] 增加云端请求前上下文预览和本地脱敏，预览内容与实际请求共用同一套 prompt 构造
- [x] 底层 AI 生成器强制要求已识别聊天对象；未知联系人即使配置了云端 API Key 也不会发起 Provider 请求
- [x] 回复建议面板展示生成证据摘要：聊天对象、分组、消息数、记忆数、页面类型和云端授权状态
- [x] 每条回复建议可见风险等级和简短依据，阻断状态也保留同一套上下文证据
- [x] 回复建议支持标记“好用/不合适”，反馈写入本地 `reply_feedback` 表并纳入导出/清空治理
- [x] 聊天对象详情增加“回复反馈”页，可查看最近反馈、好用/不合适计数和候选短预览
- [x] 诊断页和诊断包展示最近回复反馈质量摘要，便于观察建议是否持续偏差
- [x] 增加 AI Provider 诊断日志，记录耗时、状态和错误摘要且不保存密钥或完整 prompt
- [x] 诊断页增加环境自检，覆盖 Python、依赖、数据目录和密钥后端
- [x] 环境自检展示当前 OCR Provider、Paddle worker 模式、超时和 OCR 缓存目录
- [x] 诊断页增加目标窗口匹配摘要，显示启用目标、相关候选窗口、进程匹配/标题匹配原因
- [x] 目标窗口诊断摘要会显示前景状态、是否命中、是否被排除标题阻断和下一步动作
- [x] 目标窗口诊断支持单独刷新和复制，复制内容会执行脱敏，便于用户贴出最小排障信息
- [x] 诊断页日志支持按级别过滤，复制和导出仍保留完整日志
- [x] 诊断复制和调试样本导出增加最终脱敏保护，拦截密钥、认证头、邮箱、链接、手机号和长数字
- [x] 调试样本导出包含标题快路径 OCR 元数据和标题裁剪图，便于定位联系人识别问题
- [x] 诊断页和复制诊断包展示标题快路径 OCR 摘要，可直接查看标题裁剪、候选文本和 warning
- [x] 诊断页运行态展示联系人识别/入库摘要，区分标题缺失、OCR warning、页面阻断和已创建疑似联系人
- [x] 采集管线记录标题 OCR、消息区 OCR 和总耗时，诊断样本可定位性能瓶颈
- [x] 采集样本元数据持久化标题裁剪、标题/消息区 OCR 耗时和总耗时，便于长期观察性能
- [x] 诊断页和复制诊断包展示最近采集样本性能摘要，直接查看 title/content/total OCR 耗时
- [x] 诊断性能摘要支持最近样本平均耗时和最慢 job，便于判断 OCR 是否退化
- [x] 诊断性能摘要提供 ok/warning/slow 分级和处理建议，帮助用户判断是否需要调整 OCR 间隔或重新校准
- [x] 自动采集会根据最近 PaddleOCR 总耗时动态降频，warning/slow 时避免滚动或窗口变化触发连续重 OCR
- [x] 手动运行采集管线失败时会显示具体阻断原因，例如目标窗口缺失、用户暂停、区域不可用或 OCR 冷却
- [x] 应用退出时统一停止窗口轮询、自动采集、采集线程池、回复线程池和 PaddleOCR daemon，避免后台资源残留
- [x] 增加当前前台聊天诊断探针，输出窗口匹配、截图、标题裁剪、标题 OCR 耗时和联系人候选数量
- [x] 技术探针：识别微信窗口
- [x] 技术探针：悬浮窗跟随微信
- [x] 技术探针：截图和 OCR 预览骨架
- [x] 技术探针：真实 OCR Provider 适配入口，默认首选 PaddleOCR
- [x] 技术探针：真实 OCR 依赖安装与截图样本效果验证
- [x] 技术探针：点击复制回复
- [ ] MVP：企业级主窗口和悬浮小部件持续完善
- [ ] MVP：真实当前聊天页识别
- [ ] MVP：真实 AI 回复建议和请求审计
- [ ] MVP：本地联系人画像

详细需求见 [docs/PRD.md](docs/PRD.md)，企业级完善计划见 [docs/ENTERPRISE_PLAN.md](docs/ENTERPRISE_PLAN.md)。

## 本地运行

PaddleOCR/PaddlePaddle 当前建议使用 Python 3.12。项目已配置 `.venv312` 作为 VS Code F5 默认运行环境。
Windows 窗口识别依赖 `pywin32`，并使用 `psutil` 作为进程名读取回退，避免 `tasklist` 权限问题导致只能靠标题匹配。

```powershell
.venv312\Scripts\python -m whochat.app
```

运行 UI 验证：

```powershell
.venv312\Scripts\python tools\smoke_ui.py
```

验证主路径端到端闭环：

```powershell
.venv312\Scripts\python tools\verify_main_path.py
.venv312\Scripts\python tools\verify_non_chat_main_path.py
```

运行微信窗口探针：

```powershell
.venv312\Scripts\python tools\probe_wechat_window.py
.venv312\Scripts\python tools\diagnose_window_matching.py
```

运行截图探针：

```powershell
.venv312\Scripts\python tools\probe_screenshot.py
.venv312\Scripts\python tools\probe_current_chat.py --redact
.venv312\Scripts\python tools\probe_current_chat.py --wait-seconds 3 --redact
```

如果当前执行环境无法访问真实桌面，截图探针会生成 `tmp/probe/screenshot_unavailable.png` 作为诊断结果；在普通 Windows 桌面会优先尝试截取当前前台白名单聊天窗口。目标应用在后台、最小化或被其他前台窗口覆盖时不会采集。
`probe_current_chat.py` 默认只跑标题 OCR，用来定位“窗口已匹配但联系人没识别”的问题；阻断时会列出相关窗口候选、前景状态和 `window_api` 状态。加 `--wait-seconds 3` 后可在倒计时内切到目标聊天窗口；加 `--messages` 会继续识别消息区，耗时更长。`--redact` 会隐藏识别出的标题文本，只保留候选数量和耗时。

验证数据层：

```powershell
.venv312\Scripts\python tools\verify_storage.py
.venv312\Scripts\python tools\verify_migration_validation.py
.venv312\Scripts\python tools\verify_schema_migration.py
```

验证联系人合并：

```powershell
.venv312\Scripts\python tools\verify_contact_merge.py
.venv312\Scripts\python tools\verify_contact_action_sync.py
.venv312\Scripts\python tools\verify_memory_review_sync.py
```

验证分组策略搜索、归档和恢复：

```powershell
.venv312\Scripts\python tools\verify_strategy_management.py
```

验证跨应用身份和群成员模型：

```powershell
.venv312\Scripts\python tools\verify_identity_model.py
```

验证跨应用身份 UI：

```powershell
.venv312\Scripts\python tools\verify_identity_ui.py
```

验证群成员 UI：

```powershell
.venv312\Scripts\python tools\verify_group_members_ui.py
```

验证滚动截图的聊天记录拼接：

```powershell
.venv312\Scripts\python tools\verify_transcript_stitcher.py
```

验证联系人级数据导出和清空：

```powershell
.venv312\Scripts\python tools\verify_data_governance.py
```

验证全局数据导出和清空：

```powershell
.venv312\Scripts\python tools\verify_global_governance.py
```

验证本地诊断文件保留期清理：

```powershell
.venv312\Scripts\python tools\verify_retention_cleanup.py
```

验证云端 AI 请求治理：

```powershell
.venv312\Scripts\python tools\verify_ai_request_policy.py
```

验证异步回复生成任务：

```powershell
.venv312\Scripts\python tools\verify_reply_tasks.py
.venv312\Scripts\python tools\verify_reply_stale_ui.py
```

验证应用退出生命周期：

```powershell
.venv312\Scripts\python tools\verify_shutdown_lifecycle.py
```

验证 AI Provider 健康状态和失败退避：

```powershell
.venv312\Scripts\python tools\verify_provider_health.py
.venv312\Scripts\python tools\verify_provider_health_ui.py
.venv312\Scripts\python tools\verify_provider_health_persistence.py
```

验证 AI Provider 诊断日志：

```powershell
.venv312\Scripts\python tools\verify_ai_connection_test.py
.venv312\Scripts\python tools\verify_ai_provider_diagnostics.py
```

验证云端 prompt 预览和脱敏：

```powershell
.venv312\Scripts\python tools\verify_prompt_privacy.py
```

验证配置安全：

```powershell
.venv312\Scripts\python tools\verify_config_security.py
.venv312\Scripts\python tools\verify_settings_validation.py
```

验证设置变更审计：

```powershell
.venv312\Scripts\python tools\verify_settings_audit.py
```

验证窗口运行态、区域估算和采集门控：

```powershell
.venv312\Scripts\python tools\verify_runtime.py
```

验证窗口最小化、标题匹配和悬浮窗隐藏诊断：

```powershell
.venv312\Scripts\python tools\verify_window_diagnostics.py
.venv312\Scripts\python tools\verify_floating_content.py
.venv312\Scripts\python tools\verify_floating_preferences.py
.venv312\Scripts\python tools\verify_floating_follow_behavior.py
```

验证环境自检和诊断导出：

```powershell
.venv312\Scripts\python tools\verify_environment_diagnostics.py
.venv312\Scripts\python tools\verify_diagnostics_actions.py
.venv312\Scripts\python tools\verify_debug_sample_export.py
.venv312\Scripts\python tools\verify_ingestion_diagnostics.py
```

验证不同尺寸和屏幕位置的响应式布局估算：

```powershell
.venv312\Scripts\python tools\verify_layout_responsiveness.py
```

验证自动采集控制器：

```powershell
.venv312\Scripts\python tools\verify_autocapture.py
.venv312\Scripts\python tools\verify_autocapture_performance.py
.venv312\Scripts\python tools\verify_manual_capture_feedback.py
```

验证多目标应用配置、自定义应用、匹配规则编辑和焦点优先跟随：

```powershell
.venv312\Scripts\python tools\verify_target_windows.py
.venv312\Scripts\python tools\verify_window_match_diagnostics_ui.py
```

验证区域校准覆盖层：

```powershell
.venv312\Scripts\python tools\verify_calibration_ui.py
```

验证 OCR 解析骨架：

```powershell
.venv312\Scripts\python tools\verify_ocr_parser.py
```

验证 OCR golden 样本回放：

```powershell
.venv312\Scripts\python tools\verify_ocr_goldens.py
```

验证截图样本回放：

```powershell
.venv312\Scripts\python tools\verify_screenshot_samples.py
```

验证 OCR Provider 配置和可选适配器：

```powershell
.venv312\Scripts\python tools\verify_ocr_providers.py
```

回放单张截图样本，输出 OCR 框、页面分类和消息候选：

```powershell
.venv312\Scripts\python tools\replay_ocr_sample.py path\to\screenshot.png --provider PaddleOCR
```

批量截图样本放在 `fixtures/screenshot_samples/<sample_name>/`：

- `sample.png`：截图，可使用脱敏后的真实微信截图。
- `layout.json`：窗口区域布局。
- `manifest.json`：图片、布局、预期页面类型和消息断言。

默认 `verify_screenshot_samples.py` 使用 manifest 中的结构化 OCR 框，不初始化真实 OCR 模型；需要实测 PaddleOCR 时可以加 `--provider PaddleOCR`。

把单张截图回放结果导出为样本：

```powershell
.venv312\Scripts\python tools\replay_ocr_sample.py path\to\redacted.png --layout path\to\layout.json --provider PaddleOCR --output tmp\replay.json
.venv312\Scripts\python tools\export_screenshot_sample.py --replay-json tmp\replay.json --name wechat_dm_real_redacted_001
```

导出后请人工检查 `sample.png` 和 `manifest.json`，确认截图和 OCR 文本已经脱敏，再纳入长期样本。

也可以从应用诊断页保存的 debug sample 导出：

```powershell
.venv312\Scripts\python tools\export_screenshot_sample.py --debug-sample-dir .whochat-data\debug_samples\sample-xxx --name wechat_dm_debug_redacted_001
```

可选安装真实本地 OCR：

```powershell
pip install -e ".[rapidocr]"
.venv312\Scripts\python -m pip install -e ".[paddleocr]"
```

新配置默认首选 `PaddleOCR`。`Preview Fixture` 只用于验证坐标流，不是真实文字识别；如果更重视本地轻量部署和启动速度，可以尝试 RapidOCR。
PaddleOCR 的自动采集默认按完整主流程结束后的 30 秒级冷却执行，并优先通过常驻子进程 worker 复用已加载模型；CPU worker 默认 90 秒超时，连续失败会临时熔断，避免滚动时反复重载模型导致桌面卡死。采集管线会优先裁剪右侧内容区送入 OCR，降低整窗识别开销。需要调整时可设置 `WHOCHAT_HEAVY_OCR_MIN_INTERVAL_MS`、`WHOCHAT_PADDLEOCR_TIMEOUT_SECONDS`、`WHOCHAT_PADDLEOCR_WORKER_MODE` 和 `WHOCHAT_PADDLEOCR_FAILURE_COOLDOWN_SECONDS`。
自动采集还会读取最近采集样本的 PaddleOCR 总耗时：平均超过 15 秒会拉长间隔，超过 45 秒会进入更保守的 slow 间隔；手动运行采集管线不受这层自动降频影响。
`fixtures/ocr/` 里的 golden JSON 样本用于回放结构化 OCR 结果，验证私聊/群聊页面分类、非聊天页阻断、消息归属、群成员昵称行过滤、时间锚点和 partial 处理，不依赖真实桌面或模型初始化。

验证采集结果入库：

```powershell
.venv312\Scripts\python tools\verify_ingestion.py
```

验证 AI 回复生成门控：

```powershell
.venv312\Scripts\python tools\verify_reply_generator.py
.venv312\Scripts\python tools\verify_reply_explainability.py
.venv312\Scripts\python tools\verify_reply_feedback.py
.venv312\Scripts\python tools\verify_reply_feedback_diagnostics.py
```

验证 AI 生成审计：

```powershell
.venv312\Scripts\python tools\verify_generation_audit.py
```

验证异步采集管线：

```powershell
.venv312\Scripts\python tools\verify_pipeline.py
.venv312\Scripts\python tools\verify_pipeline_ocr_crop.py
.venv312\Scripts\python tools\verify_capture_samples.py
```

## 低风险边界

WhoChat 的 MVP 不做：

- 自动发送消息
- 自动点击左侧聊天列表
- 批量遍历联系人
- 读取微信本地数据库
- 注入、Hook 或修改微信客户端
- 自动打开图片、语音、链接、小程序

未来即使支持更高级的自动化，也应该默认关闭，并由用户明确开启。

## 为什么开源

聊天助手这件事很容易做歪。

它可以是一个节省注意力的工具，也可能变成一个过度自动化、污染关系、侵犯隐私的东西。开源的意义是让设计边界、实现方式和风险控制都能被看见、被讨论、被改进。

如果你也对这个方向感兴趣，欢迎 Star、提 Issue 或参与讨论。
