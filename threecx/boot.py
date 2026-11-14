import frappe


def boot_session(bootinfo):
	if frappe.session.user == "Guest" or not frappe.db.get_single_value("ThreeCX Settings", "enabled"):
		return

	settings = frappe.get_cached_doc("ThreeCX Settings")
	bootinfo.threecx = {
		"click_to_call": settings.click_to_call_mode,
		"extension": frappe.db.get_value("User", frappe.session.user, "threecx_extension"),
	}
