"""Privacy-safe aggregate dashboards, comparisons, trends, and advisory alerts."""
from collections import Counter
from datetime import datetime
from statistics import mean
from sqlalchemy import func, select
from .. import models
from ..metrics import LEGACY_METRIC, as_metric_availability, build_metric, frame_quality_metric

METRICS={"observable_participation":"engagement_score","visual_orientation":"attention_score","possible_fatigue":"fatigue_score","occupancy":"occupancy_rate"}

# Metrics computed per-frame by the CV pipeline and persisted as canonical
# MetricAvailability envelopes in AnalyticsSnapshot.details["metrics"] (see
# video_processor.py:_snapshot). camera_quality/audio_quality/question_count/
# fusion are NOT in this set - they come from separate tables (quality
# assessments, audio analysis, discourse analysis, evidence fusion) and keep
# using the coarser session-level _avg() aggregation below.
CANONICAL_METRIC_NAMES=("occupancy","peak_occupancy","unoccupied_capacity","visual_orientation","observable_participation","prolonged_eye_closure","possible_fatigue","yawning","raised_hands")

def _avg(values):
    available=[float(v) for v in values if v is not None]
    return round(mean(available),2) if available else None

def _session_metric_results(snapshots):
    """One canonical MetricAvailability per CANONICAL_METRIC_NAMES entry for
    a single session, derived from its already-fetched snapshot rows (no
    extra query). A metric key absent from every snapshot's stored envelope
    (sessions processed before this contract existed) reports
    legacy_data_without_evidence rather than a guessed value."""
    results={}
    for name in CANONICAL_METRIC_NAMES:
        seen_key=False;entries=[];total_valid=0;total_total=0
        for row in snapshots:
            stored=(row.details or {}).get("metrics",{}).get(name)
            if stored is None:continue
            seen_key=True;envelope=as_metric_availability(stored)
            total_valid+=envelope["valid_observations"] or 0;total_total+=envelope["total_observations"] or 0
            if envelope["available"]:entries.append(envelope)
        if not snapshots:
            results[name]=build_metric(None,valid_observations=0,total_observations=0)
        elif not seen_key:
            results[name]=dict(LEGACY_METRIC)
        elif entries:
            weights=[max(e["coverage"] or .0001,.0001) for e in entries]
            value=round(sum(e["value"]*w for e,w in zip(entries,weights))/sum(weights),2)
            has_confidence=any(e["confidence"] is not None for e in entries)
            confidence=round(sum((e["confidence"] or 0)*w for e,w in zip(entries,weights))/sum(weights),4) if has_confidence else None
            # minimum_coverage=0: per-frame availability was already gated by
            # metric_envelope() when each snapshot was written: a session-level
            # aggregate should not be re-gated just because the classroom was
            # sometimes empty (raising total_observations without the metric
            # itself being any less measurable while people were present).
            results[name]=build_metric(value,valid_observations=total_valid,total_observations=total_total,confidence=confidence,minimum_coverage=0)
        else:
            results[name]=build_metric(None,valid_observations=total_valid,total_observations=total_total)
    return results

def load_evidence_data(db,session_ids):
    """Every per-session dataset session_evidence needs, loaded with a fixed number of grouped queries
    (never one per session), keyed by session id."""
    ids=list(session_ids)
    data={i:{"snapshots":[],"quality":[],"audio":None,"discourse":None,"fusion":None,"excluded":0,"event_counts":{}} for i in ids}
    if not ids:return data
    for row in db.scalars(select(models.AnalyticsSnapshot).where(models.AnalyticsSnapshot.session_id.in_(ids)).order_by(models.AnalyticsSnapshot.id)).all():data[row.session_id]["snapshots"].append(row)
    for row in db.scalars(select(models.QualityAssessment).where(models.QualityAssessment.session_id.in_(ids)).order_by(models.QualityAssessment.id)).all():data[row.session_id]["quality"].append(row)
    for row in db.scalars(select(models.AudioAnalysis).where(models.AudioAnalysis.session_id.in_(ids)).order_by(models.AudioAnalysis.id.desc())).all():data[row.session_id]["audio"]=row
    for row in db.scalars(select(models.DiscourseAnalysis).where(models.DiscourseAnalysis.session_id.in_(ids)).order_by(models.DiscourseAnalysis.id.desc())).all():data[row.session_id]["discourse"]=row
    for row in db.scalars(select(models.EvidenceFusionResult).where(models.EvidenceFusionResult.session_id.in_(ids)).order_by(models.EvidenceFusionResult.id)).all():data[row.session_id]["fusion"]=row  # highest id wins
    for session_id,count in db.execute(select(models.Event.session_id,func.count()).where(models.Event.session_id.in_(ids),models.Event.review_state.in_(["INCORRECT","EXCLUDED"])).group_by(models.Event.session_id)).all():data[session_id]["excluded"]=count
    # Reliable and cheap: counts of each stored event type, excluding events a reviewer marked incorrect/excluded.
    # Unlike region comparison (see compare()'s docstring), event frequency needs no cross-session spatial
    # correlation, so it is safe to compare directly.
    for session_id,event_type,count in db.execute(select(models.Event.session_id,models.Event.event_type,func.count()).where(models.Event.session_id.in_(ids),models.Event.review_state.notin_(["INCORRECT","EXCLUDED"])).group_by(models.Event.session_id,models.Event.event_type)).all():data[session_id]["event_counts"][event_type]=count
    return data

def evidence_for_sessions(db,sessions):
    sessions=list(sessions);data=load_evidence_data(db,[s.id for s in sessions])
    return [session_evidence(db,s,data[s.id]) for s in sessions]

def session_evidence(db,session,data=None):
    data=data or load_evidence_data(db,[session.id])[session.id]
    snapshots,quality,audio,discourse,fusion,excluded,event_counts=data["snapshots"],data["quality"],data["audio"],data["discourse"],data["fusion"],data["excluded"],data["event_counts"]
    metrics={key:_avg(getattr(row,field) for row in snapshots) for key,field in METRICS.items()}
    metrics.update({"camera_quality":_avg(row.overall_quality for row in quality),"audio_quality":audio.quality.get("score") if audio and audio.status=="AVAILABLE" else None,"question_count":discourse.metrics.get("question_count",{}).get("value") if discourse and isinstance(discourse.metrics.get("question_count"),dict) else None,"fusion":fusion.value if fusion else None})
    coverage=round(len([r for r in snapshots if r.student_count>0])/len(snapshots),3) if snapshots else None
    metric_results=_session_metric_results(snapshots)
    quality_scores=[r.overall_quality for r in quality if r.overall_quality is not None]
    quality_overall=round(sum(quality_scores)/len(quality_scores),2) if quality_scores else None
    quality_warnings=sorted({w for r in quality for w in (r.details or {}).get("warnings",[])})
    metric_results["frame_quality"]=frame_quality_metric(quality,quality_overall,quality_warnings)
    return {"session_id":session.id,"name":session.name,"created_at":session.created_at,"duration":session.duration,"context":session.activity_context,"classroom_id":session.classroom_id,"course_id":session.course_id,"source_type":session.source_type,"status":session.status,"metrics":metrics,"metric_results":metric_results,"event_counts":event_counts,"quality_available":sum(1 for r in quality if r.overall_quality is not None),"quality_total":len(quality),"coverage":coverage,"confidence":fusion.confidence if fusion else None,"methodology_version":fusion.methodology_version if fusion else None,"audio_status":audio.status if audio else "NOT_PROCESSED","excluded_evidence":excluded,"valid_observation_count":sum(r.student_count for r in snapshots if r.student_count>0),"snapshot_count":len(snapshots),"limitations":list(fusion.limitations) if fusion else ["Evidence fusion unavailable."]}
def aggregate_dashboard(db,sessions):
    evidence=evidence_for_sessions(db,[s for s in sessions if not s.archived]);keys=list(METRICS)+["camera_quality","audio_quality","question_count","fusion"]
    metrics={key:{"value":_avg(row["metrics"].get(key) for row in evidence),"available_sessions":sum(row["metrics"].get(key) is not None for row in evidence),"total_sessions":len(evidence)} for key in keys}
    limitations=Counter(l for row in evidence for l in row["limitations"])
    available=sum(envelope["available_sessions"]>0 for envelope in metrics.values());status="INSUFFICIENT_EVIDENCE" if not evidence or not available else "PARTIAL_EVIDENCE" if available<len(metrics) else "AVAILABLE"
    ids=[row["session_id"] for row in evidence];region_counts=Counter(db.scalars(select(models.StudentObservation.region_id).where(models.StudentObservation.session_id.in_(ids),models.StudentObservation.region_id.is_not(None))).all()) if ids else Counter();topics=Counter()
    if ids:
        for item in db.scalars(select(models.GeneratedContentItem).where(models.GeneratedContentItem.session_id.in_(ids),models.GeneratedContentItem.content_type.in_(["KEY_TERM","DEFINITION","CONCEPT"]))).all():topics[(item.edited_text or item.text).strip()[:120]]+=1
    timeline=[{"session_id":row["session_id"],"name":row["name"],"created_at":row["created_at"],"context":row["context"],"observable_participation":row["metrics"]["observable_participation"],"camera_quality":row["metrics"]["camera_quality"],"audio_quality":row["metrics"]["audio_quality"],"question_count":row["metrics"]["question_count"],"coverage":row["coverage"],"confidence":row["confidence"],"status":"PARTIAL_EVIDENCE" if any(value is None for value in row["metrics"].values()) else "AVAILABLE"} for row in evidence]
    return {"status":status,"session_count":len(evidence),"included_session_ids":ids,"metrics":metrics,"average_coverage":_avg(row["coverage"] for row in evidence),"average_confidence":_avg(row["confidence"] for row in evidence),"contexts":dict(Counter(row["context"] for row in evidence)),"methodology_versions":dict(Counter(row["methodology_version"] or "UNAVAILABLE" for row in evidence)),"audio_availability":dict(Counter(row["audio_status"] for row in evidence)),"reviewer_excluded_evidence":sum(row["excluded_evidence"] for row in evidence),"common_limitations":[{"text":k,"count":v} for k,v in limitations.most_common(5)],"session_timeline":timeline,"region_summaries":[{"region_id":key,"observation_count":value} for key,value in region_counts.most_common()],"topic_recurrence":[{"topic":key,"session_evidence_count":value} for key,value in topics.most_common(12)],"recent_sessions":evidence[-8:]}
def _compatibility_notices(rows):
    """Structured compatibility notices: 'warning' for things that make a
    comparison possible-but-caution-worthy, 'info' for a metric simply
    having no evidence anywhere in the selection. Hard-invalid comparisons
    (missing/unauthorized sessions, too few/many) are rejected before this
    point with HTTP errors, not represented here."""
    notices=[]
    contexts={r["context"] for r in rows}
    if len(contexts)>1:notices.append({"level":"warning","code":"DIFFERENT_ACTIVITY_CONTEXTS","message":"Selected sessions use different activity contexts; interpret metric differences separately rather than as a single trend."})
    classroom_ids={r["classroom_id"] for r in rows if r["classroom_id"] is not None}
    if len(classroom_ids)>1:notices.append({"level":"warning","code":"DIFFERENT_CLASSROOMS","message":"Selected sessions were recorded in different classrooms; layout and camera placement differences may affect occupancy and region metrics."})
    source_types={r["source_type"] for r in rows}
    if len(source_types)>1:notices.append({"level":"warning","code":"DIFFERENT_SOURCE_TYPES","message":"Selected sessions mix uploaded-video and live-camera sources, which can differ in frame rate and coverage."})
    versions={r["methodology_version"] for r in rows if r["methodology_version"]}
    if len(versions)>1:notices.append({"level":"warning","code":"DIFFERENT_METHODOLOGY_VERSIONS","message":"Selected sessions use different methodology versions for evidence fusion."})
    coverages=[r["coverage"] for r in rows if r["coverage"] is not None]
    if coverages and max(coverages)-min(coverages)>.3:notices.append({"level":"warning","code":"LOW_COVERAGE_SPREAD","message":"Evidence coverage differs by more than 30 percentage points across the selected sessions."})
    durations=[r["duration"] for r in rows if r["duration"]]
    if durations and min(durations)>0 and max(durations)/min(durations)>2:notices.append({"level":"warning","code":"DIFFERENT_DURATIONS","message":"Selected session durations differ by more than 2x; per-session totals are not directly comparable."})
    incomplete=[r for r in rows if r["status"]!="COMPLETED"]
    if incomplete:notices.append({"level":"warning","code":"SESSION_NOT_COMPLETED","message":f"{len(incomplete)} selected session(s) have not finished processing; their evidence may still be partial."})
    legacy=[r for r in rows if any(m.get("reason")=="legacy_data_without_evidence" for m in r["metric_results"].values())]
    if legacy:notices.append({"level":"info","code":"MISSING_HISTORICAL_EVIDENCE","message":f"{len(legacy)} selected session(s) predate tracking for one or more requested metrics; those cells show legacy_data_without_evidence, not zero."})
    return notices

def compare(db,sessions,metrics):
    rows=evidence_for_sessions(db,sessions)
    notices=_compatibility_notices(rows)
    canonical_metrics=[m for m in metrics if m=="frame_quality" or m in CANONICAL_METRIC_NAMES]
    metric_results={metric:{str(row["session_id"]):row["metric_results"][metric] for row in rows} for metric in canonical_metrics}
    for metric in canonical_metrics:
        if not any(entry["available"] for entry in metric_results[metric].values()):
            notices.append({"level":"info","code":"METRIC_UNAVAILABLE","message":f"No selected session has available evidence for {metric}; values were not converted to zero."})
    unavailable=[metric for metric in metrics if not any(row["metrics"].get(metric) is not None for row in rows) and metric not in canonical_metrics]
    unavailable+=[metric for metric in canonical_metrics if not any(metric_results[metric][sid]["available"] for sid in metric_results[metric])]
    if unavailable:notices.append({"level":"warning","code":"INSUFFICIENT_EVIDENCE_FOR_METRICS","message":"Insufficient evidence for: "+", ".join(sorted(set(unavailable)))+"; unavailable values were not converted to zero."})
    status="INSUFFICIENT_EVIDENCE" if not rows or len(set(unavailable))==len(metrics) else "PARTIAL_EVIDENCE" if unavailable else "AVAILABLE"
    warnings=[n["message"] for n in notices]  # legacy flat field, preserved for existing consumers
    compatible=not any(n["code"] in {"DIFFERENT_ACTIVITY_CONTEXTS","DIFFERENT_METHODOLOGY_VERSIONS"} for n in notices)
    return {"status":status,"sessions":rows,"metrics":metrics,"metric_results":metric_results,"compatibility":{"compatible":compatible,"notices":notices},"warnings":warnings,"compatible":compatible,"limitations":["Aggregate descriptive comparison; not an individual or causal conclusion."]}
def _canonical_bucket_result(items,metric):
    """Coverage-weighted MetricAvailability for one trend bucket, built from
    each contributing session's already-computed canonical metric_results
    (no per-point recomputation from raw observations)."""
    per_session=[item["metric_results"][metric] for item in items]
    available=[entry for entry in per_session if entry["available"]]
    total_valid=sum(entry["valid_observations"] for entry in per_session)
    total_total=sum(entry["total_observations"] for entry in per_session)
    if not available:
        return build_metric(None,valid_observations=total_valid,total_observations=total_total),available
    weights=[max(entry["coverage"] or .0001,.0001) for entry in available]
    value=round(sum(entry["value"]*weight for entry,weight in zip(available,weights))/sum(weights),2)
    has_confidence=any(entry["confidence"] is not None for entry in available)
    confidence=round(sum((entry["confidence"] or 0)*weight for entry,weight in zip(available,weights))/sum(weights),4) if has_confidence else None
    return build_metric(value,valid_observations=total_valid,total_observations=total_total,confidence=confidence,minimum_coverage=0),available

def trend_buckets(db,sessions,period="daily",rolling_window=3,metric="observable_participation"):
    evidence=evidence_for_sessions(db,sessions)
    def key(row):
        stamp=row["created_at"]
        if period=="daily":bucket=stamp.strftime("%Y-%m-%d")
        elif period=="weekly":bucket=f"{stamp.isocalendar().year}-W{stamp.isocalendar().week:02d}"
        elif period=="monthly":bucket=stamp.strftime("%Y-%m")
        else:bucket=f"session-{row['session_id']}"
        return bucket,row["context"],row["methodology_version"] or "UNAVAILABLE"
    grouped={}
    for row in evidence:grouped.setdefault(key(row),[]).append(row)
    is_canonical=metric in CANONICAL_METRIC_NAMES or metric=="frame_quality"
    points=[]
    for (bucket,context,version),items in sorted(grouped.items()):
        if is_canonical:
            result,contributing=_canonical_bucket_result(items,metric)
            value=result["value"];valid_observation_count=sum(item["metric_results"][metric]["valid_observations"] for item in items)
        else:
            contributing=[r for r in items if r["metrics"].get(metric) is not None]
            weights=[max(float(r["coverage"] or 0),.0001) for r in contributing]
            value=round(sum(float(r["metrics"][metric])*weight for r,weight in zip(contributing,weights))/sum(weights),2) if contributing else None
            result=build_metric(value,valid_observations=len(contributing),total_observations=len(items),confidence=_avg(r["confidence"] for r in contributing))
            valid_observation_count=sum(r["valid_observation_count"] for r in contributing)
        # `coverage`/`confidence`/`reason`/`status`/`value` below are the
        # legacy flat fields kept for existing consumers; `result` is the
        # canonical MetricAvailability carrying the same numbers.
        points.append({"bucket":bucket,"context":context,"series":context,"methodology_version":version,"metric":metric,"value":value,metric:value,"result":result,"session_count":len(items),"contributing_sessions":len(contributing),"valid_observation_count":valid_observation_count,"coverage":result["coverage"],"confidence":result["confidence"],"reason":None if contributing else (result["reason"] or "No valid stored evidence for the selected metric."),"status":"AVAILABLE" if contributing else "INSUFFICIENT_EVIDENCE"})
    history={}
    for point in points:
        compatible=history.setdefault((point["context"],point["methodology_version"]),[])
        if point["value"] is not None:compatible.append(point["value"])
        window=compatible[-rolling_window:];point["rolling_average"]=_avg(window) if len(window)>=2 else None;point["rolling_contributing_buckets"]=len(window);point["rolling_window"]=rolling_window;point["rolling_status"]="AVAILABLE" if len(window)>=2 else "INSUFFICIENT_EVIDENCE"
    return points
def generate_alerts(db,sessions,user_id,settings):
    created=0
    for session in sessions:
        evidence=session_evidence(db,session);checks=[]
        camera=evidence["metrics"]["camera_quality"]
        if camera is not None and camera<settings.notification_quality_threshold:checks.append(("POOR_CAMERA","Repeated poor camera evidence",camera))
        if evidence["audio_status"] in {"MODEL_UNAVAILABLE","FAILED"}:checks.append(("MODEL_PROVIDER_UNAVAILABLE","Audio/model provider unavailable",evidence["audio_status"]))
        audio=evidence["metrics"]["audio_quality"]
        if audio is not None and audio<settings.notification_quality_threshold:checks.append(("POOR_AUDIO","Repeated poor audio quality evidence",audio))
        if evidence["coverage"] is None:checks.append(("INSUFFICIENT_EVIDENCE","Insufficient aggregate evidence",None))
        if session.status=="FAILED":checks.append(("PROCESSING_FAILED","Session processing failed",session.failure_code))
        for category,title,value in checks:
            key=f"{category}:session:{session.id}"
            existing=db.scalar(select(models.Notification).where(models.Notification.user_id==user_id,models.Notification.dedupe_key==key))
            if not existing:db.add(models.Notification(user_id=user_id,session_id=session.id,category=category,title=title,message=f"{title} for session {session.id}. Review aggregate evidence before acting.",evidence={"value":value,"coverage":evidence["coverage"],"advisory_only":True},dedupe_key=key));created+=1
    groups={}
    for session in sessions:groups.setdefault((session.course_id,session.classroom_id,session.activity_context),[]).append(session)
    for group in groups.values():
        ordered=sorted(group,key=lambda row:row.created_at)
        if len(ordered)<2:continue
        previous,current=ordered[-2:];before=session_evidence(db,previous);after=session_evidence(db,current);left=before["metrics"]["observable_participation"];right=after["metrics"]["observable_participation"]
        if left is None or right is None or abs(right-left)<settings.notification_participation_change_threshold:continue
        key=f"PARTICIPATION_CHANGE:sessions:{previous.id}:{current.id}";existing=db.scalar(select(models.Notification).where(models.Notification.user_id==user_id,models.Notification.dedupe_key==key))
        if not existing:db.add(models.Notification(user_id=user_id,session_id=current.id,category="PARTICIPATION_CHANGE",title="Meaningful aggregate participation change",message=f"Observable participation changed by {round(right-left,2)} points across comparable sessions. Review coverage and context before acting.",evidence={"previous_session_id":previous.id,"current_session_id":current.id,"change":round(right-left,2),"previous_coverage":before["coverage"],"current_coverage":after["coverage"],"advisory_only":True},dedupe_key=key));created+=1
    db.commit();return created
