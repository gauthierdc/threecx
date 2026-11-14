// Intégration 3CX côté Desk : click-to-call et notification d'appel entrant.
frappe.provide("threecx");

threecx.normalize_number = (number) => (number || "").replace(/[^\d+]/g, "");

threecx.dial = (number) => {
	const destination = threecx.normalize_number(number);
	if (!destination) return;

	if (frappe.boot.threecx.click_to_call !== "API Call Control") {
		// L'application 3CX (ou l'extension navigateur 3CX) est le gestionnaire des liens tel:.
		window.location.href = `tel:${destination}`;
		return;
	}

	if (!frappe.boot.threecx.extension) {
		frappe.msgprint(__("Renseignez votre poste 3CX dans votre fiche Utilisateur pour passer des appels."));
		return;
	}
	frappe.show_alert({ message: __("Appel de {0} en cours…", [destination]), indicator: "blue" });
	frappe.call({
		method: "threecx.api.desk.make_call",
		args: { number: destination },
		error_msg: __("3CX n'a pas pu lancer l'appel"),
	});
};

// Frappe affiche une icône d'appel sur tous les champs « Phone » dès qu'un handler existe.
if (frappe.boot.threecx && frappe.boot.threecx.click_to_call !== "Désactivé") {
	frappe.phone_call.handler = (number) => threecx.dial(number);
}

threecx.show_incoming_call = ({ number, matches }) => {
	const caller = matches.length
		? matches
				.map((m) => {
					const label = frappe.utils.escape_html(
						[m.display_name, m.company].filter(Boolean).join(" – ")
					);
					return `<a href="/app/${frappe.router.slug(m.type)}/${encodeURIComponent(m.id)}">${label}</a>`;
				})
				.join("<br>")
		: __("Numéro inconnu");

	frappe.utils.play_sound("incoming-call");
	frappe.show_alert(
		{
			message: `<b>${__("Appel entrant")} ${frappe.utils.escape_html(number)}</b><br>${caller}`,
			indicator: matches.length ? "green" : "orange",
		},
		20
	);
};

$(document).on("app_ready", () => {
	if (!frappe.boot.threecx) return;
	frappe.realtime.on("threecx_incoming_call", threecx.show_incoming_call);
});
