"""Client des API 3CX V20 : API de configuration (XAPI, OData) et Call Control.

Les deux API partagent la même authentification OAuth2 « client_credentials » : un client créé
dans la console 3CX > Intégrations > API (licence Enterprise / 8SC+ requise).
"""

import datetime

import frappe
import requests

TOKEN_CACHE_KEY = "threecx:access_token"
TIMEOUT = 30
PAGE_SIZE = 500


class ThreeCXError(Exception):
	pass


def clear_token_cache():
	frappe.cache.delete_value(TOKEN_CACHE_KEY)


class ThreeCXClient:
	def __init__(self):
		settings = frappe.get_cached_doc("ThreeCX Settings")
		if not (
			settings.pbx_url
			and settings.client_id
			and settings.get_password("client_secret", raise_exception=False)
		):
			raise ThreeCXError("Renseignez l'URL du PBX, le Client ID et la clé API dans les paramètres 3CX.")
		self.base_url = settings.pbx_url
		self.client_id = settings.client_id
		self.client_secret = settings.get_password("client_secret")

	# --- Authentification -----------------------------------------------------

	def _token(self, force: bool = False) -> str:
		if not force and (token := frappe.cache.get_value(TOKEN_CACHE_KEY)):
			return token

		response = self._send(
			"POST",
			"/connect/token",
			data={
				"grant_type": "client_credentials",
				"client_id": self.client_id,
				"client_secret": self.client_secret,
			},
		)
		if response.status_code != 200:
			raise ThreeCXError(
				f"Authentification 3CX refusée ({response.status_code}) : {response.text[:300]}"
			)

		payload = response.json()
		token = payload["access_token"]
		# Le jeton dure 1 h (sans refresh token) : on le garde une minute de moins.
		frappe.cache.set_value(
			TOKEN_CACHE_KEY, token, expires_in_sec=max(int(payload.get("expires_in", 3600)) - 60, 60)
		)
		return token

	def request(self, method: str, path: str, **kwargs) -> requests.Response:
		extra_headers = kwargs.pop("headers", {})
		# Un 401 peut venir d'un jeton révoqué côté 3CX : on en redemande un, une seule fois.
		for attempt in range(2):
			headers = {**extra_headers, "Authorization": f"Bearer {self._token(force=attempt > 0)}"}
			response = self._send(method, path, headers=headers, **kwargs)
			if response.status_code != 401:
				break
		if response.status_code >= 400:
			raise ThreeCXError(f"3CX {method} {path} : HTTP {response.status_code} {response.text[:300]}")
		return response

	def _send(self, method: str, path: str, **kwargs) -> requests.Response:
		kwargs.setdefault("timeout", TIMEOUT)
		try:
			return requests.request(method, f"{self.base_url}{path}", **kwargs)
		except requests.RequestException as e:
			raise ThreeCXError(f"PBX 3CX injoignable ({self.base_url}) : {e}") from e

	def get_json(self, path: str, params: dict | None = None):
		return self.request("GET", path, params=params).json()

	# --- API de configuration (XAPI) -------------------------------------------

	def system_status(self) -> dict:
		return self.get_json("/xapi/v1/SystemStatus")

	def call_log(self, period_from: datetime.datetime, period_to: datetime.datetime) -> list[dict]:
		"""Journal d'appels (rapport « Call Log » de la console) sur une période, bornes en UTC.

		Les paramètres de la fonction OData font partie du chemin et sont tous obligatoires.
		"""
		params = ",".join(
			[
				f"periodFrom={_odata_datetime(period_from)}",
				f"periodTo={_odata_datetime(period_to)}",
				"sourceType=0",
				"sourceFilter=''",
				"destinationType=0",
				"destinationFilter=''",
				"callsType=0",
				"callTimeFilterType=0",
				# Des bornes horaires vides renvoient zéro ligne.
				"callTimeFilterFrom='00:00:00'",
				"callTimeFilterTo='23:59:59'",
				"hidePcalls=false",
			]
		)
		path = f"/xapi/v1/ReportCallLogData/Pbx.GetCallLogData({params})"

		rows, skip = [], 0
		while True:
			page = self.get_json(path, {"$top": PAGE_SIZE, "$skip": skip}).get("value", [])
			rows += page
			if len(page) < PAGE_SIZE:
				return rows
			skip += PAGE_SIZE

	def recording(self, recording_id: int) -> dict:
		values = self.get_json("/xapi/v1/Recordings", {"$filter": f"Id eq {int(recording_id)}", "$top": 1})
		return (values.get("value") or [{}])[0]

	def download_recording(self, recording_id: int) -> requests.Response:
		return self.request(
			"GET", f"/xapi/v1/Recordings/Pbx.DownloadRecording(recId={int(recording_id)})", stream=True
		)

	def transcribe_recordings(self, recording_ids: list[int]):
		self.request("POST", "/xapi/v1/Recordings/Pbx.TranscribeRecordings", json={"ids": recording_ids})

	# --- Call Control -----------------------------------------------------------

	def make_call(self, extension: str, destination: str, timeout: int = 30) -> dict:
		"""Fait sonner le poste `extension` puis compose `destination`."""
		return self.request(
			"POST",
			f"/callcontrol/{extension}/makecall",
			json={"destination": destination, "timeout": timeout},
		).json()


def _odata_datetime(value: datetime.datetime) -> str:
	if value.tzinfo:
		value = value.astimezone(datetime.timezone.utc)
	return value.strftime("%Y-%m-%dT%H:%M:%SZ")
