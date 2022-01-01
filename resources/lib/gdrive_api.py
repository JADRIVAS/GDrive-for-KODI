import re
import json
import urllib.error
import urllib.parse
import urllib.request

import xbmc

from . import encryption

API_VERSION = "3"
GOOGLE_AUTH_URL = "https://oauth2.googleapis.com/token"
SCOPE_URL = "https://www.googleapis.com/auth/drive.readonly"
GDRIVE_URL = "https://www.googleapis.com/drive/v3/files/"
GDRIVE_PARAMS = "?supportsAllDrives=true&alt=media"
USER_AGENT = "Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US) AppleWebKit/532.0 (KHTML, like Gecko) Chrome/3.0.195.38 Safari/532.0"


class GoogleDrive:

	def setAccount(self, account):
		self.account = account

	@staticmethod
	def constructDriveURL(fileID):
		return GDRIVE_URL + fileID + GDRIVE_PARAMS

	@staticmethod
	def sendPayload(url, data=None, headers={}, cookie=None):

		if data:
			data = data.encode("utf8")

		req = urllib.request.Request(url, data, headers)

		try:
			response = urllib.request.urlopen(req)
		except urllib.error.URLError as e:
			xbmc.log("gdrive error: " + str(e))
			return "failed", str(e)

		responseData = response.read().decode("utf-8")
		if cookie: cookie = response.headers['set-cookie']
		response.close()

		try:
			responseData = json.loads(responseData)

			if responseData.get("error_description"):
				error = responseData["error_description"]
				xbmc.log("gdrive error: " + error)
				return "failed", error
		except:
			pass

		if not cookie:
			return responseData
		else:
			return responseData, cookie

	def getToken(self, code, clientID, clientSecret):
		data = "code={}&client_id={}&client_secret={}&redirect_uri=urn:ietf:wg:oauth:2.0:oob&grant_type=authorization_code".format(
			code, clientID, clientSecret
		)
		headers = {"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"}
		response = self.sendPayload(GOOGLE_AUTH_URL, data, headers)

		if "failed" in response:
			return response

		return response["refresh_token"]

	def refreshToken(self):
		key = self.account.get("key")

		if key:
			jwt = encryption.JasonWebToken(self.account["email"], key, SCOPE_URL, GOOGLE_AUTH_URL).create()
			data = "grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion=" + jwt
		else:
			data = "client_id={}&client_secret={}&refresh_token={}&grant_type=refresh_token".format(
				self.account["client_id"], self.account["client_secret"], self.account["refresh_token"]
			)

		headers = {"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"}
		response = self.sendPayload(GOOGLE_AUTH_URL, data, headers)

		if "failed" in response:
			return "failed"

		self.account["access_token"] = response["access_token"].rstrip(".")
		self.account["expiry"] = response["expires_in"]

	def getHeaders(self, accessToken=None, additionalHeader=None, additionalValue=None):
		cookie = self.account.get("drive_stream")
		accessToken = self.account.get("access_token")
		if not accessToken: accessToken = ""
		if not cookie: cookie = ""

		if additionalHeader:
			return {"Cookie": "DRIVE_STREAM=" + cookie, "Authorization": "Bearer " + accessToken, additionalHeader: additionalValue}
		else:
			return {"Cookie": "DRIVE_STREAM=" + cookie, "Authorization": "Bearer " + accessToken}

	def getHeadersEncoded(self):
		return urllib.parse.urlencode(self.getHeaders())

	def getStreams(self, fileID, resolutionPriority=None):
		url = "https://drive.google.com/get_video_info?docid=" + fileID
		self.account["drive_stream"] = ""
		responseData, cookie = self.sendPayload(url, headers=self.getHeaders(), cookie=True)
		self.account["drive_stream"] = re.findall("DRIVE_STREAM=(.*?);", cookie)[0]

		for _ in range(5):
			responseData = urllib.parse.unquote(responseData)

		# urls = re.sub("\\\\u003d", "=", urls)
		# urls = re.sub("\\\\u0026", "&", urls)
		urls = re.sub("\&url\=https://", "\@", responseData)
		streams = {}
		resolutions = {}

		for r in re.finditer("([\d]+)/[\d]+x([\d]+)", urls, re.DOTALL):
			itag, resolution = r.groups()
			resolution = resolution + "P"
			resolutions[resolution] = itag
			streams[itag] = {"resolution": resolution}

		for r in re.finditer("\@([^\@]+)", urls):
			videoURL = r.group(1)
			itag = re.findall("itag=([\d]+)", videoURL)[0]
			streams[itag]["url"] = "https://" + videoURL + "|" + self.getHeadersEncoded()

		if streams and resolutionPriority:

			for resolution in resolutionPriority:

				if resolution == "Original":
					return
				elif resolution in resolutions:
					return resolution, streams[resolutions[resolution]]["url"]

		elif streams:
			return sorted([(v["resolution"], v["url"]) for k, v in streams.items()], key=lambda x: int(x[0][:-1]), reverse=True)
