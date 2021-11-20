"""
	CloudService XBMC Plugin
	Copyright (C) 2013-2014 ddurdle

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
import os
import sys
import time
import urllib
import xbmc
import xbmcgui
import xbmcplugin
import constants
from resources.lib import settings


def decode(data):
	return re.sub("&#(\d+)(;|(?=\s))", _callback, data).strip()


def decodeDict(data):

	for k, v in data.items():

		if type(v) is str or type(v) is unicode:
			data[k] = decode(v)

	return data


# http://stackoverflow.com/questions/1208916/decoding-html-entities-with-python/1208931#1208931
def _callback(matches):
	id = matches.group(1)

	try:
		return unichr(int(id))
	except:
		return id


class ContentEngine:
	PLUGIN_HANDLE = None
	PLUGIN_URL = ""

	##
	# load eclipse debugger
	#	parameters: none
	##
	def debugger(self):

		try:
			remoteDebugger = self.settingsModule.getSetting("remote_debugger")
			remoteDebuggerHost = self.settingsModule.getSetting("remote_debugger_host")

			# append pydev remote debugger
			if remoteDebugger == "true":
				# Make pydev debugger works for auto reload.
				# Note pydevd module need to be copied in XBMC\system\python\Lib\pysrc
				import pysrc.pydevd as pydevd
				# stdoutToServer and stderrToServer redirect stdout and stderr to eclipse console
				pydevd.settrace(remoteDebuggerHost, stdoutToServer=True, stderrToServer=True)

		except ImportError:
			xbmc.log(self.addon.getLocalizedString(30016), xbmc.LOGERROR)
			sys.exit(1)
		except:
			return

	##
	# Delete an account, enroll an account or refresh the current listings
	#	parameters: mode
	##
	def accountActions(self, addon, mode, instanceName):

		if mode == "makedefault":
			addon.setSetting("default_account", re.sub("[^\d]", "", instanceName))
			addon.setSetting("default_account_ui", addon.getSetting(instanceName + "_username"))
			xbmc.executebuiltin("Container.Refresh")

		elif mode == "rename":
			input = xbmcgui.Dialog().input(addon.getLocalizedString(30002))

			if not input:
				return

			accountName = addon.getSetting(instanceName + "_username")
			addon.setSetting(instanceName + "_username", input)

			if addon.getSetting("default_account_ui") == accountName:
				addon.setSetting("default_account_ui", input)

			fallbackAccounts = addon.getSetting("fallback_accounts_ui").split(", ")

			if accountName in fallbackAccounts:
				fallbackAccounts.remove(accountName)
				fallbackAccounts.append(input)
				addon.setSetting("fallback_accounts_ui", ", ".join(fallbackAccounts))

			xbmc.executebuiltin("Container.Refresh")

		# delete the configuration for the specified account
		elif mode == "delete":

			class Deleter:

				def __init__(self):
					self.fallbackAccountNumbers = addon.getSetting("fallback_accounts").split(",")
					self.fallbackAccountNames = addon.getSetting("fallback_accounts_ui").split(", ")

				def deleteAccount(self, instanceName):
					accountName = addon.getSetting(instanceName + "_username")

					addon.setSetting(instanceName + "_username", "")
					addon.setSetting(instanceName + "_code", "")
					addon.setSetting(instanceName + "_client_id", "")
					addon.setSetting(instanceName + "_client_secret", "")
					addon.setSetting(instanceName + "_auth_access_token", "")
					addon.setSetting(instanceName + "_auth_refresh_token", "")

					if addon.getSetting("default_account_ui") == accountName:
						addon.setSetting("default_account_ui", "")
						addon.setSetting("default_account", "")

					if accountName in self.fallbackAccountNames:
						self.fallbackAccountNumbers.remove(re.sub("[^\d]", "", instanceName))
						self.fallbackAccountNames.remove(accountName)
						addon.setSetting("fallback_accounts", ",".join(self.fallbackAccountNumbers))
						addon.setSetting("fallback_accounts_ui", ", ".join(self.fallbackAccountNames))

			delete = Deleter()

			if isinstance(instanceName, list):
				[delete.deleteAccount(x) for x in instanceName]
			else:
				delete.deleteAccount(instanceName)

			xbmc.executebuiltin("Container.Refresh")

		elif mode == "deletefallback" or mode == "addfallback":
			fallbackAccountNumbers = addon.getSetting("fallback_accounts")
			fallbackAccountNames = addon.getSetting("fallback_accounts_ui")
			accountName = addon.getSetting(instanceName + "_username")
			accountNumber = re.sub("[^\d]", "", instanceName)

			if fallbackAccountNumbers:
				fallbackAccountNumbers = fallbackAccountNumbers.split(",")
				fallbackAccountNames = fallbackAccountNames.split(", ")

				if mode == "deletefallback":
					fallbackAccountNumbers.remove(accountNumber)
					fallbackAccountNames.remove(accountName)
				else:
					fallbackAccountNumbers.append(accountNumber)
					fallbackAccountNames.append(accountName)

				addon.setSetting("fallback_accounts", ",".join(fallbackAccountNumbers))
				addon.setSetting("fallback_accounts_ui", ", ".join(fallbackAccountNames))
			else:
				addon.setSetting("fallback", "true")
				addon.setSetting("fallback_accounts", accountNumber)
				addon.setSetting("fallback_accounts_ui", accountName)

			xbmc.executebuiltin("Container.Refresh")

		elif mode == "validate":
			validation = self.cloudservice2(self.PLUGIN_HANDLE, self.PLUGIN_URL, addon, instanceName, self.userAgent, self.settingsModule)
			validation.refreshToken()

			if validation.failed:
				accountName = addon.getSetting(instanceName + "_username")
				selection = xbmcgui.Dialog().yesno(addon.getLocalizedString(30000), accountName + addon.getLocalizedString(30019))

				if selection:
					self.accountActions(addon, "delete", instanceName)

			else:
				xbmcgui.Dialog().ok(addon.getLocalizedString(30000), addon.getLocalizedString(30020))

		# enroll a new account
		elif mode == "enroll":
			import socket

			s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
			s.connect(("8.8.8.8", 80))
			IP = s.getsockname()[0]
			s.close()

			display = xbmcgui.Dialog().ok(
				addon.getLocalizedString(30000),
				"{} [B][COLOR blue]http://{}:{}/enroll[/COLOR][/B] {}".format(
					addon.getLocalizedString(30210),
					IP,
					self.addon.getSetting("server_port"),
					addon.getLocalizedString(30218),
				)
			)

			if display:
				xbmc.executebuiltin("Container.Refresh")

	##
	# add a menu to a directory screen
	#	parameters: url to resolve, title to display, optional: icon, fanart, totalItems, instance name
	##
	def addMenu(self, url, title, totalItems=0, instanceName=None):
		listitem = xbmcgui.ListItem(title)

		if instanceName is not None:
			cm = []
			cm.append((self.addon.getLocalizedString(30211), "Addon.OpenSettings({})".format(self.addon.getAddonInfo("id"))))
			listitem.addContextMenuItems(cm, True)

		xbmcplugin.addDirectoryItem(self.PLUGIN_HANDLE, url, listitem, totalItems=totalItems)

	# Retrieves all active accounts
	def getAccounts(self):
		self.accountNumbers, self.accountNames, self.accountInstances = [], [], []

		for count in range(1, self.accountAmount + 1):
			instanceName = self.PLUGIN_NAME + str(count)
			username = self.addon.getSetting(instanceName + "_username")

			if username:
				self.accountNumbers.append(str(count))
				self.accountNames.append(username)
				self.accountInstances.append(instanceName)

	def run(self, dbID, dbType, filePath):
		addon = constants.addon
		self.addon = addon

		self.PLUGIN_URL = constants.PLUGIN_NAME
		self.PLUGIN_NAME = constants.PLUGIN_NAME
		self.cloudservice2 = constants.cloudservice2

		# global variables
		self.PLUGIN_URL = sys.argv[0]
		self.PLUGIN_HANDLE = int(sys.argv[1])
		pluginQueries = settings.parseQuery(sys.argv[2][1:])

		# cloudservice - create settings module
		self.settingsModule = settings.Settings(addon)

		self.userAgent = self.settingsModule.getSetting("user_agent")
		self.accountAmount = addon.getSettingInt("account_amount")
		mode = self.settingsModule.getParameter("mode", "main").lower()

		try:
			instanceName = (pluginQueries["instance"]).lower()
		except:
			instanceName = None

		if not instanceName and mode == "main":
			self.addMenu(self.PLUGIN_URL + "?mode=enroll", "[B]1. {}[/B]".format(addon.getLocalizedString(30207)), instanceName=True)
			self.addMenu(self.PLUGIN_URL + "?mode=fallback", "[B]2. {}[/B]".format(addon.getLocalizedString(30220)), instanceName=True)
			self.addMenu(self.PLUGIN_URL + "?mode=validate", "[B]3. {}[/B]".format(addon.getLocalizedString(30021)), instanceName=True)
			self.addMenu(self.PLUGIN_URL + "?mode=delete", "[B]4. {}[/B]".format(addon.getLocalizedString(30022)), instanceName=True)

			defaultAccount = addon.getSetting("default_account")
			fallBackAccounts = addon.getSetting("fallback_accounts").split(",")

			for count in range (1, self.accountAmount + 1):
				instanceName = self.PLUGIN_NAME + str(count)
				username = self.addon.getSetting(instanceName + "_username")

				if username:
					countStr = str(count)

					if countStr == defaultAccount:
						username = "[COLOR crimson][B]{}[/B][/COLOR]".format(username)
					elif countStr in fallBackAccounts:
						username = "[COLOR deepskyblue][B]{}[/B][/COLOR]".format(username)

					self.addMenu("{}?mode=main&instance={}".format(self.PLUGIN_URL, instanceName), username, instanceName=instanceName)

			xbmcplugin.setContent(self.PLUGIN_HANDLE, "files")
			xbmcplugin.addSortMethod(self.PLUGIN_HANDLE, xbmcplugin.SORT_METHOD_LABEL)

		elif instanceName and mode == "main":
			fallbackAccounts = addon.getSetting("fallback_accounts").split(",")
			options = [
				self.addon.getLocalizedString(30219),
				self.addon.getLocalizedString(30002),
				addon.getLocalizedString(30023),
				self.addon.getLocalizedString(30159),
			]
			account = re.sub("[^\d]", "", instanceName)

			if account in fallbackAccounts:
				fallbackExists = True
				options.insert(0, self.addon.getLocalizedString(30212))
			else:
				fallbackExists = False
				options.insert(0, self.addon.getLocalizedString(30213))

			selection = xbmcgui.Dialog().contextmenu(options)

			if selection == 0:

				if fallbackExists:
					mode = "deletefallback"
				else:
					mode = "addfallback"

			elif selection == 1:
				mode = "makedefault"
			elif selection == 2:
				mode = "rename"
			elif selection == 3:
				mode = "validate"
			elif selection == 4:
				mode = "delete"
				selection = xbmcgui.Dialog().yesno(
					self.addon.getLocalizedString(30000),
					"{} {}?".format(
						self.addon.getLocalizedString(30121),
						addon.getSetting(instanceName + "_username"),
					)
				)

				if not selection:
					return

			else:
				return

			self.accountActions(addon, mode, instanceName)

		elif mode == "enroll" or mode == "makedefault":
			self.accountActions(addon, mode, instanceName)

		elif mode == "settings_default":
			self.getAccounts()
			selection = xbmcgui.Dialog().select(addon.getLocalizedString(30120), self.accountNames)

			if selection == -1:
				return

			addon.setSetting("default_account", self.accountNumbers[selection])
			addon.setSetting("default_account_ui", self.accountNames[selection])

		elif mode == "fallback":
			self.getAccounts()
			fallbackAccounts = addon.getSetting("fallback_accounts")
			fallbackAccountNames = addon.getSetting("fallback_accounts_ui")

			if fallbackAccounts:
				fallbackAccounts = [self.accountNumbers.index(x) for x in fallbackAccounts.split(",") if x in self.accountNumbers]
				selection = xbmcgui.Dialog().multiselect(addon.getLocalizedString(30120), self.accountNames, preselect=fallbackAccounts)
			else:
				selection = xbmcgui.Dialog().multiselect(addon.getLocalizedString(30120), self.accountNames)

			if selection is None:
				return

			addon.setSetting("fallback_accounts", ",".join(self.accountNumbers[x] for x in selection))
			addon.setSetting("fallback_accounts_ui", ", ".join(self.accountNames[x] for x in selection))
			addon.setSetting("fallback", "true")
			xbmc.executebuiltin("Container.Refresh")

		elif mode == "validate":
			self.getAccounts()
			selection = xbmcgui.Dialog().multiselect(addon.getLocalizedString(30024), self.accountNames)

			if selection is None:
				return

			for index_ in selection:
				instanceName = self.accountInstances[index_]
				validation = self.cloudservice2(self.PLUGIN_HANDLE, self.PLUGIN_URL, addon, instanceName, self.userAgent, self.settingsModule)
				validation.refreshToken()

				if validation.failed:
					accountName = self.accountNames[index_]
					selection = xbmcgui.Dialog().yesno(addon.getLocalizedString(30000), "{} {}".format(accountName, addon.getLocalizedString(30019)))

					if selection:
						self.accountActions(addon, "delete", instanceName)

			xbmcgui.Dialog().ok(addon.getLocalizedString(30000), addon.getLocalizedString(30020))

		elif mode == "settings_delete" or mode == "delete":
			self.getAccounts()
			selection = xbmcgui.Dialog().multiselect(addon.getLocalizedString(30158), self.accountNames)

			if selection is None:
				return

			self.accountActions(addon, "delete", [self.accountInstances[x] for x in selection])

			if mode == "settings_delete" and selection:
				xbmcgui.Dialog().ok(addon.getLocalizedString(30000), addon.getLocalizedString(30160))

		elif mode == "video":
			instanceName = constants.PLUGIN_NAME + str(self.settingsModule.getSetting("default_account", 1))
			service = self.cloudservice2(self.PLUGIN_HANDLE, self.PLUGIN_URL, addon, instanceName, self.userAgent, self.settingsModule)

			if service.failed:
				xbmcgui.Dialog().ok(addon.getLocalizedString(30000), addon.getLocalizedString(30005))
				return

			if not self.settingsModule.cryptoPassword or not self.settingsModule.cryptoSalt:
				xbmcgui.Dialog().ok(addon.getLocalizedString(30000), addon.getLocalizedString(30208))
				return

			try:
				service
			except NameError:
				xbmcgui.Dialog().ok(addon.getLocalizedString(30000), addon.getLocalizedString(30051) + " " + addon.getLocalizedString(30052))
				xbmc.log(addon.getLocalizedString(30051) + constants.PLUGIN_NAME + "-login", xbmc.LOGERROR)
				return

			if (not dbID or not dbType) and not filePath:
				timeEnd = time.time() + 1

				while time.time() < timeEnd and (not dbID or not dbType):
					xbmc.executebuiltin("Dialog.Close(busydialog)")
					dbID = xbmc.getInfoLabel("ListItem.DBID")
					dbType = xbmc.getInfoLabel("ListItem.DBTYPE")

			if dbID:

				if dbType == "movie":
					jsonQuery = xbmc.executeJSONRPC(
						'{"jsonrpc": "2.0", "id": "1", "method": "VideoLibrary.GetMovieDetails", "params": {"movieid": %s, "properties": ["resume"]}}'
						% dbID
					)
					jsonKey = "moviedetails"
				else:
					jsonQuery = xbmc.executeJSONRPC(
						'{"jsonrpc": "2.0", "id": "1", "method": "VideoLibrary.GetEpisodeDetails", "params": {"episodeid": %s, "properties": ["resume"]}}'
						% dbID
					)
					jsonKey = "episodedetails"

				import json

				jsonQuery = jsonQuery.encode("utf-8", errors="ignore")
				jsonResponse = json.loads(jsonQuery)

				try:
					resumeData = jsonResponse["result"][jsonKey]["resume"]
				except:
					return

				resumePosition = resumeData["position"]
				videoLength = resumeData["total"]

			elif filePath:
				from sqlite3 import dbapi2 as sqlite

				dbPath = xbmc.translatePath(self.settingsModule.getSetting("video_db"))
				db = sqlite.connect(dbPath)
				dirPath = os.path.dirname(filePath) + os.sep
				fileName = os.path.basename(filePath)
				resumePosition = list(
					db.execute(
						"SELECT timeInSeconds FROM bookmark WHERE idFile=(SELECT idFile FROM files WHERE idPath=(SELECT idPath FROM path WHERE strPath=?) AND strFilename=?)",
						(dirPath, fileName)
					)
				)

				if resumePosition:
					resumePosition = resumePosition[0][0]
					videoLength = list(
						db.execute(
							"SELECT totalTimeInSeconds FROM bookmark WHERE idFile=(SELECT idFile FROM files WHERE idPath=(SELECT idPath FROM path WHERE strPath=?) AND strFilename=?)",
							(dirPath, fileName)
						)
					)[0][0]
				else:
					resumePosition = 0

			else:
				resumePosition = 0

				# import pickle

				# resumeDBPath = xbmc.translatePath(self.settingsModule.resumeDBPath)
				# resumeDB = os.path.join(resumeDBPath, "kodi_resumeDB.p")

				# try:
					# with open(resumeDB, "rb") as dic:
						# videoData = pickle.load(dic)
				# except:
					# videoData = {}

				# try:
					# resumePosition = videoData[filename]
				# except:
					# videoData[filename] = 0
					# resumePosition = 0

				# strmName = self.settingsModule.getParameter("title") + ".strm"
				# cursor = list(db.execute("SELECT timeInSeconds FROM bookmark WHERE idFile=(SELECT idFile FROM files WHERE strFilename='%s')" % strmName))

				# if cursor:
					# resumePosition = cursor[0][0]
				# else:
					# resumePosition = 0

			resumeOption = False

			if resumePosition > 0:
				options = ("Resume from " + str(time.strftime("%H:%M:%S", time.gmtime(resumePosition))), "Play from beginning")
				selection = xbmcgui.Dialog().contextmenu(options)

				if selection == 0:
					# resumePosition = resumePosition / total * 100
					resumeOption = True
				# elif selection == 1:
					# resumePosition = "0"
					# videoData[filename] = 0
				elif selection == -1:
					return

			driveID = self.settingsModule.getParameter("filename")	# file ID
			driveURL = "https://www.googleapis.com/drive/v2/files/{}?includeTeamDriveItems=true&supportsTeamDrives=true&alt=media".format(driveID)
			url = "http://localhost:{}/crypto_playurl".format(service.settings.serverPort)
			data = "instance={}&url={}".format(service.instanceName, driveURL)
			req = urllib.request.Request(url, data.encode("utf-8"))

			try:
				response = urllib.request.urlopen(req)
				response.close()
			except urllib.error.URLError as e:
				xbmc.log(self.addon.getAddonInfo("name") + ": " + str(e), xbmc.LOGERROR)
				return

			item = xbmcgui.ListItem(path="http://localhost:{}/play".format(service.settings.serverPort))
			# item.setProperty("StartPercent", str(position))
			# item.setProperty("startoffset", "60")

			if resumeOption:
				# item.setProperty("totaltime", "1")
				item.setProperty("totaltime", str(videoLength))
				item.setProperty("resumetime", str(resumePosition))

			xbmcplugin.setResolvedUrl(self.PLUGIN_HANDLE, True, item)

			if dbID:
				widget = 0 if xbmc.getInfoLabel("Container.Content") else 1
				url = "http://localhost:{}/start_gplayer".format(service.settings.serverPort)
				data = "dbid={}&dbtype={}&widget={}".format(dbID, dbType, widget)
				req = urllib.request.Request(url, data.encode("utf-8"))
			else:
				url = "http://localhost:{}/start_player".format(service.settings.serverPort)
				req = urllib.request.Request(url)

			response = urllib.request.urlopen(req)
			response.close()

		xbmcplugin.endOfDirectory(self.PLUGIN_HANDLE)
		return

				# with open(resumeDB, "wb+") as dic:
					# pickle.dump(videoData, dic)

				# del videoData

				# with open(resumeDB, "rb") as dic:
					# videoData = pickle.load(dic)

				# if player.videoWatched:
					# del videoData[filename]
				# else:
					# videoData[filename] = player.time

				# with open(resumeDB, "wb+") as dic:
					# pickle.dump(videoData, dic)

		# request = {"jsonrpc": "2.0", "method": "VideoLibrary.GetMovies", "params": { "filter": {"field": "playcount", "operator": "greaterthan", "value": "0"}, "limits": { "start": 0 }, "properties": ["playcount"], "sort": { "order": "ascending", "method": "label" } }, "id": "libMovies"}
		# request = {"jsonrpc": "2.0", "method": "VideoLibrary.GetMovies", "params": { "filter": {"field": "playcount", "operator": "greaterthan", "value": "0"}, "limits": { "start": 0 }, "properties": ["playcount"], "sort": { "order": "ascending", "method": "label" } }, "id": "libMovies"}
