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
#   Credit to Billy2011 @ vuplus-support.org for the X_FORWARDS idea
#   and dictionary from his version of the plugin distributed under
#   the same license.
#

# for localized messages
from . import _
from .Variables import TIMER_FILE, PLUGIN_FOLDER, BOUQUET_FILE, BOUQUET_NAME, NUMBER_OF_LIVETV_BOUQUETS, PLUGIN_ICON

from Components.ActionMap import ActionMap
from Components.config import ConfigSelection, ConfigSubsection, config
from Components.Label import Label
from Components.ProgressBar import ProgressBar
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Tools.CountryCodes import ISO3166
from Tools.Directories import fileExists, sanitizeFilename

from enigma import eDVBDB, eEPGCache, eTimer

import datetime
import os
import re
import requests
import shutil
import time
import uuid
from urllib.parse import quote

import threading  # for fetching picons
from twisted.internet import threads  # for updating GUI widgets


class PlutoRequest:
	X_FORWARDS = {
		"us": "185.236.200.172",
		"gb": "185.199.220.58",
		"de": "85.214.132.117",
		"es": "88.26.241.248",
		"ca": "192.206.151.131",
		"br": "177.47.27.205",
		"mx": "200.68.128.83",
		"fr": "176.31.84.249",
		"at": "2.18.68.0",
		"ch": "5.144.31.245",
		"it": "5.133.48.0",
		"ar": "104.103.238.0",
		"co": "181.204.4.74",
		"cr": "138.122.24.0",
		"pe": "190.42.0.0",
		"ve": "103.83.193.0",
		"cl": "161.238.0.0",
		"bo": "186.27.64.0",
		"sv": "190.53.128.0",
		"gt": "190.115.2.25",
		"hn": "181.115.0.0",
		"ni": "186.76.0.0",
		"pa": "168.77.0.0",
		"uy": "179.24.0.0",
		"ec": "181.196.0.0",
		"py": "177.250.0.0",
		"do": "152.166.0.0",
		"se": "185.39.146.168",
		"dk": "80.63.84.58",
		"no": "84.214.150.146",
		"au": "144.48.37.140",
		"fi": "85.194.236.0",
	}

	BASE_API = "https://api.pluto.tv"
	GUIDE_URL = "https://service-channels.clusters.pluto.tv/v1/guide?start=%s&stop=%s&%s"
	BASE_GUIDE = BASE_API + "/v2/channels?start=%s&stop=%s&%s"
	BASE_LINEUP = BASE_API + "/v2/channels.json?%s"
	BASE_VOD = BASE_API + "/v3/vod/categories?includeItems=true&deviceType=web&%s"
	SEASON_VOD = BASE_API + "/v3/vod/series/%s/seasons?includeItems=true&deviceType=web&%s"
	# BASE_CLIPS = BASE_API + "/v2/episodes/%s/clips.json"

	sid1_hex = str(uuid.uuid1().hex)
	deviceId1_hex = str(uuid.uuid4().hex)

	def __init__(self):
		self.requestCache = {}

	def getURL(self, url, param=None, header={"User-agent": "Mozilla/5.0 (Windows NT 6.2; rv:24.0) Gecko/20100101 Firefox/24.0"}, life=60 * 15, country=None):
		if param is None:
			param = {}
		now = time.time()
		country = country or config.plugins.plutotv.country.value
		if country not in self.requestCache:
			self.requestCache[country] = {}
		if url in self.requestCache[country] and self.requestCache[country][url][1] > (now - life):
			return self.requestCache[country][url][0]
		try:
			req = requests.get(url, param, headers=header, timeout=2)
			req.raise_for_status()
			response = req.json()
			req.close()
			self.requestCache[country][url] = (response, now)
			return response
		except Exception:
			return {}

	def getUUID(self):
		return self.sid1_hex, self.deviceId1_hex

	def getUUIDstr(self):
		return "sid=%s&deviceId=%s" % self.getUUID()

	def buildHeader(self, country=None):
		ip = self.X_FORWARDS.get(country or config.plugins.plutotv.country.value)
		return {
			"Accept": "application/json, text/javascript, */*; q=0.01",
			"Host": "api.pluto.tv",
			"Connection": "keep-alive",
			"Referer": "http://pluto.tv/",
			"Origin": "http://pluto.tv",
			"User-Agent": "Mozilla/5.0 (Windows NT 6.2; rv:24.0) Gecko/20100101 Firefox/24.0",
		} | ({"X-Forwarded-For": ip} if ip else {})

	# def getClips(self, epid, country=None):
	# 	return self.getURL(self.BASE_CLIPS % (epid), header=self.buildHeader(), life=60 * 60, country=country))

	def getVOD(self, epid, country=None):
		return self.getURL(self.SEASON_VOD % (epid, self.getUUIDstr()), header=self.buildHeader(country), life=60 * 60, country=country)

	def getOndemand(self, country=None):
		return self.getURL(self.BASE_VOD % self.getUUIDstr(), header=self.buildHeader(country), life=60 * 60, country=country)

	def getChannels(self, country=None):
		return self.getURL(self.BASE_LINEUP % self.getUUIDstr(), header=self.buildHeader(country), life=60 * 60, country=country)

	def getFullGuide(self, start, stop, country=None):
		return self.getURL(self.GUIDE_URL % (start, stop, self.getUUIDstr()), header=self.buildHeader(country), life=60 * 60, country=country)

	def getBaseGuide(self, start, stop, country=None):
		return self.getURL(self.BASE_GUIDE % (start, stop, self.getUUIDstr()), header=self.buildHeader(country), life=60 * 60, country=country)


plutoRequest = PlutoRequest()


COUNTRY_NAMES = {cc: country[0].split("(")[0].strip() for country in sorted(ISO3166) if (cc := country[1].lower()) in PlutoRequest.X_FORWARDS}  # ISO3166 is sorted in English, sorted will sort by locale.

TSIDS = {cc: "%X" % i for i, cc in enumerate(COUNTRY_NAMES, 1)}


config.plugins.plutotv = ConfigSubsection()
config.plugins.plutotv.country = ConfigSelection(default="local", choices=[("local", _("Local"))] + list(COUNTRY_NAMES.items()))
config.plugins.plutotv.picons = ConfigSelection(default="snp", choices=[("snp", _("service name")), ("srp", _("service reference")), ("", _("None"))])


def getselectedcountries(skip=0):
	return [getattr(config.plugins.plutotv, "live_tv_country" + str(n)).value for n in range(1, NUMBER_OF_LIVETV_BOUQUETS + 1) if n != skip]


def autocountry(configElement):
	for n in range(1, NUMBER_OF_LIVETV_BOUQUETS + 1):
		selected_countries = getselectedcountries(n)  # run only once, not loop during list comprehension
		getattr(config.plugins.plutotv, "live_tv_country" + str(n)).setChoices([x for x in [("", _("None"))] + list(COUNTRY_NAMES.items()) if x[0] and x[0] not in selected_countries or not x[0] and (n == NUMBER_OF_LIVETV_BOUQUETS or not getattr(config.plugins.plutotv, "live_tv_country" + str(n + 1)).value)])


for n in range(1, NUMBER_OF_LIVETV_BOUQUETS + 1):
	setattr(config.plugins.plutotv, "live_tv_country" + str(n), ConfigSelection(default="", choices=[("", _("None"))] + list(COUNTRY_NAMES.items())))

for n in range(1, NUMBER_OF_LIVETV_BOUQUETS + 1):
	getattr(config.plugins.plutotv, "live_tv_country" + str(n)).addNotifier(autocountry, initial_call=n == NUMBER_OF_LIVETV_BOUQUETS)


class PiconFetcher:
	def __init__(self, parent=None):
		self.parent = parent
		self.piconDir = self.getPiconPath()
		self.pluginPiconDir = os.path.join(self.piconDir, "PlutoTV")
		piconWidth = 220
		piconHeight = 132
		self.resolutionStr = f"?h={piconHeight}&w={piconWidth}"
		self.piconList = []

	def createFolders(self):
		os.makedirs(self.piconDir, exist_ok=True)
		os.makedirs(self.pluginPiconDir, exist_ok=True)
		self.defaultIcon = os.path.join(self.pluginPiconDir, PLUGIN_ICON)
		shutil.copy(os.path.join(PLUGIN_FOLDER, PLUGIN_ICON), self.defaultIcon)

	def addPicon(self, ref, name, url, silent):
		if not config.plugins.plutotv.picons.value:
			return
		piconname = os.path.join(self.piconDir, ch_name + ".png") if config.plugins.plutotv.picons.value == "snp" and (ch_name := sanitizeFilename(name.lower())) else os.path.join(self.piconDir, ref.replace(":", "_") + ".png")
		one_week_ago = time.time() - 60 * 60 * 24 * 7
		if not (fileExists(piconname) and (silent or os.path.getmtime(piconname) > one_week_ago)):
			self.piconList.append((url, piconname))

	def fetchPicons(self):
		maxthreads = 100  # make configurable
		self.counter = 0
		failed = []
		self.createFolders()
		if self.piconList:
			threads = [threading.Thread(target=self.downloadURL, args=(url, filename)) for url, filename in self.piconList]
			for thread in threads:
				while threading.activeCount() > maxthreads:
					time.sleep(1)
				try:
					thread.start()
				except RuntimeError:
					failed.append(thread)
			for thread in threads:
				if thread not in failed:
					thread.join()
			print("[Fetcher] all fetched")

	def downloadURL(self, url, piconname):
		filepath = os.path.join(self.pluginPiconDir, piconname.removeprefix(self.piconDir))
		self.counter += 1
		try:
			response = requests.get(f"{url}{self.resolutionStr}", timeout=2.50, headers={"User-Agent": "Mozilla/5.0 (Windows NT 6.2; rv:24.0) Gecko/20100101 Firefox/24.0"})
			response.raise_for_status()
			content_type = response.headers.get('content-type')
			if content_type and content_type.lower() == 'image/png' and len(rc := response.content):
				with open(filepath, "wb") as f:
					f.write(rc)
		except requests.exceptions.RequestException:
			pass
		if not fileExists(filepath):  # it seems nothing was downloaded
			filepath = self.defaultIcon
		self.makesoftlink(filepath, piconname)
		if self.parent:
			threads.deferToThread(self.parent.updateProgressBar, self.counter)

	def makesoftlink(self, filepath, softlinkpath):
		svgpath = softlinkpath.removesuffix(".png") + ".svg"
		islink = os.path.islink(softlinkpath)
		# isfile follows symbolic links so we need to check this is not a symbolic link first
		# or if user.svg exists do not write symbolic link
		if not islink and os.path.isfile(softlinkpath) or os.path.isfile(svgpath):
			return  # if a file exists here don't touch it, it is not ours
		if islink:
			if os.readlink(softlinkpath) == filepath:
				return
			os.remove(softlinkpath)
		os.symlink(filepath, softlinkpath)

	def removeall(self):
		if os.path.exists(self.piconDir):
			for f in os.listdir(self.piconDir):
				item = os.path.join(self.piconDir, f)
				if os.path.islink(item) and self.pluginPiconDir in os.readlink(item):
					os.remove(item)
		if os.path.exists(self.pluginPiconDir):
			shutil.rmtree(self.pluginPiconDir)

	@staticmethod
	def getPiconPath():
		try:
			from Components.Renderer.Picon import lastPiconPath, searchPaths
		except ImportError:
			try:
				from Components.Renderer.Picon import piconLocator
				lastPiconPath = piconLocator.activePiconPath
				searchPaths = piconLocator.searchPaths
			except ImportError:
				lastPiconPath = None
				searchPaths = None
		if searchPaths and len(searchPaths) == 1:
			return searchPaths[0]
		return lastPiconPath or "/picon"


class PlutoDownloadBase():
	downloadActive = False  # shared between instances

	def __init__(self, silent=False):
		self.channelsList = {}
		self.guideList = {}
		self.categories = []
		self.state = 1  # this is a hack
		self.silent = silent
		PlutoDownloadBase.downloadActive = False
		self.epgcache = eEPGCache.getInstance()

	def cc(self):
		countries = [x for x in getselectedcountries() if x] or [config.plugins.plutotv.country.value]
		from enigma import eDVBDB
		# Delete bouquets of not selected countries. Don't delete the bouquets we are updating so they retain their current position.
		eDVBDB.getInstance().removeBouquet(re.escape(BOUQUET_FILE) % ("(?!%s).+" % "|".join(countries)))
		for cc in countries:
			yield cc

	def download(self):
		if PlutoDownloadBase.downloadActive:
			if not self.silent:
				self.session.openWithCallback(self.close, MessageBox, _("A silent download is in progress."), MessageBox.TYPE_INFO, timeout=30)
			print("[PlutoDownload] A silent download is in progress.")
			return
		self.ccGenerator = self.cc()
		self.piconFetcher = PiconFetcher(self)
		self.manager()

	def manager(self):
		PlutoDownloadBase.downloadActive = True
		if cc := next(self.ccGenerator, None):
			self.downloadBouquet(cc)
		else:
			self.channelsList.clear()
			self.guideList.clear()
			self.categories.clear()
			PlutoDownloadBase.downloadActive = False
			self.ccGenerator = None
			if self.piconFetcher.piconList:
				self.total = len(self.piconFetcher.piconList)
				threads.deferToThread(self.updateProgressBar, 0)  # reset
				threads.deferToThread(self.updateAction, _("picons"))  # GUI widget
				threads.deferToThread(self.updateStatus, _("Fetching picons..."))  # GUI widget
				self.piconFetcher.fetchPicons()
				threads.deferToThread(self.updateProgressBar, self.total)  # reset
			self.piconFetcher = None
			threads.deferToThread(self.updateStatus, _("LiveTV update completed"))  # GUI widget
			time.sleep(3)
			self.exitOk()
			self.start()

	def downloadBouquet(self, cc):
		self.bouquet = []
		self.bouquetCC = cc
		self.tsid = TSIDS.get(cc, "0")
		self.stop()
		self.channelsList.clear()
		self.guideList.clear()
		self.categories.clear()
		threads.deferToThread(self.updateAction, cc)  # GUI widget
		threads.deferToThread(self.updateProgressBar, 0)  # reset
		threads.deferToThread(self.updateStatus, _("Processing data..."))  # GUI widget
		channels = sorted(plutoRequest.getChannels(cc), key=lambda x: x["number"])
		guide = self.getGuidedata(cc)
		[self.buildM3U(channel) for channel in channels]
		self.total = len(channels)

		if len(self.categories) == 0:
			self.noCategories()
		else:
			if self.categories[0] in self.channelsList:
				self.subtotal = len(self.channelsList[self.categories[0]])
			else:
				self.subtotal = 0
			self.key = 0
			self.chitem = 0
			[self.buildGuide(event) for event in guide]
			for i in range(self.total + 1):
				self.updateprogress(param=i)

	def updateprogress(self, param):
		if hasattr(self, "state") and self.state == 1:  # hack for exit before end
			threads.deferToThread(self.updateProgressBar, param)
			if param < self.total:
				key = self.categories[self.key]
				if self.chitem == self.subtotal:
					self.chitem = 0
					found = False
					while not found:
						self.key += 1
						key = self.categories[self.key]
						found = key in self.channelsList
					self.subtotal = len(self.channelsList[key])

				if self.chitem == 0:
					self.bouquet.append("1:64:%s:0:0:0:0:0:0:0::%s" % (self.key, self.categories[self.key]))

				ch_sid, ch_hash, ch_name, ch_logourl, ch_url = self.channelsList[key][self.chitem]

				self.bouquet.append("4097:0:1:%s:%s:FF:CCCC0000:0:0:0:%s:%s" % (ch_sid, self.tsid, quote(ch_url), ch_name))
				self.chitem += 1

				ref = "4097:0:1:%s:%s:FF:CCCC0000:0:0:0" % (ch_sid, self.tsid)
				# print("[updateprogress] ref", ref)
				threads.deferToThread(self.updateStatus, _("Waiting for Channel: ") + ch_name)  # GUI widget

				chevents = []
				if ch_hash in self.guideList:
					for evt in self.guideList[ch_hash]:
						title = evt[0]
						summary = evt[1]
						begin = int(round(evt[2]))
						duration = evt[3]
						genre = evt[4]

						chevents.append((begin, duration, title, "", summary, genre))
				if len(chevents) > 0:
					iterator = iter(chevents)
					events_tuple = tuple(iterator)
					self.epgcache.importEvents(ref + ":https%3a//.m3u8", events_tuple)

				self.piconFetcher.addPicon(ref, ch_name, ch_logourl, self.silent)
			else:
				eDVBDB.getInstance().addOrUpdateBouquet(BOUQUET_NAME % COUNTRY_NAMES[self.bouquetCC], BOUQUET_FILE % self.bouquetCC, self.bouquet, False)  # place at bottom if not exists
				os.makedirs(os.path.dirname(TIMER_FILE), exist_ok=True)  # create config folder recursive if not exists
				open(TIMER_FILE, "w").write(str(time.time()))
				self.manager()

	def buildGuide(self, event):
		# (title, summary, start, duration, genre)
		_id = event.get("_id", "")
		if len(_id) == 0:
			return
		self.guideList[_id] = []
		timelines = event.get("timelines", [])
		chplot = (event.get("description", "") or event.get("summary", ""))

		for item in timelines:
			episode = (item.get("episode", {}) or item)
			series = (episode.get("series", {}) or item)
			epdur = int(episode.get("duration", "0") or "0") // 1000  # in seconds
			epgenre = episode.get("genre", "")
			etype = series.get("type", "film")

			genre = self.convertgenre(epgenre)

			offset = datetime.datetime.now() - datetime.datetime.utcnow()
			try:
				starttime = self.strpTime(item["start"]) + offset
			except:
				return
			start = time.mktime(starttime.timetuple())
			title = (item.get("title", ""))
			tvplot = (series.get("description", "") or series.get("summary", "") or chplot)
			epnumber = episode.get("number", 0)
			epseason = episode.get("season", 0)
			epname = (episode["name"])
			epmpaa = episode.get("rating", "")
			epplot = (episode.get("description", "") or tvplot or epname)

			if len(epmpaa) > 0 and "Not Rated" not in epmpaa:
				epplot = "(%s). %s" % (epmpaa, epplot)

			noserie = "live film"
			if epseason > 0 and epnumber > 0 and etype not in noserie:
				title = title + " (T%d)" % epseason
				epplot = "T%d Ep.%d %s" % (epseason, epnumber, epplot)

			if epdur > 0:
				self.guideList[_id].append((title, epplot, start, epdur, genre))

	def buildM3U(self, channel):
		# (number, _id, name, logo, url)
		# Select type of logo we want
		# logo = (channel.get("logo", {}).get("path", None) or None)
		# logo = (channel.get("solidLogoPNG", {}).get("path", None) or None)  # blancos
		logo = (channel.get("colorLogoPNG", {}).get("path", None) or None)
		group = channel.get("category", "")
		_id = channel["_id"]

		urls = channel.get("stitched", {}).get("urls", [])
		if len(urls) == 0:
			return False

		if isinstance(urls, list):
			urls = [url["url"].replace("deviceType=&", "deviceType=web&").replace("deviceMake=&", "deviceMake=Chrome&").replace("deviceModel=&", "deviceModel=Chrome&").replace("appName=&", "appName=web&") for url in urls if url["type"].lower() == "hls"][0]  # todo select quality

		if group not in list(self.channelsList.keys()):
			self.channelsList[group] = []
			self.categories.append(group)

		if int(channel["number"]) == 0:
			number = _id[-4:].upper()
		else:
			number = channel["number"]

		self.channelsList[group].append((str(number), _id, channel["name"], logo, urls))
		return True

	@staticmethod
	def convertgenre(genre):
		id = 0
		if genre in ("Classics", "Romance", "Thrillers", "Horror") or "Sci-Fi" in genre or "Action" in genre:
			id = 0x10
		elif "News" in genre or "Educational" in genre:
			id = 0x20
		elif genre == "Comedy":
			id = 0x30
		elif "Children" in genre:
			id = 0x50
		elif genre == "Music":
			id = 0x60
		elif genre == "Documentaries":
			id = 0xA0
		return id

	@staticmethod
	def getGuidedata(cc, full=False):
		start = (datetime.datetime.fromtimestamp(PlutoDownloadBase.getLocalTime()).strftime("%Y-%m-%dT%H:00:00Z"))
		stop = (datetime.datetime.fromtimestamp(PlutoDownloadBase.getLocalTime()) + datetime.timedelta(hours=24)).strftime("%Y-%m-%dT%H:00:00Z")

		if full:  # this is never used
			return plutoRequest.getFullGuide(start, stop, cc)
		else:
			return sorted(plutoRequest.getBaseGuide(start, stop, cc), key=lambda x: x["number"])

	@staticmethod
	def getLocalTime():
		offset = datetime.datetime.utcnow() - datetime.datetime.now()
		return time.time() + offset.total_seconds()

	@staticmethod
	def strpTime(datestring, format="%Y-%m-%dT%H:%M:%S.%fZ"):
		try:
			return datetime.datetime.strptime(datestring, format)
		except TypeError:
			return datetime.datetime.fromtimestamp(time.mktime(time.strptime(datestring, format)))

	def start(self):
		pass

	def stop(self):
		pass

	def exitOk(self, answer=None):
		pass

	def updateProgressBar(self, param):
		pass

	def updateStatus(self, name):
		pass

	def updateAction(self, cc=""):
		pass


class PlutoDownload(PlutoDownloadBase, Screen):
	skin = f"""
		<screen name="PlutoTVdownload" position="60,60" resolution="1920,1080" size="615,195" flags="wfNoBorder" backgroundColor="#ff000000">
		<eLabel position="0,0" size="615,195" zPosition="-1" alphatest="blend" backgroundColor="#2d101214" cornerRadius="8" widgetBorderWidth="2" widgetBorderColor="#2d888888"/>
		<ePixmap position="15,80" size="120,45" pixmap="{PLUGIN_FOLDER}/{PLUGIN_ICON}" scale="1" alphatest="blend" transparent="1" zPosition="10"/>
		<widget name="action" halign="left" valign="center" position="13,9" size="433,30" font="Regular;25" foregroundColor="#dfdfdf" transparent="1" backgroundColor="#000000" borderColor="black" borderWidth="1" noWrap="1"/>
		<widget name="progress" position="150,97" size="420,12" borderWidth="0" backgroundColor="#1143495b" pixmap="{PLUGIN_FOLDER}/images/progresoHD.png" zPosition="2" alphatest="blend" />
		<eLabel name="progess_background" position="150,97" size="420,12" backgroundColor="#102a3b58" />
		<widget name="wait" valign="center" halign="center" position="150,63" size="420,30" font="Regular;22" foregroundColor="#dfdfdf" transparent="1" backgroundColor="#000000" borderColor="black" borderWidth="1" noWrap="1"/>
		<widget name="status" halign="center" valign="center" position="150,120" size="420,30" font="Regular;24" foregroundColor="#ffffff" transparent="1" backgroundColor="#000000" borderColor="black" borderWidth="1" noWrap="1"/>
		</screen>"""

	def __init__(self, session):
		self.session = session
		Screen.__init__(self, session)
		self.title = _("PlutoTV updating")
		PlutoDownloadBase.__init__(self)
		self.total = 0
		self["progress"] = ProgressBar()
		self["action"] = Label()
		self.updateAction()
		self["wait"] = Label()
		self["status"] = Label(_("Please wait..."))
		self["actions"] = ActionMap(["OkCancelActions"], {"cancel": self.exit}, -1)
		self.onFirstExecBegin.append(self.init)

	def updateAction(self, cc=""):
		self["action"].text = _("Updating: Pluto TV %s") % cc.upper()

	def init(self):
		self["progress"].setValue(0)
		threads.deferToThread(self.download)

	def exit(self):
		self.session.openWithCallback(self.cleanup, MessageBox, _("The download is in progress. Exit now?"), MessageBox.TYPE_YESNO, timeout=30)

	def cleanup(self, answer=None):
		if answer:
			PlutoDownloadBase.downloadActive = False
			self.exitOk(answer)

	def exitOk(self, answer=True):
		if answer:
			Silent.stop()
			Silent.start()
			self.close(True)

	def updateProgressBar(self, param):
		try:
			progress = ((param + 1) * 100) // self.total
		except:
			progress = 0
		else:
			if progress > 100:
				progress = 100
		self["progress"].setValue(progress)
		self["wait"].text = str(progress) + " %"

	def updateStatus(self, msg):
		self["status"].text = msg

	def noCategories(self):
		self.session.openWithCallback(self.exitOk, MessageBox, _("There is no data, it is possible that Pluto TV is not available in your country"), type=MessageBox.TYPE_ERROR, timeout=10)


class DownloadSilent(PlutoDownloadBase):
	def __init__(self):
		self.afterUpdate = []  # for callbacks
		PlutoDownloadBase.__init__(self, silent=True)
		self.timer = eTimer()
		self.timer.timeout.get().append(self.download)

	def init(self, session):  # called on session start
		self.session = session
		bouquets = open("/etc/enigma2/bouquets.tv", "r").read()
		if "pluto_tv" in bouquets:
			self.start(True)

	def start(self, fromSessionStart=False):
		self.stop()
		minutes = 60 * 5
		if fileExists(TIMER_FILE):
			last = float(open(TIMER_FILE, "r").read().strip())
			minutes -= int((time.time() - last) / 60)
			if minutes < 0:
				minutes = 1  # do we want to do this so close to reboot
		self.timer.startLongTimer(minutes * 60)
		if not fromSessionStart:
			self.afterUpdateCallbacks()

	def stop(self):
		self.timer.stop()

	def afterUpdateCallbacks(self):
		for f in self.afterUpdate:
			if callable(f):
				f()

	def noCategories(self):
		print("[Pluto TV] There is no data, it is possible that Pluto TV is not available in your country.")
		self.stop()
		os.makedirs(os.path.dirname(TIMER_FILE), exist_ok=True)  # create config folder recursive if not exists
		open(TIMER_FILE, "w").write(str(time.time()))
		self.start()


Silent = DownloadSilent()
