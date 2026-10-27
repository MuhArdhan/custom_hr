"""Fill Employee.user_username for employees already linked to a user (fetch_from only runs on save)."""

import frappe
from frappe.utils.fixtures import sync_fixtures


def execute():
	sync_fixtures("custom_hr")  # fixtures normally sync after patches, but the column must exist first
	frappe.db.sql(
		"""update `tabEmployee` e join `tabUser` u on u.name = e.user_id
		set e.user_username = u.username where ifnull(e.user_username, '') = ''"""
	)
