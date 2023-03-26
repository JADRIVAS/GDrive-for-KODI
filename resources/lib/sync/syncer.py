import os

import xbmc

from . import cache
from .. import filesystem
from ..threadpool import threadpool


class Syncer:

	def __init__(self, accountManager, cloudService, encrypter, fileOperations, remoteFileProcessor, localFileProcessor, fileTree, settings):
		self.encrypter = encrypter
		self.cloudService = cloudService
		self.accountManager = accountManager
		self.remoteFileProcessor = remoteFileProcessor
		self.localFileProcessor = localFileProcessor
		self.fileTree = fileTree
		self.fileOperations = fileOperations
		self.settings = settings
		self.cache = cache.Cache()

	def sortChanges(self, changes):
		trashed, oldFolders, newFolders, files = [], [], [], []

		for change in changes:
			file = change["file"]

			if file["trashed"]:
				trashed.append(file)
				continue

			file["name"] = filesystem.helpers.removeProhibitedFSchars(file["name"])

			if file["mimeType"] == "application/vnd.google-apps.folder":
				cachedDirectory = self.cache.getDirectory(file["id"])

				if cachedDirectory:
					oldFolders.append(file)
				else:
					newFolders.append(file)

			else:
				files.append(file)

		return trashed + oldFolders + newFolders + files

	def syncChanges(self, driveID):
		account = self.accountManager.getAccount(driveID)
		self.cloudService.setAccount(account)
		self.cloudService.refreshToken()
		syncRootPath = self.cache.getSyncRootPath()
		driveSettings = self.cache.getDrive(driveID)
		drivePath = driveSettings["local_path"]
		changes, pageToken = self.cloudService.getChanges(driveSettings["page_token"])

		if not changes:
			return

		changes = self.sortChanges(changes)
		self.deleted = False
		newFiles = {}
		syncedIDs = []

		for file in changes:
			fileID = file["id"]

			if fileID in syncedIDs:
				continue

			syncedIDs.append(fileID)

			if file["trashed"]:
				self.syncDeletions(file, syncRootPath, drivePath)
				continue

			try:
				parentFolderID = file["parents"][0]
			except:
				parentFolderID = None

			if file["mimeType"] == "application/vnd.google-apps.folder":
				self.syncFolderChanges(file, parentFolderID, driveID, syncRootPath, drivePath, syncedIDs)
			else:
				self.syncFileChanges(file, parentFolderID, driveID, syncRootPath, drivePath, newFiles)

		if newFiles:
			self.syncFileAdditions(newFiles, syncRootPath, driveID)
			xbmc.executebuiltin(f"UpdateLibrary(video,{syncRootPath})")

		if self.deleted:

			if os.name == "nt":
				syncRootPath = syncRootPath.replace("\\", "\\\\")

			xbmc.executeJSONRPC('{"jsonrpc": "2.0", "id": 1, "method": "VideoLibrary.Clean", "params": {"showdialogs": false, "content": "video", "directory": "%s"}}' % syncRootPath)

		self.cache.updateDrive({"page_token": pageToken}, driveID)

	def syncDeletions(self, file, syncRootPath, drivePath):
		fileID = file["id"]
		cachedFiles = True

		if file["mimeType"] == "application/vnd.google-apps.folder":
			cachedFiles = self.cache.getFile(fileID, "parent_folder_id")
			folderID = fileID
		else:
			cachedFile = self.cache.getFile(fileID)
			self.cache.deleteFile(fileID)

			if cachedFile:
				folderID = cachedFile["parent_folder_id"]
				cachedDirectory = self.cache.getDirectory(folderID)
				cachedFiles = self.cache.getFile(folderID, "parent_folder_id")

				if cachedFile["original_folder"]:
					dirPath = os.path.join(syncRootPath, drivePath, cachedDirectory["local_path"])
					self.fileOperations.deleteFile(syncRootPath, dirPath, cachedFile["local_name"])
				else:
					filePath = os.path.join(syncRootPath, cachedFile["local_path"])
					self.fileOperations.deleteFile(syncRootPath, filePath=filePath)

		if not cachedFiles:
			self.cache.deleteDirectory(folderID)

		self.deleted = True

	def syncFolderChanges(self, folder, parentFolderID, driveID, syncRootPath, drivePath, syncedIDs):
		folderID = folder["id"]
		folderName = folder["name"]
		cachedDirectory = self.cache.getDirectory(folderID)

		if not cachedDirectory:
			# new folder added
			dirPath, rootFolderID = self.cloudService.getDirectory(self.cache, folderID)

			if not rootFolderID:
				return

			folderSettings = self.cache.getFolder(rootFolderID)
			self.syncFolderAdditions(syncRootPath, drivePath, dirPath, folderSettings, parentFolderID, folderID, rootFolderID, driveID, syncedIDs)
			return

		# existing folder
		cachedDirectoryPath = cachedDirectory["local_path"]
		cachedParentFolderID = cachedDirectory["parent_folder_id"]
		cachedRootFolderID = cachedDirectory["root_folder_id"]

		if parentFolderID != cachedParentFolderID and folderID != cachedRootFolderID:
			# folder has been moved into another directory
			dirPath, rootFolderID = self.cloudService.getDirectory(self.cache, folderID)

			if dirPath:
				syncedIDs.append(parentFolderID)
				self.cache.updateDirectory({"parent_folder_id": parentFolderID}, folderID)
				cachedDirectory = self.cache.getDirectory(parentFolderID)

				if not cachedDirectory:
					parentsParentFolderID = self.cloudService.getParentDirectoryID(parentFolderID)
					directory = {
						"drive_id": driveID,
						"folder_id": parentFolderID,
						"local_path": os.path.split(dirPath)[0],
						"parent_folder_id": parentsParentFolderID if parentsParentFolderID != driveID else parentsParentFolderID,
						"root_folder_id": rootFolderID,
					}
					self.cache.addDirectory(directory)

				oldPath = os.path.join(syncRootPath, drivePath, cachedDirectoryPath)
				newPath = os.path.join(syncRootPath, drivePath, dirPath)
				self.fileOperations.renameFolder(syncRootPath, oldPath, newPath)
				self.cache.updateChildPaths(cachedDirectoryPath, dirPath, folderID)
			else:
				# folder moved to another root folder != existing root folder - delete current folder
				drivePath = os.path.join(syncRootPath, drivePath)
				self.cache.cleanCache(syncRootPath, drivePath, folderID, self.fileOperations)
				self.deleted = True

			return

		cachedDirectoryPathHead, cachedFolderName = os.path.split(cachedDirectoryPath.rstrip(os.sep))

		if cachedFolderName != folderName:
			# folder renamed
			newDirectoryPath = os.path.join(cachedDirectoryPathHead, folderName)
			oldPath = os.path.join(syncRootPath, drivePath, cachedDirectoryPath)
			newPath = os.path.join(syncRootPath, drivePath, newDirectoryPath)
			self.fileOperations.renameFolder(syncRootPath, oldPath, newPath)
			self.cache.updateChildPaths(cachedDirectoryPath, newDirectoryPath, folderID)

			if folderID == cachedRootFolderID:
				self.cache.updateFolder({"local_path": newDirectoryPath}, cachedRootFolderID)

	def syncFileChanges(self, file, parentFolderID, driveID, syncRootPath, drivePath, newFiles):
		fileID = file["id"]
		cachedDirectory = self.cache.getDirectory(parentFolderID)
		cachedFile = self.cache.getFile(fileID)

		if not cachedDirectory:
			dirPath, rootFolderID = self.cloudService.getDirectory(self.cache, parentFolderID)

			if not rootFolderID:

				if cachedFile:
					# file has moved outside of root folder hierarchy/tree
					cachedParentFolderID = cachedFile["parent_folder_id"]
					cachedDirecory = self.cache.getDirectory(cachedParentFolderID)

					if cachedFile["original_folder"]:
						cachedFilePath = os.path.join(syncRootPath, drivePath, cachedDirecory["local_path"], cachedFile["local_name"])
					else:
						cachedFilePath = os.path.join(syncRootPath, cachedFile["local_path"])

					self.fileOperations.deleteFile(syncRootPath, filePath=cachedFilePath)
					self.cache.deleteFile(fileID)
					self.deleted = True

				return

			# file added to synced folder but the directory isn't present locally
			dirParentFolderID = self.cloudService.getParentDirectoryID(parentFolderID)
			directory = {
				"drive_id": driveID,
				"folder_id": parentFolderID,
				"local_path": dirPath,
				"parent_folder_id": dirParentFolderID if dirParentFolderID != driveID else parentFolderID,
				"root_folder_id": rootFolderID,
			}
			self.cache.addDirectory(directory)
		else:
			dirPath = cachedDirectory["local_path"]
			cachedParentFolderID = cachedDirectory["parent_folder_id"]
			rootFolderID = cachedDirectory["root_folder_id"]

		folderSettings = self.cache.getFolder(rootFolderID)
		excludedTypes = filesystem.helpers.getExcludedTypes(folderSettings)

		if folderSettings["contains_encrypted"]:
			encrypter = self.encrypter
		else:
			encrypter = None

		file = filesystem.helpers.makeFile(file, excludedTypes, encrypter)

		if not file:
			return

		filename = file.name

		if cachedFile:
			cachedParentFolderID = cachedFile["parent_folder_id"]
			cachedDirectory = self.cache.getDirectory(cachedParentFolderID)
			cachedDirPath = cachedDirectory["local_path"]
			rootFolderID = cachedDirectory["root_folder_id"]

			if cachedFile["original_folder"]:
				cachedFilePath = os.path.join(syncRootPath, drivePath, cachedDirPath, cachedFile["local_name"])
			else:
				cachedFilePath = os.path.join(syncRootPath, cachedFile["local_path"])

			if cachedFile["remote_name"] == filename and cachedDirPath == dirPath:
				# GDrive creates a change after a newly uploaded vids metadata has been processed

				if file.type != "video" or not file.metadata:
					return

				filesystem.helpers.refreshMetadata(file.metadata, cachedFilePath)
				return

			if cachedFile["original_name"]:

				if not os.path.exists(cachedFilePath):
					# file doesn't exist locally - redownload it
					self.cache.deleteFile(fileID)
					self.deleted = True
				else:
					# rename/move file
					filenameWithoutExt = os.path.splitext(filename)[0]
					fileExtension = os.path.splitext(cachedFile["local_name"])[1]
					newFilename = filenameWithoutExt + fileExtension

					if cachedFile["original_folder"]:
						dirPath = os.path.join(syncRootPath, drivePath, dirPath)
						self.fileOperations.renameFile(syncRootPath, cachedFilePath, dirPath, newFilename)
					else:
						newFilePath = self.fileOperations.renameFile(syncRootPath, cachedFilePath, os.path.dirname(cachedFilePath), newFilename)
						cachedFile["local_path"] = newFilePath

					cachedFile["local_name"] = newFilename
					cachedFile["remote_name"] = filename
					cachedFile["parent_folder_id"] = parentFolderID
					self.cache.updateFile(cachedFile, fileID)
					return

			else:
				# redownload file
				self.fileOperations.deleteFile(syncRootPath, filePath=cachedFilePath)
				self.cache.deleteFile(fileID)
				self.deleted = True

		if not newFiles.get(rootFolderID):
			newFiles[rootFolderID] = {}
			newFiles[rootFolderID][parentFolderID] = self.fileTree.getNode(parentFolderID, os.path.join(drivePath, dirPath))
		else:

			if not newFiles[rootFolderID].get(parentFolderID):
				newFiles[rootFolderID][parentFolderID] = self.fileTree.getNode(parentFolderID, os.path.join(drivePath, dirPath))

		if file.type in ("poster", "fanart", "subtitles", "nfo"):
			mediaAssets = newFiles[rootFolderID][parentFolderID]["files"]["media_assets"]

			if file.ptn_name not in mediaAssets:
				mediaAssets[file.ptn_name] = {
					"nfo": [],
					"subtitles": [],
					"fanart": [],
					"poster": [],
				}

			mediaAssets[file.ptn_name][file.type].append(file)
		else:
			newFiles[rootFolderID][parentFolderID]["files"][file.type].append(file)

	def syncFolderAdditions(self, syncRootPath, drivePath, dirPath, folderSettings, parentFolderID, folderID, rootFolderID, driveID, syncedIDs=None):

		if folderSettings["contains_encrypted"]:
			encrypter = self.encrypter
		else:
			encrypter = False

		excludedTypes = filesystem.helpers.getExcludedTypes(folderSettings)
		fileTree = self.fileTree.buildTree(folderID, dirPath, excludedTypes, encrypter, syncedIDs)
		args = []

		for folderID, folderInfo in fileTree.items():
			parentFolderID = folderInfo["parent_folder_id"]
			remotePath = folderInfo["path"]
			directoryPath = os.path.join(drivePath, remotePath)
			directory = {
				"drive_id": driveID,
				"folder_id": folderID,
				"local_path": remotePath,
				"parent_folder_id": parentFolderID,
				"root_folder_id": rootFolderID,
			}
			self.cache.addDirectory(directory)
			args.append((folderInfo["files"], folderSettings, directoryPath, syncRootPath, driveID, rootFolderID, folderID))

		with threadpool.ThreadPool(30) as pool:
			pool.map(self.remoteFileProcessor.processFiles, args)

		folderRestructure = folderSettings["folder_restructure"]
		fileRenaming = folderSettings["file_renaming"]

		if not folderRestructure and not fileRenaming:
			return

		with threadpool.ThreadPool(30) as pool:
			pool.map(self.localFileProcessor.processFiles, args)

	def syncFileAdditions(self, files, syncRootPath, driveID):
		data = {}

		for rootFolderID, directories in files.items():
			folderSettings = self.cache.getFolder(rootFolderID)
			folderRestructure = folderSettings["folder_restructure"]
			fileRenaming = folderSettings["file_renaming"]
			args = []

			for folderID, tree in directories.items():
				remotePath = tree["path"]
				args.append((tree["files"], folderSettings, remotePath, syncRootPath, driveID, rootFolderID, folderID))

			data[folderID] = {"args": args, "folder_restructure": folderRestructure, "file_renaming": fileRenaming}

		args = [data["args"][0] for data in data.values()]

		with threadpool.ThreadPool(30) as pool:
			pool.map(self.remoteFileProcessor.processFiles, args)

		args = [data["args"][0] for data in data.values() if data["file_renaming"] or data["folder_restructure"]]

		if not args:
			return

		with threadpool.ThreadPool(30) as pool:
			pool.map(self.localFileProcessor.processFiles, args)
