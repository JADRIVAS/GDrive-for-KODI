"""
	Copyright (C) 2014-2016 ddurdle

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

import re
import time
import urllib
import xbmc
import xbmcgui
import constants
from threading import Thread
from socketserver import ThreadingMixIn
from http.server import BaseHTTPRequestHandler, HTTPServer
from resources.lib import account_manager, encryption, enrolment, gplayer


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
	"""Handle requests in a separate thread."""


class MyHTTPServer(ThreadingMixIn, HTTPServer):

	def __init__(self, *args, **kwargs):
		HTTPServer.__init__(self, *args, **kwargs)

	def setDetails(self, pluginName, settings):
		self.pluginName = pluginName
		self.settings = settings
		self.userAgent = self.settings.getSetting("user_agent")

		self.accountManager = account_manager.AccountManager(self.settings)
		self.service = constants.cloudservice2(self.settings, self.accountManager, self.userAgent)
		self.close = False

	def run(self):

		try:
			self.serve_forever()
		except:
			self.close = True
			# Clean-up server (close socket, etc.)
			self.server_close()

	def startGPlayer(self, dbID, dbType, widget, trackProgress):
		lastUpdate = time.time()
		player = gplayer.GPlayer(dbID, dbType, int(widget), int(trackProgress), self.settings)

		while not player.close and not self.close:

			if time.time() - lastUpdate >= 1740:
				lastUpdate = time.time()
				self.service.refreshToken()

			xbmc.sleep(1000)


class MyStreamer(BaseHTTPRequestHandler):

	def do_POST(self):

		if self.path == "/crypto_playurl":
			contentLength = int(self.headers["Content-Length"]) # <--- Gets the size of data
			postData = self.rfile.read(contentLength).decode("utf-8") # <--- Gets the data itself
			accountNumber, url = re.findall("account=(.*)&url=(.*)", postData)[0]
			self.server.accountManager.loadAccounts()
			self.server.service.setAccount(self.server.accountManager.accounts[accountNumber])

			self.server.service.refreshToken()
			self.server.playbackURL = url
			self.send_response(200)
			self.end_headers()

		elif self.path == "/start_gplayer":
			contentLength = int(self.headers["Content-Length"])
			postData = self.rfile.read(contentLength).decode("utf-8")
			self.send_response(200)

			self.end_headers()
			dbID, dbType, widget, trackProgress = re.findall("dbid=([\d]+)&dbtype=(.*)&widget=(\d)&track=(\d)", postData)[0]
			Thread(target=self.server.startGPlayer, args=(dbID, dbType, widget, trackProgress)).start()

		elif self.path == "/enroll?default=false":
			contentLength = int(self.headers["Content-Length"])  # <--- Gets the size of data
			postData = self.rfile.read(contentLength).decode("utf-8")  # <--- Gets the data itself
			self.send_response(200)
			self.end_headers()

			clientID, clientSecret = re.findall("client_id=(.*)&client_secret=(.*)", postData)[0]
			data = enrolment.form2(clientID, clientSecret)
			self.wfile.write(data.encode("utf-8"))

		elif self.path == "/enroll":
			contentLength = int(self.headers["Content-Length"])  # <--- Gets the size of data
			postData = self.rfile.read(contentLength).decode("utf-8")  # <--- Gets the data itself
			postData = urllib.parse.unquote_plus(postData)
			self.send_response(200)

			self.end_headers()
			accountName, code, clientID, clientSecret = re.findall("account=(.*)&code=(.*)&client_id=(.*)&client_secret=(.*)", postData)[0]
			refreshToken = self.server.service.getToken(code, clientID, clientSecret)

			if "failed" in refreshToken:
				data = enrolment.status(refreshToken[1])
				self.wfile.write(data.encode("utf-8"))
				return

			self.server.accountManager.loadAccounts()
			accountNumber = self.server.accountManager.addAccount(
				{
					"username": accountName,
					"code": code,
					"client_id": clientID,
					"client_secret": clientSecret,
					"refresh_token": refreshToken,
				}
			)

			defaultAccountName, defaultAccountNumber = self.server.accountManager.getDefaultAccount()

			if not defaultAccountName:
				self.server.accountManager.setDefaultAccount(accountName, accountNumber)

			data = enrolment.status("Successfully enrolled account")
			self.wfile.write(data.encode("utf-8"))

	def do_HEAD(self):

		if self.path == "/play":
			url = self.server.playbackURL
			req = urllib.request.Request(url, None, self.server.service.getHeaders())
			req.get_method = lambda: "HEAD"

			try:
				response = urllib.request.urlopen(req)
			except urllib.error.URLError as e:
				self.server.failed = True

				if e.code == 404:
					xbmcgui.Dialog().ok(self.server.settings.getLocalizedString(30003), self.server.settings.getLocalizedString(30209))
					return

				elif e.code == 401:
					xbmcgui.Dialog().ok(self.server.settings.getLocalizedString(30003), self.server.settings.getLocalizedString(30018))
					return

				elif e.code == 403 or e.code == 429:

					if not self.server.settings.getSetting("fallback"):
						xbmcgui.Dialog().ok(
							self.server.settings.getLocalizedString(30003) + ": " + self.server.settings.getLocalizedString(30006),
							self.server.settings.getLocalizedString(30009),
						)
						return

					fallbackAccountNames, fallbackAccountNumbers = self.server.accountManager.getFallbackAccounts()
					defaultAccountName, defaultAccountNumber = self.server.accountManager.getDefaultAccount()
					accounts = self.server.accountManager.accounts
					accountChange = False

					for fallbackAccountNumber in fallbackAccountNumbers:
						account = accounts[fallbackAccountNumber]
						accountName = account["username"]
						self.server.service.setAccount(account)
						refreshToken = self.server.service.refreshToken()

						if refreshToken == "failed":
							continue

						req = urllib.request.Request(url, None, self.server.service.getHeaders())
						req.get_method = lambda: "HEAD"

						try:
							response = urllib.request.urlopen(req)
						except urllib.error.URLError as e:
							continue

						if not defaultAccountNumber in fallbackAccountNumbers:
							fallbackAccountNumbers.append(defaultAccountNumber)

						fallbackAccountNumbers.remove(fallbackAccountNumber)
						self.server.accountManager.setDefaultAccount(accountName, fallbackAccountNumber)

						accountChange = True
						xbmcgui.Dialog().notification(
							self.server.settings.getLocalizedString(30003) + ": " + self.server.settings.getLocalizedString(30006),
							self.server.settings.getLocalizedString(30007),
						)
						break

					self.server.accountManager.setFallbackAccounts([accounts[n]["username"] for n in fallbackAccountNumbers], fallbackAccountNumbers)

					if not accountChange:
						xbmcgui.Dialog().ok(
							self.server.settings.getLocalizedString(30003) + ": " + self.server.settings.getLocalizedString(30006),
							self.server.settings.getLocalizedString(30009),
						)
						return

				else:
					xbmc.log(self.server.settings.getLocalizedString(30003) + ": " + str(e))
					return

			self.server.failed = False
			self.send_response(200)
			self.send_header("Content-Type", response.info().get("Content-Type"))
			self.send_header("Content-Length", response.info().get("Content-Length"))
			self.send_header("Cache-Control", response.info().get("Cache-Control"))
			self.send_header("Date", response.info().get("Date"))
			self.send_header("Content-type", "video/mp4")
			self.send_header("Accept-Ranges", "bytes")
			# self.send_header("ETag", response.info().get("ETag"))
			# self.send_header("Server", response.info().get("Server"))
			self.end_headers()

			## may want to add more granular control over chunk fetches
			# self.wfile.write(response.read())
			response.close()
			self.server.length = response.info().get("Content-Length")

	def do_GET(self):

		if self.path == "/play":

			if self.server.failed:
				return

			start, end = re.findall("Range: bytes=([\d]+)-([\d]+)?", str(self.headers), re.DOTALL)[0]
			if start: start = int(start)
			if end: end = int(end)
			startOffset = 0

			if start and start > 16 and not end:
				# start = start - (16 - (end % 16))
				xbmc.log("START = " + str(start))
				startOffset = 16 - ((int(self.server.length) - start) % 16) + 8

			# if start == 23474184:
				# start = start - (16 - (end % 16))
				# start = 23474184 - 8

			url = self.server.playbackURL
			xbmc.log("GET " + url + "\n" + self.server.service.getHeadersEncoded() + "\n")

			if not start:
				req = urllib.request.Request(url, None, self.server.service.getHeaders())
			else:
				req = urllib.request.Request(
					url,
					None,
					self.server.service.getHeaders(
						additionalHeader="Range",
						additionalValue="bytes=" + str(start - startOffset) + "-" + str(end),
					)
				)

			try:
				response = urllib.request.urlopen(req)
			except urllib.error.URLError as e:
				xbmc.log(self.server.settings.getLocalizedString(30003) + ": " + str(e))
				return

			if not start:
				self.send_response(200)
				self.send_header("Content-Length", response.info().get("Content-Length"))
			else:
				self.send_response(206)
				self.send_header("Content-Length", str(int(response.info().get("Content-Length")) - startOffset))
				# self.send_header("Content-Range", "bytes " + str(start) + "-" + str(end))

				if not end:
					self.send_header("Content-Range", "bytes {}-{}/{}".format(start, int(self.server.length) - 1, self.server.length))
				else:
					self.send_header("Content-Range", "bytes {}-{}/{}".format(start, end, self.server.length))

				# self.send_header("Content-Range", response.info().get("Content-Range"))
				xbmc.log("Content-Range!!!{}-{}/{}\n".format(start, int(self.server.length) - 1, self.server.length))

			xbmc.log(str(response.info()) + "\n")

			self.send_header("Content-Type", response.info().get("Content-Type"))
			# self.send_header("Content-Length", response.info().get("Content-Length"))
			self.send_header("Cache-Control", response.info().get("Cache-Control"))
			self.send_header("Date", response.info().get("Date"))
			self.send_header("Content-type", "video/mp4")
			self.send_header("Accept-Ranges", "bytes")
			self.end_headers()

			# may want to add more granular control over chunk fetches
			# self.wfile.write(response.read())
			decrypt = encryption.Encryption(self.server.settings.getSetting("crypto_salt"), self.server.settings.getSetting("crypto_password"))

			try:
				decrypt.decryptStreamChunkOld(response, self.wfile, startOffset=startOffset)
			except Exception as e:
				xbmc.log(str(e))

			response.close()

		elif self.path == "/enroll":
			self.send_response(200)
			self.end_headers()
			data = enrolment.form1
			self.wfile.write(data.encode("utf-8"))
