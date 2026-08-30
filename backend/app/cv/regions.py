"""Resolution-independent polygon assignment and aggregate region analytics."""
from __future__ import annotations


def point_in_polygon(point: tuple[float, float], polygon: list[dict[str, float] | list[float]]) -> bool:
    x, y = point; points=[(float(p["x"]),float(p["y"])) if isinstance(p,dict) else (float(p[0]),float(p[1])) for p in polygon]
    if len(points)<3: return False
    inside=False; previous=points[-1]
    for current in points:
        x1,y1=previous; x2,y2=current
        if ((y1>y)!=(y2>y)) and x < (x2-x1)*(y-y1)/max(y2-y1,1e-12)+x1: inside=not inside
        previous=current
    return inside


def assign_region(center_pixels: tuple[float,float], width: int, height: int, regions: list) -> str | None:
    if width<=0 or height<=0: return None
    normalized=(center_pixels[0]/width,center_pixels[1]/height)
    for region in regions:
        polygon=region.polygon if hasattr(region,"polygon") else region["polygon"]
        active=region.active if hasattr(region,"active") else region.get("active",True)
        if active and point_in_polygon(normalized,polygon): return region.region_key if hasattr(region,"region_key") else region["region_key"]
    return None


def region_summary(observations: list, regions: list) -> list[dict]:
    output=[]
    for region in regions:
        key=region.region_key if hasattr(region,"region_key") else region["region_key"]
        rows=[row for row in observations if row.region_id==key]
        tracks={row.tracking_id for row in rows}; hands=sum(bool(row.raised_hand) for row in rows)
        output.append({"region_id":key,"name":region.name if hasattr(region,"name") else region["name"],"observation_count":len(rows),"estimated_unique_tracks":len(tracks),"raised_hand_observations":hands,"visual_coverage":round(sum(row.yaw is not None for row in rows)/len(rows)*100,2) if rows else None})
    return output
