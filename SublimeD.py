import sublime
import sublime_plugin
import subprocess
import json
import time
import os
import os.path
from threading import Thread

instance = str(int(time.time()))

targetVersion = [2, 7, 2]

def debugOutput(stderr, workspaced):
	while workspaced.running:
		line = stderr.readline()
		if line:
			print("workspace-d Debug: " + str(line))

def workspacedOutput(stdout, workspaced):
	while workspaced.running:
		data = os.read(stdout.fileno(), 4096)
		workspaced.putChunk(data)

def formatVersion(version):
	return str(version[0]) + "." + str(version[1]) + "." + str(version[2])

class WorkspaceD:
	def start(self, window, folder):
		print("Starting workspace-d in folder " + folder)
		self.dubReady = False

		self.window = window
		self.projectRoot = folder
		self.running = True
		self.process = subprocess.Popen(["workspace-d"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

		self.stderrThread = Thread(target=debugOutput, args=(self.process.stderr, self))
		self.stdoutThread = Thread(target=workspacedOutput, args=(self.process.stdout, self))

		self.stderrThread.daemon = True
		self.stdoutThread.daemon = True
		self.stderrThread.start()
		self.stdoutThread.start()

		self.requestNum = 0
		self.callbacks = {}

		def printVersion(err, data):
			if err:
				print("Error!", err)
			else:
				major = data["major"]
				minor = data["minor"]
				patch = data["patch"]
				if major < targetVersion[0]:
					sublime.error_message("workspace-d is outdated! Please update to continue using this plugin. (target=" + formatVersion(targetVersion) + ", workspaced=" + formatVersion([major, minor, patch]) + ")")
					return
				if major == targetVersion[0] and minor < targetVersion[1]:
					sublime.error_message("workspace-d might be outdated! Please update if things are not working as expected. (target=" + formatVersion(targetVersion) + ", workspaced=" + formatVersion([major, minor, patch]) + ")")
				self.setupDub()
		self.request({"cmd":"version"}, printVersion)

		self.buffer = b""

	def request(self, data, callback=None):
		dataStr = json.dumps(data).encode("utf-8")
		lengthBuf = (len(dataStr) + 4).to_bytes(4, byteorder="big")
		self.requestNum += 1
		reqID = self.requestNum
		idBuf = (reqID).to_bytes(4, byteorder="big")
		if callback != None:
			self.callbacks[reqID] = callback
		self.process.stdin.write(lengthBuf + idBuf + dataStr)
		self.process.stdin.flush()

	def putChunk(self, chunk):
		self.buffer += chunk
		while self.processMessage():
			pass

	def dubPackageDescriptorExists(self):
		return os.path.isfile(os.path.join(self.projectRoot, "dub.json")) or\
			os.path.isfile(os.path.join(self.projectRoot, "dub.sdl")) or\
			os.path.isfile(os.path.join(self.projectRoot, "package.json"))

	def setupDub(self):
		if self.window.active_view().settings().get("d_disable_dub", False):
			self.setupCustomWorkspace()
			return

		if self.dubPackageDescriptorExists():
			def dubCallback(err, data):
				if err:
					sublime.error_message("Could not initialize dub. See console for details!")
					return
				print("dub is ready")
				self.dubReady = True

				self.setupDCD()
				self.setupDScanner()
			self.request({"cmd": "load", "components": ["dub"], "dir": self.projectRoot}, dubCallback)
		else:
			self.setupCustomWorkspace()

	def setupCustomWorkspace(self):
		paths = self.window.folders()
		rootDir = paths[0]
		addPaths = []
		if len(paths) > 1:
			addPaths = paths[1:]
		def fsworkspaceCallback(err, data):
			if err:
				sublime.error_message("Could not initialize fsworkspace. See console for details!")
				return
			print("fsworkspace is ready")
		this.request({"cmd": "load", "components": ["fsworkspace"], "dir": rootDir, "additionalPaths": addPaths}, fsworkspaceCallback)

	def processMessage(self):
		if len(self.buffer) < 8:
			return False
		length = int.from_bytes(self.buffer[0:4], byteorder="big")
		if len(self.buffer) >= length + 4:
			reqID = int.from_bytes(self.buffer[4:8], byteorder="big")
			jsonStr = self.buffer[8:length + 4].decode("utf-8")
			data = json.loads(jsonStr)
			self.buffer = self.buffer[length + 4:]
			if type(data) == dict and "error" in data:
				print(data)
				if reqID in self.callbacks:
					self.callbacks[reqID](data, None)
				else:
					print("Uncaught workspace-d error response")
					print(data)
			else:
				if reqID in self.callbacks:
					self.callbacks[reqID](None, data)
			return True
		return False

	def setupDScanner(self):
		def dscannerCallback(err, data):
			if err:
				sublime.error_message("Could not initialize DScanner. See console for details!")
				return
			print("DScanner is ready")
		self.request({
			"cmd": "load",
			"components": ["dscanner"],
			"dir": self.projectRoot,
			"dscannerPath": "dscanner"
		}, dscannerCallback)

	def setupDCD(self):
		if self.window.active_view().settings().get("d_disable_dcd", False):
			return

		def dcdCallback(err, data):
			if err:
				sublime.error_message("Could not initialize DCD. See console for details!")
				return
			self.startDCD()

		self.request({
			"cmd": "load",
			"components": ["dcd"],
			"dir": self.projectRoot,
			"autoStart": False,
			"clientPath": "dcd-client",
			"serverPath": "dcd-server"
		}, dcdCallback)

	def startDCD(self):
		def dcdCallback(err, data):
			if err:
				sublime.error_message("Could not initialize DCD. See console for details!")
				return

			def serverCallback(err2, data):
				if err2:
					sublime.error_message("Could not initialize DCD. See console for details!")
					return
				def importRefreshCallback(err3, data3):
					if err3:
						sublime.error_message("Could not initialize DCD. See console for details!")
						return
					def importCallback(err4, imports):
						print(imports)
						print("Loaded completions for", len(imports), "import paths")
					self.listImports(importCallback)
				print("DCD is ready")
				self.dcdReady = True
				self.request({
					"cmd": "dcd",
					"subcmd": "refresh-imports"
				}, importRefreshCallback)

			self.request({
				"cmd": "dcd",
				"subcmd": "start-server"
			}, serverCallback)

		self.request({
			"cmd": "dcd",
			"subcmd": "find-and-select-port",
			"port": 9166
		}, dcdCallback)

	def listImports(self, callback):
		if not self.dubReady:
			callback(None, [])
			return
		self.request({"cmd": "dub", "subcmd": "list:import"}, callback)

	def onClosed(self):
		self.running = False

	def stop(self):
		self.running = False
		self.process.terminate()

workspaced = {}

class WorkspaceDCompletion(sublime_plugin.EventListener):
	def on_query_completions(self, view, prefix, locations):
		filename = view.file_name()
		window = view.window()
		instance = get_workspaced(filename, window)
		if not instance:
			return None
		completions = []
		location = locations[0]
		offset = location
		completionDone = False
		def completionCallback(err, data):
			nonlocal completions
			nonlocal completionDone
			completionDone = True
			if err:
				return
			if (data["type"] == "identifiers"):
				for element in data["identifiers"]:
					completion = element["identifier"]
					detail = element["type"]
					completions += [[completion + "\t" + detail, completion]]
		instance.request({
			"cmd": "dcd",
			"subcmd": "list-completion",
			"code": view.substr(sublime.Region(0, view.size())),
			"pos": offset
		}, completionCallback)
		startTime = time.time()
		while not completionDone:
			if time.time() - startTime < 0.05: # at least run at 20 fps if completion isnt working
				continue
			else:
				break
		return completions, sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS

	def on_hover(self, view, point, hover_zone):
		filename = view.file_name()
		window = view.window()
		if hover_zone == sublime.HOVER_TEXT:
			instance = get_workspaced(filename, window)
			if not instance:
				return
			def hoverCallback(err, documentation):
				if err:
					return
				view.show_popup(documentation.replace("\n", "<br>"), sublime.COOPERATE_WITH_AUTO_COMPLETE | sublime.HIDE_ON_MOUSE_MOVE_AWAY, point)
			instance.request({
				"cmd": "dcd",
				"subcmd": "get-documentation",
				"code": view.substr(sublime.Region(0, view.size())),
				"pos": point
			}, hoverCallback)

	def on_modified_async(self, view):
		position = view.sel()[0].begin()
		typedChar = view.substr(position - 1)
		if typedChar == "(" or typedChar == ",":
			filename = view.file_name()
			window = view.window()
			instance = get_workspaced(filename, window)
			if not instance:
				return
			filename = view.file_name()
			window = view.window()
			def calltipCallback(err, data):
				if err:
					return
				if (data["type"] == "calltips"):
					calltips = data["calltips"]
					view.show_popup("<br>".join(calltips), sublime.COOPERATE_WITH_AUTO_COMPLETE, position)
			print("calltips")
			instance.request({
				"cmd": "dcd",
				"subcmd": "list-completion",
				"code": view.substr(sublime.Region(0, view.size())),
				"pos": position
			}, calltipCallback)
		if typedChar == ")":
			view.hide_popup()

def get_workspaced(filename, window, ignoreFolder = False):
	if filename[-2:] == ".d":
		for folder in window.folders():
			if folder in workspaced:
				if (ignoreFolder or filename.startswith(folder)):
					return workspaced[folder]
	return None

class SublimedGotoDefinitionCommand(sublime_plugin.TextCommand):
	def run(self, edit):
		print("Goto Definition")
		filename = self.view.file_name()
		window = self.view.window()
		instance = get_workspaced(filename, window)
		if not instance:
			return
		point = self.view.sel()[0].begin()
		def definitionCallback(err, declaration):
			if err:
				return
			if declaration[0] == "stdin":
				declaration[0] = self.view.file_name()
			targetView = window.find_open_file(declaration[0])
			if targetView == None:
				targetView = window.open_file(declaration[0], sublime.TRANSIENT)
			def jumpTo():
				targetView.show_at_center(declaration[1])
				targetView.sel().clear()
				targetView.sel().add(sublime.Region(declaration[1], declaration[1]))
			sublime.set_timeout(jumpTo, 100)
		instance.request({
			"cmd": "dcd",
			"subcmd": "find-declaration",
			"code": self.view.substr(sublime.Region(0, self.view.size())),
			"pos": point
		}, definitionCallback)

class SublimedOutlineDocumentCommand(sublime_plugin.TextCommand):
	def run(self, edit):
		print("Outline Document")
		filename = self.view.file_name()
		window = self.view.window()
		instance = get_workspaced(filename, window, True)
		if not instance:
			return
		point = self.view.sel()[0].begin()
		def outlineCallback(err, definitions):
			if err:
				return
			items = []
			lines = []

			for element in sorted(definitions, key=lambda e: e["line"]):
				container = None
				if "attributes" in element:
					if "struct" in element["attributes"]:
						container = element["attributes"]["struct"]
					if "class" in element["attributes"]:
						container = element["attributes"]["class"]
					if "enum" in element["attributes"]:
						container = element["attributes"]["enum"]
					if "union" in element["attributes"]:
						container = element["attributes"]["union"]
				label = element["name"]
				if "signature" in element:
					label += element["signature"]
				if container:
					label = container + ":  " + label
				label = element["type"] + "\t" + label
				items += [label]
				lines += [element["line"] - 1]

			origPos = self.view.viewport_position()
			origSel = list(self.view.sel())

			def onDone(index):
				if index == -1:
					self.view.set_viewport_position(origPos, False)
					self.view.sel().clear()
					self.view.sel().add_all(origSel)

			def previewSelection(index):
				point = self.view.text_point(lines[index], 0)
				line = self.view.line(point)
				self.view.sel().clear()
				self.view.sel().add(line)
				self.view.show_at_center(point)

			window.show_quick_panel(items, onDone, sublime.MONOSPACE_FONT, 0, previewSelection)
		instance.request({
			"cmd": "dscanner",
			"subcmd": "list-definitions",
			"file": filename
		}, outlineCallback)

def plugin_loaded():
	window = sublime.active_window()
	if window.active_view().settings().get("d", False):
		start_sublimed(window)

def start_sublimed(window):
	global workspaced
	for folder in window.folders():
		if folder in workspaced:
			continue
		workspaced[folder] = WorkspaceD()
		workspaced[folder].start(window, folder)

def plugin_unloaded():
	for key in workspaced:
		workspaced[key].stop()