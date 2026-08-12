from __future__ import annotations

from dataclasses import dataclass

from whochat.config import AppConfig
from whochat.core.models import Contact, ContactStatus, Strategy
from whochat.core.runtime import PageType, RuntimeState, WindowState


@dataclass(frozen=True)
class StatusStep:
    stage: str
    state: str
    reason: str
    action: str = ""


def build_status_chain(
    *,
    runtime: RuntimeState,
    contact: Contact | None,
    strategy: Strategy | None,
    config: AppConfig,
    reply_running: bool,
    provider_health: str,
) -> list[StatusStep]:
    return [
        _window_step(runtime),
        _page_step(runtime, config),
        _contact_step(contact, config),
        _capture_step(runtime),
        _ocr_step(runtime),
        _privacy_step(contact, strategy, config),
        _ai_step(runtime, contact, strategy, config, reply_running, provider_health),
    ]


def _window_step(runtime: RuntimeState) -> StatusStep:
    if runtime.window.state == WindowState.VISIBLE:
        title = runtime.window.title or "目标窗口已连接"
        detail = f"{title}；{runtime.window.diagnostic}" if runtime.window.diagnostic else title
        return StatusStep("窗口", "通过", detail, "继续保持目标聊天窗口可见")
    if runtime.window.diagnostic:
        if "不是当前前景窗口" in runtime.window.diagnostic:
            return StatusStep("窗口", "阻断", runtime.window.diagnostic, "切到目标窗口前台，或在设置里关闭“仅采集当前前台目标窗口”用于测试")
        if "后台测试模式" in runtime.window.diagnostic:
            return StatusStep("窗口", "警告", runtime.window.diagnostic, "当前允许后台测试采集，但结果可能受遮挡影响")
        return StatusStep("窗口", "阻断", runtime.window.diagnostic, "打开目标聊天窗口，或在设置中补充进程名/标题规则")
    if runtime.window.state == WindowState.MINIMIZED:
        return StatusStep("窗口", "阻断", "目标窗口已最小化", "还原目标窗口后悬浮窗和采集会自动恢复")
    if runtime.window.state == WindowState.MISSING:
        return StatusStep("窗口", "阻断", "未发现已启用的目标聊天窗口", "打开微信或启用对应目标应用")
    return StatusStep("窗口", "阻断", f"目标窗口状态：{runtime.window.state.value}", "等待窗口稳定或重新选择目标应用")


def _page_step(runtime: RuntimeState, config: AppConfig) -> StatusStep:
    if runtime.page.page_type in {PageType.CHAT_DM, PageType.CHAT_GROUP} and runtime.page.confidence >= 0.65:
        return StatusStep("页面", "通过", f"{runtime.page.page_type.value} / {runtime.page.confidence:.2f}", "可以生成回复建议")
    if not config.capture.pause_ai_on_unknown_page:
        return StatusStep("页面", "放行", f"{runtime.page.page_type.value} / {runtime.page.confidence:.2f}", "已允许未知页面继续，但建议确认内容无误")
    if runtime.pipeline_status == "title_ready":
        return StatusStep("页面", "待确认", "标题已识别，消息仍在 OCR 读取中", "等待消息识别完成后自动确认页面")
    if runtime.capture_decision.should_capture and runtime.pipeline_status in {"idle", "title_ready"}:
        return StatusStep("页面", "待确认", runtime.page.reason, "点击“立即采集”用 OCR 确认聊天页")
    return StatusStep("页面", "阻断", runtime.page.reason, "切换到聊天页，或点击校准重新指定区域")


def _contact_step(contact: Contact | None, config: AppConfig) -> StatusStep:
    if contact is None:
        return StatusStep("联系人", "阻断", "尚未识别或选择联系人", "等待 OCR 识别标题，或在聊天对象页手动选择/确认")
    if contact.status == ContactStatus.IGNORED:
        return StatusStep("联系人", "阻断", f"{contact.display_name} 已被忽略", "从聊天对象页移出忽略列表后再生成建议")
    if contact.status == ContactStatus.MERGED or contact.merged_into:
        return StatusStep("联系人", "阻断", f"{contact.display_name} 已合并到其他对象", "切换到合并后的聊天对象")
    if contact.status in {ContactStatus.UNCONFIRMED, ContactStatus.SUSPECTED}:
        return StatusStep("联系人", "通过", f"{contact.display_name} / {contact.status.value}", "已自动建立聊天对象，可后续确认、合并或忽略")
    return StatusStep("联系人", "通过", f"{contact.display_name} / {contact.status.value}", "联系人已可用于当前策略")


def _capture_step(runtime: RuntimeState) -> StatusStep:
    if runtime.paused:
        return StatusStep("采集", "暂停", "用户已暂停采集", "点击顶部“继续采集”恢复")
    if runtime.capture_decision.should_capture:
        return StatusStep("采集", "通过", runtime.capture_decision.reason, "可运行采集管线或等待自动采集")
    return StatusStep("采集", "等待", runtime.capture_decision.reason, "等待窗口稳定、滚动停止或内容变化")


def _ocr_step(runtime: RuntimeState) -> StatusStep:
    status = runtime.pipeline_status or "idle"
    if status == "title_ready":
        return StatusStep("OCR", "读取消息", "标题已识别，消息区 OCR 仍在运行", "可以先核对联系人，等待消息读取完成")
    if runtime.ocr_pending or status == "running":
        return StatusStep("OCR", "运行中", "正在截图识别，UI 可继续操作", "等待 OCR 完成，不需要重复点击")
    if status.startswith("finished:"):
        page_type = status.split(":", 1)[1]
        if runtime.visible_message_count > 0:
            return StatusStep("OCR", "通过", f"{page_type}；可见消息 {runtime.visible_message_count} 条", "可核对聊天记录后生成建议")
        return StatusStep("OCR", "空结果", f"{page_type}；未解析到可见消息", "滚动到有文本消息的位置，或检查 OCR 引擎")
    if status.startswith("discarded:pipeline_failed"):
        return StatusStep("OCR", "失败", status.removeprefix("discarded:pipeline_failed:") or status, "查看诊断页 OCR 日志，必要时切换 OCR Provider")
    if status.startswith("discarded:duplicate_snapshot"):
        return StatusStep("OCR", "跳过", "截图与上次相同，未重复识别", "这是正常去重；切换聊天或滚动后会重新识别")
    if status.startswith("discarded:pipeline_busy"):
        return StatusStep("OCR", "等待", "上一轮 OCR 仍在运行", "等待当前 OCR 完成")
    if status.startswith("discarded:flow_cooldown"):
        return StatusStep("OCR", "等待", "OCR 冷却中，避免高频识别", "等待冷却结束，或在设置中调整自动 OCR 间隔")
    if status.startswith("discarded:"):
        return StatusStep("OCR", "跳过", status.removeprefix("discarded:"), "根据原因调整窗口、页面或采集设置")
    return StatusStep("OCR", "等待", "尚无 OCR 采集结果", "打开聊天窗口后运行采集管线或启用自动采集")


def _privacy_step(contact: Contact | None, strategy: Strategy | None, config: AppConfig) -> StatusStep:
    if config.privacy.manual_protection_blocks_replies and strategy and strategy.requires_manual_reply:
        return StatusStep("隐私", "阻断", f"分组「{strategy.name}」启用手动回复保护", "改用手动回复，或编辑分组关闭手动保护")
    if config.ai.provider in {"OpenAI", "OpenAI Compatible"} and config.ai.api_key:
        if contact is None or not contact.allow_cloud_ai:
            return StatusStep("隐私", "阻断", "联系人未允许第三方 AI 外发", "在联系人资料中开启云端授权，或移除 API Key 使用本地预览")
        return StatusStep("隐私", "通过", "云端外发已获得联系人级授权", "云端请求前仍会按设置进行预览和脱敏")
    return StatusStep("隐私", "通过", "本地预览或 AI 未配置云端密钥", "不会向第三方发送上下文")


def _ai_step(
    runtime: RuntimeState,
    contact: Contact | None,
    strategy: Strategy | None,
    config: AppConfig,
    reply_running: bool,
    provider_health: str,
) -> StatusStep:
    if reply_running:
        return StatusStep("AI", "运行中", "正在后台生成回复建议", "等待生成完成后再复制")
    if config.ai.provider == "Disabled":
        return StatusStep("AI", "阻断", "AI 已在设置中禁用", "在设置页选择 Local Preview 或配置 Provider")
    if "status=backoff" in provider_health:
        return StatusStep("AI", "退避", provider_health, "检查 Provider 配置或点击恢复健康状态")
    blocking = [
        step
        for step in [
            _page_step(runtime, config),
            _contact_step(contact, config),
            _privacy_step(contact, strategy, config),
        ]
        if step.state == "阻断" or (step.stage == "页面" and step.state == "待确认")
    ]
    if blocking:
        first = blocking[0]
        return StatusStep("AI", "阻断", f"{first.stage}未通过：{first.reason}", first.action)
    return StatusStep("AI", "就绪", f"{config.ai.provider} / {config.ai.model}", "点击生成建议")
