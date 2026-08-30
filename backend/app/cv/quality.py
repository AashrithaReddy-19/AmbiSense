import cv2
import numpy as np

from ..metrics import bounded_percentage


def assess_frame_quality(frame: np.ndarray, *, people: int = 0, face_count: int = 0, pose_count: int = 0) -> dict:
    if frame is None or frame.size == 0:
        return {"overall_quality": None, "status": "UNAVAILABLE", "warnings": ["No decodable frame was available."]}
    gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY); brightness=float(gray.mean()); contrast=float(gray.std()); blur=float(cv2.Laplacian(gray,cv2.CV_64F).var())
    brightness_score=bounded_percentage(100-abs(brightness-127.5)/127.5*100) or 0
    contrast_score=bounded_percentage(contrast/55*100) or 0; sharpness_score=bounded_percentage(blur/180*100) or 0
    face_coverage=bounded_percentage(face_count/max(people,1)*100) if people else None; pose_coverage=bounded_percentage(pose_count/max(people,1)*100) if people else None
    components=[brightness_score,contrast_score,sharpness_score]
    if face_coverage is not None: components.append(face_coverage)
    overall=round(sum(components)/len(components),2)
    warnings=[]
    if brightness<45: warnings.append("Video is underexposed.")
    if brightness>220: warnings.append("Video is overexposed.")
    if blur<45: warnings.append("Video appears blurred; landmark metrics may be unreliable.")
    if people and (face_coverage or 0)<25: warnings.append("Visual orientation has insufficient face-landmark coverage.")
    return {"overall_quality":overall,"status":"GOOD" if overall>=70 else "LIMITED" if overall>=40 else "POOR","brightness":round(brightness,2),"contrast":round(contrast,2),"blur":round(blur,2),"brightness_score":brightness_score,"contrast_score":contrast_score,"sharpness_score":sharpness_score,"face_coverage_score":face_coverage,"pose_coverage_score":pose_coverage,"warnings":warnings}
