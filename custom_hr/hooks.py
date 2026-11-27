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
after_migrate = [
	"custom_hr.patches.add_leave_calendar_sidebar.execute",
	"custom_hr.services.pph21_ter_seed.seed_defaults",
	"custom_hr.services.payroll_payable.seed_default_payable_account_number",
	"custom_hr.services.attendance_overtime.sync_existing_attendances",
]
after_sync = [
	"custom_hr.install.set_default_overtime_component",
	"custom_hr.services.pph21_ter_seed.seed_defaults",
]

scheduler_events = {
	"daily": [
		"custom_hr.contract_notifications.send_contract_expiry_reminders",
		"custom_hr.services.leave_auto_allocation.allocate",
		"custom_hr.services.auto_absence.mark_department_absences",
	],
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
		"route": "/app/hrm",
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
	"Bulk Salary Structure Assignment": "public/js/bulk_salary_structure_assignment.js",
	"Department": "public/js/shift_days.js",
	"Employee": "public/js/employee_face.js",
	"Leave Application": "public/js/leave_application.js",
	"Outlet": ["public/js/outlet.js", "public/js/shift_days.js"],
	"Overtime Request": "public/js/overtime_request.js",
	"Payroll Entry": "public/js/payroll_entry_match.js",
	"Salary Structure": "public/js/salary_structure.js",
	"Salary Structure Assignment": "public/js/salary_structure_assignment.js",
	"Shift Location": "public/js/shift_location.js",
	"Shift Request": "public/js/shift_request.js",
}

doctype_list_js = {
	"Attendance": "public/js/attendance_list.js",
	"Employee Advance": "public/js/employee_advance_list.js",
	"Employee Checkin": "public/js/employee_checkin_list.js",
	"Holiday List Assignment": "public/js/holiday_list_assignment_list.js",
	"Outlet": "public/js/outlet.js",
	"Overtime Request": "public/js/overtime_request.js",
	"Payroll Entry": ["public/js/payroll_bulk.js", "public/js/payroll_entry_list.js"],
	"Salary Slip": ["public/js/payroll_bulk.js", "public/js/salary_slip_list.js"],
	"Salary Structure Assignment": "public/js/salary_structure_assignment_list.js",
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
	"Employee": "custom_hr.overrides.employee.CustomEmployee",
	"Employee Checkin": "custom_hr.overrides.employee_checkin.CustomEmployeeCheckin",
	"Shift Type": "custom_hr.overrides.shift_type.CustomShiftType",
	"Email Queue": "custom_hr.overrides.email_queue.CustomEmailQueue",
	"Leave Application": "custom_hr.overrides.leave_application.CustomLeaveApplication",
	"Attendance": "custom_hr.overrides.attendance.CustomAttendance",
	"Salary Slip": "custom_hr.overrides.payroll.CustomSalarySlip",
	"Salary Structure Assignment": "custom_hr.overrides.payroll.CustomSalaryStructureAssignment",
	"Payroll Entry": "custom_hr.overrides.payroll.CustomPayrollEntry",
}

override_whitelisted_methods = {
	"hrms.hr.doctype.leave_application.leave_application.get_leave_approver": "custom_hr.services.leave_approver.get_leave_approver",
	"hrms.api.get_leave_approval_details": "custom_hr.services.leave_approver.get_leave_approval_details",
	"hrms.api.get_current_employee_info": "custom_hr.services.employee_outlet.get_current_employee_info",
	"hrms.payroll.doctype.payroll_entry.payroll_entry.employee_query": "custom_hr.overrides.payroll.payroll_entry_employee_query",
}

doc_events = {
	"Company": {
		"on_update": "custom_hr.services.component_accounts.on_company_update",
	},
	"Department": {
		"validate": [
			"custom_hr.services.department_shift.validate_department",
			"custom_hr.services.department_approvers.validate_department_approvers",
		],
	},
	"Attendance": {
		"validate": [
			"custom_hr.services.attendance_duration.fill_durations",
			"custom_hr.services.hourly_leave.fill_attendance_izin",
			"custom_hr.services.attendance_overtime.fill_attendance_overtime",
		],
		"on_update_after_submit": "custom_hr.services.attendance_overtime.fill_attendance_overtime",
	},
	"Overtime Request": {
		"on_update": "custom_hr.services.attendance_overtime.stamp_request_attendances",
		"on_trash": "custom_hr.services.attendance_overtime.clear_request_attendances",
	},
	"Employee": {
		"validate": "custom_hr.services.employee_outlet.fill_outlet",
	},
	"HR Settings": {
		"on_update": "custom_hr.services.employee_nip.keep_visible",
	},
	"Leave Application": {
		"before_validate": [
			"custom_hr.services.leave_approver.fill_leave_approver",
			"custom_hr.services.hourly_leave.validate_hourly_leave",
			"custom_hr.services.employee_scope.validate_leave_application_scope",
		],
		"on_submit": "custom_hr.services.hourly_leave.stamp_attendance_izin",
		"on_cancel": "custom_hr.services.hourly_leave.stamp_attendance_izin",
		"after_insert": "custom_hr.services.leave_approver.submit_to_approver",
		"on_update": "custom_hr.services.leave_approver.hand_over_to_approver_2",
	},
	"Shift Request": {
		"before_validate": "custom_hr.services.employee_scope.validate_shift_request_scope",
	},
	"Overtime Type": {
		"validate": "custom_hr.api.overtime_pay.validate_overtime_type",
	},
	"Leave Type": {
		"validate": "custom_hr.services.leave_auto_allocation.validate_leave_type",
		"on_update": "custom_hr.services.leave_auto_allocation.on_leave_type_update",
	},
	"Salary Slip": {
		"before_validate": "custom_hr.services.payroll_penalties.fill_attendance_penalties",
	},
	"Salary Structure Assignment": {
		"before_validate": "custom_hr.services.payroll_payable.fill_payable_account",
	},
	"Salary Structure": {
		"validate": "custom_hr.services.salary_structure_scope.validate_salary_structure",
		"on_update_after_submit": "custom_hr.services.salary_structure_scope.validate_salary_structure",
	},
	"Payroll Settings": {
		"validate": [
			"custom_hr.services.payroll_settings.validate",
			"custom_hr.services.pph21_ter.validate_settings",
		],
		"on_update": "custom_hr.services.component_accounts.on_settings_update",
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
					"Department-leave_approvers-label",
					"Department-leave_approvers-description",
					"Shift Location-longitude-precision",
					"Shift Type-late_entry_grace_period-label",
					"Shift Type-late_entry_grace_period-description",
					"Shift Type-early_exit_grace_period-label",
					"Shift Type-early_exit_grace_period-description",
					"Shift Type-enable_auto_attendance-default",
					"Shift Type-allow_overtime-default",
					"Shift Type-overtime_type-hidden",
					"Shift Type-overtime_type-mandatory_depends_on",
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
					"Employee-employee_number-label",
					"Salary Slip-main-default_print_format",
					"Bulk Salary Structure Assignment-company-fetch_from",
					"Bulk Salary Structure Assignment-company-read_only",
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
					"Leave Type-auto_allocation_section",
					"Leave Type-auto_allocate",
					"Leave Type-auto_allocate_every",
					"Leave Type-auto_allocate_leaves",
					"Leave Type-auto_allocate_for",
					"Leave Type-auto_allocate_start_day",
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
					"Salary Slip-attendance_penalty_section",
					"Salary Slip-jumlah_telat",
					"Salary Slip-jumlah_pulang_cepat",
					"Salary Slip-jumlah_tidak_out",
					"Salary Slip-jumlah_hadir",
					"Salary Slip-hari_kerja",
					"Salary Slip-jumlah_alpha",
					"Salary Slip-jam_izin",
					"Salary Slip-jam_lembur",
					"Salary Slip-upah_lembur",
					"Salary Slip-upah_lembur_reguler",
					"Salary Slip-upah_lembur_holiday",
					"Salary Slip-tunjangan_shift",
					"Salary Slip-tunjangan_jabatan",
					"Salary Slip-tunjangan_resiko",
					"Payroll Settings-designation_allowance_section",
					"Payroll Settings-designation_allowances",
					"Payroll Settings-component_account_section",
					"Payroll Settings-component_accounts",
					"Leave Type-dihitung_hadir",
					"HR Settings-batasi_checkout_awal",
					"HR Settings-checkout_dibuka_menit",
					"Leave Type-izin_per_jam",
					"Leave Application-izin_per_jam",
					"Leave Application-from_time",
					"Leave Application-to_time",
					"Leave Application-jam_izin",
					"Attendance-jam_izin",
					"Attendance-overtime_request",
					"Attendance-approved_overtime_hours",
					"Attendance-paid_overtime_hours",
					"Salary Slip-attendance_penalty_column",
					"Salary Slip-tarif_telat",
					"Salary Slip-tarif_pulang_cepat",
					"Salary Slip-tarif_tidak_out",
					"Salary Slip-tarif_uang_makan",
					"Salary Slip-tarif_transport",
					"Salary Slip-dasar_bpjs",
					"Employee-tidak_ikut_bpjs",
					"Payroll Settings-hrm_tab",
					"Payroll Settings-wage_base_section",
					"Payroll Settings-wage_base_components",
					"Payroll Settings-column_break_wage",
					"Payroll Settings-overtime_salary_component",
					"Payroll Settings-overtime_hourly_divisor",
					"Payroll Settings-driver_report_opens_at",
					"Payroll Settings-daily_rate_section",
					"Payroll Settings-daily_rates",
					"Payroll Settings-bpjs_section",
					"Payroll Settings-bpjs_rates",
					"Payroll Settings-attendance_penalty_section",
					"Payroll Settings-attendance_penalty_rates",
					"Payroll Settings-shift_allowance_section",
					"Payroll Settings-shift_allowances",
					"Payroll Settings-match_section",
					"Payroll Settings-match_columns",
					"Payroll Settings-je_section",
					"Payroll Settings-outlet_expense_account_number",
					"Payroll Settings-intercompany_receivable_account_number",
					"Payroll Settings-intercompany_payable_account_name",
					"Salary Component-show_in_period_input",
					"Department-auto_shift_section",
					"Department-enable_auto_shift",
					"Department-manual_shift_choice",
					"Department-auto_shift_transition_minutes",
					"Department-auto_shift_allow_unscheduled_days",
					"Department-auto_shift_effective_from",
					"Department-auto_shifts",
					"Department-auto_shift_help",
					"Department-checkin_location_section",
					"Department-shift_location",
					"HR Settings-enable_face_checkin",
					"HR Settings-require_face_checkin",
					"HR Settings-face_match_threshold",
					"HR Settings-face_enroll_samples",
					"HR Settings-grooming_deadline_minutes",
					"Employee-dependents",
					"Employee-nik",
					"Payroll Settings-hrm_accounting_tax_tab",
					"Payroll Settings-default_payroll_payable_account_number",
					"Payroll Settings-pph21_ter_section",
					"Payroll Settings-enable_pph21_ter",
					"Payroll Settings-pph21_ter_companies",
					"Payroll Settings-pph21_ter_tables_section",
					"Payroll Settings-pph21_ptkp_map",
					"Payroll Settings-pph21_employer_bpjs",
					"Payroll Settings-pph21_ter_rates",
					"Salary Slip-dasar_bruto_pph21",
					"Salary Slip-tarif_ter_pph21",
					"Salary Structure-lintas_company",
					"Salary Structure-berlaku_untuk",
					"Salary Structure-hanya_department",
					"Overtime Type-disabled",
					"Overtime Type-berlaku_untuk",
					"Overtime Type-hanya_department",
					"Leave Type-berlaku_untuk",
					"Leave Type-hanya_department",
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
