# -*- coding: utf-8 -*-
#
#   Copyright (C) 2021 Team OpenSPA
#   https://openspa.info/
#
#   SPDX-License-Identifier: GPL-2.0-or-later
#   See LICENSES/README.md for more information.
#
#   PlutoTV is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   PlutoTV is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with PlutoTV.  If not, see <http://www.gnu.org/licenses/>.
#


# for localized messages
from . import _, PluginLanguageDomain
from .PlutoDownload import plutoRequest, PlutoDownload, Silent, getselectedcountries, PiconFetcher  # , getClips
from .Variables import RESUMEPOINTS_FILE, TIMER_FILE, PLUGIN_FOLDER, BOUQUET_FILE, NUMBER_OF_LIVETV_BOUQUETS, PLUGIN_ICON

from skin import applySkinFactor, fonts, parameters

from Components.ActionMap import ActionMap, HelpableActionMap
from Components.AVSwitch import AVSwitch
from Components.config import config, ConfigSelection
from Components.Label import Label
from Components.MenuList import MenuList
from Components.MultiContent import MultiContentEntryText, MultiContentEntryPixmapAlphaBlend
from Components.Pixmap import Pixmap
from Components.ScrollLabel import ScrollLabel
from Components.ServiceEventTracker import ServiceEventTracker
from Components.Sources.StaticText import StaticText
from Plugins.Plugin import PluginDescriptor
from Screens.HelpMenu import HelpableScreen
from Screens.InfoBar import MoviePlayer
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.Setup import Setup
from Tools.Directories import fileExists, isPluginInstalled, resolveFilename, SCOPE_CURRENT_SKIN
from Components.Harddisk import harddiskmanager
from Tools.Hex2strColor import Hex2strColor
from Tools.LoadPixmap import LoadPixmap
from Tools import Notifications

from enigma import BT_KEEP_ASPECT_RATIO, BT_SCALE, eListboxPythonMultiContent, ePicLoad, eServiceReference, eTimer, gFont, iPlayableService

import os
from gettext import dngettext
from pickle import load as pickle_load, dump as pickle_dump
import re
from time import time, strftime, gmtime, localtime
from urllib.parse import quote

from twisted.internet import threads  # for fetching posters
import requests

DATA_FOLDER = ""


class MountChoices:
	def __init__(self):
		choices = self.getMountChoices()
		config.plugins.plutotv.datalocation = ConfigSelection(choices=choices, default=self.getMountDefault(choices))
		harddiskmanager.on_partition_list_change.append(MountChoices.__onPartitionChange)  # to update data location choices on mountpoint change
		config.plugins.plutotv.datalocation.addNotifier(MountChoices.updateDataFolder, immediate_feedback=False)

	@staticmethod
	def getMountChoices():
		choices = []
		for p in harddiskmanager.getMountedPartitions():
			if os.path.exists(p.mountpoint):
				d = os.path.normpath(p.mountpoint)
				if p.mountpoint != "/":
					choices.append((p.mountpoint, d))
		choices.sort()
		return choices

	@staticmethod
	def getMountDefault(choices):
		choices = {x[1]: x[0] for x in choices}
		default = choices.get("/media/hdd") or choices.get("/media/usb") or ""
		return default

	@staticmethod
	def __onPartitionChange(*args, **kwargs):
		choices = MountChoices.getMountChoices()
		config.plugins.plutotv.datalocation.setChoices(choices=choices, default=MountChoices.getMountDefault(choices))
		MountChoices.updateDataFolder()

	@staticmethod
	def updateDataFolder(*args, **kwargs):
		global DATA_FOLDER
		DATA_FOLDER = ""
		if v := config.plugins.plutotv.datalocation.value:
			if os.path.exists(v):
				DATA_FOLDER = os.path.join(config.plugins.plutotv.datalocation.value, "PlutoTV")
				os.makedirs(DATA_FOLDER, exist_ok=True)  # create data folder if not exists


MountChoices()


class ResumePoints():
	# We can't use the ResumePoints class built in to enigma because
	# the id's are hashes, not srefs, so would be deleted on reboot.
	def __init__(self):
		self.resumePointFile = RESUMEPOINTS_FILE
		self.resumePointCache = {}
		self.loadResumePoints()
		self.cleanCache()  # get rid of stale entries on reboot

	def loadResumePoints(self):
		self.resumePointCache.clear()
		if fileExists(self.resumePointFile):
			with open(self.resumePointFile, "rb") as f:
				self.resumePointCache.update(pickle_load(f, encoding="utf8"))

	def saveResumePoints(self):
		os.makedirs(os.path.dirname(self.resumePointFile), exist_ok=True)  # create config folder recursive if not exists
		with open(self.resumePointFile, "wb") as f:
			pickle_dump(self.resumePointCache, f, protocol=5)

	def setResumePoint(self, session, sid):
		service = session.nav.getCurrentService()
		ref = session.nav.getCurrentlyPlayingServiceOrGroup()
		if service and ref:
			seek = service.seek()
			if seek:
				pos = seek.getPlayPosition()
				if not pos[0]:
					lru = int(time())
					duration = sl[1] if (sl := seek.getLength()) else None
					position = pos[1]
					self.resumePointCache[sid] = [lru, position, duration]
					self.saveResumePoints()

	def getResumePoint(self, sid):
		last = None
		length = 0
		if sid and (entry := self.resumePointCache.get(sid)):
			entry[0] = int(time())  # update LRU timestamp
			last = entry[1]
			length = entry[2]
		return last, length

	def cleanCache(self):
		changed = False
		now = int(time())
		for sid, v in list(self.resumePointCache.items()):
			if now > v[0] + 30 * 24 * 60 * 60:  # keep resume points a maximum of 30 days
				del self.resumePointCache[sid]
				changed = True
		if changed:
			self.saveResumePoints()


resumePointsInstance = ResumePoints()


class DownloadPosters:
	def __init__(self):
		if not DATA_FOLDER:
			return
		os.makedirs(DATA_FOLDER, exist_ok=True)  # create data folder if not exists

	def downloadURL(self, url, name, callback):
		success = False
		if not name or not DATA_FOLDER:
			return
		filename = os.path.join(DATA_FOLDER, name)
		if fileExists(filename):
			success = True
		else:
			try:
				response = requests.get(url, timeout=2.50, headers={"User-Agent": "Mozilla/5.0 (Windows NT 6.2; rv:24.0) Gecko/20100101 Firefox/24.0"})
				response.raise_for_status()
				content_type = response.headers.get('content-type')
				if content_type and content_type.lower() == 'image/jpeg' and len(rc := response.content):
					with open(filename, "wb") as f:
						f.write(rc)
						success = True
			except requests.exceptions.RequestException:
				pass
		if success:
			threads.deferToThread(callback, filename, name)


class PlutoList(MenuList):
	def __init__(self, list):
		self.menu_png = LoadPixmap(x if fileExists(x := resolveFilename(SCOPE_CURRENT_SKIN, "icons/pluto_menu.png")) else f"{PLUGIN_FOLDER}/images/menu.png")
		self.series_png = LoadPixmap(x if fileExists(x := resolveFilename(SCOPE_CURRENT_SKIN, "icons/pluto_series.png")) else f"{PLUGIN_FOLDER}/images/series.png")
		self.cine_png = LoadPixmap(x if fileExists(x := resolveFilename(SCOPE_CURRENT_SKIN, "icons/pluto_cine.png")) else f"{PLUGIN_FOLDER}/images/cine.png")
		self.cine_half_png = LoadPixmap(x if fileExists(x := resolveFilename(SCOPE_CURRENT_SKIN, "icons/pluto_cine_half.png")) else f"{PLUGIN_FOLDER}/images/cine_half.png")
		self.cine_end_png = LoadPixmap(x if fileExists(x := resolveFilename(SCOPE_CURRENT_SKIN, "icons/pluto_cine_end.png")) else f"{PLUGIN_FOLDER}/images/cine_end.png")

		MenuList.__init__(self, list, content=eListboxPythonMultiContent)
		font = fonts.get("PlutoList", applySkinFactor("Regular", 19, 35))
		self.l.setFont(0, gFont(font[0], font[1]))
		self.l.setItemHeight(font[2])

	def listentry(self, name, data, _id, epid=0):
		res = [(name, data, _id, epid)]

		png = None
		if data == "menu":
			png = self.menu_png
		elif data in ("series", "seasons"):
			png = self.series_png
		elif data in ("movie", "episode"):
			png = self.cine_png
			if data == "episode":
				sid = epid
			else:
				sid = _id
			last, length = resumePointsInstance.getResumePoint(sid)
			if last:
				if self.cine_half_png and (last > 900000) and (not length or (last < length - 900000)):
					png = self.cine_half_png
				elif self.cine_end_png and last >= length - 900000:
					png = self.cine_end_png

		res.append(MultiContentEntryText(pos=applySkinFactor(45, 7), size=applySkinFactor(533, 35), font=0, text=name))
		if png:
			res.append(MultiContentEntryPixmapAlphaBlend(pos=applySkinFactor(7, 9), size=applySkinFactor(20, 20), png=png, flags=BT_SCALE | BT_KEEP_ASPECT_RATIO))
		return res


class PlutoTV(Screen, HelpableScreen):
	skin = f"""
		<screen name="PlutoTV" zPosition="2" position="0,0" resolution="1920,1080" size="1920,1080" flags="wfNoBorder" title="Pluto TV" transparent="0">
			<ePixmap pixmap="{PLUGIN_FOLDER}/images/plutotv-backdrop.jpg" position="0,0" size="1920,1080" zPosition="-2" alphatest="blend" />
			<ePixmap position="70,30" size="1780,90" pixmap="{PLUGIN_FOLDER}/images/transblack.png" zPosition="1" alphatest="blend" transparent="1" cornerRadius="12"/><!-- header background -->
			<ePixmap pixmap="{PLUGIN_FOLDER}/images/logo.png" position="70,30" size="486,90" zPosition="5" alphatest="blend" transparent="1" scale="1"/>
			<widget source="global.CurrentTime" render="Label" position="e-400,48" size="300,55" font="Regular; 43" halign="right" zPosition="5" backgroundColor="#00000000" transparent="1">
				<convert type="ClockToText">Format:%H:%M</convert>
			</widget>

			<widget name="loading" position="center,center" size="800,60" font="Regular;50" backgroundColor="#00000000" transparent="0" zPosition="10" halign="center" valign="center" />
			<widget source="playlist" render="Label" position="400,48" size="1150,55" font="Regular;40" backgroundColor="#00000000" transparent="5" foregroundColor="#00ffff00" zPosition="2" halign="center" />
			<ePixmap position="70,170" size="615,745" pixmap="extensions/transblack.png" zPosition="1" alphatest="blend" transparent="1"/><!-- list background -->
			<widget name="feedlist" position="70,170" size="615,728" scrollbarMode="showOnDemand" enableWrapAround="1" transparent="1" zPosition="5" foregroundColor="#00ffffff" backgroundColorSelected="#00ff0063" backgroundColor="#00000000" />
			<widget source="vtitle" render="Pixmap" pixmap="{PLUGIN_FOLDER}/images/transblack.png" position="685,170" size="1165,745" zPosition="0" transparent="1" alphatest="blend"><!-- background for all info -->
				<convert type="ConditionalShowHide"/>
			</widget>
			<widget source="vtitle" render="Label" position="778,180" size="1065,48" font="Regular;35" backgroundColor="#00000000" foregroundColor="#00ffff00" zPosition="3" transparent="1" />
			<widget name="poster" position="735,235" size="483,675" zPosition="3" alphatest="blend" />
			<widget name="info" position="1238,235" size="604,675" font="Regular;28" backgroundColor="#00000000" foregroundColor="#00ffffff" zPosition="3" transparent="1" />

			<widget source="updated" render="Pixmap" pixmap="extensions/transblack.png" position="70,950" size="615,50" zPosition="1" transparent="1" alphatest="blend"><!-- updated background -->
				<convert type="ConditionalShowHide"/>
			</widget>
			<widget source="updated" render="Label" position="70,950" size="615,50" font="Regular;25" zPosition="5" transparent="1" valign="center" halign="center"/>

			<ePixmap position="0,e-60" size="1920,60" pixmap="{PLUGIN_FOLDER}/images/transblack.png" zPosition="1" alphatest="blend" transparent="1" cornerRadius="12"/><!-- key background -->
			<widget addon="ColorButtonsSequence" connection="key_red,key_green,key_yellow,key_blue"
				textColors="key_red:#00ff0808,key_green:#0004c81b,key_yellow:#00edf506,key_blue:#00077cf5"
				position="224,1030" size="1694,42" font="Regular;33" backgroundColor="#00000000" transparent="1" alignment="left" zPosition="10" spacing="10" />
			<ePixmap pixmap="buttons/key_menu.png" alphatest="blend" position="30,1031" size="52,38" backgroundColor="#00000000" transparent="1" zPosition="2"/>
		</screen>"""

	def __init__(self, session):
		self.session = session
		Screen.__init__(self, session)
		HelpableScreen.__init__(self)

		self.colors = parameters.get("PlutoTvColors", [])  # First item must be default text colour. If parameter is missing adding colours will be skipped.

		self.downloadPosters = DownloadPosters()
		self.titlemenu = _("VOD Menu")
		self["feedlist"] = PlutoList([])
		self["playlist"] = StaticText(self.titlemenu)
		self["loading"] = Label(_("Loading data... Please wait"))
		self["vtitle"] = StaticText()
		self.vinfo = ""
		self.description = ""
		self.eptitle = ""
		self.epinfo = ""
		self["key_red"] = StaticText(_("Exit"))
		self["key_yellow"] = StaticText()
		self.mdb = isPluginInstalled("tmdb") and "tmdb" or isPluginInstalled("IMDb") and "imdb"
		self.yellowLabel = _("TMDb Search") if self.mdb == "tmdb" else (_("IMDb Search") if self.mdb else "")
		self["key_green"] = StaticText()
		self["updated"] = StaticText()
		self["key_menu"] = StaticText(_("MENU"))
		self["poster"] = Pixmap()
		self["logo"] = Pixmap()
		self.title = _("PlutoTV") + " - " + self.titlemenu
		self["info"] = ScrollLabel()  # combined info for fluid layout

		self["feedlist"].onSelectionChanged.append(self.update_data)
		self.films = []
		self.menu = []
		self.history = []
		self.chapters = {}
		self.numSeasons = 0

		self.sc = AVSwitch().getFramebufferScale()
		self.picload = ePicLoad()

		self["actions"] = HelpableActionMap(self, ["SetupActions", "ColorActions", "InfobarChannelSelection", "MenuActions"],
		{
			"ok": (self.action, _("Go forward one level incuding starting playback")),
			"cancel": (self.exit, _("Go back one level including exiting")),
			"save": (self.green, _("Create or update PlutoTV live bouquets")),
			"yellow": (self.MDB, _("Search for information in %s") % (_("The Movie Database") if self.mdb == "tmdb" else _("the Internet Movie Database"))),
			"historyBack": (self.back, _("Go back one level")),
			"menu": (self.loadSetup, _("Open the plugin configuration screen")),
		}, -1)

		self["InfoNavigationActions"] = HelpableActionMap(self, ["NavigationActions"],
		{
			"pageUp": (self["info"].pageUp, _("Scroll the information field")),
			"pageDown": (self["info"].pageDown, _("Scroll the information field")),
		}, -1)

		self.updatebutton()

		if self.updatebutton not in Silent.afterUpdate:
			Silent.afterUpdate.append(self.updatebutton)

		self.TimerTemp = eTimer()
		self.TimerTemp.callback.append(self.getCategories)
		self.TimerTemp.start(10, 1)

	def update_data(self):
		if len(self["feedlist"].list) == 0:
			return
		index, name, __type, _id = self.getSelection()
		picname = None
		self["key_yellow"].text = ""
		if __type == "menu":
			self["poster"].hide()

		if __type in ("movie", "series"):
			film = self.films[index]
			self.description = film[2].decode("utf-8")
			self["vtitle"].text = film[1].decode("utf-8")
			info = film[4].decode("utf-8") + "       "
			self["key_yellow"].text = self.yellowLabel

			if __type == "movie":
				info += strftime("%Hh %Mm", gmtime(int(film[5])))
			else:
				info += dngettext(PluginLanguageDomain, "%s Season available", "%s Seasons available", film[10]) % film[10]
				self.numSeasons = film[10]
			self.vinfo = info
			picname = film[0] + ".jpg"
			self.picname = picname
			pic = film[6]
			if len(picname) > 5:
				self["poster"].hide()
				threads.deferToThread(self.downloadPosters.downloadURL, pic, picname, self.downloadPostersCallback)  # url, name, callback

		elif __type == "seasons":
			self.eptitle = ""
			self.epinfo = ""
			if self.numSeasons == 1:  # if numSeans == 1 skip displaying the seasons level and go directly to the next level.
				# Fix a timing issue. Calling self.lastAction directly results in the title for the previous level being displayed.
				self.lastActionTimer = eTimer()
				self.lastActionTimer.callback.append(self.lastAction)
				self.lastActionTimer.start(10, 1)
				return  # skip calling self.updateInfo

		elif __type == "episode":
			film = self.chapters[_id][index]
			self.eptitle = film[1].decode("utf-8") + "  " + strftime("%Hh %Mm", gmtime(int(film[5])))
			self.epinfo = film[3].decode("utf-8")
		self.updateInfo()

	def updateInfo(self):
		# combine info for fluid layout
		vinfoColored = self.vinfo and self.addColor(self.vinfo)
		eptitleColored = self.eptitle and self.addColor(self.eptitle)
		spacer = "\n" if (vinfoColored or self.description) and (eptitleColored or self.epinfo) else ""
		self["info"].setText("\n".join([x for x in (vinfoColored, self.description, spacer, eptitleColored, self.epinfo) if x]))

	def downloadPostersCallback(self, filename, name):
		if name == self.picname:  # check if this is the current image we are waiting for
			self.decodePoster(filename)

	def decodePoster(self, image):
		try:
			x, y = self["poster"].getSize()
			picture = image.replace("\n", "").replace("\r", "")
			self.picload.setPara(
				(
					x,
					y,
					self.sc[0],
					self.sc[1],
					0,
					0,
					"#00000000"
				)
			)
			pictureData = self.picload.PictureData.get()
			del pictureData[:]
			pictureData.append(self.showImage)
			self.picload.startDecode(picture)
		except Exception as ex:
			print("[PlutoScreen] decodeImage, ERROR", ex)

	def showImage(self, picInfo=None):
		try:
			ptr = self.picload.getData()
			if ptr is not None:
				self["poster"].setPixmap(ptr.__deref__())
				self["poster"].show()
		except Exception as ex:
			print("[PlutoScreen] showImage, ERROR", ex)

	def getCategories(self):
		self.lvod = {}
		ondemand = plutoRequest.getOndemand()
		categories = ondemand.get("categories", [])
		if not categories:
			self.session.open(MessageBox, _("There is no data, it is possible that Pluto TV is not available in your country"), type=MessageBox.TYPE_ERROR, timeout=10)
		else:
			[self.buildlist(category) for category in categories]
			list = []
			for key in self.menu:
				list.append(self["feedlist"].listentry(key.decode("utf-8"), "menu", ""))
			self["feedlist"].setList(list)
		self["loading"].hide()

	def buildlist(self, category):
		name = category["name"].encode("utf-8")
		self.lvod[name] = []

		self.menu.append(name)
		items = category.get("items", [])
		for item in items:
			# film = (_id, name, summary, genre, rating, duration, poster, image, type)
			itemid = item.get("_id", "")
			if len(itemid) == 0:
				continue
			itemname = item.get("name", "").encode("utf-8")
			itemsummary = item.get("summary", "").encode("utf-8")
			itemgenre = item.get("genre", "").encode("utf-8")
			itemrating = item.get("rating", "").encode("utf-8")
			itemduration = int(item.get("duration", "0") or "0") // 1000  # in seconds
			itemimgs = item.get("covers", [])
			itemtype = item.get("type", "")
			seasons = len(item.get("seasonsNumbers", []))
			itemimage = ""
			itemposter = ""
			urls = item.get("stitched", {}).get("urls", [])
			if len(urls) > 0:
				url = urls[0].get("url", "")
			else:
				url = ""

			if len(itemimgs) > 2:
				itemimage = itemimgs[2].get("url", "")
			if len(itemimgs) > 1 and len(itemimage) == 0:
				itemimage = itemimgs[1].get("url", "")
			if len(itemimgs) > 0:
				itemposter = itemimgs[0].get("url", "")
			self.lvod[name].append((itemid, itemname, itemsummary, itemgenre, itemrating, itemduration, itemposter, itemimage, itemtype, url, seasons))

	def buildchapters(self, chapters):
		self.chapters.clear()
		items = chapters.get("seasons", [])
		for item in items:
			chs = item.get("episodes", [])
			for ch in chs:
				season = str(ch.get("season", 0))
				if season != "0":
					if season not in self.chapters:
						self.chapters[season] = []
					_id = ch.get("_id", "")
					name = ch.get("name", "").encode("utf-8")
					number = str(ch.get("number", 0))
					summary = ch.get("description", "").encode("utf-8")
					rating = ch.get("rating", "")
					duration = ch.get("duration", 0) // 1000
					genre = ch.get("genre", "").encode("utf-8")
					imgs = ch.get("covers", [])
					urls = ch.get("stitched", {}).get("urls", [])
					if len(urls) > 0:
						url = urls[0].get("url", "")

					itemimage = ""
					itemposter = ""
					if len(imgs) > 2:
						itemimage = imgs[2].get("url", "")
					if len(imgs) > 1 and len(itemimage) == 0:
						itemimage = imgs[1].get("url", "")
					if len(imgs) > 0:
						itemposter = imgs[0].get("url", "")
					self.chapters[season].append((_id, name, number, summary, rating, duration, genre, itemposter, itemimage, url))

	def getSelection(self):
		index = self["feedlist"].getSelectionIndex()
		if current := self["feedlist"].getCurrent():
			data = current[0]
			return index, data[0], data[1], data[2]

	def action(self):
		if not (selection := self.getSelection()):
			return
		self.lastAction = self.action
		index, name, __type, _id = selection
		menu = []
		menuact = self.titlemenu
		if __type == "menu":
			self.films = self.lvod[self.menu[index]]
			for x in self.films:
				sname = x[1].decode("utf-8")
				stype = x[8]
				sid = x[0]
				menu.append(self["feedlist"].listentry(sname, stype, sid))
			self["feedlist"].moveToIndex(0)
			self["feedlist"].setList(menu)
			self.titlemenu = name
			self["playlist"].text = self.titlemenu
			self.title = _("PlutoTV") + " - " + self.titlemenu
			self.history.append((index, menuact))
		if __type == "series":
			chapters = plutoRequest.getVOD(_id)
			self.buildchapters(chapters)
			for key in list(self.chapters.keys()):
				sname = key
				stype = "seasons"
				sid = key
				menu.append(self["feedlist"].listentry(_("Season") + " " + sname, stype, sid))
			self["feedlist"].setList(menu)
			self.titlemenu = name + " - " + _("Seasons")
			self["playlist"].text = self.titlemenu
			self.title = _("PlutoTV") + " - " + self.titlemenu
			self.history.append((index, menuact))
			self["feedlist"].moveToIndex(0)
		if __type == "seasons":
			for key in self.chapters[_id]:
				sname = key[1].decode("utf-8")
				stype = "episode"
				sid = key[0]
				menu.append(self["feedlist"].listentry(_("Episode") + " " + key[2] + ". " + sname, stype, _id, key[0]))
			self["feedlist"].setList(menu)
			self.titlemenu = menuact.split(" - ")[0] + " - " + name
			self["playlist"].text = self.titlemenu
			self.title = _("PlutoTV") + " - " + self.titlemenu
			self.history.append((index, menuact))
			self["feedlist"].moveToIndex(0)
		if __type == "movie":
			film = self.films[index]
			sid = film[0]
			name = film[1].decode("utf-8")
			sessionid, deviceid = plutoRequest.getUUID()
			url = film[9]
			self.playVOD(name, sid, url)
		if __type == "episode":
			film = self.chapters[_id][index]
			sid = film[0]
			name = film[1]
			sessionid, deviceid = plutoRequest.getUUID()
			url = film[9]
			self.playVOD(name, sid, url)

	def back(self):
		if not (selection := self.getSelection()):
			return
		self.lastAction = self.back
		index, name, __type, _id = selection
		menu = []
		if self.history:
			hist = self.history[-1][0]
			histname = self.history[-1][1]
			if __type in ("movie", "series"):
				for key in self.menu:
					menu.append(self["feedlist"].listentry(key.decode("utf-8"), "menu", ""))
				self["vtitle"].text = ""
				self.vinfo = ""
				self.description = ""
			if __type == "seasons":
				for x in self.films:
					sname = x[1].decode("utf-8")
					stype = x[8]
					sid = x[0]
					menu.append(self["feedlist"].listentry(sname, stype, sid))
			if __type == "episode":
				for key in list(self.chapters.keys()):
					sname = str(key)
					stype = "seasons"
					sid = str(key)
					menu.append(self["feedlist"].listentry(_("Season") + " " + sname, stype, sid))
			self["feedlist"].setList(menu)
			self.history.pop()
			self["feedlist"].moveToIndex(hist)
			self.titlemenu = histname
			self["playlist"].text = self.titlemenu
			self.title = _("PlutoTV") + " - " + self.titlemenu
			if not self.history:
				self["poster"].hide()

	def playVOD(self, name, id, url=None):
		# data = plutoRequest.getClips(id)[0]
		# if not data: return
		# url   = (data.get("url", "") or data.get("sources", [])[0].get("file", ""))
		# url = url.replace("siloh.pluto.tv", "dh7tjojp94zlv.cloudfront.net") ## Hack for siloh.pluto.tv not access - siloh.pluto.tv redirect to dh7tjojp94zlv.cloudfront.net
		if url:
			uid, did = plutoRequest.getUUID()
			url = url.replace("deviceModel=", "deviceModel=web").replace("deviceMake=", "deviceMake=chrome") + uid

		if url and name:
			string = "4097:0:0:0:0:0:0:0:0:0:%s:%s" % (quote(url), quote(name))
			reference = eServiceReference(string)
			if "m3u8" in url.lower():
				self.session.open(Pluto_Player, service=reference, sid=id)

	def green(self):
		self.session.openWithCallback(self.endupdateLive, PlutoDownload)

	def endupdateLive(self, ret=None):
		self.session.openWithCallback(self.updatebutton, MessageBox, _("The Pluto TV bouquets in your channel list have been updated.\n\nThey will now be rebuilt automatically every 5 hours."), type=MessageBox.TYPE_INFO, timeout=10)

	def updatebutton(self, ret=None):
		bouquets = open("/etc/enigma2/bouquets.tv", "r").read()
		if fileExists(TIMER_FILE) and all(((BOUQUET_FILE % cc) in bouquets) for cc in [x for x in getselectedcountries() if x]):
			last = float(open(TIMER_FILE, "r").read().replace("\n", "").replace("\r", ""))
			updated = strftime(" %x %H:%M", localtime(int(last)))
			self["key_green"].text = _("Update LiveTV Bouquet")
			self["updated"].text = _("LiveTV Bouquet last updated:") + updated
		elif "pluto_tv" in bouquets:
			self["key_green"].text = _("Update LiveTV Bouquet")
			self["updated"].text = _("LiveTV Bouquet needs updating. Press GREEN.")
		else:
			self["key_green"].text = _("Create LiveTV Bouquet")
			self["updated"].text = ""

	def exit(self, *args, **kwargs):
		if self.history:
			self.back()
		else:
			self.close()

	def MDB(self):
		index, name, __type, _id = self.getSelection()
		if __type in ("movie", "series") and self.mdb:
			if self.mdb == "tmdb":
				from Plugins.Extensions.tmdb.tmdb import tmdbScreen
				self.session.open(tmdbScreen, name, 2)
			else:
				from Plugins.Extensions.IMDb.plugin import IMDB
				self.session.open(IMDB, name, False)

	def loadSetup(self):
		self.session.openWithCallback(self.close, PlutoSetup)

	def addColor(self, text, i=1):
		if i < len(self.colors):
			text = Hex2strColor(self.colors[i]) + text + Hex2strColor(self.colors[0])
		return text

	def close(self, *args, **kwargs):
		if self.updatebutton in Silent.afterUpdate:
			Silent.afterUpdate.remove(self.updatebutton)
		Screen.close(self)


class PlutoSetup(Setup):
	def __init__(self, session):
		Setup.__init__(self, session, yellow_button={"function": self.yellow}, blue_button={"function": self.blue})
		self.updateYellowButton()
		self.updateBlueButton()
		self.setTitle(_("PlutoTV Setup"))

	def createSetup(self):
		configList = []
		configList.append((_("VoD country"), config.plugins.plutotv.country, _("Select the country that the VoD list will be created for.")))
		configList.append(("---",))
		for n in range(1, NUMBER_OF_LIVETV_BOUQUETS + 1):
			if n == 1 or getattr(config.plugins.plutotv, "live_tv_country" + str(n - 1)).value:
				configList.append((_("LiveTV bouquet %s") % n, getattr(config.plugins.plutotv, "live_tv_country" + str(n)), _("Country for which LiveTV bouquet %s will be created.") % n))
		configList.append(("---",))
		configList.append((_("Picon type"), config.plugins.plutotv.picons, _("Using service name picons means they will continue to work even if the service reference changes. Also, they can be shared between channels of the same name that don't have the same service references.")))
		configList.append((_("Data location"), config.plugins.plutotv.datalocation, _("Used for storing video cover graphics, etc. A hard drive that goes into standby mode or a slow network mount are not good choices.")))
		self["config"].list = configList

	def keyCancel(self):
		for x in self['config'].list:
			if len(x) > 1:
				x[1].cancel()
		self.exit()

	def closeRecursive(self):
		self.keyCancel()

	def keySave(self):
		self.saveAll()
		self.exit()

	def exit(self):
		self.session.openWithCallback(self.close, PlutoTV)

	def updateYellowButton(self):
		if os.path.isdir(PiconFetcher().pluginPiconDir):
			self["key_yellow"].text = _("Remove picons")
		else:
			self["key_yellow"].text = ""

	def updateBlueButton(self):
		bouquets = open("/etc/enigma2/bouquets.tv", "r").read()
		if "pluto_tv" in bouquets:
			self["key_blue"].text = _("Remove LiveTV Bouquet")
		else:
			self["key_blue"].text = ""

	def yellow(self):
		if self["key_yellow"].text:
			PiconFetcher().removeall()
			self.updateYellowButton()

	def blue(self):
		if self["key_blue"].text:
			Silent.stop()
			from enigma import eDVBDB
			eDVBDB.getInstance().removeBouquet(re.escape(BOUQUET_FILE) % ".*")
			self.updateBlueButton()


class Pluto_Player(MoviePlayer):

	ENABLE_RESUME_SUPPORT = False    # Don"t use Enigma2 resume support. We use self resume support

	def __init__(self, session, service, sid):
		self.session = session
		self.mpservice = service
		self.id = sid
		MoviePlayer.__init__(self, self.session, service, sid)
		self.end = False
		self.started = False
		self.skinName = ["MoviePlayer"]

		self.__event_tracker = ServiceEventTracker(
			screen=self,
			eventmap={
				iPlayableService.evStart: self.__serviceStarted,
				# iPlayableService.evBuffering: self.__serviceStarted,
				# iPlayableService.evVideoSizeChanged: self.__serviceStarted,
				iPlayableService.evEOF: self.__evEOF,
			}
		)

		self["actions"] = ActionMap(["MoviePlayerActions", "OkActions"],
		{
			"leavePlayerOnExit": self.leavePlayer,
			"leavePlayer": self.leavePlayer,
			"ok": self.toggleShow,
		}, -3)
		self.session.nav.playService(self.mpservice)

	def up(self):
		pass

	def down(self):
		pass

	def doEofInternal(self, playing):
		self.close()

	def __evEOF(self):
		self.end = True

	def __serviceStarted(self):
		service = self.session.nav.getCurrentService()
		seekable = service.seek()
		self.started = True
		last, length = resumePointsInstance.getResumePoint(self.id)
		if last is None or seekable is None:
			return
		length = seekable.getLength() or (None, 0)
		print("seekable.getLength() returns:", length)
		# Hmm, this implies we don"t resume if the length is unknown...
		if (last > 900000) and (not length[1] or (last < length[1] - 900000)):
			self.last = last
			last /= 90000
			Notifications.AddNotificationWithCallback(self.playLastCB, MessageBox, _("Do you want to resume this playback?") + "\n" + (_("Resume position at %s") % ("%d:%02d:%02d" % (last / 3600, last % 3600 / 60, last % 60))), timeout=10, default="yes" in config.usage.on_movie_start.value)

	def playLastCB(self, answer):
		if answer is True and self.last:
			self.doSeek(self.last)
		self.hideAfterResume()

	def leavePlayer(self):
		self.is_closing = True
		resumePointsInstance.setResumePoint(self.session, self.id)
		self.close()

	def leavePlayerConfirmed(self, answer):
		pass


def autostart(reason, session):
	Silent.init(session)


def Download_PlutoTV(session, **kwargs):
	session.open(PlutoDownload)


def system(session, **kwargs):
	session.open(PlutoTV)


def Plugins(**kwargs):
	return [
		PluginDescriptor(name=_("PlutoTV"), where=PluginDescriptor.WHERE_PLUGINMENU, icon=PLUGIN_ICON, description=_("View video on demand and download a bouquet of live tv channels"), fnc=system, needsRestart=True),
		PluginDescriptor(name=_("Download PlutoTV bouquet, picons and EPG"), where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=Download_PlutoTV, needsRestart=True),
		PluginDescriptor(name=_("Silently download PlutoTV"), where=PluginDescriptor.WHERE_SESSIONSTART, fnc=autostart),
	]
