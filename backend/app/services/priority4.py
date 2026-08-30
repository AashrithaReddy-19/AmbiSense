"""Privacy-safe aggregate dashboards, comparisons, trends, and advisory alerts."""
from collections import Counter
from datetime import datetime
from statistics import mean
from sqlalchemy import select
from .. import models

METRICS={"observable_participation":"engagement_score","visual_orientation":"attention_score","possible_fatigue":"fatigue_score","occupancy":"occupancy_rate"}
def _avg(values):
    available=[float(v) for v in values if v is not None]
    return round(mean(available),2) if available else None
def session_evidence(db,session):
    snapshots=db.scalars(select(models.AnalyticsSnapshot).where(models.AnalyticsSnapshot.session_id==session.id)).all();quality=db.scalars(select(models.QualityAssessment).where(models.QualityAssessment.session_id==session.id)).all();audio=db.scalar(select(models.AudioAnalysis).where(models.AudioAnalysis.session_id==session.id));discourse=db.scalar(select(models.DiscourseAnalysis).where(models.DiscourseAnalysis.session_id==session.id));fusion=db.scalar(select(models.EvidenceFusionResult).where(models.EvidenceFusionResult.session_id==session.id).order_by(models.EvidenceFusionResult.id.desc()))
    excluded=db.scalars(select(models.Event).where(models.Event.session_id==session.id,models.Event.review_state.in_(["INCORRECT","EXCLUDED"]))).all()
    metrics={key:_avg(getattr(row,field) for row in snapshots) for key,field in METRICS.items()}
    metrics.update({"camera_quality":_avg(row.overall_quality for row in quality),"audio_quality":audio.quality.get("score") if audio and audio.status=="AVAILABLE" else None,"question_count":discourse.metrics.get("question_count",{}).get("value") if discourse and isinstance(discourse.metrics.get("question_count"),dict) else None,"fusion":fusion.value if fusion else None})
    coverage=round(len([r for r in snapshots if r.student_count>0])/len(snapshots),3) if snapshots else None
    return {"session_id":session.id,"name":session.name,"created_at":session.created_at,"duration":session.duration,"context":session.activity_context,"metrics":metrics,"coverage":coverage,"confidence":fusion.confidence if fusion else None,"methodology_version":fusion.methodology_version if fusion else None,"audio_status":audio.status if audio else "NOT_PROCESSED","excluded_evidence":len(excluded),"valid_observation_count":sum(r.student_count for r in snapshots if r.student_count>0),"snapshot_count":len(snapshots),"limitations":list(fusion.limitations) if fusion else ["Evidence fusion unavailable."]}
def aggregate_dashboard(db,sessions):
    evidence=[session_evidence(db,s) for s in sessions if not s.archived];keys=list(METRICS)+["camera_quality","audio_quality","question_count","fusion"]
    metrics={key:{"value":_avg(row["metrics"].get(key) for row in evidence),"available_sessions":sum(row["metrics"].get(key) is not None for row in evidence),"total_sessions":len(evidence)} for key in keys}
    limitations=Counter(l for row in evidence for l in row["limitations"])
    available=sum(envelope["available_sessions"]>0 for envelope in metrics.values());status="INSUFFICIENT_EVIDENCE" if not evidence or not available else "PARTIAL_EVIDENCE" if available<len(metrics) else "AVAILABLE"
    ids=[row["session_id"] for row in evidence];region_counts=Counter(db.scalars(select(models.StudentObservation.region_id).where(models.StudentObservation.session_id.in_(ids),models.StudentObservation.region_id.is_not(None))).all()) if ids else Counter();topics=Counter()
    if ids:
        for item in db.scalars(select(models.GeneratedContentItem).where(models.GeneratedContentItem.session_id.in_(ids),models.GeneratedContentItem.content_type.in_(["KEY_TERM","DEFINITION","CONCEPT"]))).all():topics[(item.edited_text or item.text).strip()[:120]]+=1
    timeline=[{"session_id":row["session_id"],"name":row["name"],"created_at":row["created_at"],"context":row["context"],"observable_participation":row["metrics"]["observable_participation"],"camera_quality":row["metrics"]["camera_quality"],"audio_quality":row["metrics"]["audio_quality"],"question_count":row["metrics"]["question_count"],"coverage":row["coverage"],"confidence":row["confidence"],"status":"PARTIAL_EVIDENCE" if any(value is None for value in row["metrics"].values()) else "AVAILABLE"} for row in evidence]
    return {"status":status,"session_count":len(evidence),"included_session_ids":ids,"metrics":metrics,"average_coverage":_avg(row["coverage"] for row in evidence),"average_confidence":_avg(row["confidence"] for row in evidence),"contexts":dict(Counter(row["context"] for row in evidence)),"methodology_versions":dict(Counter(row["methodology_version"] or "UNAVAILABLE" for row in evidence)),"audio_availability":dict(Counter(row["audio_status"] for row in evidence)),"reviewer_excluded_evidence":sum(row["excluded_evidence"] for row in evidence),"common_limitations":[{"text":k,"count":v} for k,v in limitations.most_common(5)],"session_timeline":timeline,"region_summaries":[{"region_id":key,"observation_count":value} for key,value in region_counts.most_common()],"topic_recurrence":[{"topic":key,"session_evidence_count":value} for key,value in topics.most_common(12)],"recent_sessions":evidence[-8:]}
def compare(db,sessions,metrics):
    rows=[session_evidence(db,s) for s in sessions];contexts={r["context"] for r in rows};versions={r["methodology_version"] for r in rows if r["methodology_version"]};coverages=[r["coverage"] for r in rows if r["coverage"] is not None];warnings=[]
    if len(contexts)>1:warnings.append("Sessions use incompatible activity contexts; interpret metric differences separately.")
    if coverages and max(coverages)-min(coverages)>.3:warnings.append("Evidence coverage differs by more than 30 percentage points.")
    if len(versions)>1:warnings.append("Sessions use different methodology versions.")
    unavailable=[metric for metric in metrics if not any(row["metrics"].get(metric) is not None for row in rows)]
    if unavailable:warnings.append("Insufficient evidence for: "+", ".join(unavailable)+"; unavailable values were not converted to zero.")
    status="INSUFFICIENT_EVIDENCE" if not rows or len(unavailable)==len(metrics) else "PARTIAL_EVIDENCE" if unavailable else "AVAILABLE"
    return {"status":status,"sessions":rows,"metrics":metrics,"warnings":warnings,"compatible":not any("incompatible" in warning.lower() or "different methodology" in warning.lower() for warning in warnings),"limitations":["Aggregate descriptive comparison; not an individual or causal conclusion."]}
def trend_buckets(db,sessions,period="daily",rolling_window=3,metric="observable_participation"):
    evidence=[session_evidence(db,s) for s in sessions]
    def key(row):
        stamp=row["created_at"]
        if period=="daily":bucket=stamp.strftime("%Y-%m-%d")
        elif period=="weekly":bucket=f"{stamp.isocalendar().year}-W{stamp.isocalendar().week:02d}"
        elif period=="monthly":bucket=stamp.strftime("%Y-%m")
        else:bucket=f"session-{row['session_id']}"
        return bucket,row["context"],row["methodology_version"] or "UNAVAILABLE"
    grouped={}
    for row in evidence:grouped.setdefault(key(row),[]).append(row)
    points=[]
    for (bucket,context,version),items in sorted(grouped.items()):
        valid=[r for r in items if r["metrics"].get(metric) is not None]
        weights=[max(float(r["coverage"] or 0),.0001) for r in valid]
        value=round(sum(float(r["metrics"][metric])*weight for r,weight in zip(valid,weights))/sum(weights),2) if valid else None
        points.append({"bucket":bucket,"context":context,"series":context,"methodology_version":version,"metric":metric,"value":value,metric:value,"session_count":len(items),"contributing_sessions":len(valid),"valid_observation_count":sum(r["valid_observation_count"] for r in valid),"coverage":_avg(r["coverage"] for r in valid),"confidence":_avg(r["confidence"] for r in valid),"reason":None if valid else "No valid stored evidence for the selected metric.","status":"AVAILABLE" if valid else "INSUFFICIENT_EVIDENCE"})
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
