'''
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


'''

import sys
import cgi
import re

#http://stackoverflow.com/questions/1208916/decoding-html-entities-with-python/1208931#1208931
def _callback(matches):
	id = matches.group(1)

	try:
		return unichr(int(id) )
	except:
		return id

def decode(data):
	return re.sub("&#(\d+)(;|(?=\s))", _callback, data).strip()

def getParameter0(key, default=''):

	try:
		value = plugin_queries[key]

		if value == 'true' or value == 'True':
			return True
		elif value == 'false' or value == 'False':
			return False
		else:
			return value

	except:
		return default

def getParameterInt0(key, default=0):

	try:
		value = plugin_queries[key]

		if value == '':
			return default
		elif value == 'true' or value == 'True':
			return True
		elif value == 'false' or value == 'False':
			return False
		elif value is None:
			return default
		else:
			return value

	except:
		return default

def getSetting0(key, default=''):

	try:
		value = addon.getSetting(key)

		if value == 'true' or value == 'True':
			return True
		elif value == 'false' or value == 'False':
			return False
		else:
			return value

	except:
		return default

def getSettingInt0(key, default=0):

	try:
		value = addon.getSetting(key)

		if value == '':
			return default
		elif value == 'true' or value == 'True':
			return True
		elif value == 'false' or value == 'False':
			return False
		elif value is None:
			return default
		else:
			return value

	except:
		return default

def parse_query(query):
	queries = {}

	try:
		queries = cgi.parse_qs(query)
	except:
		return

	q = {}

	for key, value in queries.items():
		q[key] = value[0]

	q['mode'] = q.get('mode', 'main')
	return q

plugin_queries = None

try:
	plugin_queries = parse_query(sys.argv[2][1:])
except:
	plugin_queries = None

class settings:
	# Settings
	##
	##
	def __init__(self, addons):
		self.addon = addons
		self.username = self.getParameter('username', '')
		self.serverPort = self.getSettingInt('server_port', 8011)
		self.movieWatchTime = self.getSetting('movie_watch_time')
		self.tvWatchTime = self.getSetting('tv_watch_time')
		self.cryptoPassword = self.getSetting('crypto_password')
		self.cryptoSalt = self.getSetting('crypto_salt')

	def getParameter(self, key, default=''):

		try:
			value = plugin_queries[key]

			if value == 'true' or value == 'True':
				return True
			elif value == 'false' or value == 'False':
				return False
			else:
				return value

		except:
			return default

	def getParameterInt(self, key, default=0):

		try:

			value = plugin_queries[key]

			if value == 'true' or value == 'True':
				return True
			elif value == 'false' or value == 'False':
				return False
			else:
				return value

		except:
			return default

	def getSetting(self, key, default='', forceSync=False):

		try:
			value = self.addon.getSetting(key)

			if value == 'true' or value == 'True':
				return True
			elif value == 'false' or value == 'False':
				return False
			elif value is None:
				return default
			else:
				return value

		except:
			return default

	def getSettingInt(self, key, default=0):

		try:
			return int(self.addon.getSetting(key) )
		except:
			return default