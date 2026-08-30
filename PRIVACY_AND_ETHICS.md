# Privacy and Ethics

AmbiSense is an aggregate, privacy-conscious research prototype. It does not identify people, infer protected traits, rank students, diagnose motivation or health, or make academic/disciplinary decisions. Anonymous identifiers expire and are never matched across sessions. Raw face crops are not stored.

Operators are responsible for consent, lawful purpose, access controls, camera/audio notices, retention, and human review. Visual estimates are affected by lighting, camera angle, occlusion, distance, disability, behavior context, and model bias.

Optional audio processing extracts a local mono WAV and may store anonymous timestamped transcript text. It does not identify voices, create voiceprints, match speakers across sessions, or infer emotion, intelligence, motivation, or confusion. Audio defaults off (`AUDIO_ANALYTICS_ENABLED=false`) and transcription defaults to `NONE`. The shared scheduler removes raw audio/transcript-derived records after the configured period, preserves permitted aggregate analytics, and audits each action. Diarization defaults off; adapters may emit anonymous session-local spans only, provider identity labels are discarded, and manual roles never contain names.

Priority 4 dashboards, comparisons, alerts, and exports remain aggregate. Alerts are advisory quality/evidence notices only and never rank students, grade work, recommend discipline, or infer emotion, intelligence, motivation, or learning ability. Ownership and course membership restrict classroom, session, layout, transcript, report, note, content and WebSocket resources; changing a URL or body identifier does not bypass the parent-resource check. Collaboration notes must remain evidence-based and must not become student profiles.
