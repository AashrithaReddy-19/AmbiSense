ACTIVITY_CONTEXTS=("LECTURE","EXAMINATION","GROUP_DISCUSSION","LABORATORY","STUDENT_PRESENTATION","INDEPENDENT_WRITING","READING","VIDEO_SCREENING","BREAK")
CONTEXT_LIMITATIONS={"EXAMINATION":["Looking down may represent writing; visual orientation should not be interpreted as distraction."],"GROUP_DISCUSSION":["Multiple head directions are expected during group discussion."],"INDEPENDENT_WRITING":["Forward visual orientation is not a meaningful participation proxy during writing."],"READING":["Looking down may represent reading rather than reduced participation."],"VIDEO_SCREENING":["Orientation estimates depend on screen position and camera placement."],"BREAK":["Participation and visual-orientation metrics are not meaningful during a break."]}

def context_limitations(activity_type: str, metric: str) -> list[str]:
    return list(CONTEXT_LIMITATIONS.get(activity_type.upper(),[])) if metric in {"visual_orientation","observable_participation"} else []

def metric_relevant(activity_type: str, metric: str) -> bool:
    return not (activity_type.upper()=="BREAK" and metric in {"visual_orientation","observable_participation","possible_fatigue"})
