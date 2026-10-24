// Face attendance actions on the Employee form (HR back office).
// Registered as an additional Employee script via custom_hr doctype_js, so the
// hrms app itself stays untouched.

const FACE_MODELS_URL = "/assets/custom_hr/face/models";
const HR_FACE_ROLES = ["HR Manager", "HR User", "System Manager"];

function add_face_attendance_buttons(frm) {
	const is_hr_user = HR_FACE_ROLES.some((role) => frappe.user.has_role(role));
	if (frm.is_new() || !is_hr_user) return;

	frappe.db.get_single_value("HR Settings", "enable_face_checkin").then((enabled) => {
		if (!enabled) return;

		frappe
			.call({
				method: "custom_hr.api.face.get_face_status",
				args: { employee: frm.doc.name },
			})
			.then((r) => {
				const enrolled = r.message && r.message.enrolled;

				frm.add_custom_button(
					__("Enroll Face"),
					() => open_face_enrollment_dialog(frm),
					__("Face Attendance")
				);

				if (enrolled) {
					frm.add_custom_button(
						__("Reset Face"),
						() => {
							frappe.confirm(
								__("Delete face data for {0}? The employee must enroll again.", [
									frm.doc.employee_name || frm.doc.name,
								]),
								() => {
									frappe.call({
										method: "custom_hr.api.face.reset_face",
										type: "POST",
										args: { employee: frm.doc.name },
										freeze: true,
										callback: () => {
											frappe.show_alert({
												message: __("Face data deleted"),
												indicator: "green",
											});
											frm.reload_doc();
										},
									});
								}
							);
						},
						__("Face Attendance")
					);
				}
			});
	});
}

function load_face_api() {
	if (window.faceapi) return Promise.resolve(window.faceapi);
	if (!window.__face_api_loading) {
		window.__face_api_loading = new Promise((resolve, reject) => {
			const script = document.createElement("script");
			script.src = "/assets/custom_hr/face/face-api.min.js";
			script.onload = () => resolve(window.faceapi);
			script.onerror = () => reject(new Error("Gagal memuat face-api"));
			document.head.appendChild(script);
		});
	}
	return window.__face_api_loading;
}

async function setup_face_models(faceapi) {
	await Promise.all([
		faceapi.nets.tinyFaceDetector.loadFromUri(FACE_MODELS_URL),
		faceapi.nets.faceLandmark68Net.loadFromUri(FACE_MODELS_URL),
		faceapi.nets.faceRecognitionNet.loadFromUri(FACE_MODELS_URL),
	]);
}

function open_face_enrollment_dialog(frm) {
	frappe.db.get_single_value("HR Settings", "face_enroll_samples").then((samples) => {
		const required_samples = samples || 3;
		const captured_samples = [];
		let captured_photo = null;
		const dialog = new frappe.ui.Dialog({
			title: __("Enroll Face: {0}", [frm.doc.employee_name || frm.doc.name]),
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "camera_area",
					options: `
						<div style="text-align:center">
							<video autoplay muted playsinline
								style="width:100%;max-width:480px;border-radius:8px;background:#000"></video>
							<p class="text-muted face-status" style="margin-top:8px">
								${__("Starting camera...")}
							</p>
							<canvas class="face-canvas" style="display:none"></canvas>
						</div>
					`,
				},
			],
			primary_action_label: __("Save ({0} samples)", [required_samples]),
			primary_action: async () => {
				if (captured_samples.length < required_samples) {
					frappe.show_alert({ message: __("Face samples are incomplete"), indicator: "red" });
					return;
				}
				dialog.get_primary_btn().prop("disabled", true);
				try {
					await frappe.call({
						method: "custom_hr.api.face.enroll_face",
						type: "POST",
						args: {
							employee: frm.doc.name,
							descriptors: JSON.stringify(captured_samples),
							photo: captured_photo,
						},
					});
					stopCamera();
					dialog.hide();
					frappe.show_alert({ message: __("Face enrolled successfully"), indicator: "green" });
					frm.reload_doc();
				} catch (error) {
					dialog.get_primary_btn().prop("disabled", false);
				}
			},
		});

		let camera_stream = null;

		const video = dialog.get_field("camera_area").$wrapper.find("video")[0];
		const canvas = dialog.get_field("camera_area").$wrapper.find("canvas")[0];
		const status = dialog.get_field("camera_area").$wrapper.find(".face-status");

		function stopCamera() {
			if (camera_stream) {
				camera_stream.getTracks().forEach((track) => track.stop());
				camera_stream = null;
			}
		}

		function setStatus(text, color) {
			status.text(text).css("color", color || "");
		}

		dialog.show();
		dialog.get_primary_btn().prop("disabled", true);

		load_face_api()
			.then(async (faceapi) => {
				await setup_face_models(faceapi);
				camera_stream = await navigator.mediaDevices.getUserMedia({
					video: { facingMode: "user", width: 480 },
					audio: false,
				});
				video.srcObject = camera_stream;
				setStatus(__("Position your face in front of the camera"), "green");
			})
			.catch((error) => {
				setStatus(error.message || __("Unable to access the camera"), "red");
			});

		dialog.$wrapper.on("click", "video", async () => {
			if (!window.faceapi || !camera_stream) return;
			if (captured_samples.length >= required_samples) return;

			const faceapi = window.faceapi;
			const detection = await faceapi
				.detectSingleFace(video, new faceapi.TinyFaceDetectorOptions())
				.withFaceLandmarks()
				.withFaceDescriptor();

			if (!detection) {
				setStatus(__("Face not detected, try again"), "orange");
				return;
			}

			captured_samples.push(Array.from(detection.descriptor));
			canvas.width = 480;
			canvas.height = (video.videoHeight / video.videoWidth) * 480;
			canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
			captured_photo = canvas.toDataURL("image/jpeg", 0.8);

			const remaining = required_samples - captured_samples.length;
			setStatus(
				remaining
					? __("Sample {0}/{1} saved. Move your head slightly and click the video again.", [
							captured_samples.length,
							required_samples,
						])
					: __("All samples saved. Click Save."),
				remaining ? "green" : "blue"
			);
			dialog.get_primary_btn().prop("disabled", remaining > 0);
		});

		dialog.onhide = () => stopCamera();
	});
}

frappe.ui.form.on("Employee", {
	refresh(frm) {
		add_face_attendance_buttons(frm);
	},
	async company(frm) {
		// Outlets are named after their Company; the server fills it too on save
		if (!frm.doc.company || frm.doc.outlet) return;
		const exists = await frappe.db.exists("Outlet", frm.doc.company);
		if (exists && !frm.doc.outlet) frm.set_value("outlet", frm.doc.company);
	},
});
