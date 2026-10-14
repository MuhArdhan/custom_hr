app_name = "custom_hr"
app_title = "HRM"
app_publisher = "callmevan1120"
app_description = "HRM: HR app with attendance gallery, face check-in and realtime attendance on top of Frappe HR"
app_email = "admin@example.com"
app_license = "mit"
required_apps = ["hrms"]

# ----------------------------------------------------------------------------
# App switcher entry (own icon, separate from Frappe HR)
# ----------------------------------------------------------------------------

add_to_apps_screen = [
	{
		"name": "custom_hr",
		"logo": "/assets/custom_hr/images/hrm-logo.svg",
		"title": "HRM",
		"route": "/app/employee-attendance-gallery",
	}
]

# ----------------------------------------------------------------------------
# Desk assets
# ----------------------------------------------------------------------------

# Drop Frappe's cached copy of the attendance gallery page on every desk boot,
# so an updated page script/style is always picked up.
app_include_js = "custom_hr.bundle.js"

# ----------------------------------------------------------------------------
# DocType javascript
# ----------------------------------------------------------------------------

doctype_js = {
	"Employee": "public/js/employee_face.js",
	"Outlet": "public/js/outlet.js",
	"Overtime Request": "public/js/overtime_request.js",
}

doctype_list_js = {
	"Employee Checkin": "public/js/employee_checkin_list.js",
	"Outlet": "public/js/outlet.js",
	"Overtime Request": "public/js/overtime_request.js",
}

# ----------------------------------------------------------------------------
# Row-level permissions
# ----------------------------------------------------------------------------

permission_query_conditions = {
	"Overtime Request": "custom_hr.api.overtime.get_permission_query_conditions",
}

has_permission = {
	"Overtime Request": "custom_hr.api.overtime.has_permission",
}

# ----------------------------------------------------------------------------
# DocType overrides
# ----------------------------------------------------------------------------

# self-service check-in limits, face verification requirement, realtime
# attendance marking right after check-out
override_doctype_class = {
	"Employee Checkin": "custom_hr.overrides.employee_checkin.CustomEmployeeCheckin",
}

# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------

fixtures = [
	{
		"doctype": "Property Setter",
		"filters": [["doc_type", "=", "Salary Slip"], ["property", "=", "default_print_format"],
			["value", "=", "Slip Gaji JURI"]],
	},
	{
		"doctype": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				[
					"Employee-outlet",
					"Employee Checkin-face_verification_section",
					"Employee Checkin-face_verified",
					"Employee Checkin-face_score",
					"Employee Checkin-column_break_face",
					"Employee Checkin-face_photo",
					"HR Settings-enable_face_checkin",
					"HR Settings-require_face_checkin",
					"HR Settings-face_match_threshold",
					"HR Settings-face_enroll_samples",
				],
			]
		],
	},
	{"doctype": "Workspace", "filters": [["name", "=", "Shift & Attendance"]]},
	{"doctype": "Workflow", "filters": [["document_type", "=", "Overtime Request"]]},
	{
		"doctype": "Workflow State",
		"filters": [
			[
				"name",
				"in",
				["Menunggu Leader", "Menunggu SPV", "Menunggu HRD", "Disetujui", "Ditolak"],
			]
		],
	},
	{
		"doctype": "Workflow Action Master",
		"filters": [["name", "in", ["Setujui", "Setujui (HRD)", "Tolak"]]],
	},
	{"doctype": "Salary Component", "filters": [["name", "in", ["Lembur", "Tunjangan Tetap"]]]},
	{"doctype": "Overtime Type", "filters": [["name", "=", "Lembur"]]},
	{
		"doctype": "Custom DocPerm",
		"filters": [["parent", "in", ["Overtime Type", "Employee", "Shift Type"]]],
	},
]
