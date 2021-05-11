import sys
import xbmc
import threading
import constants
from resources.lib import settings
from resources.lib import streamer

try:
	plugin_handle = int(sys.argv[1])
	plugin_queries = settings.parse_query(sys.argv[2][1:])
except:
	plugin_handle = None
	plugin_queries = None

def run():
	addon = constants.addon
	settings_ = settings.settings(addon)
	user_agent = settings_.getSetting('user_agent')
	PLUGIN_URL = constants.PLUGIN_NAME
	PLUGIN_NAME = constants.PLUGIN_NAME

	port = settings_.getSettingInt('server_port', 8011)
	server = streamer.MyHTTPServer( ('', port), streamer.myStreamer)
	server.setDetails(plugin_handle, PLUGIN_NAME, PLUGIN_URL, addon, user_agent, settings_)

	monitor = xbmc.Monitor()

	thread = threading.Thread(None, server.run)
	thread.start()

	while not monitor.abortRequested():

		if monitor.waitForAbort(1):
			break

	server.socket.close()
	server.shutdown()
	thread.join()

# class KodiServer:

	# def __init__(self):
		# addon = constants.addon
		# settings_ = settings.settings(addon)
		# user_agent = settings_.getSetting('user_agent')
		# PLUGIN_URL = constants.PLUGIN_NAME
		# PLUGIN_NAME = constants.PLUGIN_NAME

		# port = settings_.getSettingInt('server_port', 8011)
		# server = streamer.MyHTTPServer( ('', port), streamer.myStreamer)
		# server.setDetails(plugin_handle, PLUGIN_NAME, PLUGIN_URL, addon, user_agent, settings_)

	# def terminate(self):
		# self.server.socket.close()
		# self.server.shutdown()