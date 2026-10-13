frappe.ui.form.on("Contract Notification Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Preview Recipients"), () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Please save settings before previewing."));
				return;
			}
			frappe.call({
				method: "custom_hr.contract_notifications.preview_contract_expiry_reminders",
				freeze: true,
				callback({ message }) {
					const content = frappe.utils.escape_html(JSON.stringify(message, null, 2));
					frappe.msgprint({ title: __("Contract Reminder Preview"), message: `<pre>${content}</pre>`, wide: true });
				},
			});
		});
		if (frappe.session.user === "Administrator" || frappe.user.has_role("HR Manager")) {
			frm.add_custom_button(__("Send Test Email"), () => {
				if (frm.is_dirty()) {
					frappe.msgprint(__("Please save settings before testing."));
					return;
				}
				const dialog = new frappe.ui.Dialog({
					title: __("Send Contract Test Email"),
					fields: [{ fieldname: "employee", label: __("Employee"), fieldtype: "Link", options: "Employee", reqd: 1,
						get_query: () => ({ filters: { status: "Active", contract_end_date: [">=", frappe.datetime.get_today()] } }) }],
					primary_action_label: __("Preview Recipients"),
					primary_action({ employee }) {
						frappe.call({
							method: "custom_hr.contract_notifications.preview_test_email",
							args: { employee }, freeze: true,
							callback({ message }) {
								const eligible = message.reminders.filter((item) => !item.skip_reason);
								if (!eligible.length) {
									frappe.msgprint(__("No eligible recipients in the allowlist."));
									return;
								}
								const escape = frappe.utils.escape_html;
								const recipients = eligible.map((item) => escape(item.recipient)).join("<br>");
								const skipped = message.reminders.filter((item) => item.skip_reason)
									.map((item) => `${escape(item.recipient || "Employee")}: ${escape(item.skip_reason)}`).join("<br>");
								frappe.confirm(
									__("This sends real [TEST] emails even when Enabled is off or Dry Run is on.") +
									`<br><br>${recipients}` + (skipped ? `<br><br>${__("Skipped")}:<br>${skipped}` : ""),
									() => {
										dialog.hide();
										frappe.call({
											method: "custom_hr.contract_notifications.send_test_email",
											args: { employee }, type: "POST", freeze: true,
											callback({ message: result }) {
												frappe.msgprint({ title: __("Test Emails Queued"), message:
													__("Check Email Queue for delivery status.") + "<br><br>" +
													result.queued.map((item) => `${escape(item.recipient)}: ${escape(item.email_queue)}`).join("<br>") });
											},
										});
									}
								);
							},
						});
					},
				});
				dialog.show();
			});
		}
	},
});
