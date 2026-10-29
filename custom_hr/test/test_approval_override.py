"""A user holding every approver role can step in at a stuck stage; one role alone is not enough."""

import unittest
from unittest.mock import patch

import frappe
from frappe.model.workflow import is_transition_condition_satisfied

from custom_hr.services.approval_override import LEAVE_ROLES, OVERTIME_ROLES, leave_transitions, overtime_transitions


class Doc(frappe._dict):
	def as_dict(self):
		return self


class TestApprovalOverride(unittest.TestCase):
	def allowed(self, transition, doc, user, roles):
		def get_value(doctype, filters=None, *args, **kwargs):
			if doctype == "Has Role":
				return "row" if filters["parent"] == user and filters["role"] in roles else None
			if doctype == "Employee":
				return {"outlet": "OUT-1", "user_id": "crew@example.com"}[args[0] if args else kwargs.get("fieldname")]
			return None

		with patch("frappe.session", new=frappe._dict(user=user)), patch("frappe.db.get_value", side_effect=get_value):
			return is_transition_condition_satisfied(frappe._dict(transition), doc)

	def test_overtime_needs_every_approver_role_and_moves_only_one_stage(self):
		doc = Doc(approver_1="leader@example.com", approver_2="spv@example.com", employee="EMP-1")
		steps = {(t["state"], t["action"], t["next_state"]): t for t in overtime_transitions()}
		to_spv = steps[("Menunggu Leader", "Setujui", "Menunggu SPV")]
		self.assertTrue(self.allowed(to_spv, doc, "admin@example.com", OVERTIME_ROLES))
		self.assertTrue(self.allowed(to_spv, doc, "Administrator", ()))
		for partial in (("HR Manager",), ("Outlet Leader", "SPV Outlet")):
			with self.subTest(roles=partial):
				self.assertFalse(self.allowed(to_spv, doc, "admin@example.com", partial))
		self.assertFalse(self.allowed(to_spv, doc, "leader@example.com", OVERTIME_ROLES))  # the leader uses the normal step
		self.assertFalse(self.allowed(steps[("Menunggu Leader", "Setujui", "Menunggu HRD")], doc, "admin@example.com", OVERTIME_ROLES))
		self.assertNotIn("Disetujui", {t["next_state"] for t in overtime_transitions()})

	def test_leave_needs_every_approver_role_and_never_the_own_leave(self):
		doc = Doc(employee="EMP-1", leave_approver="pl@example.com", owner="crew@example.com")
		approve, reject = leave_transitions()
		self.assertEqual((approve["next_state"], reject["next_state"]), ("Menunggu HRD", "Rejected"))
		self.assertTrue(self.allowed(approve, doc, "admin@example.com", LEAVE_ROLES))
		self.assertFalse(self.allowed(approve, doc, "admin@example.com", ("HR Manager",)))
		self.assertFalse(self.allowed(approve, doc, "pl@example.com", LEAVE_ROLES))
		self.assertFalse(self.allowed(approve, Doc(doc, owner="admin@example.com"), "admin@example.com", LEAVE_ROLES))
