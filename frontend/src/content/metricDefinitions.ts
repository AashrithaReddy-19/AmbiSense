/**
 * Plain-language definition of every metric the interface shows. Wording is deliberately
 * observational: these are anonymous, aggregate estimates - never judgements about a person.
 */
export type MetricDefinition = {
  label: string;
  meaning: string;
  requiredEvidence: string;
  coverage: string;
  confidence: string;
  failureReasons: string[];
  limitations: string[];
  contexts: string;
};

const COVERAGE = "Coverage is the share of processed samples in which the evidence needed for this metric was actually present. A low coverage means the value rests on few samples.";
const CONFIDENCE = "Confidence summarises how reliable the underlying detections were (detector/landmark confidence and frame quality). It is not a probability that a conclusion is correct.";
const VISUAL_FAILURES = ["no_person_detected", "facial_landmarks_unavailable", "poor_frame_quality", "low_light", "excessive_blur", "face_occluded", "model_unavailable", "insufficient_valid_observations"];

export const METRIC_DEFINITIONS: Record<string, MetricDefinition> = {
  occupancy: {
    label: "Anonymous occupancy estimate",
    meaning: "How many people the detector found in frame, tracked anonymously within one session only.",
    requiredEvidence: "At least one processed frame with the person detector available.",
    coverage: COVERAGE, confidence: CONFIDENCE,
    failureReasons: ["no_observations", "model_unavailable", "poor_frame_quality"],
    limitations: ["An estimate, not verified attendance: people can be missed, double-counted or hidden.", "Anonymous tracks are session-local and never matched to identities or across sessions."],
    contexts: "All activity contexts.",
  },
  peak_occupancy: {
    label: "Peak anonymous occupancy",
    meaning: "The highest anonymous occupancy estimate seen in the session.",
    requiredEvidence: "Occupancy estimates for the session.",
    coverage: COVERAGE, confidence: CONFIDENCE,
    failureReasons: ["no_observations", "model_unavailable"],
    limitations: ["A single high sample can reflect a detection error rather than a real peak."],
    contexts: "All activity contexts.",
  },
  unoccupied_capacity: {
    label: "Estimated unoccupied capacity",
    meaning: "Configured seats minus the anonymous occupancy estimate.",
    requiredEvidence: "A configured seat total and occupancy estimates.",
    coverage: COVERAGE, confidence: CONFIDENCE,
    failureReasons: ["no_observations"],
    limitations: ["Depends on the configured seat total; it does not identify which seats are empty unless a calibrated layout exists."],
    contexts: "All activity contexts.",
  },
  observable_participation: {
    label: "Observable participation indicator",
    meaning: "A combined indicator of visible activity such as forward-facing orientation and raised-hand observations. It describes what the camera can see, not how much anyone is learning or participating.",
    requiredEvidence: "Detected people with usable face or pose landmarks.",
    coverage: COVERAGE, confidence: CONFIDENCE,
    failureReasons: VISUAL_FAILURES,
    limitations: ["Looking down may be writing or reading; looking away may be normal.", "Must not be the sole basis for grading, discipline, attendance or other high-impact decisions."],
    contexts: "Interpret per activity context. Not applicable during breaks; use caution during examinations, group discussion and independent writing.",
  },
  visual_orientation: {
    label: "Visual-orientation estimate",
    meaning: "The share of samples where the estimated head direction was toward the front of the room. It is a geometric estimate, not attention.",
    requiredEvidence: "Detected faces with head-pose landmarks.",
    coverage: COVERAGE, confidence: CONFIDENCE,
    failureReasons: VISUAL_FAILURES,
    limitations: ["Head direction is not a reliable measure of attention or comprehension.", "Camera angle and seating position bias the estimate."],
    contexts: "Interpret per activity context. Not applicable during breaks.",
  },
  possible_fatigue: {
    label: "Possible fatigue indicator",
    meaning: "A combined indicator built from possible prolonged eye closure and yawning observations. It is not a medical or psychological assessment.",
    requiredEvidence: "Detected faces with eye and mouth landmarks.",
    coverage: COVERAGE, confidence: CONFIDENCE,
    failureReasons: VISUAL_FAILURES,
    limitations: ["Blinking, glasses, lighting and camera angle affect eye and mouth landmarks.", "Never infer that a person is sleeping or disengaged from this indicator."],
    contexts: "Interpret per activity context. Not applicable during breaks.",
  },
  prolonged_eye_closure: {
    label: "Possible prolonged eye closure",
    meaning: "Observations where the eye-aspect ratio stayed below the configured threshold for the configured duration.",
    requiredEvidence: "Face landmarks with visible eyes.",
    coverage: COVERAGE, confidence: CONFIDENCE,
    failureReasons: ["facial_landmarks_unavailable", "face_occluded", "low_light", "excessive_blur", "insufficient_valid_observations"],
    limitations: ["Looking down or squinting can look like eye closure.", "Threshold values have not been validated on real classroom footage."],
    contexts: "Interpret per activity context.",
  },
  yawning: {
    label: "Yawning observation",
    meaning: "Observations where the mouth-aspect ratio exceeded the configured threshold for the configured duration.",
    requiredEvidence: "Face landmarks with a visible mouth.",
    coverage: COVERAGE, confidence: CONFIDENCE,
    failureReasons: ["facial_landmarks_unavailable", "face_occluded", "excessive_blur", "insufficient_valid_observations"],
    limitations: ["Speaking and laughing can trigger the same signal."],
    contexts: "Interpret per activity context.",
  },
  raised_hands: {
    label: "Raised-hand observation",
    meaning: "Observations where pose landmarks placed a wrist above the shoulder.",
    requiredEvidence: "Pose landmarks for detected people.",
    coverage: COVERAGE, confidence: CONFIDENCE,
    failureReasons: ["pose_landmarks_unavailable", "poor_frame_quality", "model_unavailable", "insufficient_valid_observations"],
    limitations: ["Stretching or adjusting hair can look like a raised hand."],
    contexts: "Most meaningful during lectures and discussions.",
  },
  frame_quality: {
    label: "Frame quality",
    meaning: "An overall quality score for processed frames combining sharpness, lighting and visibility.",
    requiredEvidence: "Processed frames with a quality assessment.",
    coverage: COVERAGE, confidence: CONFIDENCE,
    failureReasons: ["no_observations", "processing_incomplete"],
    limitations: ["Low quality lowers the reliability of every visual metric in that period."],
    contexts: "All activity contexts.",
  },
  camera_quality: {
    label: "Camera quality",
    meaning: "The session-level average of frame quality, useful for judging whether a recording is suitable for analysis.",
    requiredEvidence: "Stored quality assessments.",
    coverage: COVERAGE, confidence: CONFIDENCE,
    failureReasons: ["no_observations"],
    limitations: ["A good score does not make the detections themselves accurate."],
    contexts: "All activity contexts.",
  },
  audio_quality: {
    label: "Audio quality",
    meaning: "A signal-quality score for the optional audio track (silence ratio, voiced fraction).",
    requiredEvidence: "Optional audio analysis enabled and FFmpeg available.",
    coverage: COVERAGE, confidence: CONFIDENCE,
    failureReasons: ["model_unavailable", "processing_incomplete"],
    limitations: ["Audio is optional and disabled by default. Speakers are anonymous roles; no speaker is ever identified."],
    contexts: "All activity contexts.",
  },
  question_count: {
    label: "Question count",
    meaning: "The number of question-like utterances found in an available transcript.",
    requiredEvidence: "A transcript produced by a configured transcription adapter.",
    coverage: COVERAGE, confidence: CONFIDENCE,
    failureReasons: ["model_unavailable", "processing_incomplete"],
    limitations: ["Depends entirely on transcript quality; unavailable when transcription is disabled or removed by retention."],
    contexts: "Most meaningful during lectures and discussions.",
  },
  fusion: {
    label: "Fused evidence estimate",
    meaning: "An explainable weighted combination of the available evidence sources for a session.",
    requiredEvidence: "At least one included evidence component.",
    coverage: COVERAGE, confidence: CONFIDENCE,
    failureReasons: ["insufficient_valid_observations"],
    limitations: ["A research estimate; not a medical, psychological or pedagogical conclusion."],
    contexts: "Weights depend on the activity context.",
  },
};

export function metricDefinition(metric: string): MetricDefinition | null {
  return METRIC_DEFINITIONS[metric] ?? null;
}
