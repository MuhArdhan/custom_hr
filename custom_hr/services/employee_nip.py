"""NIP (Employee Number) is optional: PH staff have one, an outlet crew may not."""

from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def keep_visible(doc, method=None):
	"""HR Settings on_update: with Naming Series, HRMS hides the NIP field on every save; it is shown again."""
	make_property_setter("Employee", "employee_number", "hidden", 0, "Check", validate_fields_for_doctype=False)
