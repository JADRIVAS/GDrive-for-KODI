"""
	gdrive (Google Drive ) for KODI / XBMC Plugin
	Copyright (C) 2013-2016 ddurdle

	This program is free software: you can redistribute it and/or modify
	it under the terms of the GNU General Public License as published by
	the Free Software Foundation, either version 3 of the License, or
	(at your option) any later version.

	This program is distributed in the hope that it will be useful,
	but WITHOUT ANY WARRANTY; without even the implied warranty of
	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
	GNU General Public License for more details.

	You should have received a copy of the GNU General Public License
	along with this program.  If not, see <http://www.gnu.org/licenses/>.


"""

import os
import re
import sys
import socket
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar
import xbmc
import xbmcgui
from resources.lib import authorization

SERVICE_NAME = "dmdgdrive"

#
# Google Drive API 2 implementation of Google Drive
#
class GDrive:
	API_VERSION = "3.0"
	PROTOCOL = "https://"
	API_URL = PROTOCOL + "www.googleapis.com/drive/v2/"

	##
	# initialize (save addon, instance name, user agent)
	##
	def __init__(self, PLUGIN_HANDLE, PLUGIN_URL, settings, instanceName, userAgent, authenticate=True):
		self.PLUGIN_HANDLE = PLUGIN_HANDLE
		self.PLUGIN_URL = PLUGIN_URL
		self.settings = settings
		self.instanceName = instanceName
		self.cookiejar = http.cookiejar.CookieJar()
		self.userAgent = userAgent
		self.failed = False

		try:
			username = self.getInstanceSetting("username")
			# username = self.getInstanceSetting(str(instanceName) + "_username")
		except:
			username = ""

		self.authorization = authorization.Authorization(username)

		# load the OAUTH2 tokens or force fetch if not set
		if authenticate == True and (
			not self.authorization.loadToken(self.instanceName, self.settings, "auth_access_token")
			or not self.authorization.loadToken(self.instanceName, self.settings, "auth_refresh_token")
		):

			if self.getInstanceSetting("code"):
				self.getToken(self.getInstanceSetting("code"))
			else:
				# xbmcgui.Dialog().ok(self.settings.getLocalizedString(30003), self.settings.getLocalizedString(30005))
				self.failed = True
				return

	##
	# get OAUTH2 access and refresh token for provided code
	#	parameters: OAUTH2 code
	#	returns: none
	##
	def getToken(self, code):
		url = "https://accounts.google.com/o/oauth2/token"
		clientID = self.getInstanceSetting("client_id")
		clientSecret = self.getInstanceSetting("client_secret")
		header = {"User-Agent": self.userAgent, "Content-Type": "application/x-www-form-urlencoded"}
		data = "code={}&client_id={}&client_secret={}&redirect_uri=urn:ietf:wg:oauth:2.0:oob&grant_type=authorization_code".format(
			code, clientID, clientSecret
		)
		data = data.encode("utf-8")
		req = urllib.request.Request(url, data, header)

		# try login
		try:
			response = urllib.request.urlopen(req)
		except urllib.error.URLError as e:
			# xbmcgui.Dialog().ok(self.settings.getLocalizedString(30000), self.settings.getLocalizedString(30017))
			xbmc.log(str(e))
			return

		responseData = response.read().decode("utf-8")
		response.close()

		# retrieve authorization token
		for r in re.finditer('\"access_token\"\s?\:\s?\"([^\"]+)\".+?' + '\"refresh_token\"\s?\:\s?\"([^\"]+)\".+?', responseData, re.DOTALL):
			accessToken, refreshToken = r.groups()
			self.authorization.setToken("auth_access_token", accessToken)
			self.authorization.setToken("auth_refresh_token", refreshToken)
			self.updateAuthorization()
			# xbmcgui.Dialog().ok(self.settings.getLocalizedString(30000), self.settings.getLocalizedString(30142))

		for r in re.finditer('\"error_description\"\s?\:\s?\"([^\"]+)\"', responseData, re.DOTALL):
			errorMessage = r.group(1)
			# xbmcgui.Dialog().ok(self.settings.getLocalizedString(30000), self.settings.getLocalizedString(30119) + errorMessage)
			xbmc.log(errorMessage)

		return

	##
	# refresh OAUTH2 access given refresh token
	#	parameters: none
	#	returns: none
	##
	def refreshToken(self):
		url = "https://accounts.google.com/o/oauth2/token"
		clientID = self.getInstanceSetting("client_id")
		clientSecret = self.getInstanceSetting("client_secret")
		header = {"User-Agent": self.userAgent, "Content-Type": "application/x-www-form-urlencoded"}
		data = "client_id={}&client_secret={}&refresh_token={}&grant_type=refresh_token".format(
			clientID, clientSecret, self.authorization.getToken("auth_refresh_token")
		)
		data = data.encode("utf-8")
		req = urllib.request.Request(url, data, header)

		# try login
		try:
			response = urllib.request.urlopen(req)
		except urllib.error.URLError as e:
			# xbmcgui.Dialog().ok(self.settings.getLocalizedString(30000), self.settings.getLocalizedString(30017))
			self.failed = True
			xbmc.log(str(e))
			return

		responseData = response.read().decode("utf-8")
		response.close()

		# retrieve authorization token
		for r in re.finditer('\"access_token\"\s?\:\s?\"([^\"]+)\".+?', responseData, re.DOTALL):
			accessToken = r.group(1)
			self.authorization.setToken("auth_access_token", accessToken)
			self.updateAuthorization()

		for r in re.finditer('\"error_description\"\s?\:\s?\"([^\"]+)\"', responseData, re.DOTALL):
			errorMessage = r.group(1)
			# xbmcgui.Dialog().ok(self.settings.getLocalizedString(30000), self.settings.getLocalizedString(30119) + errorMessage)
			xbmc.log(errorMessage)

		return

	##
	# return the appropriate "headers" for Google Drive requests that include 1) user agent, 2) authorization token
	#	returns: list containing the header
	##
	def getHeadersList(self, isPOST=False, additionalHeader=None, additionalValue=None, isJSON=False):

		if self.authorization.isToken(self.instanceName, self.settings, "auth_access_token") and not isPOST:
			# return {"User-Agent": self.userAgent, "Authorization": "Bearer " + self.authorization.getToken("auth_access_token")}
			if additionalHeader is not None:
				return {
					"Cookie": "DRIVE_STREAM=" + self.authorization.getToken("DRIVE_STREAM"),
					"Authorization": "Bearer " + self.authorization.getToken("auth_access_token"),
					additionalHeader: additionalValue,
				}
			else:
				return {
					"Cookie": "DRIVE_STREAM=" + self.authorization.getToken("DRIVE_STREAM"),
					"Authorization": "Bearer " + self.authorization.getToken("auth_access_token"),
				}

		elif isJSON and self.authorization.isToken(self.instanceName, self.settings, "auth_access_token"):
			# return {"User-Agent": self.userAgent, "Authorization": "Bearer " + self.authorization.getToken("auth_access_token")}
			return {
				"Content-Type": "application/json",
				"Cookie": "DRIVE_STREAM=" + self.authorization.getToken("DRIVE_STREAM"),
				"Authorization": "Bearer " + self.authorization.getToken("auth_access_token"),
			}

		elif self.authorization.isToken(self.instanceName, self.settings, "auth_access_token"):
			# return {"User-Agent": self.userAgent, "Authorization": "Bearer " + self.authorization.getToken("auth_access_token")}
			return {
				"If-Match": "*",
				"Content-Type": "application/atom+xml",
				"Cookie": "DRIVE_STREAM=" + self.authorization.getToken("DRIVE_STREAM"),
				"Authorization": "Bearer " + self.authorization.getToken("auth_access_token"),
			}
			# return {"Content-Type": "application/atom+xml", "Authorization": "Bearer " + self.authorization.getToken("auth_access_token")}

		elif self.authorization.isToken(self.instanceName, self.settings, "DRIVE_STREAM") and not isPOST:

			if additionalHeader is not None:
				return {"Cookie": "DRIVE_STREAM=" + self.authorization.getToken("DRIVE_STREAM"), additionalHeader: additionalValue}
			else:
				return {"Cookie": "DRIVE_STREAM=" + self.authorization.getToken("DRIVE_STREAM")}

		else:
			return {"User-Agent": self.userAgent}

	##
	# return the appropriate "headers" for Google Drive requests that include 1) user agent, 2) authorization token, 3) api version
	#	returns: URL-encoded header string
	##
	def getHeadersEncoded(self):
		return urllib.parse.urlencode(self.getHeadersList())

	def getInstanceSetting(self, setting, default=None):

		try:
			return self.settings.getSetting(self.instanceName + "_" + setting)
		except:
			return default

	##
	# perform login
	##
	def login(self):
		pass

	##
	# if we don't have an authorization token set for the plugin, set it with the recent login.
	#	auth_token will permit "quicker" login in future executions by reusing the existing login session (less HTTPS calls = quicker video transitions between clips)
	##
	def updateAuthorization(self):

		if self.authorization.isUpdated: # and settings.getSetting(self.instanceName + "_save_auth_token") == "true":
			self.authorization.saveTokens(self.instanceName, self.settings)
