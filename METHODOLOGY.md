# Methodology

AmbiSense estimates observable classroom signals. It does not make medical, psychological or pedagogical diagnoses. Results must not be used as the sole basis for decisions about students or instructors.

- Current occupancy is the number of valid anonymous occupants in the current frame; occupancy rate uses configured room capacity.
- Estimated unique tracks count only deduplicated session-local tracks meeting observation, duration, confidence, age, expiry, IoU, and re-entry rules.
- Verified attendance is unavailable unless a separate lawful source is configured.
- Visual orientation uses visible face landmarks and PnP head pose. Missing landmarks are unavailable evidence, not zero.
- Observable participation combines available visual orientation, eye-state, activity, and posture/participation signals. Missing inputs are excluded rather than averaged as zero.
- Possible prolonged eye closure, yawning, and possible fatigue are uncertain visual indicators and are not diagnoses.

Every inferred metric envelope reports status, confidence, coverage, limitations, and value. Values are finite and constrained to 0–100. Poor image quality reduces usable coverage and exposes warnings.

Region heat maps reuse session-scoped anonymous observations. Camera visibility represents usable landmark coverage, model confidence represents detector confidence, participation is an observable signal rather than cognition, and unavailable cells remain transparent. Heat-map comparisons are descriptive associations and require the same classroom calibration.

Audio quality uses windowed RMS voice activity, silence ratio, clipping ratio, and an estimated signal-to-noise ratio. Transcript-derived questions, definitions, key terms, and chapters are extractive and cite source segment IDs/timestamps. Unknown speaker roles are not guessed. Fusion excludes unavailable evidence and renormalizes remaining weights rather than treating missing values as zero. Lecture, examination, group-discussion, writing, reading, presentation, video-screening, break, and custom contexts use explicit versioned relevance rules. Reviewer-excluded/incorrect evidence is retained for traceability but carries zero effective weight and an explanation.

Cross-session aggregates include non-archived sessions and only available metric values; each envelope reports its contributing-session count. Contexts and methodology versions remain explicit rather than silently mixed. Comparisons flag context differences, coverage gaps above 30 percentage points, methodology-version differences, and insufficient metrics. UTC trend responses implement daily, ISO-weekly, monthly and per-session buckets. Rolling averages use only prior compatible context/version buckets, require at least two available values, report their contributing-bucket count, and never substitute zero for missing evidence.

## See also

- [docs/METRICS.md](docs/METRICS.md): plain-language definition, required evidence, limitations and contexts for every metric, and the availability contract.
- [docs/EVALUATION.md](docs/EVALUATION.md): how accuracy would be measured. **These methods are not validated on real classroom footage.**
- Wording: results are called *estimates*, *indicators* and *observations*; never verified attendance, and never statements about an individual's attention, engagement, honesty or performance.
