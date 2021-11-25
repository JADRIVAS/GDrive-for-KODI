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

import sys
import xbmc
import urllib.parse
from xbmcaddon import Addon


def parseQuery(query):
	queries = {}

	try:
		queries = urllib.parse.parse_qs(query)
	except:
		return

	q = {key: value[0] for key, value in queries.items()}
	q["mode"] = q.get("mode", "main")
	return q


pluginQueries = None

try:
	pluginQueries = parseQuery(sys.argv[2][1:])
except:
	pluginQueries = None


class Settings(Addon):

	def __init__(self):
		self.username = self.getParameter("username", "")
		self.serverPort = self.getSettingInt("server_port", 8011)
		self.cryptoPassword = self.getSetting("crypto_password")
		self.cryptoSalt = self.getSetting("crypto_salt")

	def getParameter(self, key, default=""):

		try:
			value = pluginQueries[key]

			if value == "true" or value == "True":
				return True
			elif value == "false" or value == "False":
				return False
			else:
				return value

		except:
			return default

	def getParameterInt(self, key, default=0):

		try:
			value = pluginQueries[key]

			if value == "true" or value == "True":
				return True
			elif value == "false" or value == "False":
				return False
			else:
				return value

		except:
			return default

	def getSetting(self, key, default=""):

		try:
			value = super(Settings, self).getSetting(key)

			if value == "true" or value == "True":
				return True
			elif value == "false" or value == "False":
				return False
			elif value is None:
				return default
			else:
				return value

		except:
			return default

	def getSettingInt(self, key, default=0):

		try:
			return int(self.getSetting(key))
		except:
			return default
