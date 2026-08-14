from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from whochat.config import ConfigStore
from whochat.ocr.engine import create_ocr_engine
from whochat.storage.database import Database
from whochat.storage.repositories import (
    CalibrationRepository,
    CaptureSampleRepository,
    ContactRepository,
    LogRepository,
    MemoryRepository,
    MessageRepository,
    GenerationLogRepository,
    IdentityRepository,
    ReplyFeedbackRepository,
    StrategyRepository,
    SettingsAuditRepository,
)
from whochat.services.ingestion import ChatIngestionService
from whochat.services.autocapture import AutoCaptureController
from whochat.services.environment import EnvironmentDiagnosticsService
from whochat.services.governance import DataGovernanceService
from whochat.services.reply import ReplyGenerationService
from whochat.services.reply_tasks import ReplyTaskService
from whochat.services.retention import RetentionCleanupService
from whochat.services.runtime import RuntimeStateService
from whochat.services.pipeline import CapturePipelineService
from whochat.services.transcript_stitcher import TranscriptStitcher
from dataclasses import replace


@dataclass(frozen=True)
class AppServices:
    db: Database
    strategies: StrategyRepository
    contacts: ContactRepository
    identities: IdentityRepository
    messages: MessageRepository
    memories: MemoryRepository
    logs: LogRepository
    generation_logs: GenerationLogRepository
    reply_feedback: ReplyFeedbackRepository
    capture_samples: CaptureSampleRepository
    settings_audit: SettingsAuditRepository
    runtime: RuntimeStateService
    calibrations: CalibrationRepository
    pipeline: CapturePipelineService
    reply_generator: ReplyGenerationService
    reply_tasks: ReplyTaskService
    ingestion: ChatIngestionService
    autocapture: AutoCaptureController
    governance: DataGovernanceService
    retention: RetentionCleanupService
    environment: EnvironmentDiagnosticsService
    transcript_stitcher: TranscriptStitcher

    def shutdown(self) -> None:
        try:
            self.autocapture.stop()
            self.autocapture.set_enabled(False)
        except Exception:
            pass
        try:
            self.pipeline.shutdown()
        except Exception:
            pass
        try:
            self.reply_tasks.shutdown()
        except Exception:
            pass
        try:
            self.logs.append("info", "bootstrap", "services_shutdown", "Application services shut down")
        except Exception:
            pass


def build_services(db_path: Path | None = None) -> AppServices:
    db = Database(db_path)
    db.migrate()
    calibrations = CalibrationRepository(db)
    strategies = StrategyRepository(db)
    contacts = ContactRepository(db)
    identities = IdentityRepository(db)
    messages = MessageRepository(db)
    memories = MemoryRepository(db)
    logs = LogRepository(db)
    generation_logs = GenerationLogRepository(db)
    reply_feedback = ReplyFeedbackRepository(db)
    capture_samples = CaptureSampleRepository(db)
    settings_audit = SettingsAuditRepository(db)
    governance = DataGovernanceService(contacts, messages, memories, generation_logs, reply_feedback, logs, db)
    retention = RetentionCleanupService(logs, reply_feedback=reply_feedback)
    environment = EnvironmentDiagnosticsService()
    runtime = RuntimeStateService(calibrations=calibrations)
    config = ConfigStore().load()
    runtime.capture_gate.policy = replace(
        runtime.capture_gate.policy,
        scroll_debounce_ms=config.capture.scroll_debounce_ms,
        ocr_min_interval_ms=config.capture.ocr_min_interval_ms,
    )
    pipeline = CapturePipelineService(
        ocr_engine=create_ocr_engine(config.ocr),
        capture_samples=capture_samples,
        retain_capture_images=config.privacy.save_debug_screenshots,
    )
    transcript_stitcher = TranscriptStitcher()
    ingestion = ChatIngestionService(contacts, messages, logs, transcript_stitcher)
    autocapture = AutoCaptureController(runtime, pipeline, enabled=config.capture.auto_capture_enabled, interval_ms=5000)
    reply_generator = ReplyGenerationService(generation_logs)
    reply_tasks = ReplyTaskService(reply_generator)
    pipeline.status_changed.connect(lambda message: runtime.apply_pipeline_started() if "pipeline_started" in message else None)
    pipeline.title_ready.connect(runtime.apply_title_result)
    pipeline.title_ready.connect(ingestion.ingest_title_result)
    pipeline.result_ready.connect(runtime.apply_pipeline_result)
    pipeline.result_ready.connect(ingestion.ingest_pipeline_result)
    pipeline.result_discarded.connect(runtime.apply_pipeline_discarded)
    services = AppServices(
        db=db,
        strategies=strategies,
        contacts=contacts,
        identities=identities,
        messages=messages,
        memories=memories,
        logs=logs,
        generation_logs=generation_logs,
        reply_feedback=reply_feedback,
        capture_samples=capture_samples,
        settings_audit=settings_audit,
        runtime=runtime,
        calibrations=calibrations,
        pipeline=pipeline,
        reply_generator=reply_generator,
        reply_tasks=reply_tasks,
        ingestion=ingestion,
        autocapture=autocapture,
        governance=governance,
        retention=retention,
        environment=environment,
        transcript_stitcher=transcript_stitcher,
    )
    services.strategies.ensure_defaults()
    services.logs.append("info", "bootstrap", "services_ready", "Application services initialized")
    return services
