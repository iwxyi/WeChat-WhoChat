# Enterprise Completion Plan

WhoChat 的目标不是做一个能展示窗口的 demo，而是做成一个本地优先、可验证、可审计、低风险的桌面聊天辅助应用。下面是长期 goal 的执行计划和验收标准。

## 1. 产品与交互

### 当前已完成

- 主窗口信息架构：总览、聊天对象、分组、记忆、设置；排障工具收纳在总览链路和设置页。
- 总览页接入真实运行态、当前聊天对象画像、最近一次完整 OCR 结果和记忆摘要，不再展示硬编码示例聊天；结果展示说话人、消息时间、置信度和状态。
- 总览页增加运行链路，逐项解释窗口、页面、联系人、采集、OCR、隐私和 AI 的通过/阻断状态。
- 总览页和悬浮窗为阻断状态增加下一步建议，减少只看见“失败”但不知道该怎么处理的问题。
- 微信贴边悬浮窗：优先贴在微信窗口外侧的底部或顶部，空间不足时隐藏，避免遮挡微信。
- 悬浮窗用户主动隐藏后不会被轮询逻辑自动拉起。
- 悬浮窗支持贴靠优先位置、透明度和可见回复数量设置，启动和保存设置后立即应用。
- 悬浮窗接入真实聊天对象、分组策略、AI 状态和回复建议；主形态为单行 `应用·昵称（分组） 回复1 回复2 回复3`，阻断状态禁用复制按钮，避免展示固定假建议或旧上下文建议。
- 悬浮窗建议按钮显示回复正文短前缀并固定尺寸，完整长文本保留在 tooltip，复制仍使用完整回复。
- 总览页回复建议已移到右侧栏底部独立滚动区域，主区域优先展示运行链路和最近一次 OCR 结果。
- 自定义 AI 设置入口：Provider、Base URL、Model、API Key、温度、上下文长度、超时。
- 分组策略可新增、复制、编辑，不把目标写死。
- 分组策略可搜索、归档和恢复；归档不会删除历史引用，也不会破坏已分配聊天对象。
- 聊天对象详情可随列表选择联动展示画像、身份链接、聊天记录和记忆。
- 联系人页支持确认、编辑显示名称、备注、确认等级、分组策略和手动保护。
- 新识别聊天对象的第三方 AI 外发授权默认开启，可在聊天对象详情中单独关闭；关闭后仍保留本地识别和整理能力。
- OCR 完成并识别到聊天对象和消息后自动提交 AI 请求，默认生成恰好 3 条建议并更新悬浮窗，用户点击建议复制后手动发送。
- AI 请求期间上下文发生变化时保留旧建议；直到下一次 AI 请求真正开始才替换为“生成中”。
- 联系人支持手动添加别名和合并，合并后源联系人隐藏。
- 联系人页支持导出数据和清空记录，清空前需要用户确认。
- 记忆支持待确认、确认、拒绝的人机协作流程。

### 下一步

- 总览链路已包含窗口、页面、联系人、采集、OCR、隐私和 AI 环节；设置页提供复制运行日志、保存调试样本、立即采集和重新校准区域。
- 分组页面继续增加删除、风险提示和个人覆盖策略。
- 联系人页面增加更完整的合并历史展示。
- 记忆页面增加编辑、批量确认、来源消息回看、过期时间。
- 设置页继续优化 OCR、AI 和隐私配置的信息密度与风险提示。
- 悬浮窗继续增强单行/多行建议布局、风险状态颜色和更细的贴靠策略。

## 2. 平台与识别

### 当前已完成

- Windows 微信窗口探针。
- 按进程名优先识别微信窗口，避免项目名或 VS Code 窗口误匹配。
- 可配置目标应用列表，默认启用微信，可启用 Telegram 和通用聊天目标；用户可新增/删除自定义目标并编辑进程名和标题关键词匹配规则。
- 目标窗口跟随优先选择当前焦点窗口；焦点不是受支持目标时，回退到最大的受支持窗口。
- 目标窗口最小化、不可见或缺失时隐藏悬浮窗并暂停采集；仅标题匹配时在诊断中提示补充进程名或检查权限。
- 微信窗口截图探针。
- 运行态模型：窗口状态、页面类型、区域估算、截图门控、暂停状态。
- `PlatformAdapter` 接口和微信/通用聊天目标适配：微信输出三栏几何布局估算，通用聊天使用低置信度保守布局。
- 页面未确认时默认阻断 AI 回复流程。
- 区域校准持久化：按相对窗口比例保存 active 校准。
- 总览和设置页可打开截图覆盖层式区域校准对话框，拖动导航、聊天列表、标题、聊天记录和输入区。
- 校准对话框支持比例微调，保存后仍只记录相对窗口比例。
- 微信适配器优先使用用户校准布局，再回退自动估算。
- 微信自动布局估算已按窗口宽度和宽高比选择 compact / standard / wide profile，避免单一固定比例。
- 自动布局支持多显示器负坐标和任意窗口原点，并保留内容区最小宽度。

### 下一步

- 建立窗口状态模型：不存在、最小化、遮挡、可见、移动中、缩放中。
- 建立页面类型分类：聊天、群聊、文件传输助手、公众号、文章、设置、搜索、图片查看器、未知。
- 建立区域识别模型：导航栏、聊天列表、标题、消息区、输入区。
- 同时支持自动区域识别和用户校准，用户校准优先。
- 保存校准结果为相对窗口比例，兼容窗口大小、DPI 和分割线调整。
- 支持同一平台的多套校准 profile，后续按窗口尺寸、DPI、主题和平台版本选择最接近的一套。
- 下一步将在覆盖层中加入 OCR 预览和视觉分割线建议。
- 已加入可替换 OCR 抽象和校准覆盖层 OCR 预览候选框；当前预览引擎用于验证坐标流，不代表真实 OCR。
- 已加入 OCR Provider 配置和首选本地 PaddleOCR 适配器；Python 3.12 环境已验证真实 PaddleOCR 推理链路。
- 已加入 OCR 区域归属、页面证据分类和基础消息候选解析；当前用于打通数据流，未宣称完整还原聊天记录。
- 下一步继续用真实截图样本验证中文聊天识别效果，并在覆盖层中加入视觉分割线建议。
- 已加入采集结果入库服务：只有聊天页和标题 OCR 证据达标时，才创建疑似聊天对象，并通过聊天记录拼接器写入可靠新增消息。
- 已加入明显居中时间锚点识别，拼接和入库会保存 OCR 解析出的 `message_time` 与 `time_source`；消息时间只使用聊天界面中解析出的时间，不能用采集或 OCR 完成时间代替。
- PaddleOCR 裁剪结果统一映射回完整截图坐标系；裁剪、气泡采样和框索引均有边界保护，避免 `image index out of range`。

## 3. OCR 与上下文

### 当前已完成

- 已建立可替换 OCR 引擎接口和结构化结果：文本、坐标、置信度、截图来源。
- 已建立 OCR Provider 工厂，支持 Preview Fixture、RapidOCR、PaddleOCR；新配置默认首选 PaddleOCR。
- 设置页可配置 OCR Provider、语言、最低置信度和 GPU 开关。
- 已建立基础解析：OCR 文本框按布局归属到标题、聊天列表、消息区和输入区；消息区候选按水平位置推断我/对方；标题含群聊特征时分类为群聊，群成员昵称行不作为正文入库。
- 已建立非聊天页阻断分类：设置页、公众号/服务号、文章页会在聊天页判断前优先识别，避免误触发 AI 和入库。
- 识别 `me`、`other`、`member`、`system`、`unknown`。
- 不允许用 LLM 编造 OCR 缺失内容。
- 未知页面、低置信度 OCR 不写入长期记忆。
- OCR 识别到聊天标题后会立即创建可用聊天对象；疑似联系人可用于本地建议，等待用户后续确认、合并或忽略。

### 下一步

- 继续用真实微信截图样本验证中文识别效果和气泡归属准确率。
- 使用 `tools/replay_ocr_sample.py` 回放截图样本，形成 OCR 框、页面分类和消息候选的可审计输出。
- 根据消息气泡位置、头像、文本坐标和时间戳解析消息。
- 对跨页、截断、重复消息做更完整的去重和 `partial` 标记。

## 4. 性能与任务队列

### 当前已完成

- 截图 hash 去重，内容无变化不触发 OCR。
- 截图门控基础实现：暂停、窗口不可见、区域低置信度、节流、重复截图跳过。
- 窗口移动、缩放、滚动时进入防抖等待。
- 已建立截图-OCR-解析异步采集管线骨架，UI 线程不直接执行采集任务。
- 采集管线支持单 worker、旧任务取消、重复截图丢弃、过期结果丢弃。
- 采集管线会优先裁剪右侧内容区送入 OCR，并把图片内坐标映射回窗口布局坐标，降低真实 OCR 成本并支持非零屏幕坐标窗口。
- 采集管线会写入采集样本元数据：目标应用、截图 hash、OCR 裁剪图路径、裁剪区域、OCR 状态、页面分类和消息数量；默认不写聊天原文。
- 已建立自动采集控制器：窗口轮询刷新运行态后，按防抖策略自动提交截图-OCR-解析管线。
- 自动采集尊重用户暂停、自动采集开关、截图节流和运行中任务保护。
- 已增加 PaddleOCR 自动采集稳定性保护：完整主流程结束后冷却、运行中保留一个待处理请求、连续失败短期熔断，并写入 `capture_pipeline` / `ocr_worker` 诊断日志。
- 采集管线结果可进入本地消息库，支持消息 fingerprint 去重。
- 每类采集任务只保留最新请求，旧结果带 snapshot hash 校验后再展示。
- 已增加云端 AI 请求治理：相同上下文 hash 在配置窗口内不重复请求，快速连点进入冷却阻断。
- 已增加每日云端请求上限，并把限额阻断写入 AI 生成审计。
- 已增加后台回复生成任务服务，主窗口提交 AI 任务后立即返回，结果通过 Qt 信号回写 UI。
- 回复任务运行中拒绝并行提交，避免真实 Provider 被重复打爆。
- 已增加 AI Provider 健康状态：连续失败计数、退避阻断和成功恢复。
- 设置页已增加 AI Provider 健康状态展示、真实轻量连接测试和手动恢复入口，测试与恢复操作写入诊断日志和 app 日志。
- Provider、接口地址、模型或 API Key 变更并保存后会自动清除历史退避，避免修正配置后仍被旧失败状态阻断。
- AI Provider 健康状态已本地持久化，重启后仍会尊重退避窗口，不会立刻重复打失败 Provider。
- Provider 退避过期后会由本地定时检查转入 recovering 状态，不主动发起网络请求。
- 自动采集主流程按窗口状态、截图指纹、OCR、解析、入库、AI 串行执行；完整主流程结束后默认等待 5 秒再尝试下一轮。多联系人切换时保留多张近期图片指纹缓存，内容未变化时跳过 OCR。
- 相同上下文命中云端请求去重时复用当前会话内缓存的建议，避免空的阻断结果覆盖悬浮窗；OCR 刷新期间保留同一会话建议，只有窗口失效或最终确认联系人变化才清空。

### 下一步

- 继续优化 PaddleOCR 性能，评估常驻 worker 或裁剪区域识别，减少每次识别的模型初始化成本。
- 增加 Provider 网络重试策略和用户可见的重试按钮。

## 5. AI 与安全

### 当前已完成

- API Key 保存到本地配置文件，便于个人使用和排障。
- 诊断、审计和导出边界不明文输出 API Key。
- 日志不记录 API Key。
- 建立统一 `ReplyGenerator` 服务边界，UI 不再硬编码回复候选。
- 支持离线 Local Preview 候选生成，便于无网络、无 Key 时验证交互闭环。
- 支持 OpenAI-compatible `/chat/completions` 调用路径，用户配置 API Key 后可发起真实请求。
- 结构化输出解析：候选回复、依据、风险。
- 手动回复保护、未知页面、被忽略聊天对象会阻断可复制回复。
- 第三方 AI Provider 有 API Key 时，新聊天对象默认允许外发；用户可按聊天对象关闭授权，关闭后只允许本地预览或直接阻断。
- 云端 AI 请求支持冷却时间、相同上下文去重和每日请求上限。
- AI Provider 连续失败会进入退避期，期间不再反复请求第三方接口。
- 手动测试或设置场景可预览上下文；自动 OCR 主流程不弹确认框，识别完成后直接提交后台任务。
- Prompt 构造抽为统一模块，预览内容与真实 OpenAI-compatible 请求共用同一套 system/user prompt。
- 默认启用本地脱敏，识别邮箱、手机号、链接、长数字和常见 API key 形态。
- 设置页的隐私与采集选项会从配置加载并持久化保存。
- 增加 `generation_logs` 审计表和 repository，记录生成时间、联系人、策略、Provider、模型、上下文 hash、页面类型、消息/记忆数量、风险摘要。
- AI 生成审计不保存 API Key，也不保存完整聊天文本。
- 总览链路展示 AI 允许或阻断的主要原因；排障工具可复制完整脱敏诊断包。
- AI Provider 诊断日志记录 endpoint 主机、耗时、状态和错误摘要，不记录 API Key、完整 prompt 或聊天原文。
- 总览链路已接入环境和窗口状态摘要；设置页提供复制日志和保存调试样本入口。
- 运行日志仍支持按 debug/info/warning/error 过滤；复制日志和保存调试样本仍包含完整日志。
- 总览和设置页的日志复制、调试样本导出已接入最终脱敏层，即使未来日志误写入密钥、认证头、邮箱、链接、手机号或长数字，也会在导出边界拦截。
- Debug sample 会包含最后一次采集的结构化 layout、OCR boxes 和 parsed messages；开启截图样本保存后，可从设置页排障工具导出为 screenshot sample fixture。

### 下一步

- Prompt 输入分层，聊天内容不能覆盖系统规则。
- 增加更完整的脱敏规则和可解释的发送差异视图。
- 高风险内容生成保守建议，并提示用户自行判断。
- 增加本地脱敏策略和联系人级别外发开关。

## 6. 数据与审计

### 当前已完成

- SQLite 数据库、WAL、迁移框架。
- 表：strategies、contacts、contact_aliases、messages、memories、app_logs、settings_audit。
- 默认分组策略和手动回复保护。
- 联系人、消息、记忆、日志 repository。
- 采集入库服务会将可信聊天页中的标题 OCR 识别为疑似聊天对象，并保存拼接后确认新增的 OCR 文本消息。
- 联系人 repository 支持别名、资料更新和手动合并。
- 合并联系人时迁移消息、记忆和 AI 生成审计，并保留源联系人显示名与别名。
- 联系人级数据导出：包含联系人资料、别名、消息、记忆和 AI 生成审计元数据。
- 联系人级记录清空：删除消息、记忆和 AI 生成审计，保留联系人资料、别名、备注和分组。
- 全局数据导出：导出策略、聊天对象、身份、群成员、消息、记忆、生成审计、设置审计、校准和最近 app 日志。
- 全局内容清空：删除聊天对象、身份、群成员、消息、记忆和生成审计，保留策略、校准、设置审计和配置。
- 已新增身份层数据模型：Person、PersonAlias、ContactPersonLink 和 GroupMember，支持 `APP + 昵称` 联系人线索手动链接到真实人。
- 聊天对象详情已新增身份页，可查看已链接 Person、同名候选、创建真实身份、链接同名身份和维护身份别名。
- 聊天对象详情已新增群成员页，可维护群成员候选，链接真实身份或已有平台聊天对象。
- 私聊和群聊统一作为聊天对象，均可分配分组策略。
- 已新增聊天记录拼接器：基于可见窗口重叠前接、后接或判定待确认片段。
- 已把 PaddleOCR 自动采集调为主流程完成后冷却：默认 5 秒，子进程 90 秒超时，失败后熔断；采集管线会缓存最近多个标题区和聊天区图片指纹，内容未变化时跳过 OCR。
- 已新增设置变更审计：记录 AI、隐私和采集配置差异，API Key 只记录是否变更，不保存明文。
- 已新增本地文件保留期清理：按天数清理日志、调试样本、截图缓存和校准样本，不默认清理数据库、导出文件或 OCR 模型缓存。

### 下一步

- 增加 conversations、screenshots 表。
- 已增加 `layout_calibrations` 表，保存平台、主题、DPI、相对区域和 active 状态。
- 已增加 `generation_logs` 表，保存 AI 生成审计元数据和上下文 hash。
- 支持截图样本默认关闭保存，调试模式明确提示。
- 可选加密联系人画像和记忆数据库。

## 7. 自动化验证

### 当前已完成

- 编译检查。
- 存储层验证。
- 配置安全验证。
- Offscreen UI smoke 截图验证。
- 主路径端到端验证：窗口运行态、采集、OCR、自动创建聊天对象、入库、回复生成、悬浮窗复制和审计写入串联通过。
- 非聊天主路径验证：先生成可用建议后切到设置页，要求不新增聊天记录、不触发可用建议、悬浮窗旧按钮置灰。
- Offscreen UI smoke 会断言总览页使用真实联系人消息和记忆，避免回退到硬编码示例数据。
- 状态链路验证：未知页面、自动识别聊天对象、忽略对象、OCR 运行/完成/失败/冷却、云端未授权和就绪状态都有明确环节状态。
- 微信窗口探针和截图探针。
- 运行态验证：窗口状态、区域顺序、unknown 页面阻断、暂停、截图 hash 去重。
- 窗口诊断验证：最小化窗口会阻断采集并隐藏悬浮窗，标题匹配窗口会保留权限/规则诊断。
- 悬浮窗偏好验证：贴靠优先位置、透明度和可见回复数量可保存并立即应用。
- 悬浮窗内容验证：真实联系人、分组、风险状态和回复建议会同步到悬浮窗，阻断状态下按钮不可复制。
- 多目标应用验证：目标应用配置、自定义项和匹配规则可持久化，通用聊天目标不会误标为微信，焦点窗口优先跟随。
- 校准 UI 验证：合成截图、覆盖层拖拽、截图保存、active 校准持久化。
- OCR 预览验证：校准覆盖层展示 OCR 候选框和摘要。
- OCR Provider 验证：默认预览引擎可用，可选 RapidOCR / PaddleOCR 未安装时不崩溃且有明确 warning。
- OCR 解析验证：区域归属、页面分类、说话人推断、适配器 OCR 证据入口。
- OCR golden 验证：结构化 fixture 可回放私聊/群聊页面分类、设置页/公众号/文章页阻断、消息归属、群成员昵称行过滤和 partial 结果，不依赖真实桌面。
- 截图样本回放验证：`fixtures/screenshot_samples` 支持截图、layout 和 expected manifest，既能跑结构化 OCR 框，也能切换到真实 OCR Provider。
- 截图样本导出验证：可将 `replay_ocr_sample.py` 输出转换成可提交的样本目录，便于沉淀脱敏真实微信截图。
- 页面响应式验证：compact、standard、wide 和多显示器负坐标窗口都能生成非重叠布局。
- 采集管线验证：正常产出、重复截图丢弃、采集失败不崩溃、旧任务结果丢弃、runtime 结果回写。
- OCR 裁剪验证：非零屏幕坐标窗口裁剪右侧内容区后，OCR 结果仍可映射回原布局并解析消息。
- 采集样本验证：管线完成后写入目标应用和结构化元数据，且不包含聊天正文。
- AI 回复生成验证：离线候选、未知页面阻断、结构化结果。
- 采集入库验证：聊天页入库、群聊对象类型、重复消息去重、未知页面阻断。
- AI 生成审计验证：允许和阻断都写审计，且不泄露 API Key 或完整聊天文本。
- AI 请求治理验证：重复上下文、快速连点和每日上限都会在调用 Provider 前阻断并写审计。
- 异步回复任务验证：提交立即返回、运行中拒绝并行生成、完成后发出结果信号并写审计；UI 会丢弃联系人或窗口已变化的旧回复结果。
- Provider 健康验证：连续失败进入退避、退避期间不调用 Provider、重启后退避仍生效，退避过期本地转入 recovering，手动恢复和成功请求都会恢复健康状态。
- Prompt 隐私验证：预览和真实 Provider payload 都使用脱敏后的上下文。
- AI Provider 诊断验证：成功、HTTP 错误和坏响应都会写本地日志，且不泄露密钥、prompt 或聊天原文。
- AI Provider 连接测试验证：设置页会发起真实轻量 `/chat/completions` 测试请求，本地预览/禁用模式不联网，诊断日志不泄露密钥。
- 环境诊断验证：剪贴板 bundle 和调试样本都包含依赖、路径、配置存储和窗口匹配摘要。
- 诊断动作验证：日志级别过滤只影响可见 UI，剪贴板 bundle 和调试样本保留完整诊断信息，并对密钥、认证头、邮箱、链接、手机号和长数字做最终脱敏。
- Debug sample 导出验证：诊断样本可转换为截图样本 fixture，并通过同一套 screenshot sample 回放断言。
- 自动采集验证：窗口轮询可提交采集、短暂节流不取消挂起任务、暂停和禁用会阻断提交。
- OCR 稳定性验证：PaddleOCR 连续失败会进入熔断，自动采集不会在运行中或冷却期重复堆积 OCR 任务。
- 联系人合并验证：别名保留、消息去重、记忆迁移、AI 审计迁移、源联系人隐藏。
- 身份模型验证：跨应用联系人可链接同一 Person，同昵称可对应不同 Person，群成员可链接好友也可保持未解析。
- 身份 UI 验证：聊天对象详情可渲染跨应用 Person 链接和身份别名。
- 群成员 UI 验证：群聊详情可渲染已链接成员和未解析成员。
- 聊天记录拼接验证：上下滚动重叠时合并，无可靠重叠时进入 pending segment。
- 数据治理验证：联系人级导出包含完整本地资料，清空记录不删除联系人壳和别名；全局导出和全局内容清空保留设置审计与策略。
- 设置审计验证：AI、隐私和采集配置变更写入 settings_audit，且不泄露 API Key。
- 分组策略管理验证：搜索、归档、恢复、内置安全策略保护和 UI 过滤。
- 本地保留期验证：过期日志、调试样本、截图缓存和校准样本会被清理，数据库、配置、导出和 OCR 缓存保持不变。

### 下一步

- 增加截图样本回放测试，不依赖真实微信隐私内容。
- 增加区域识别测试：日间、夜间、不同 DPI、不同窗口宽度。
- 继续补充真实微信日间/夜间、不同 DPI 和群聊截图 golden 样本。
- 增加防抖、限频、任务取消测试。
- 增加更多真实 Provider 兼容性样本，不依赖真实用户聊天内容。
- 增加 UI 交互测试：新增分组、编辑分组、确认联系人、确认记忆、复制建议。

## 8. 风险边界

MVP 坚持 L1：生成建议，用户点击复制，用户手动粘贴发送。

默认不做：

- 自动发送。
- 自动点击左侧聊天列表。
- 批量遍历联系人。
- 读取微信数据库。
- 注入、Hook 或修改微信客户端。
- 自动打开图片、语音、链接、小程序。

任何更高等级自动化都必须用户显式开启、联系人白名单、页面和联系人高置信度、可取消、有审计日志。

## 9. 当前验收命令

```powershell
.venv312\Scripts\python -m compileall whochat tools
.venv312\Scripts\python tools\verify_main_path.py
.venv312\Scripts\python tools\verify_non_chat_main_path.py
.venv312\Scripts\python tools\verify_storage.py
.venv312\Scripts\python tools\verify_strategy_management.py
.venv312\Scripts\python tools\verify_contact_merge.py
.venv312\Scripts\python tools\verify_identity_model.py
.venv312\Scripts\python tools\verify_identity_ui.py
.venv312\Scripts\python tools\verify_group_members_ui.py
.venv312\Scripts\python tools\verify_transcript_stitcher.py
.venv312\Scripts\python tools\verify_data_governance.py
.venv312\Scripts\python tools\verify_global_governance.py
.venv312\Scripts\python tools\verify_retention_cleanup.py
.venv312\Scripts\python tools\verify_config_security.py
.venv312\Scripts\python tools\verify_settings_audit.py
.venv312\Scripts\python tools\verify_runtime.py
.venv312\Scripts\python tools\verify_window_diagnostics.py
.venv312\Scripts\python tools\verify_environment_diagnostics.py
.venv312\Scripts\python tools\verify_diagnostics_actions.py
.venv312\Scripts\python tools\verify_debug_sample_export.py
.venv312\Scripts\python tools\verify_layout_responsiveness.py
.venv312\Scripts\python tools\verify_status_chain.py
.venv312\Scripts\python tools\verify_autocapture.py
.venv312\Scripts\python tools\verify_target_windows.py
.venv312\Scripts\python tools\verify_ocr_parser.py
.venv312\Scripts\python tools\verify_ocr_providers.py
.venv312\Scripts\python tools\verify_screenshot_samples.py
.venv312\Scripts\python tools\verify_screenshot_sample_export.py
.venv312\Scripts\python tools\verify_paddleocr_real.py
.venv312\Scripts\python tools\verify_pipeline.py
.venv312\Scripts\python tools\verify_pipeline_ocr_crop.py
.venv312\Scripts\python tools\verify_capture_samples.py
.venv312\Scripts\python tools\verify_ingestion.py
.venv312\Scripts\python tools\verify_reply_generator.py
.venv312\Scripts\python tools\verify_generation_audit.py
.venv312\Scripts\python tools\verify_ai_request_policy.py
.venv312\Scripts\python tools\verify_ai_connection_test.py
.venv312\Scripts\python tools\verify_ai_provider_diagnostics.py
.venv312\Scripts\python tools\verify_reply_tasks.py
.venv312\Scripts\python tools\verify_reply_stale_ui.py
.venv312\Scripts\python tools\verify_provider_health.py
.venv312\Scripts\python tools\verify_provider_health_ui.py
.venv312\Scripts\python tools\verify_provider_health_persistence.py
.venv312\Scripts\python tools\verify_prompt_privacy.py
.venv312\Scripts\python tools\smoke_ui.py
```

真实微信窗口探针需要在可访问桌面的 Windows 会话运行：

```powershell
.venv312\Scripts\python tools\probe_wechat_window.py
.venv312\Scripts\python tools\probe_screenshot.py
```
