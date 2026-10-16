"""Keep native coordinates precise without changing global float formatting."""

from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	for fieldname in ("latitude", "longitude"):
		make_property_setter("Shift Location", fieldname, "precision", "7", "Int")
