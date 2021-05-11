'''
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
'''

import re
import sys
import os
import urllib, urllib2
import xbmc, xbmcgui, xbmcplugin, xbmcvfs
import constants
from resources.lib import settings

def decode(data):
	return re.sub('&#(\d+)(;|(?=\s))', _callback, data).strip()

def decode_dict(data):

	for k, v in data.items():

		if type(v) is str or type(v) is unicode:
			data[k] = decode(v)

	return data

#http://stackoverflow.com/questions/1208916/decoding-html-entities-with-python/1208931#1208931
def _callback(matches):
	id = matches.group(1)

	try:
		return unichr(int(id) )
	except:
		return id

class contentengine(object):
	plugin_handle = None
	PLUGIN_URL = ''

	##
	# load eclipse debugger
	#	parameters: none
	##
	def debugger(self):

		try:
			remote_debugger = self.settingsModule.getSetting('remote_debugger')
			remote_debugger_host = self.settingsModule.getSetting('remote_debugger_host')

			# append pydev remote debugger
			if remote_debugger == 'true':
				# Make pydev debugger works for auto reload.
				# Note pydevd module need to be copied in XBMC\system\python\Lib\pysrc
				import pysrc.pydevd as pydevd
				# stdoutToServer and stderrToServer redirect stdout and stderr to eclipse console
				pydevd.settrace(remote_debugger_host, stdoutToServer=True, stderrToServer=True)

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

		if mode == 'makedefault':
			addon.setSetting('default_account', re.sub('[^\d]', '', instanceName) )
			addon.setSetting('default_account_ui', addon.getSetting(instanceName + '_username') )
			xbmc.executebuiltin('Container.Refresh')

		elif mode == 'rename':
			input = xbmcgui.Dialog().input(addon.getLocalizedString(30002) )

			if not input:
				return

			accountName = addon.getSetting(instanceName + '_username')
			addon.setSetting(instanceName + '_username', input)

			if addon.getSetting('default_account_ui') == accountName:
				addon.setSetting('default_account_ui', input)

			fallbackAccounts = addon.getSetting('fallback_accounts_ui').split(', ')

			if accountName in fallbackAccounts:
				fallbackAccounts.remove(accountName)
				fallbackAccounts.append(input)
				addon.setSetting('fallback_accounts_ui', ', '.join(fallbackAccounts) )

			xbmc.executebuiltin('Container.Refresh')

		# delete the configuration for the specified account
		elif mode == 'delete':

			class Deleter:
				def __init__(self):
					self.fallbackAccountNumbers = addon.getSetting('fallback_accounts').split(',')
					self.fallbackAccountNames = addon.getSetting('fallback_accounts_ui').split(', ')

				def deleteAccount(self, instanceName):
					accountName = addon.getSetting(instanceName + '_username')

					addon.setSetting(instanceName + '_username', '')
					addon.setSetting(instanceName + '_code', '')
					addon.setSetting(instanceName + '_client_id', '')
					addon.setSetting(instanceName + '_client_secret', '')
					addon.setSetting(instanceName + '_auth_access_token', '')
					addon.setSetting(instanceName + '_auth_refresh_token', '')

					if addon.getSetting('default_account_ui') == accountName:
						addon.setSetting('default_account_ui', '')
						addon.setSetting('default_account', '')

					if accountName in self.fallbackAccountNames:
						self.fallbackAccountNumbers.remove(re.sub('[^\d]', '', instanceName) )
						self.fallbackAccountNames.remove(accountName)

						addon.setSetting('fallback_accounts', ','.join(self.fallbackAccountNumbers) )
						addon.setSetting('fallback_accounts_ui', ', '.join(self.fallbackAccountNames) )

			delete = Deleter()

			if isinstance(instanceName, list):
				[delete.deleteAccount(x) for x in instanceName]
			else:
				delete.deleteAccount(instanceName)

			xbmc.executebuiltin('Container.Refresh')


		elif mode == 'deletefallback' or mode == 'addfallback':
			fallbackAccountNumbers = addon.getSetting('fallback_accounts')
			fallbackAccountNames = addon.getSetting('fallback_accounts_ui')
			accountName = addon.getSetting(instanceName + '_username')
			accountNumber = re.sub('[^\d]', '', instanceName)

			if fallbackAccountNumbers:
				fallbackAccountNumbers = fallbackAccountNumbers.split(',')
				fallbackAccountNames = fallbackAccountNames.split(', ')

				if mode == 'deletefallback':
					fallbackAccountNumbers.remove(accountNumber)
					fallbackAccountNames.remove(accountName)
				else:
					fallbackAccountNumbers.append(accountNumber)
					fallbackAccountNames.append(accountName)

				addon.setSetting('fallback_accounts', ','.join(fallbackAccountNumbers) )
				addon.setSetting('fallback_accounts_ui', ', '.join(fallbackAccountNames) )
			else:
				addon.setSetting('fallback', 'true')
				addon.setSetting('fallback_accounts', accountNumber)
				addon.setSetting('fallback_accounts_ui', accountName)

			xbmc.executebuiltin('Container.Refresh')

		elif mode == 'validate':
			validation = self.cloudservice2(self.plugin_handle, self.PLUGIN_URL, addon, instanceName, self.user_agent, self.settingsModule)
			validation.refreshToken()

			if validation.failed:
				accountName = addon.getSetting(instanceName + '_username')
				selection = xbmcgui.Dialog().yesno(addon.getLocalizedString(30000), '%s %s' % (accountName, addon.getLocalizedString(30019) ) )

				if selection:
					self.accountActions(addon, 'delete', instanceName)

			else:
				xbmcgui.Dialog().ok(addon.getLocalizedString(30000), addon.getLocalizedString(30020) )

		# enroll a new account
		elif mode == 'enroll':

			import socket
			s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
			s.connect( ('8.8.8.8', 80) )
			IP = s.getsockname()[0]
			s.close()

			display = xbmcgui.Dialog().ok(addon.getLocalizedString(30000), '%s [B][COLOR blue]http://%s:%s/enroll[/COLOR][/B] %s' % (addon.getLocalizedString(30210), IP, self.addon.getSetting('server_port'), addon.getLocalizedString(30218) ) )

			if display:
				xbmc.executebuiltin('Container.Refresh')

	##
	# add a menu to a directory screen
	#	parameters: url to resolve, title to display, optional: icon, fanart, total_items, instance name
	##
	def addMenu(self, url, title, total_items=0, instanceName=None):
		listitem = xbmcgui.ListItem(title)

		if instanceName is not None:
			cm = []
			cm.append( (self.addon.getLocalizedString(30211), 'Addon.OpenSettings(%s)' % self.addon.getAddonInfo('id') ) )
			listitem.addContextMenuItems(cm, True)

		xbmcplugin.addDirectoryItem(self.plugin_handle, url, listitem, totalItems=total_items)

	# Retrieves all active accounts
	def getAccounts(self):
		self.accountNumbers = []
		self.accountNames = []
		self.accountInstances = []

		for count in range (1, self.accountAmount + 1):
			instanceName = self.PLUGIN_NAME + str(count)
			username = self.addon.getSetting(instanceName + '_username')

			if username:
				self.accountNumbers.append(str(count) )
				self.accountNames.append(username)
				self.accountInstances.append(instanceName)

	def run(self, dbID=None, dbType=None, filePath=None, writer=None, query=None, addon=None, host=None):
		addon = constants.addon
		self.addon = addon

		self.PLUGIN_URL = constants.PLUGIN_NAME
		self.PLUGIN_NAME = constants.PLUGIN_NAME
		self.cloudservice2 = constants.cloudservice2

		#global variables
		self.PLUGIN_URL = sys.argv[0]
		self.plugin_handle = int(sys.argv[1])
		plugin_queries = settings.parse_query(sys.argv[2][1:])

		# cloudservice - create settings module
		self.settingsModule = settings.settings(addon)

		self.user_agent = self.settingsModule.getSetting('user_agent')
		self.accountAmount = addon.getSettingInt('account_amount')
		mode = self.settingsModule.getParameter('mode', 'main')
		mode = mode.lower()

		try:
			instanceName = (plugin_queries['instance']).lower()
		except:
			instanceName = None

		if not instanceName and mode == 'main':
			self.addMenu(self.PLUGIN_URL + '?mode=enroll', '[B]1. %s[/B]' % addon.getLocalizedString(30207), instanceName=True)
			self.addMenu(self.PLUGIN_URL + '?mode=fallback', '[B]2. %s[/B]' % addon.getLocalizedString(30220), instanceName=True)
			self.addMenu(self.PLUGIN_URL + '?mode=validate', '[B]3. %s[/B]' % addon.getLocalizedString(30021), instanceName=True)
			self.addMenu(self.PLUGIN_URL + '?mode=delete', '[B]4. %s[/B]' % addon.getLocalizedString(30022), instanceName=True)

			defaultAccount = addon.getSetting('default_account')
			fallBackAccounts = addon.getSetting('fallback_accounts').split(',')

			for count in range (1, self.accountAmount + 1):
				instanceName = self.PLUGIN_NAME + str(count)
				username = self.addon.getSetting(instanceName + '_username')

				if username:
					countStr = str(count)

					if countStr == defaultAccount:
						username = '[COLOR crimson][B]%s[/B][/COLOR]' % username
					elif countStr in fallBackAccounts:
						username = '[COLOR deepskyblue][B]%s[/B][/COLOR]' % username

					self.addMenu('%s?mode=main&instance=%s' % (self.PLUGIN_URL, instanceName), username, instanceName=instanceName)

			xbmcplugin.setContent(self.plugin_handle, 'files')
			xbmcplugin.addSortMethod(self.plugin_handle, xbmcplugin.SORT_METHOD_LABEL)

		elif instanceName and mode == 'main':
			fallbackAccounts = addon.getSetting('fallback_accounts').split(',')
			options = [self.addon.getLocalizedString(30219), self.addon.getLocalizedString(30002), addon.getLocalizedString(30023), self.addon.getLocalizedString(30159) ]
			account = re.sub('[^\d]', '', instanceName)
			fallbackExists = False

			if account in fallbackAccounts:
				fallbackExists = True
				options.insert(0, self.addon.getLocalizedString(30212) )
			else:
				options.insert(0, self.addon.getLocalizedString(30213) )

			selection = xbmcgui.Dialog().contextmenu(options)

			if selection == 0:

				if fallbackExists:
					mode = 'deletefallback'
				else:
					mode = 'addfallback'

			elif selection == 1:
				mode = 'makedefault'
			elif selection == 2:
				mode = 'rename'
			elif selection == 3:
				mode = 'validate'
			elif selection == 4:
				mode = 'delete'
				selection = xbmcgui.Dialog().yesno(self.addon.getLocalizedString(30000), '%s %s?' % (self.addon.getLocalizedString(30121), addon.getSetting(instanceName + '_username') ) )

				if not selection:
					return

			else:
				return

			self.accountActions(addon, mode, instanceName)

		elif mode == 'enroll' or mode == 'makedefault':
			self.accountActions(addon, mode, instanceName)

		elif mode == 'settings_default':
			self.getAccounts()
			selection = xbmcgui.Dialog().select(addon.getLocalizedString(30120), self.accountNames)

			if selection == -1:
				return

			addon.setSetting('default_account', self.accountNumbers[selection] )
			addon.setSetting('default_account_ui', self.accountNames[selection] )

		elif mode == 'fallback':
			self.getAccounts()
			fallbackAccounts = addon.getSetting('fallback_accounts')
			fallbackAccountNames = addon.getSetting('fallback_accounts_ui')

			if fallbackAccounts:
				fallbackAccounts = [self.accountNumbers.index(x) for x in fallbackAccounts.split(',') if x in self.accountNumbers]
				selection = xbmcgui.Dialog().multiselect(addon.getLocalizedString(30120), self.accountNames, preselect=fallbackAccounts)
			else:
				selection = xbmcgui.Dialog().multiselect(addon.getLocalizedString(30120), self.accountNames)

			if selection is None:
				return

			addon.setSetting('fallback_accounts', ','.join(self.accountNumbers[x] for x in selection) )
			addon.setSetting('fallback_accounts_ui', ', '.join(self.accountNames[x] for x in selection) )
			addon.setSetting('fallback', 'true')

			xbmc.executebuiltin('Container.Refresh')

		elif mode == 'validate':
			self.getAccounts()
			selection = xbmcgui.Dialog().multiselect(addon.getLocalizedString(30024), self.accountNames)

			if selection is None:
				return

			for index_ in selection:
				instanceName = self.accountInstances[index_]
				validation = self.cloudservice2(self.plugin_handle, self.PLUGIN_URL, addon, instanceName, self.user_agent, self.settingsModule)
				validation.refreshToken()

				if validation.failed:
					accountName = self.accountNames[index_]
					selection = xbmcgui.Dialog().yesno(addon.getLocalizedString(30000), '%s %s' % (accountName, addon.getLocalizedString(30019) ) )

					if selection:
						self.accountActions(addon, 'delete', instanceName)

			xbmcgui.Dialog().ok(addon.getLocalizedString(30000), addon.getLocalizedString(30020) )

		elif mode == 'settings_delete' or mode == 'delete':
			self.getAccounts()
			selection = xbmcgui.Dialog().multiselect(addon.getLocalizedString(30158), self.accountNames)

			if selection is None:
				return

			self.accountActions(addon, 'delete', [self.accountInstances[x] for x in selection] )

			if mode == 'settings_delete' and selection:
				xbmcgui.Dialog().ok(addon.getLocalizedString(30000), addon.getLocalizedString(30160) )

		elif mode == 'video':

			if not dbType and not dbID and not filePath:
				return

			instanceName = constants.PLUGIN_NAME + str(self.settingsModule.getSetting('default_account', 1) )
			service = self.cloudservice2(self.plugin_handle, self.PLUGIN_URL, addon, instanceName, self.user_agent, self.settingsModule)

			if service.failed:
				xbmcgui.Dialog().ok(addon.getLocalizedString(30000), addon.getLocalizedString(30005) )
				return

			if not self.settingsModule.cryptoPassword or not self.settingsModule.cryptoSalt:
				xbmcgui.Dialog().ok(addon.getLocalizedString(30000), addon.getLocalizedString(30208) )
				return

			try:
				service
			except NameError:
				xbmcgui.Dialog().ok(addon.getLocalizedString(30000), addon.getLocalizedString(30051) + ' ' + addon.getLocalizedString(30052) )
				xbmc.log(addon.getLocalizedString(30051) + constants.PLUGIN_NAME + '-login', xbmc.LOGERROR)
				xbmcplugin.endOfDirectory(self.plugin_handle)
				return

			if dbID:

				if dbType == 'movie':
					jsonQuery = xbmc.executeJSONRPC('{"jsonrpc": "2.0", "id": "1", "method": "VideoLibrary.GetMovieDetails", "params": { "movieid":' + str(dbID) + ', "properties": ["resume"] } }')
					jsonKey = 'moviedetails'
				else:
					jsonQuery = xbmc.executeJSONRPC('{"jsonrpc": "2.0", "id": "1", "method": "VideoLibrary.GetEpisodeDetails", "params": { "episodeid":' + str(dbID) + ', "properties": ["resume"] } }')
					jsonKey = 'episodedetails'

				import json
				jsonQuery = jsonQuery.encode('utf-8', errors='ignore')
				jsonResponse = json.loads(jsonQuery)
				resumeData = jsonResponse['result'][jsonKey]['resume']

				resumePosition = resumeData['position']
				videoLength = resumeData['total']

			else:

				from sqlite3 import dbapi2 as sqlite
				dbPath = xbmc.translatePath(self.settingsModule.getSetting('video_db') )
				db = sqlite.connect(dbPath)

				dirPath = os.path.dirname(filePath).decode('utf-8') + os.sep
				fileName = os.path.basename(filePath).decode('utf-8')
				resumePosition = list(db.execute('SELECT timeInSeconds FROM bookmark WHERE idFile=(SELECT idFile FROM files WHERE idPath=(SELECT idPath FROM path WHERE strPath=?) AND strFilename=?)', (dirPath, fileName) ) )

				if resumePosition:
					resumePosition = resumePosition[0][0]
					videoLength = list(db.execute('SELECT totalTimeInSeconds FROM bookmark WHERE idFile=(SELECT idFile FROM files WHERE idPath=(SELECT idPath FROM path WHERE strPath=?) AND strFilename=?)', (dirPath, fileName) ) )[0][0]
				else:
					resumePosition = 0

				# import pickle

				# resumeDBPath = xbmcvfs.translatePath(self.settingsModule.resumeDBPath)
				# resumeDB = os.path.join(resumeDBPath, 'kodi_resumeDB.p')

				# try:
					# with open(resumeDB, 'rb') as dic:
						# videoData = pickle.load(dic)
				# except:
					# videoData = {}

				# try:
					# resumePosition = videoData[filename]
				# except:
					# videoData[filename] = 0
					# resumePosition = 0

				# strmName = self.settingsModule.getParameter('title') + ".strm"
				# cursor = list(db.execute('SELECT timeInSeconds FROM bookmark WHERE idFile=(SELECT idFile FROM files WHERE strFilename="%s")' % strmName) )

				# if cursor:
					# resumePosition = cursor[0][0]
				# else:
					# resumePosition = 0

			resumeOption = False

			if resumePosition > 0:

				import time
				options = []
				options.append('Resume from ' + str(time.strftime('%H:%M:%S', time.gmtime(resumePosition) ) ) )
				options.append('Play from beginning')

				selection = xbmcgui.Dialog().contextmenu(options)

				if selection == 0:
					# resumePosition = resumePosition / total * 100
					resumeOption = True
				# elif selection == 1:
					# resumePosition = '0'
					# videoData[filename] = 0
				elif selection == -1:
					return

			driveID = self.settingsModule.getParameter('filename') # file ID
			driveURL = 'https://www.googleapis.com/drive/v2/files/%s?includeTeamDriveItems=true&supportsTeamDrives=true&alt=media' % driveID
			url = 'http://localhost:' + str(service.settings.serverPort) + '/crypto_playurl'
			req = urllib2.Request(url, 'instance=' + str(service.instanceName) + '&url=' + driveURL)

			try:
				response = urllib2.urlopen(req)
				response.close()
			except urllib2.URLError, e:
				xbmc.log(self.addon.getAddonInfo('name') + ': ' + str(e), xbmc.LOGERROR)
				return

			item = xbmcgui.ListItem(path='http://localhost:' + str(service.settings.serverPort) + '/play')
			# item.setProperty('StartPercent', str(position) )
			# item.setProperty('startoffset', '60')

			if resumeOption:
				# item.setProperty('totaltime', '1')
				item.setProperty('totaltime', str(videoLength) )
				item.setProperty('resumetime', str(resumePosition) )

			xbmcplugin.setResolvedUrl(self.plugin_handle, True, item)

			if dbID:

				from resources.lib import gplayer
				player = gplayer.gPlayer(dbID=dbID, dbType=dbType)

				# with open(resumeDB, 'w+') as dic:
				#	pickle.dump(videoData, dic)

				# del videoData

				xbmc.sleep(100)
				monitor = xbmc.Monitor()

				while not monitor.abortRequested() and not player.isExit:
					player.sleep()
					player.saveTime()

				# with open(resumeDB, 'r') as dic:
				#	videoData = pickle.load(dic)

				# if player.videoWatched:
				#	del videoData[filename]
				# else:
				#	videoData[filename] = player.time

				# with open(resumeDB, 'w+') as dic:
				#	pickle.dump(videoData, dic)

		# if dbType == 'movie':
			# xbmc.executeJSONRPC('{"jsonrpc": "2.0", "method": "VideoLibrary.RefreshMovie", "params": {"movieid":' + str(dbID) + ', "ignorenfo": true}, "id": "1"}')
		# elif dbType == 'episode':
			# xbmc.executeJSONRPC('{"jsonrpc": "2.0", "method": "VideoLibrary.RefreshEpisode", "params": {"episodeid":' + str(dbID) + ', "ignorenfo": true}, "id": "1"}')

		# request = {"jsonrpc": "2.0", "method": "VideoLibrary.GetMovies", "params": { "filter": {"field": "playcount", "operator": "greaterthan", "value": "0"}, "limits": { "start" : 0 }, "properties": ["playcount"], "sort": { "order": "ascending", "method": "label" } }, "id": "libMovies"}
		# request = {"jsonrpc": "2.0", "method": "VideoLibrary.GetMovies", "params": { "filter": {"field": "playcount", "operator": "greaterthan", "value": "0"}, "limits": { "start" : 0 }, "properties": ["playcount"], "sort": { "order": "ascending", "method": "label" } }, "id": "libMovies"}

		xbmcplugin.endOfDirectory(self.plugin_handle)
		return