// Copyright (c) 2026, Verre & Transparence and contributors
// For license information, please see license.txt

frappe.ui.form.on("ThreeCX Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Télécharger le template 3CX"), () => {
			if (frm.is_dirty()) {
				return frappe.msgprint(__("Enregistrez les paramètres avant de générer le template."));
			}
			window.open("/api/method/threecx.api.desk.download_template");
		});

		frm.add_custom_button(
			__("Tester la connexion API"),
			() =>
				frm.call({ method: "threecx.api.desk.test_connection", freeze: true }).then(({ message }) => {
					const rows = Object.entries(message)
						.map(
							([key, value]) =>
								`<tr><td>${key}</td><td>${frappe.utils.escape_html(String(value ?? ""))}</td></tr>`
						)
						.join("");
					frappe.msgprint({
						title: __("Connexion à 3CX réussie"),
						indicator: "green",
						message: `<table class="table table-bordered">${rows}</table>`,
					});
				}),
			__("API 3CX")
		);

		frm.add_custom_button(
			__("Synchroniser l'historique maintenant"),
			() =>
				frm
					.call({
						method: "threecx.api.desk.sync_now",
						freeze: true,
						freeze_message: __("Synchronisation avec 3CX…"),
					})
					.then(({ message }) => {
						frappe.msgprint(
							__(
								"{0} lignes lues dans 3CX : {1} appels synchronisés, {2} ignorés (internes ou sous-segments), {3} erreurs.",
								[message.rows, message.synced, message.skipped, message.errors]
							)
						);
						frm.reload_doc();
					}),
			__("API 3CX")
		);
	},
});
