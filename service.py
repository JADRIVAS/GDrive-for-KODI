import xbmc

from resources.lib.network.server import ServerRunner
from resources.lib.library.monitor import LibraryMonitor


if __name__ == "__main__":
	monitor = xbmc.Monitor()
	libaryMonitor = LibraryMonitor()
	server = ServerRunner()
	server.start()

	while not monitor.abortRequested():

		if monitor.waitForAbort(0.1):
			break

	server.shutdown()
