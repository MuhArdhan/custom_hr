"""Add the Grooming link to the HRM sidebar on sites that already ran add_hrm_sidebar_links."""

from custom_hr.patches.add_hrm_sidebar_links import execute as add_links


def execute():
	add_links()  # idempotent: only links that are still missing are added
