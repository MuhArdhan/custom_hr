(() => {
  // ../custom_hr/custom_hr/public/js/custom_hr.bundle.js
  for (const page of ["employee-attendance-gallery", "outlet-roster"]) {
    try {
      localStorage.removeItem(`_page:${page}`);
    } catch (e) {
    }
  }
  var FRAPPE_HR_WORKSPACES = /* @__PURE__ */ new Set([
    "Payroll",
    "Shift & Attendance",
    "Leaves",
    "Tenure",
    "HR Setup",
    "Recruitment",
    "Expenses",
    "Performance",
    "Tax & Benefits"
  ]);
  var contract_popup_in_flight = false;
  var contract_popup_open = false;
  function contract_popup_storage_key() {
    var _a;
    return `custom_hr:contract_popup_dismissed:${((_a = frappe.session) == null ? void 0 : _a.user) || "Guest"}`;
  }
  function contract_popup_dismissed_today() {
    try {
      return localStorage.getItem(contract_popup_storage_key()) === frappe.datetime.get_today();
    } catch (e) {
      return false;
    }
  }
  function dismiss_contract_popup_today() {
    try {
      localStorage.setItem(contract_popup_storage_key(), frappe.datetime.get_today());
    } catch (e) {
    }
  }
  function in_frappe_hr_workspace() {
    const route = frappe.get_route ? frappe.get_route() : [];
    if (route[0] !== "Workspaces")
      return false;
    const name = route[1] === "private" ? route[2] : route[1];
    return FRAPPE_HR_WORKSPACES.has(name);
  }
  function is_hr_popup_user() {
    var _a;
    return Boolean(
      ((_a = frappe.user) == null ? void 0 : _a.has_role) && (frappe.user.has_role("HR Manager") || frappe.user.has_role("HR User"))
    );
  }
  function show_contract_expiry_dialog(data) {
    const esc = frappe.utils.escape_html;
    const badge = (theme, text) => `<span class="es-badge" data-theme="${theme}">${esc(text)}</span>`;
    const status_badge = (row) => {
      if (row.days_left < 0)
        return badge("red", __("Lewat {0} hari", [Math.abs(row.days_left)]));
      if (row.days_left === 0)
        return badge("red", __("Hari ini"));
      return badge("orange", __("{0} hari lagi", [row.days_left]));
    };
    const summary_parts = [];
    if (data.overdue_count)
      summary_parts.push(badge("red", __("Lewat kontrak: {0}", [data.overdue_count])));
    if (data.expiring_count)
      summary_parts.push(badge("orange", __("Berakhir <= {0} hari: {1}", [data.max_days, data.expiring_count])));
    const body_rows = data.rows.map(
      (r) => `
			<tr>
				<td>
					<a href="/app/employee/${encodeURIComponent(r.employee)}" target="_blank">${esc(r.employee_name || r.employee)}</a>
					<span class="text-muted">(${esc(r.employee)})</span>
				</td>
				<td>${esc(r.company || "-")}</td>
				<td style="white-space:nowrap;">${esc(frappe.datetime.str_to_user(r.contract_end_date))}</td>
				<td style="white-space:nowrap;">${status_badge(r)}</td>
			</tr>`
    ).join("");
    contract_popup_open = true;
    const dialog = new frappe.ui.Dialog({
      title: __("Pengingat Kontrak Karyawan"),
      size: "large",
      fields: [
        {
          fieldname: "content",
          fieldtype: "HTML",
          options: `
					<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding-bottom:10px;margin-bottom:10px;border-bottom:1px solid var(--border-color);">
						${summary_parts.join("")}
						<span class="text-muted" style="font-size:12px;">${__("Klik nama karyawan untuk memperbarui kontrak atau status.")}</span>
					</div>
					<div style="max-height:55vh;overflow:auto;">
						<table class="table table-bordered table-condensed" style="margin:0;font-size:12.5px;">
							<thead>
								<tr style="background:var(--subtle-fg);">
									<th>${__("Karyawan")}</th>
									<th>${__("Company")}</th>
									<th>${__("Akhir Kontrak")}</th>
									<th>${__("Status")}</th>
								</tr>
							</thead>
							<tbody>${body_rows}</tbody>
						</table>
					</div>
				`
        }
      ],
      primary_action_label: __("Ingatkan Besok"),
      primary_action() {
        dismiss_contract_popup_today();
        dialog.hide();
      }
    });
    dialog.$wrapper.on("hidden.bs.modal", () => {
      dismiss_contract_popup_today();
      contract_popup_open = false;
    });
    dialog.show();
  }
  function maybe_show_contract_expiry_popup() {
    if (contract_popup_in_flight || contract_popup_open)
      return;
    if (!is_hr_popup_user() || !in_frappe_hr_workspace() || contract_popup_dismissed_today())
      return;
    contract_popup_in_flight = true;
    frappe.call({
      method: "custom_hr.contract_notifications.get_expiring_contracts_popup",
      type: "GET"
    }).then((r) => {
      var _a;
      const data = r == null ? void 0 : r.message;
      if (((_a = data == null ? void 0 : data.rows) == null ? void 0 : _a.length) && in_frappe_hr_workspace() && !contract_popup_dismissed_today()) {
        show_contract_expiry_dialog(data);
      }
    }).catch(() => {
    }).finally(() => {
      contract_popup_in_flight = false;
    });
  }
  $(document).on("page-change", () => {
    setTimeout(maybe_show_contract_expiry_popup, 250);
  });
  $(() => {
    setTimeout(maybe_show_contract_expiry_popup, 400);
  });
})();
//# sourceMappingURL=custom_hr.bundle.QLBEQ3SN.js.map
