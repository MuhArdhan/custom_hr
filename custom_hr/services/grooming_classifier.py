"""Server-side post-submit grooming classifier using the 5-class YOLO11n ONNX model."""

import io
import threading

import frappe
import numpy as np
from frappe.utils import cint, flt
from PIL import Image, ImageOps

MODEL_FILENAME = "lima2_yolo11n.onnx"
INPUT_SIZE = 416
CLASSES = ("topi", "celemek", "crocs", "sepatu", "jeans")

# Steps inspected for upper-body items (hat and apron) vs lower-body steps.
UPPER_BODY_STEPS = ("right_hand", "left_hand", "cap")
TROUSERS_STEP = "trousers"
FOOTWEAR_STEP = "footwear"

DEFAULT_SETTINGS = {
	"enable_auto_review": True,
	"enable_box": True,
	"hat_threshold": 0.30,
	"apron_threshold": 0.50,
	"shoes_threshold": 0.40,
	"jeans_threshold": 0.50,
	"reject_crocs": False,
	"crocs_threshold": 0.50,
}

_session_lock = threading.Lock()
_session = None


def get_model_path() -> str:
	return frappe.get_app_path("custom_hr", "public", MODEL_FILENAME)


def _get_session():
	global _session
	if _session is not None:
		return _session
	with _session_lock:
		if _session is None:
			import onnxruntime as rt

			_session = rt.InferenceSession(get_model_path(), providers=["CPUExecutionProvider"])
	return _session


def get_grooming_settings() -> dict:
	"""Load Grooming Settings with safe defaults if the Single DocType has not been migrated/saved yet."""
	settings = dict(DEFAULT_SETTINGS)
	try:
		if not frappe.db.exists("DocType", "Grooming Settings"):
			return settings
		doc = frappe.get_cached_doc("Grooming Settings")
	except Exception:
		return settings

	settings["enable_auto_review"] = bool(cint(doc.get("enable_auto_review")))
	settings["enable_box"] = bool(cint(doc.get("enable_box")))
	settings["reject_crocs"] = bool(cint(doc.get("reject_crocs")))
	for key in ("hat_threshold", "apron_threshold", "shoes_threshold", "jeans_threshold", "crocs_threshold"):
		val = doc.get(key)
		if val is not None and val != "":
			parsed = flt(val)
			if 0 < parsed <= 1:
				settings[key] = parsed
	return settings


def _letterbox_with_geometry(image_bytes: bytes, size: int = INPUT_SIZE) -> tuple[np.ndarray, int, int, int, int]:
	"""Decode image bytes into a CHW float32 tensor [1, 3, size, size] plus letterbox pixel geometry."""
	with Image.open(io.BytesIO(image_bytes)) as img:
		img = ImageOps.exif_transpose(img).convert("RGB")
		width, height = img.size
		scale = min(size / width, size / height)
		new_w, new_h = max(1, round(width * scale)), max(1, round(height * scale))
		pad_x, pad_y = (size - new_w) // 2, (size - new_h) // 2
		resized = img.resize((new_w, new_h), Image.Resampling.BILINEAR)
		canvas = Image.new("RGB", (size, size), (114, 114, 114))
		canvas.paste(resized, (pad_x, pad_y))
	arr = np.asarray(canvas, dtype=np.float32) / 255.0
	return np.transpose(arr, (2, 0, 1))[None, ...], new_w, new_h, pad_x, pad_y


def letterbox_image(image_bytes: bytes, size: int = INPUT_SIZE) -> np.ndarray:
	"""Decode image bytes and fit into a gray-padded square CHW float32 tensor [1, 3, size, size]."""
	tensor, *_ = _letterbox_with_geometry(image_bytes, size)
	return tensor


def _to_fraction_box(cx: float, cy: float, bw: float, bh: float, new_w: int, new_h: int, pad_x: int, pad_y: int) -> dict:
	x1 = max(0.0, min(1.0, (cx - bw / 2 - pad_x) / new_w))
	y1 = max(0.0, min(1.0, (cy - bh / 2 - pad_y) / new_h))
	x2 = max(0.0, min(1.0, (cx + bw / 2 - pad_x) / new_w))
	y2 = max(0.0, min(1.0, (cy + bh / 2 - pad_y) / new_h))
	return {"x": round(x1, 4), "y": round(y1, 4), "w": round(max(0.0, x2 - x1), 4), "h": round(max(0.0, y2 - y1), 4)}


def extract_class_detections(
	output: np.ndarray,
	new_w: int = INPUT_SIZE,
	new_h: int = INPUT_SIZE,
	pad_x: int = 0,
	pad_y: int = 0,
) -> dict[str, dict]:
	"""Return best confidence and normalized box per class from a YOLO tensor [1, 4+C, A] or [1, A, 4+C]."""
	arr = output[0]
	channel_first = arr.shape[0] < arr.shape[1]
	detections = {}
	for idx, name in enumerate(CLASSES):
		cls_row = arr[4 + idx, :] if channel_first else arr[:, 4 + idx]
		best_anchor = int(np.argmax(cls_row))
		score = float(cls_row[best_anchor])
		coords = arr[:4, best_anchor] if channel_first else arr[best_anchor, :4]
		box = _to_fraction_box(float(coords[0]), float(coords[1]), float(coords[2]), float(coords[3]), new_w, new_h, pad_x, pad_y)
		detections[name] = {"score": score, **box}
	return detections


def extract_class_scores(output: np.ndarray) -> dict[str, float]:
	"""Return the highest confidence per class from a YOLO detection tensor [1, 4+C, A] or [1, A, 4+C]."""
	return {name: info["score"] for name, info in extract_class_detections(output).items()}


def detect_image_bytes(image_bytes: bytes) -> dict[str, dict]:
	session = _get_session()
	input_name = session.get_inputs()[0].name
	output_name = session.get_outputs()[0].name
	tensor, new_w, new_h, pad_x, pad_y = _letterbox_with_geometry(image_bytes, INPUT_SIZE)
	output = session.run([output_name], {input_name: tensor})[0]
	return extract_class_detections(output, new_w, new_h, pad_x, pad_y)


def _step_boxes(step: str, detections: dict[str, dict], settings: dict) -> list[dict]:
	"""Pick the boxes relevant to a step when the model detected them above threshold."""
	rules = ()
	if step in UPPER_BODY_STEPS:
		rules = (
			("topi", "Topi", settings["hat_threshold"], True),
			("celemek", "Celemek", settings["apron_threshold"], True),
		)
	elif step == TROUSERS_STEP:
		rules = (("jeans", "Jeans", settings["jeans_threshold"], False),)
	elif step == FOOTWEAR_STEP:
		rules = [("sepatu", "Sepatu", settings["shoes_threshold"], True)]
		if settings["reject_crocs"]:
			rules.append(("crocs", "Crocs", settings["crocs_threshold"], False))
	boxes = []
	for key, label, threshold, ok in rules:
		det = detections.get(key)
		if det and det["score"] >= threshold and det["w"] > 0 and det["h"] > 0:
			boxes.append({"label": label, "score": round(det["score"], 4), "ok": ok, "x": det["x"], "y": det["y"], "w": det["w"], "h": det["h"]})
	return boxes


def evaluate_scores(step_scores: dict[str, dict], settings: dict) -> dict:
	"""Apply configurable compliance thresholds across the submitted step detections or scores."""
	def score_of(step: str, cls_name: str) -> float:
		entry = step_scores.get(step, {}).get(cls_name, 0.0)
		return float(entry["score"]) if isinstance(entry, dict) else float(entry)

	upper_steps = [step for step in UPPER_BODY_STEPS if step in step_scores]
	hat_score = max((score_of(step, "topi") for step in upper_steps), default=0.0)
	apron_score = max((score_of(step, "celemek") for step in upper_steps), default=0.0)
	jeans_score = score_of(TROUSERS_STEP, "jeans")
	shoes_score = score_of(FOOTWEAR_STEP, "sepatu")
	crocs_score = score_of(FOOTWEAR_STEP, "crocs")

	failures = []
	if apron_score < settings["apron_threshold"]:
		failures.append("Celemek tidak terdeteksi")
	if hat_score < settings["hat_threshold"]:
		failures.append("Topi tidak terdeteksi")
	if jeans_score >= settings["jeans_threshold"]:
		failures.append("Terdeteksi jeans")
	if shoes_score < settings["shoes_threshold"]:
		failures.append("Sepatu tidak terdeteksi")
	if settings["reject_crocs"] and crocs_score >= settings["crocs_threshold"]:
		failures.append("Terdeteksi Crocs")

	boxes_by_step = {
		step: _step_boxes(step, dets, settings)
		for step, dets in step_scores.items()
		if dets and isinstance(next(iter(dets.values()), None), dict)
	}

	if not failures:
		review_status, review_note = "Sesuai", "Auto-review: Sesuai"
	else:
		review_status = "Tidak Sesuai"
		review_note = f"Auto-review: Tidak sesuai — {', '.join(failures)}"

	return {
		"review_status": review_status,
		"review_note": review_note,
		"scores": {
			"topi": hat_score,
			"celemek": apron_score,
			"sepatu": shoes_score,
			"jeans": jeans_score,
			"crocs": crocs_score,
		},
		"boxes_by_step": boxes_by_step,
	}


def classify_grooming_photos(photos_by_step: dict[str, bytes], settings: dict | None = None) -> dict:
	cfg = settings if settings is not None else get_grooming_settings()
	step_detections = {step: detect_image_bytes(data) for step, data in photos_by_step.items() if data}
	return evaluate_scores(step_detections, cfg)


def read_doc_photos_bytes(doc) -> dict[str, bytes]:
	"""Load private image file contents from disk for each Grooming Photo row."""
	photos_by_step = {}
	for row in doc.get("photos") or []:
		if not row.photo or row.photo == "pending":
			continue
		file_doc = frappe.get_doc("File", {"file_url": row.photo})
		content = file_doc.get_content()
		if isinstance(content, str):
			content = content.encode()
		photos_by_step[row.step] = content
	return photos_by_step
