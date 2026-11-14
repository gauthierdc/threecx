frappe.ui.form.on("Call Log", {
	refresh(frm) {
		if (!frm.doc.threecx_recording_id) return;

		const group = __("3CX");
		frm.add_custom_button(
			__("Écouter l'enregistrement"),
			() => {
				const dialog = new frappe.ui.Dialog({
					title: __("Enregistrement de l'appel"),
					fields: [{ fieldtype: "HTML", fieldname: "player" }],
				});
				dialog.fields_dict.player.$wrapper.html(
					`<audio controls autoplay style="width: 100%" src="${frm.doc.recording_url}"></audio>`
				);
				dialog.onhide = () => dialog.fields_dict.player.$wrapper.empty();
				dialog.show();
			},
			group
		);

		frm.add_custom_button(
			__("Récupérer la transcription"),
			() =>
				frm
					.call({ method: "threecx.api.desk.refresh_transcription", args: { call_log: frm.doc.name } })
					.then(({ message }) => {
						if (message.transcribed) return frm.reload_doc();
						if (!message.can_be_transcribed) {
							return frappe.msgprint(__("3CX ne peut pas transcrire cet enregistrement."));
						}
						frappe.confirm(
							__("Cet enregistrement n'est pas encore transcrit. Demander la transcription à 3CX ?"),
							() =>
								frm
									.call({
										method: "threecx.api.desk.request_transcription",
										args: { call_log: frm.doc.name },
									})
									.then(() =>
										frappe.show_alert({
											message: __("Transcription demandée, réessayez dans quelques minutes."),
											indicator: "blue",
										})
									)
						);
					}),
			group
		);
	},
});
