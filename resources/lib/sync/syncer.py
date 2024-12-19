import os

import xbmc

from .sync_cache_updater import SyncCacheUpdater
from ..filesystem.folder import Folder
from ..filesystem.file_tree import FileTree
from ..filesystem.file_maker import makeFile
from ..filesystem.fs_constants import MEDIA_ASSETS
from ..filesystem.fs_helpers import getExcludedTypes, removeProhibitedFSchars
from ..filesystem.file_processor import LocalFileProcessor, RemoteFileProcessor
from ..threadpool.threadpool import ThreadPool
from helpers import sendJSONRPCCommand


class Syncer:

	def __init__(self, accountManager, cloudService, encryptor, fileOperations, settings, cache):
		self.accountManager = accountManager
		self.cloudService = cloudService
		self.encryptor = encryptor
		self.fileOperations = fileOperations
		self.settings = settings
		self.cache = cache

	def syncChanges(self, driveID):
		account = self.accountManager.getAccount(driveID)

		if not account:
			return

		self.cloudService.setAccount(account)
		self.cloudService.refreshToken()
		driveSettings = self.cache.getDrive(driveID)
		syncRootPath = self.cache.getSyncRootPath()
		drivePath = os.path.join(syncRootPath, driveSettings["local_path"])
		changes, pageToken = self.cloudService.getChanges(driveSettings["page_token"])

		if not pageToken:
			return

		if not changes:
			return True

		changes = self._sortChanges(changes)
		self.deleted = False
		syncedIDs = []
		newFiles = {}

		for item in changes:
			id = item["id"]

			if id in syncedIDs:
				continue

			syncedIDs.append(id)

			try:
				# shared items that google automatically adds to an account don't have parentFolderIDs
				parentFolderID = item["parents"][0]
			except KeyError:
				continue

			if item["trashed"]:
				self._syncDeletions(item, syncRootPath, drivePath)
				continue

			if item["mimeType"] == "application/vnd.google-apps.folder":
				self._syncFolderChanges(item, parentFolderID, driveID, syncRootPath, drivePath, syncedIDs)
			else:
				self._syncFileChanges(item, parentFolderID, driveID, syncRootPath, drivePath, newFiles)

		if newFiles:
			self._syncFileAdditions(newFiles, syncRootPath)

			if self.settings.getSetting("update_library"):
				xbmc.executebuiltin(f"UpdateLibrary(video,{syncRootPath})")

		if self.deleted and self.settings.getSetting("update_library"):

			if os.name == "nt":
				syncRootPath = syncRootPath.replace("\\", "\\\\")

			query = {
				"jsonrpc": "2.0",
				"id": 1,
				"method": "VideoLibrary.Clean",
				"params": {"showdialogs": False, "content": "video", "directory": syncRootPath},
			}
			sendJSONRPCCommand(query)

		self.cache.updateDrive({"page_token": pageToken}, driveID)
		return True

	def syncFolderAdditions(self, syncRootPath, drivePath, folder, folderSettings, progressDialog=None, syncedIDs=None):
		syncRootPath = syncRootPath + os.sep
		excludedTypes = getExcludedTypes(folderSettings)
		driveID = folderSettings["drive_id"]
		folderRenaming = folderSettings["folder_renaming"]
		fileRenaming = folderSettings["file_renaming"]
		prefix = [p for p in folderSettings["strm_prefix"].split(", ") if p]
		suffix = [s for s in folderSettings["strm_suffix"].split(", ") if s]
		threadCount = self.settings.getSettingInt("thread_count", 1)
		encryptor = self.encryptor if folderSettings["contains_encrypted"] else None
		cacheUpdater = SyncCacheUpdater(self.cache)

		with RemoteFileProcessor(self.fileOperations, cacheUpdater, threadCount, progressDialog) as fileProcessor:
			fileTree = FileTree(fileProcessor, self.cloudService, self.cache, cacheUpdater, driveID, syncRootPath, drivePath, folderRenaming, fileRenaming, threadCount, encryptor, prefix, suffix, excludedTypes, syncedIDs)
			fileTree.buildTree(folder)

		if progressDialog:
			progressDialog.processFolder()

		if folderRenaming or fileRenaming:
			localFileProcessor = LocalFileProcessor(self.fileOperations, self.cache, syncRootPath, progressDialog)

			with ThreadPool(threadCount) as pool:

				for folder in fileTree:
					pool.submit(localFileProcessor.processFiles, folder, folderSettings, threadCount)

		for folder in fileTree:
			modifiedTime = folder.modifiedTime

			try:
				os.utime(folder.localPath, (modifiedTime, modifiedTime))
			except os.error:
				continue

	def _syncFileAdditions(self, files, syncRootPath):
		syncRootPath = syncRootPath + os.sep
		threadCount = self.settings.getSettingInt("thread_count", 1)
		cacheUpdater = SyncCacheUpdater(self.cache)
		folders = []

		with RemoteFileProcessor(self.fileOperations, cacheUpdater, threadCount) as fileProcessor:

			for rootFolderID, directories in files.items():
				folderSettings = self.cache.getFolder({"folder_id": rootFolderID})
				folderRenaming = folderSettings["folder_renaming"]
				fileRenaming = folderSettings["file_renaming"]

				for folderID, folder in directories.items():

					for files in folder.files.values():

						for file in files:
							fileProcessor.addFile((file, folder))

					if folderRenaming or fileRenaming:
						folders.append((folder, folderSettings))

		with ThreadPool(threadCount) as pool:
			localFileProcessor = LocalFileProcessor(self.fileOperations, self.cache, syncRootPath)

			for folder, folderSettings in folders:
				pool.submit(localFileProcessor.processFiles, folder, folderSettings, threadCount)

	def _syncDeletions(self, item, syncRootPath, drivePath):
		id = item["id"]
		cachedFiles = True

		if item["mimeType"] == "application/vnd.google-apps.folder":
			cachedFiles = self.cache.getFile({"parent_folder_id": id})
			folderID = id
		else:
			cachedFile = self.cache.getFile({"file_id": id})

			if not cachedFile:
				return

			self.cache.deleteFile(id)
			folderID = cachedFile["parent_folder_id"]
			cachedDirectory = self.cache.getDirectory({"folder_id": folderID})
			cachedFiles = self.cache.getFile({"parent_folder_id": folderID})

			if cachedFile["original_folder"]:
				dirPath = os.path.join(drivePath, cachedDirectory["local_path"])
				self.fileOperations.deleteFile(syncRootPath, dirPath, cachedFile["local_name"])
			else:
				filePath = os.path.join(syncRootPath, cachedFile["local_path"])
				self.fileOperations.deleteFile(syncRootPath, filePath=filePath)

		if not cachedFiles:
			cachedDirectory = self.cache.getDirectory({"folder_id": folderID})

			if not cachedDirectory:
				return

			self.cache.removeEmptyDirectories(cachedDirectory["root_folder_id"])

		self.deleted = True

	def _syncFileChanges(self, file, parentFolderID, driveID, syncRootPath, drivePath, newFiles):
		fileID = file["id"]
		cachedDirectory = self.cache.getDirectory({"folder_id": parentFolderID})
		cachedFile = self.cache.getFile({"file_id": fileID})

		if cachedDirectory:
			dirPath = cachedDirectory["local_path"]
			cachedParentFolderID = cachedDirectory["parent_folder_id"]
			rootFolderID = cachedDirectory["root_folder_id"]
		else:
			dirPath, rootFolderID = self.cloudService.getDirectory(self.cache, parentFolderID)

			if not rootFolderID and cachedFile:
				# file has moved outside of root folder hierarchy/tree > delete file
				cachedParentFolderID = cachedFile["parent_folder_id"]
				cachedDirectory = self.cache.getDirectory({"folder_id": cachedParentFolderID})

				if cachedFile["original_folder"]:
					cachedFilePath = os.path.join(drivePath, cachedDirectory["local_path"], cachedFile["local_name"])
				else:
					cachedFilePath = os.path.join(syncRootPath, cachedFile["local_path"])

				self.fileOperations.deleteFile(syncRootPath, filePath=cachedFilePath)
				self.cache.deleteFile(fileID)
				self.deleted = True
				return

			if not rootFolderID:
				return

			folderName = os.path.basename(dirPath)
			dirPath = self.cache.getUniqueDirectoryPath(driveID, dirPath)
			parentsParentFolderID = self.cloudService.getParentDirectoryID(parentFolderID)
			directory = {
				"drive_id": driveID,
				"folder_id": parentFolderID,
				"local_path": dirPath,
				"remote_name": folderName,
				"parent_folder_id": parentsParentFolderID if parentsParentFolderID != driveID else parentFolderID,
				"root_folder_id": rootFolderID,
			}
			self.cache.addDirectory(directory)

		folderSettings = self.cache.getFolder({"folder_id": rootFolderID})
		excludedTypes = getExcludedTypes(folderSettings)
		folderRenaming = folderSettings["folder_renaming"]
		prefix = [p for p in folderSettings["strm_prefix"].split(", ") if p]
		suffix = [s for s in folderSettings["strm_suffix"].split(", ") if s]
		encryptor = self.encryptor if folderSettings["contains_encrypted"] else None
		file = makeFile(file, excludedTypes, prefix, suffix, encryptor)

		if not file:
			return

		filename = file.remoteName

		if cachedFile:
			cachedDirectory = self.cache.getDirectory({"folder_id": cachedFile["parent_folder_id"]})
			cachedDirPath = cachedDirectory["local_path"]
			rootFolderID = cachedDirectory["root_folder_id"]

			if cachedFile["original_folder"]:
				cachedFilePath = os.path.join(drivePath, cachedDirPath, cachedFile["local_name"])
			else:
				cachedFilePath = os.path.join(syncRootPath, cachedFile["local_path"])

			if cachedFile["remote_name"] == filename and cachedDirPath == dirPath:
				modifiedTime = file.modifiedTime

				if file.type == "video":

					if cachedFile["has_metadata"] and modifiedTime == cachedFile["modified_time"]:
						return
					elif file.metadata.get("video_duration"):
						# GDrive creates a change after a newly uploaded vids metadata has been processed
						file.updateDB = True

				elif modifiedTime == cachedFile["modified_time"]:
					return

				# file contents modified > redownload file
				self.fileOperations.deleteFile(syncRootPath, filePath=cachedFilePath)
				self.cache.deleteFile(fileID)
				self.deleted = True
			elif not cachedFile["original_name"] or not cachedFile["original_folder"] or not os.path.exists(cachedFilePath):
				# new filename needs to be processed or file not existent > redownload file
				self.fileOperations.deleteFile(syncRootPath, filePath=cachedFilePath)
				self.cache.deleteFile(fileID)
				self.deleted = True
			else:
				# file either moved or renamed
				newFilename = file.basename + os.path.splitext(cachedFile["local_name"])[1]

				if cachedFile["original_folder"]:
					dirPath = os.path.join(drivePath, dirPath)
					newFilePath = self.fileOperations.renameFile(syncRootPath, cachedFilePath, dirPath, newFilename)
				else:
					newFilePath = self.fileOperations.renameFile(syncRootPath, cachedFilePath, os.path.dirname(cachedFilePath), newFilename)
					cachedFile["local_path"] = newFilePath

				cachedFile["local_name"] = os.path.basename(newFilePath)
				cachedFile["remote_name"] = filename
				cachedFile["parent_folder_id"] = parentFolderID
				self.cache.updateFile(cachedFile, fileID)
				return

		folder = newFiles.setdefault(rootFolderID, {}).setdefault(parentFolderID, Folder(parentFolderID, parentFolderID, rootFolderID, driveID, dirPath, dirPath, os.path.join(drivePath, dirPath), syncRootPath, folderRenaming))
		files = folder.files

		if file.type in MEDIA_ASSETS:
			files["media_asset"].append(file)
		else:
			files[file.type].append(file)

	def _syncFolderChanges(self, folder, parentFolderID, driveID, syncRootPath, drivePath, syncedIDs):
		folderID = folder["id"]
		folderName = folder["name"]
		cachedDirectory = self.cache.getDirectory({"folder_id": folderID})

		if not cachedDirectory:
			# new folder added
			dirPath, rootFolderID = self.cloudService.getDirectory(self.cache, folderID)

			if not rootFolderID:
				return

			folderSettings = self.cache.getFolder({"folder_id": rootFolderID})
			modifiedTime = folder["modifiedTime"]
			dirPath = self.cache.getUniqueDirectoryPath(driveID, dirPath)
			folder = Folder(folderID, parentFolderID, rootFolderID, driveID, folderName, dirPath, os.path.join(drivePath, dirPath), syncRootPath, folderSettings["folder_renaming"], modifiedTime=modifiedTime)
			self.syncFolderAdditions(syncRootPath, drivePath, folder, folderSettings, syncedIDs=syncedIDs)
			return

		# existing folder
		cachedDirectoryPath = cachedDirectory["local_path"]
		cachedParentFolderID = cachedDirectory["parent_folder_id"]
		cachedRootFolderID = cachedDirectory["root_folder_id"]
		cachedRemoteName = cachedDirectory["remote_name"]

		if parentFolderID != cachedParentFolderID and folderID != cachedRootFolderID:
			# folder has been moved into another directory
			dirPath, rootFolderID = self.cloudService.getDirectory(self.cache, folderID)

			if not dirPath:
				# folder has moved outside of root folder hierarchy/tree > delete folder
				self.cache.removeDirectory(syncRootPath, drivePath, folderID)
				self.deleted = True
			else:
				self.cache.updateDirectory({"parent_folder_id": parentFolderID}, folderID)
				cachedParentDirectory = self.cache.getDirectory({"folder_id": parentFolderID})

				if cachedParentDirectory:
					dirPath = self.cache.getUniqueDirectoryPath(driveID, dirPath)
				else:
					parentDirPath = os.path.split(dirPath)[0]
					parentFolderName = os.path.basename(parentDirPath)
					parentDirPath = self.cache.getUniqueDirectoryPath(driveID, parentDirPath)
					dirPath = os.path.join(parentDirPath, folderName)
					dirPath = self.cache.getUniqueDirectoryPath(driveID, dirPath)
					parentsParentFolderID = self.cloudService.getParentDirectoryID(parentFolderID)
					directory = {
						"drive_id": driveID,
						"folder_id": parentFolderID,
						"local_path": parentDirPath,
						"remote_name": parentFolderName,
						"parent_folder_id": parentsParentFolderID if parentsParentFolderID != driveID else parentFolderID,
						"root_folder_id": rootFolderID,
					}
					self.cache.addDirectory(directory)

				oldPath = os.path.join(drivePath, cachedDirectoryPath)
				newPath = os.path.join(drivePath, dirPath)
				self.fileOperations.renameFolder(syncRootPath, oldPath, newPath)
				self.cache.updateChildPaths(cachedDirectoryPath, dirPath, folderID)

		elif cachedRemoteName != folderName:
			# folder renamed
			cachedDirectoryPathHead, _ = os.path.split(cachedDirectoryPath)
			newDirectoryPath = os.path.join(cachedDirectoryPathHead, folderName)
			newDirectoryPath = self.cache.getUniqueDirectoryPath(driveID, newDirectoryPath, folderID)
			oldPath = os.path.join(drivePath, cachedDirectoryPath)
			newPath = os.path.join(drivePath, newDirectoryPath)
			self.fileOperations.renameFolder(syncRootPath, oldPath, newPath)
			self.cache.updateChildPaths(cachedDirectoryPath, newDirectoryPath, folderID)
			self.cache.updateDirectory({"remote_name": folderName}, folderID)

			if folderID == cachedRootFolderID:
				self.cache.updateFolder({"local_path": newDirectoryPath, "remote_name": folderName}, folderID)

	def _sortChanges(self, changes):
		trashed, existingFolders, newFolders, files = [], [], [], []

		for change in changes:
			item = change["file"]

			if item["trashed"]:
				trashed.append(item)
				continue

			item["name"] = removeProhibitedFSchars(item["name"])

			if item["mimeType"] == "application/vnd.google-apps.folder":
				cachedDirectory = self.cache.getDirectory({"folder_id": item["id"]})

				if cachedDirectory:
					existingFolders.append(item)
				else:
					newFolders.append(item)

			else:
				files.append(item)

		return trashed + existingFolders + newFolders + files
