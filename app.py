# ======================================================================================
# LEGACY / DEPRECATED: part of the original Flask + DeepFace prototype. It is NOT used by
# AmbiSense (FastAPI backend/ + React frontend/) and must not be integrated with it: it
# performs facial recognition, which AmbiSense deliberately does not. Kept only for reference.
# ======================================================================================
import shutil
import tempfile
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename

from face_processing import process_image
from fire import detect_fire_in_video
from noice import detect_noise
from projector import process_video


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 250 * 1024 * 1024


def save_upload(upload, folder: Path) -> Path:
    if upload is None or not upload.filename:
        raise ValueError("A file is required.")
    filename = secure_filename(upload.filename)
    if not filename:
        raise ValueError("The filename is invalid.")
    destination = folder / filename
    upload.save(destination)
    return destination


def run_with_upload(field, processor):
    work_dir = Path(tempfile.mkdtemp(prefix="shiksha_"))
    try:
        source = save_upload(request.files.get(field), work_dir)
        return jsonify(processor(str(source)))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "service": "SHIKSHA classroom analytics"})


@app.post("/api/fire")
def fire_detection():
    return run_with_upload("video", detect_fire_in_video)


@app.post("/api/projector")
def projector_detection():
    return run_with_upload("video", process_video)


@app.post("/api/noise")
def noise_detection():
    return run_with_upload("audio", detect_noise)


@app.post("/api/faces")
def face_detection():
    work_dir = Path(tempfile.mkdtemp(prefix="shiksha_faces_"))
    registered_dir = work_dir / "registered"
    crops_dir = work_dir / "crops"
    registered_dir.mkdir()
    crops_dir.mkdir()
    try:
        image = save_upload(request.files.get("image"), work_dir)
        registered = request.files.getlist("registered_faces")
        if not registered or not any(item.filename for item in registered):
            raise ValueError("At least one registered face image is required.")
        for item in registered:
            if item.filename:
                save_upload(item, registered_dir)
        return jsonify(process_image(str(image), str(registered_dir), str(crops_dir)))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@app.errorhandler(ValueError)
def invalid_input(error):
    return jsonify({"error": str(error)}), 400


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "Upload is larger than 250 MB."}), 413


@app.errorhandler(Exception)
def unexpected_error(error):
    app.logger.exception("Processing failed")
    return jsonify({"error": str(error)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
