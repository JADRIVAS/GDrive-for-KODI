from threading import Thread

import xbmc

import constants
from resources.lib import streamer, watcher

if __name__ == "__main__":
	monitor = xbmc.Monitor()
	watcher = watcher.LibraryMonitor()
	server = streamer.MyHTTPServer(constants.settings)
	Thread(target=server.run, daemon=True).start()

	while not monitor.abortRequested():

		if monitor.waitForAbort(1):
			break

	server.shutdown()
