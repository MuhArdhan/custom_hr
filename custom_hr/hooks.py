app_name = "custom_hr"
app_title = "HRM"
app_publisher = "callmevan1120"
app_description = "HRM: HR app with attendance gallery, face check-in and realtime attendance on top of Frappe HR"
app_email = "admin@example.com"
app_license = "mit"
required_apps = ["hrms"]
after_install = [
	"custom_hr.patches.setup_native_leave_workflow.execute",
	"custom_hr.patches.remove_legacy_leave_approval_fields.execute",
	"custom_hr.patches.add_leave_calendar_sidebar.execute",
]
after_migrate = "custom_hr.patches.add_leave_calendar_sidebar.execute"
after_sync = "custom_hr.install.set_default_overtime_component"

scheduler_events = {
	"daily": ["custom_hr.contract_notifications.send_contract_expiry_reminders"],
	"hourly": ["custom_hr.services.outlet_scheduler.run_outlet_attendance_scheduler"],
}

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
	"Attendance": "public/js/attendance_list.js",
	"Employee Checkin": "public/js/employee_checkin_list.js",
	"Holiday List Assignment": "public/js/holiday_list_assignment_list.js",
	"Outlet": "public/js/outlet.js",
	"Overtime Request": "public/js/overtime_request.js",
	"Shift Type": "public/js/shift_type_list.js",
}

# ----------------------------------------------------------------------------
# Row-level permissions
# ----------------------------------------------------------------------------

permission_query_conditions = {
	"Overtime Request": "custom_hr.api.overtime.get_permission_query_conditions",
	"Overtime List": "custom_hr.api.overtime.get_list_permission_query_conditions",
}

has_permission = {
	"Overtime Request": "custom_hr.api.overtime.has_permission",
	"Overtime List": "custom_hr.api.overtime.has_permission",
}

# ----------------------------------------------------------------------------
# DocType overrides
# ----------------------------------------------------------------------------

# self-service check-in limits, face verification requirement, realtime
# attendance marking right after check-out
override_doctype_class = {
	"Employee Checkin": "custom_hr.overrides.employee_checkin.CustomEmployeeCheckin",
	"Shift Type": "custom_hr.overrides.shift_type.CustomShiftType",
	"Email Queue": "custom_hr.overrides.email_queue.CustomEmailQueue",
}

override_whitelisted_methods = {
	"hrms.hr.doctype.leave_application.leave_application.get_leave_approver": "custom_hr.services.leave_approver.get_leave_approver",
	"hrms.api.get_leave_approval_details": "custom_hr.services.leave_approver.get_leave_approval_details",
}

doc_events = {
	"Department": {
		"validate": "custom_hr.services.department_shift.validate_department",
	},
	"Attendance": {
		"validate": "custom_hr.services.attendance_duration.fill_durations",
	},
	"Employee": {
		"validate": "custom_hr.services.employee_outlet.fill_outlet",
	},
	"Leave Application": {
		"before_validate": "custom_hr.services.leave_approver.fill_leave_approver",
		"after_insert": "custom_hr.services.leave_approver.submit_to_approver",
	},
	"Shift Location": {
		"on_update": "custom_hr.services.outlet_location.sync_location_radius_to_outlet",
	},
}

# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------

fixtures = [
	{
		"doctype": "Property Setter",
		"filters": [
			[
				"name",
				"in",
				[
					"Shift Location-latitude-precision",
					"Shift Location-longitude-precision",
					"Shift Type-late_entry_grace_period-label",
					"Shift Type-late_entry_grace_period-description",
					"Shift Type-early_exit_grace_period-label",
					"Shift Type-early_exit_grace_period-description",
					"Shift Type-enable_auto_attendance-default",
					"Shift Type-working_hours_threshold_for_half_day-default",
					"Shift Type-late_entry_grace_period-default",
					"Shift Type-early_exit_grace_period-default",
					"Shift Type-enable_late_entry_marking-default",
					"Shift Type-enable_early_exit_marking-default",
					"Attendance-attendance_date-in_standard_filter",
					"Attendance-late_entry-in_standard_filter",
					"Attendance-early_exit-in_standard_filter",
					"Attendance-shift-in_standard_filter",
					"Attendance-company-in_standard_filter",
					"Attendance-department-in_standard_filter",
				],
			]
		],
	},
	{
		"doctype": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				[
					"Employee-outlet",
					"Employee-user_username",
					"Employee Checkin-face_verification_section",
					"Employee Checkin-face_verified",
					"Employee Checkin-face_score",
					"Employee Checkin-column_break_face",
					"Employee Checkin-face_photo",
					"Employee Checkin-outlet_shift_section",
					"Employee Checkin-attendance_source",
					"Employee Checkin-outlet_at_checkin",
					"Employee Checkin-shift_work_date",
					"Employee Checkin-outlet_shift_column",
					"Employee Checkin-paired_checkin",
					"Employee Checkin-checkout_deadline",
					"Employee Checkin-shift_policy_snapshot",
					"Attendance-outlet_attendance_section",
					"Attendance-attendance_source",
					"Attendance-outlet_at_checkin",
					"Attendance-source_checkin",
					"Attendance-source_checkout",
					"Attendance-outlet_attendance_column",
					"Attendance-missing_checkout",
					"Attendance-working_hours_source",
					"Attendance-working_duration",
					"Attendance-late_entry_duration",
					"Attendance-early_exit_duration",
					"Department-auto_shift_section",
					"Department-enable_auto_shift",
					"Department-auto_shift_transition_minutes",
					"Department-auto_shift_allow_unscheduled_days",
					"Department-auto_shift_effective_from",
					"Department-auto_shifts",
					"Department-auto_shift_help",
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
		"filters": [["name", "in", ["Setujui", "Tolak"]]],
	},
	{"doctype": "Salary Component", "filters": [["name", "in", ["Lembur", "Tunjangan Tetap"]]]},
	{"doctype": "Overtime Type", "filters": [["name", "=", "Lembur"]]},
	{
		"doctype": "Custom DocPerm",
		"filters": [["parent", "in", ["Overtime Type", "Employee", "Shift Type"]]],
	},
]
