from collections import defaultdict

from ..metrics import metric_envelope

METRICS={"occupancy":lambda r:1.0,"raised_hands":lambda r:100.0 if r.raised_hand else 0.0,"participation":lambda r:r.attention_score,"camera_visibility":lambda r:100.0 if r.yaw is not None else 0.0,"model_confidence":lambda r:r.confidence*100}

def aggregate_region_heatmap(observations, regions, metric: str, interval: float=5.0) -> dict:
    grouped=defaultdict(list); extractor=METRICS[metric]
    for row in observations:
        if row.region_id: grouped[row.region_id].append((row.timestamp,extractor(row)))
    cells=[]
    for region in regions:
        rows=grouped.get(region.region_key,[]); values=[value for _,value in rows]; eligible=len(rows)
        value=None if not values else (len({round(t/interval) for t,_ in rows}) if metric=="occupancy" else sum(values)/len(values))
        envelope=metric_envelope(metric,value,unit="count" if metric=="occupancy" else "percent",valid_observations=len(values),eligible_observations=eligible,confidence=sum(getattr(row,"confidence",0) for row in observations if row.region_id==region.region_key)/eligible if eligible else 0)
        cells.append({"region_id":region.region_key,"name":region.name,"polygon":region.polygon,**envelope})
    status="AVAILABLE" if any(cell["status"]=="AVAILABLE" for cell in cells) else "UNAVAILABLE"
    return {"metric":metric,"status":status,"cells":cells}
