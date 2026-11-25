"""Post-submit 5-class YOLO grooming classifier and configurable Grooming Settings tests."""

import io
import unittest

import frappe
import numpy as np
from PIL import Image

from custom_hr.services.grooming_classifier import (
	CLASSES,
	DEFAULT_SETTINGS,
	INPUT_SIZE,
	classify_grooming_photos,
	evaluate_scores,
	extract_class_detections,
	extract_class_scores,
	letterbox_image,
)

STEPS = ("right_hand", "left_hand", "trousers", "footwear")


def _sample_scores(**overrides):
	base = {step: {name: 0.05 for name in CLASSES} for step in STEPS}
	for step, patch in overrides.items():
		base[step].update(patch)
	return base


def _png_bytes(width=120, height=200, color=(20, 120, 220)):
	buf = io.BytesIO()
	Image.new("RGB", (width, height), color).save(buf, format="PNG")
	return buf.getvalue()


class TestGroomingClassifier(unittest.TestCase):
	def test_letterbox_pads_and_normalizes_to_chw_float32(self):
		tensor = letterbox_image(_png_bytes(208, 416, (255, 0, 0)), size=INPUT_SIZE)
		self.assertEqual(tensor.shape, (1, 3, INPUT_SIZE, INPUT_SIZE))
		self.assertEqual(tensor.dtype, np.float32)
		# Left padding should be gray (114 / 255), center pixel red (1.0, 0.0, 0.0).
		self.assertAlmostEqual(float(tensor[0, 0, 208, 0]), 114 / 255, places=3)
		self.assertAlmostEqual(float(tensor[0, 0, 208, 208]), 1.0, places=3)
		self.assertAlmostEqual(float(tensor[0, 1, 208, 208]), 0.0, places=3)

	def test_extract_class_scores_handles_channel_first_and_anchor_first(self):
		cf = np.zeros((1, 4 + len(CLASSES), 20), dtype=np.float32)
		cf[0, 4 + 0, 3] = 0.81  # topi
		cf[0, 4 + 1, 7] = 0.67  # celemek
		cf[0, 4 + 3, 2] = 0.92  # sepatu
		cf[0, 4 + 4, 15] = 0.14  # jeans
		af = np.transpose(cf, (0, 2, 1))
		for layout in (cf, af):
			scores = extract_class_scores(layout)
			self.assertAlmostEqual(scores["topi"], 0.81, places=5)
			self.assertAlmostEqual(scores["celemek"], 0.67, places=5)
			self.assertAlmostEqual(scores["sepatu"], 0.92, places=5)
			self.assertAlmostEqual(scores["jeans"], 0.14, places=5)

	def test_evaluate_scores_marks_sesuai_when_all_main_items_pass(self):
		scores = _sample_scores(
			right_hand={"celemek": 0.78, "topi": 0.84},
			trousers={"jeans": 0.12},
			footwear={"sepatu": 0.88, "crocs": 0.90},
		)
		res = evaluate_scores(scores, dict(DEFAULT_SETTINGS))
		self.assertEqual(res["review_status"], "Sesuai")
		self.assertEqual(res["review_note"], "Auto-review: Sesuai")

	def test_evaluate_scores_supports_legacy_cap_step_too(self):
		scores = _sample_scores(
			left_hand={"celemek": 0.75},
			trousers={"jeans": 0.10},
			footwear={"sepatu": 0.85},
		)
		scores["cap"] = {name: 0.05 for name in CLASSES}
		scores["cap"]["topi"] = 0.82
		res = evaluate_scores(scores, dict(DEFAULT_SETTINGS))
		self.assertEqual(res["review_status"], "Sesuai")
		self.assertEqual(res["review_note"], "Auto-review: Sesuai")

	def test_evaluate_scores_rejects_jeans_and_missing_required_items(self):
		scores = _sample_scores(
			right_hand={"celemek": 0.20, "topi": 0.10},
			trousers={"jeans": 0.72},
			footwear={"sepatu": 0.15},
		)
		res = evaluate_scores(scores, dict(DEFAULT_SETTINGS))
		self.assertEqual(res["review_status"], "Tidak Sesuai")
		self.assertEqual(
			res["review_note"],
			"Auto-review: Tidak sesuai — Celemek tidak terdeteksi, Topi tidak terdeteksi, Terdeteksi jeans, Sepatu tidak terdeteksi",
		)

	def test_extract_class_detections_normalizes_box_coordinates_from_letterbox(self):
		cf = np.zeros((1, 4 + len(CLASSES), 10), dtype=np.float32)
		cf[0, 0, 2] = 208  # cx
		cf[0, 1, 2] = 208  # cy
		cf[0, 2, 2] = 104  # bw
		cf[0, 3, 2] = 208  # bh
		cf[0, 4 + 0, 2] = 0.85  # topi
		# 208x416 image in 416x416 letterbox: new_w=208, new_h=416, pad_x=104, pad_y=0
		dets = extract_class_detections(cf, new_w=208, new_h=416, pad_x=104, pad_y=0)
		self.assertAlmostEqual(dets["topi"]["x"], 0.25, places=3)
		self.assertAlmostEqual(dets["topi"]["y"], 0.25, places=3)
		self.assertAlmostEqual(dets["topi"]["w"], 0.5, places=3)
		self.assertAlmostEqual(dets["topi"]["h"], 0.5, places=3)

	def test_evaluate_scores_collects_boxes_for_detected_items_only(self):
		det_steps = {
			"right_hand": {
				"topi": {"score": 0.80, "x": 0.2, "y": 0.1, "w": 0.3, "h": 0.2},
				"celemek": {"score": 0.20, "x": 0.1, "y": 0.4, "w": 0.5, "h": 0.4},
			},
			"left_hand": {
				"topi": {"score": 0.10, "x": 0.0, "y": 0.0, "w": 0.1, "h": 0.1},
				"celemek": {"score": 0.70, "x": 0.15, "y": 0.45, "w": 0.4, "h": 0.4},
			},
			"trousers": {"jeans": {"score": 0.75, "x": 0.2, "y": 0.3, "w": 0.5, "h": 0.6}},
			"footwear": {"sepatu": {"score": 0.85, "x": 0.25, "y": 0.5, "w": 0.4, "h": 0.3}},
		}
		res = evaluate_scores(det_steps, dict(DEFAULT_SETTINGS))
		self.assertEqual([(b["label"], b["score"]) for b in res["boxes_by_step"]["right_hand"]], [("Topi", 0.8)])
		self.assertEqual([(b["label"], b["score"]) for b in res["boxes_by_step"]["left_hand"]], [("Celemek", 0.7)])
		self.assertEqual([(b["label"], b["ok"], b["score"]) for b in res["boxes_by_step"]["trousers"]], [("Jeans", False, 0.75)])
		self.assertEqual([(b["label"], b["ok"], b["score"]) for b in res["boxes_by_step"]["footwear"]], [("Sepatu", True, 0.85)])

	def test_evaluate_scores_uses_configurable_thresholds_and_optional_crocs(self):
		scores = _sample_scores(
			left_hand={"celemek": 0.42, "topi": 0.25},
			trousers={"jeans": 0.35},
			footwear={"sepatu": 0.38, "crocs": 0.65},
		)
		lenient = {
			"enable_auto_review": True,
			"hat_threshold": 0.20,
			"apron_threshold": 0.40,
			"shoes_threshold": 0.35,
			"jeans_threshold": 0.40,
			"reject_crocs": False,
			"crocs_threshold": 0.50,
		}
		self.assertEqual(evaluate_scores(scores, lenient)["review_status"], "Sesuai")

		strict_crocs = {**lenient, "reject_crocs": True, "crocs_threshold": 0.60}
		res = evaluate_scores(scores, strict_crocs)
		self.assertEqual(res["review_status"], "Tidak Sesuai")
		self.assertIn("Crocs", res["review_note"])

	def test_real_five_class_onnx_model_runs_end_to_end(self):
		photos = {step: _png_bytes() for step in STEPS}
		res = classify_grooming_photos(photos, settings=dict(DEFAULT_SETTINGS))
		self.assertIn(res["review_status"], ("Sesuai", "Tidak Sesuai"))
		self.assertEqual(set(res["scores"].keys()), set(CLASSES))


class TestGroomingSettings(unittest.TestCase):
	def test_thresholds_must_be_between_zero_and_one(self):
		doc = frappe.new_doc("Grooming Settings")
		doc.update({"hat_threshold": 0.3, "apron_threshold": 0.5, "shoes_threshold": 0.4, "jeans_threshold": 0.5})
		doc.validate()
		for bad in (0, -0.1, 1.01):
			doc.hat_threshold = bad
			with self.subTest(bad=bad), self.assertRaises(frappe.ValidationError):
				doc.validate()
