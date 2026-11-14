app_name = "threecx"
app_title = "3CX"
app_publisher = "Verre & Transparence"
app_description = "Intégration de la téléphonie 3CX : identification de l'appelant, journal d'appels, transcriptions, click-to-call"
app_email = "gauthier@de-chezelles.com"
app_license = "mit"

# Le journal d'appels s'appuie sur le doctype "Call Log" d'ERPNext (module Telephony),
# déjà affiché dans la timeline des Contact / Lead / Customer.
required_apps = ["erpnext"]

# Includes in <head>
# ------------------

# Noms de bundles nus : résolus via assets.json (nom haché à chaque build).
app_include_js = ["threecx.bundle.js"]

doctype_js = {"Call Log": "public/js/call_log.js"}

# Installation
# ------------

after_install = "threecx.install.after_install"
# Rejoue la création des champs personnalisés à chaque migrate (idempotent) :
# les champs 3CX sont versionnés ici, pas dans la base.
after_migrate = "threecx.install.after_migrate"

boot_session = "threecx.boot.boot_session"

# Scheduled Tasks
# ---------------

scheduler_events = {
	"cron": {
		# La tâche ne fait rien tant que la synchro XAPI n'est pas activée dans les paramètres.
		"*/15 * * * *": ["threecx.tasks.sync_call_history"],
	},
}
