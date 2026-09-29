export type MetricState={metric:string;value:number|null;unit:string;status:'AVAILABLE'|'UNAVAILABLE'|'INSUFFICIENT_EVIDENCE'|'MODEL_DISABLED'|'MODEL_LOADING'|'PROCESSING'|'FAILED';confidence:number|null;confidence_label:string;coverage:{valid_observations:number;eligible_observations:number;ratio:number};limitations:string[]};

/** Machine-readable reason codes for an unavailable metric. Mirrors
 * backend/app/metrics.py:REASON_CODES exactly - keep both in sync. */
export type MetricReason=
  |'no_observations'|'insufficient_valid_observations'|'no_person_detected'
  |'facial_landmarks_unavailable'|'pose_landmarks_unavailable'|'poor_frame_quality'
  |'low_light'|'excessive_blur'|'face_occluded'|'model_unavailable'
  |'inference_failed'|'not_applicable_for_activity'|'processing_incomplete'
  |'legacy_data_without_evidence';

/** Canonical metric-availability contract. This is the strict wire shape
 * sent by the live WebSocket (`/ws/live/{id}`); REST/monitor-socket
 * responses derived from stored snapshots include these seven fields plus
 * a few legacy extras (see MetricState) for backward compatibility. */
export type MetricAvailability={
  value:number|null;
  available:boolean;
  reason:MetricReason|null;
  coverage:number|null;
  confidence:number|null;
  valid_observations:number;
  total_observations:number;
};
export type Metric={students:number;occupancy_rate:number|null;verified_attendance_rate:null;metrics:Record<string,MetricState>;attention:number;engagement:number;fatigue:number;drowsiness:number;yawning:number;raised_hands:number;empty_seats:number;occupancy:number};
export type Summary={sessions:number;active_sessions:number;latest:Metric|null;demo_mode:boolean;analytics_mode:string;current_session:{id:number;name:string;status:string;stage:string}|null;last_updated:number|null;recent_events:Array<{session_id:number;timestamp:number;type:string;severity:string;message:string}>};
export type Session={id:number;name:string;status:string;source_type:string;source_filename?:string|null;job_id?:string|null;data_source?:string;classroom_id?:number|null;course_id?:number|null;progress:number;processing_stage:string;duration:number;fps:number;total_frames:number;processed_frames:number;processing_speed:number;eta_seconds:number;analytics_mode:string;annotated_video_path:string|null;started_at:string|null;ended_at:string|null;created_at:string;error:string|null;retry_count:number;failure_code:string|null;activity_context:string;archived:boolean;is_test:boolean;stale?:boolean;stale_kind?:"STALE_VIDEO_JOB"|"LIVE_CAPTURE_INTERRUPTED"|null;stale_reason?:string|null};

/** One notice from the comparison compatibility analysis (backend
 * priority4.py:_compatibility_notices). 'warning' = possible but requires
 * caution; 'info' = a metric simply has no evidence in the selection. */
export type CompatibilityNotice={level:'warning'|'info';code:string;message:string};

export type ComparisonResponse={
  status:'AVAILABLE'|'PARTIAL_EVIDENCE'|'INSUFFICIENT_EVIDENCE';
  sessions:Array<{session_id:number;name:string;created_at:string;duration:number;context:string;classroom_id:number|null;course_id:number|null;source_type:string;status:string;coverage:number|null;confidence:number|null;methodology_version:string|null;event_counts?:Record<string,number>;metric_results:Record<string,MetricAvailability>}>;
  metric_results:Record<string,Record<string,MetricAvailability>>;
  compatibility:{compatible:boolean;notices:CompatibilityNotice[]};
  warnings:string[];
};
export type Trend={timestamp:number;engagement:number;attention:number;fatigue:number};
