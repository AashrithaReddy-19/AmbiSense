# Metric definitions

Every metric is an **anonymous, aggregate estimate** of something a camera can observe. None of them says anything
about an individual's attention, learning, health, honesty or performance. The same text is shown in the application
(*Metric definitions and limitations*), sourced from `frontend/src/content/metricDefinitions.ts`.

## The availability contract

Every metric on the wire is:

| Field | Meaning |
|---|---|
| `value` | The estimate, or `null` when unavailable. **A genuine `0` is a real zero and is shown as `0`.** |
| `available` | Whether `value` may be used |
| `reason` | Why it is unavailable (see below); `null` when available |
| `coverage` | Share of processed samples that contained the evidence this metric needs (0–1) |
| `confidence` | Summary of the underlying detection reliability (0–1). It is not the probability that a conclusion is correct. |
| `valid_observations` / `total_observations` | How many samples contributed vs. how many were considered |

Unavailable values are drawn as **gaps** in charts, shown as `—` with the reason in tables, and never converted to zero.
A malformed value such as `—%` is never displayed.

**Reason codes:** `no_observations`, `insufficient_valid_observations`, `no_person_detected`,
`facial_landmarks_unavailable`, `pose_landmarks_unavailable`, `poor_frame_quality`, `low_light`, `excessive_blur`,
`face_occluded`, `model_unavailable`, `inference_failed`, `not_applicable_for_activity`, `processing_incomplete`,
`legacy_data_without_evidence` (sessions processed before this contract existed).

## Metrics

| Metric (UI name) | Meaning | Needs | Main limitations | Contexts |
|---|---|---|---|---|
| `occupancy` - Anonymous occupancy estimate | People the detector found in frame | Person detector | An estimate, not verified attendance; people can be missed or double-counted | All |
| `peak_occupancy` | Highest occupancy estimate in the session | Occupancy estimates | One high sample can be a detection error | All |
| `unoccupied_capacity` - Estimated unoccupied capacity | Configured seats minus occupancy | Seat total | Does not say which seats are empty without a calibrated layout | All |
| `observable_participation` - Observable participation indicator | Combined visible activity (forward orientation, raised hands…) | Face or pose landmarks | Looking down may be writing; not learning or participation | Not applicable during breaks; use caution for examinations, group discussion, independent writing |
| `visual_orientation` - Visual-orientation estimate | Share of samples where head direction is toward the front | Head-pose landmarks | Not attention; camera angle and seating bias it | As above |
| `possible_fatigue` - Possible fatigue indicator | Combination of eye-closure and yawning observations | Eye and mouth landmarks | Not a medical or psychological assessment; never infer sleeping or disengagement | As above |
| `prolonged_eye_closure` - Possible prolonged eye closure | Eye-aspect ratio below threshold for the configured duration | Visible eyes | Looking down or squinting can look like closure; thresholds not validated | All |
| `yawning` - Yawning observation | Mouth-aspect ratio above threshold for the configured duration | Visible mouth | Speaking and laughing can trigger it | All |
| `raised_hands` - Raised-hand observation | Wrist above shoulder in pose landmarks | Pose landmarks | Stretching or adjusting hair can look the same | Lectures, discussions |
| `frame_quality` - Frame quality | Sharpness, lighting and visibility score | Quality assessments | Low quality lowers every visual metric | All |
| `camera_quality` | Session average of frame quality | Stored assessments | Good quality does not make detections accurate | All |
| `audio_quality` | Signal quality of the optional audio track | Audio enabled + FFmpeg | Optional; speakers are anonymous roles | All |
| `question_count` | Question-like utterances in an available transcript | Transcription adapter | Depends on transcript quality | Lectures, discussions |
| `fusion` - Fused evidence estimate | Explainable weighted combination of available sources | ≥ 1 included component | A research estimate, not a conclusion | Weights depend on context |

## Aggregation rules

- **Trends** group by period, activity context and methodology version. Values are coverage-weighted means of available evidence only; `contributing_sessions` shows how many sessions supplied a value. `minimum_coverage` / `confidence_min` hide periods below a level and report `excluded_by_filters`.
- **Comparison** shows each metric per session with its own coverage/confidence, compatibility notices (different contexts, classrooms, data sources, methodology versions, durations, low coverage, missing history, incomplete sessions, unavailable metrics), and stored event counts (excluding reviewer-excluded events). Regions are compared only when every session used the same calibrated layout.
- **Session coverage** (used by the Sessions filter and dashboard tiers) is the fraction of a session's processed samples with at least one detected person. Sessions with no processed samples are *insufficient evidence*, not zero coverage.

See [METHODOLOGY.md](../METHODOLOGY.md) for the estimation methods and [EVALUATION.md](EVALUATION.md) for how accuracy would be measured. **None of these metrics has been validated on real classroom footage.**
