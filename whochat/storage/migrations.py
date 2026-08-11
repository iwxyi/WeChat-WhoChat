from __future__ import annotations


MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE strategies (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            goal TEXT NOT NULL,
            mode TEXT NOT NULL,
            tone TEXT NOT NULL,
            avoid TEXT NOT NULL DEFAULT '',
            reply_variants TEXT NOT NULL DEFAULT '',
            requires_manual_reply INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE contacts (
            id TEXT PRIMARY KEY,
            platform TEXT NOT NULL,
            display_name TEXT NOT NULL,
            conversation_type TEXT NOT NULL,
            status TEXT NOT NULL,
            strategy_id TEXT NOT NULL,
            remark TEXT NOT NULL DEFAULT '',
            avatar_fingerprint TEXT NOT NULL DEFAULT '',
            merged_into TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(strategy_id) REFERENCES strategies(id),
            FOREIGN KEY(merged_into) REFERENCES contacts(id)
        );

        CREATE TABLE contact_aliases (
            id TEXT PRIMARY KEY,
            contact_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(contact_id, alias),
            FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE
        );

        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            contact_id TEXT NOT NULL,
            speaker TEXT NOT NULL,
            text TEXT NOT NULL,
            content_type TEXT NOT NULL,
            ocr_confidence REAL,
            observed_at TEXT NOT NULL,
            message_time TEXT,
            time_source TEXT NOT NULL,
            partial INTEGER NOT NULL DEFAULT 0,
            fingerprint TEXT NOT NULL,
            source TEXT NOT NULL,
            FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE
        );
        CREATE INDEX idx_messages_contact_observed ON messages(contact_id, observed_at);
        CREATE UNIQUE INDEX idx_messages_fingerprint ON messages(contact_id, fingerprint);

        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            contact_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            content TEXT NOT NULL,
            confidence REAL,
            source_message_id TEXT,
            expires_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
            FOREIGN KEY(source_message_id) REFERENCES messages(id)
        );
        CREATE INDEX idx_memories_contact_status ON memories(contact_id, status);

        CREATE TABLE app_logs (
            id TEXT PRIMARY KEY,
            ts TEXT NOT NULL,
            level TEXT NOT NULL,
            module TEXT NOT NULL,
            event TEXT NOT NULL,
            message TEXT NOT NULL,
            context_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX idx_app_logs_ts ON app_logs(ts);
        """,
    )
    ,
    (
        2,
        """
        CREATE TABLE layout_calibrations (
            id TEXT PRIMARY KEY,
            target TEXT NOT NULL,
            name TEXT NOT NULL,
            theme TEXT NOT NULL,
            dpi_scale REAL NOT NULL DEFAULT 1.0,
            nav_rect_json TEXT NOT NULL,
            chat_list_rect_json TEXT NOT NULL,
            content_rect_json TEXT NOT NULL,
            title_rect_json TEXT NOT NULL,
            message_rect_json TEXT NOT NULL,
            input_rect_json TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX idx_layout_calibrations_active
        ON layout_calibrations(target, active)
        WHERE active = 1;
        """,
    ),
    (
        3,
        """
        CREATE TABLE generation_logs (
            id TEXT PRIMARY KEY,
            ts TEXT NOT NULL,
            contact_id TEXT,
            strategy_id TEXT,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            allowed INTEGER NOT NULL,
            status TEXT NOT NULL,
            suggestion_count INTEGER NOT NULL,
            risk_summary TEXT NOT NULL,
            context_hash TEXT NOT NULL,
            page_type TEXT NOT NULL,
            page_confidence REAL NOT NULL,
            message_count INTEGER NOT NULL,
            memory_count INTEGER NOT NULL,
            FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE SET NULL,
            FOREIGN KEY(strategy_id) REFERENCES strategies(id) ON DELETE SET NULL
        );
        CREATE INDEX idx_generation_logs_ts ON generation_logs(ts);
        CREATE INDEX idx_generation_logs_contact_ts ON generation_logs(contact_id, ts);
        CREATE INDEX idx_generation_logs_context ON generation_logs(context_hash);
        """,
    ),
    (
        4,
        """
        ALTER TABLE contacts ADD COLUMN allow_cloud_ai INTEGER NOT NULL DEFAULT 0;
        """,
    ),
    (
        5,
        """
        CREATE TABLE people (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            status TEXT NOT NULL,
            remark TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE person_aliases (
            id TEXT PRIMARY KEY,
            person_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(person_id, alias),
            FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE
        );
        CREATE INDEX idx_person_aliases_alias ON person_aliases(alias);

        CREATE TABLE contact_person_links (
            id TEXT PRIMARY KEY,
            contact_id TEXT NOT NULL,
            person_id TEXT NOT NULL,
            confidence REAL NOT NULL,
            source TEXT NOT NULL,
            verified INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(contact_id, person_id),
            FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
            FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE
        );
        CREATE INDEX idx_contact_person_links_contact ON contact_person_links(contact_id);
        CREATE INDEX idx_contact_person_links_person ON contact_person_links(person_id);

        CREATE TABLE group_members (
            id TEXT PRIMARY KEY,
            group_contact_id TEXT NOT NULL,
            member_display_name TEXT NOT NULL,
            person_id TEXT,
            platform_contact_id TEXT,
            confidence REAL NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(group_contact_id, member_display_name),
            FOREIGN KEY(group_contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
            FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE SET NULL,
            FOREIGN KEY(platform_contact_id) REFERENCES contacts(id) ON DELETE SET NULL
        );
        CREATE INDEX idx_group_members_group ON group_members(group_contact_id);
        CREATE INDEX idx_group_members_person ON group_members(person_id);
        """,
    ),
    (
        6,
        """
        CREATE TABLE settings_audit (
            id TEXT PRIMARY KEY,
            ts TEXT NOT NULL,
            actor TEXT NOT NULL,
            scope TEXT NOT NULL,
            changes_json TEXT NOT NULL,
            secret_backend TEXT NOT NULL
        );
        CREATE INDEX idx_settings_audit_ts ON settings_audit(ts);
        CREATE INDEX idx_settings_audit_scope_ts ON settings_audit(scope, ts);
        """,
    ),
    (
        7,
        """
        ALTER TABLE strategies ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;
        CREATE INDEX idx_strategies_archived_name ON strategies(archived, name);
        """,
    ),
    (
        8,
        """
        CREATE TABLE capture_samples (
            id TEXT PRIMARY KEY,
            ts TEXT NOT NULL,
            job_id INTEGER NOT NULL,
            hwnd INTEGER,
            snapshot_hash TEXT NOT NULL,
            image_path TEXT NOT NULL,
            ocr_image_path TEXT NOT NULL,
            crop_rect_json TEXT NOT NULL,
            ocr_engine TEXT NOT NULL,
            ocr_warning TEXT NOT NULL,
            page_type TEXT NOT NULL,
            page_confidence REAL NOT NULL,
            message_count INTEGER NOT NULL,
            retained_image INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX idx_capture_samples_ts ON capture_samples(ts);
        CREATE INDEX idx_capture_samples_hash ON capture_samples(snapshot_hash);
        """,
    ),
    (
        9,
        """
        ALTER TABLE capture_samples ADD COLUMN target_app TEXT NOT NULL DEFAULT 'wechat';
        ALTER TABLE capture_samples ADD COLUMN app_label TEXT NOT NULL DEFAULT '微信';
        CREATE INDEX idx_capture_samples_target_ts ON capture_samples(target_app, ts);
        """,
    ),
    (
        10,
        """
        ALTER TABLE capture_samples ADD COLUMN title_ocr_image_path TEXT NOT NULL DEFAULT '';
        ALTER TABLE capture_samples ADD COLUMN title_crop_rect_json TEXT NOT NULL DEFAULT '';
        ALTER TABLE capture_samples ADD COLUMN title_ocr_elapsed_ms INTEGER;
        ALTER TABLE capture_samples ADD COLUMN content_ocr_elapsed_ms INTEGER;
        ALTER TABLE capture_samples ADD COLUMN total_elapsed_ms INTEGER;
        """,
    ),
    (
        11,
        """
        CREATE TABLE reply_feedback (
            id TEXT PRIMARY KEY,
            ts TEXT NOT NULL,
            contact_id TEXT,
            strategy_id TEXT,
            provider TEXT NOT NULL,
            status TEXT NOT NULL,
            suggestion_label TEXT NOT NULL,
            suggestion_text_preview TEXT NOT NULL,
            risk TEXT NOT NULL,
            feedback TEXT NOT NULL,
            context_hash TEXT NOT NULL,
            page_type TEXT NOT NULL,
            message_count INTEGER NOT NULL,
            memory_count INTEGER NOT NULL,
            FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE SET NULL,
            FOREIGN KEY(strategy_id) REFERENCES strategies(id) ON DELETE SET NULL
        );
        CREATE INDEX idx_reply_feedback_ts ON reply_feedback(ts);
        CREATE INDEX idx_reply_feedback_contact_ts ON reply_feedback(contact_id, ts);
        CREATE INDEX idx_reply_feedback_context ON reply_feedback(context_hash);
        """,
    ),
    (
        12,
        """
        ALTER TABLE messages ADD COLUMN sender_name TEXT NOT NULL DEFAULT '';
        CREATE INDEX idx_messages_contact_sender ON messages(contact_id, sender_name);
        """,
    ),
]
