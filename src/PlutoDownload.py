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
from . import _
from .Variables import TIMER_FILE, PLUGIN_FOLDER

from Components.ActionMap import ActionMap
from Components.config import ConfigSelection, ConfigSubsection, config
from Components.Label import Label
from Components.ProgressBar import ProgressBar
from Screens.ChannelSelection import service_types_tv
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Tools.CountryCodes import ISO3166
from Tools.Directories import fileExists

from enigma import eConsoleAppContainer, eDVBDB, eEPGCache, eServiceCenter, eServiceReference, eTimer

import collections
import datetime
import json
import os
import requests
import time
import uuid
from urllib.parse import quote

BASE_API      = "https://api.pluto.tv"
GUIDE_URL     = "https://service-channels.clusters.pluto.tv/v1/guide?start=%s&stop=%s&%s"
BASE_GUIDE    = BASE_API + "/v2/channels?start=%s&stop=%s&%s"
BASE_LINEUP   = BASE_API + "/v2/channels.json?%s"
BASE_VOD      = BASE_API + "/v3/vod/categories?includeItems=true&deviceType=web&%s"
SEASON_VOD    = BASE_API + "/v3/vod/series/%s/seasons?includeItems=true&deviceType=web&%s"
BASE_CLIPS    = BASE_API + "/v2/episodes/%s/clips.json"

RequestCache = {}

sid1_hex = str(uuid.uuid1().hex)
deviceId1_hex = str(uuid.uuid4().hex)


X_FORWARDS = {
	"us": "185.236.200.172",
#	"gb": "185.86.151.11",
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

COUNTRY_NAMES = {cc: country[0].split("(")[0].strip() for country in sorted(ISO3166) if (cc := country[1].lower()) in X_FORWARDS}  # ISO3166 is sorted in English, sorted will sort by locale.

config.plugins.plutotv = ConfigSubsection()
config.plugins.plutotv.country = ConfigSelection(default="local", choices=[("local", _("Local"))] + list(COUNTRY_NAMES.items()))

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


class DownloadComponent:
	EVENT_DOWNLOAD = 0
	EVENT_DONE = 1
	EVENT_ERROR = 2

	def __init__(self, n, ref, name, picon=False):
		self.cmd = eConsoleAppContainer()
		self.cache = None
		self.name = None
		self.data = None
		self.picon = picon
		self.number = n
		self.ref = ref
		self.name = name
		self.callbackList = []

	def startCmd(self, cmd):
		rute = "wget"
		picon_path = getPiconPath()
		os.makedirs(picon_path, exist_ok=True)  # create folder if not exists
		filename = os.path.join(picon_path, self.ref.replace(":", "_") + ".png")
		if filename:
			rute = rute + " -O " + filename
			self.filename = filename
		else:
			self.filename = cmd.split("/")[-1]
		
		number = self.ref.split(":")
		if len(number[3]) > 3:
			png = os.path.join(PLUGIN_FOLDER, "plutotv.png")
			rute = "cp " + png + " " +  filename
		else:
			rute = rute + " " + cmd

		if fileExists(filename) and not self.picon:
			self.callCallbacks(self.EVENT_DONE, self.number, self.ref, self.name)
		else:
			self.runCmd(rute)

	def runCmd(self, cmd):
		print("executing", cmd)
		self.cmd.appClosed.append(self.cmdFinished)
		if self.cmd.execute(cmd):
			self.cmdFinished(-1)

	def cmdFinished(self, retval):
		self.callCallbacks(self.EVENT_DONE, self.number, self.ref, self.name)
		self.cmd.appClosed.remove(self.cmdFinished)

	def callCallbacks(self, event, param=None, ref=None, name=None):
		for callback in self.callbackList:
			callback(event, param, ref, name)

	def addCallback(self, callback):
		self.callbackList.append(callback)

	def removeCallback(self, callback):
		self.callbackList.remove(callback)


def getUUID():
	return sid1_hex, deviceId1_hex

def getUUIDstr():
	return "sid=%s&deviceId=%s" % getUUID()

def buildHeader():
	return {
		"Accept": "application/json, text/javascript, */*; q=0.01",
		"Host": "api.pluto.tv",
		"Connection": "keep-alive",
		"Referer": "http://pluto.tv/",
		"Origin": "http://pluto.tv",
		"User-Agent": "Mozilla/5.0 (Windows NT 6.2; rv:24.0) Gecko/20100101 Firefox/24.0",
	} | ({"X-Forwarded-For": X_FORWARDS[config.plugins.plutotv.country.value]} if config.plugins.plutotv.country.value in X_FORWARDS else {})

#def getClips(epid):
#	return getURL(BASE_CLIPS % (epid), header=buildHeader(), life=60 * 60)

def getVOD(epid):
	return getURL(SEASON_VOD % (epid, getUUIDstr()), header=buildHeader(), life=60 * 60)

def getOndemand():
	return getURL(BASE_VOD % (getUUIDstr()), header=buildHeader(), life=60 * 60)

def getChannels():
	return sorted(getURL(BASE_LINEUP % (getUUIDstr()), header=buildHeader(), life=60 * 60), key=lambda x: x["number"])

def getURL(url, param=None, header={"User-agent": "Mozilla/5.0 (Windows NT 6.2; rv:24.0) Gecko/20100101 Firefox/24.0"}, life=60 * 15):
	if param is None:
		param = {}
	now = time.time()
	region = config.plugins.plutotv.country.value
	if not region in RequestCache:
		RequestCache[region] = {}
	if url in RequestCache[region] and RequestCache[region][url][1] > (now - life):
		return RequestCache[region][url][0]
	try:
		req = requests.get(url, param, headers=header, timeout=2)
		req.raise_for_status()
		response = req.json()
		req.close()
		RequestCache[region][url] = (response, now)
		return response
	except Exception: 
		return {}

class PlutoDownloadBase():
	downloadActive = False  # shared between instances

	def __init__(self, silent=False):
		self.bouquetfile = "userbouquet.pluto_tv.tv"
		self.bouquetname = "Pluto TV"
		self.channelsList = {}
		self.guideList = {}
		self.categories = []
		self.bouquet = []
		self.state = 1  # this is a hack
		self.silent = silent
		PlutoDownloadBase.downloadActive = False
		self.epgcache = eEPGCache.getInstance()
	
	def download(self):
		if PlutoDownloadBase.downloadActive:
			if not self.silent:
				res = self.session.openWithCallback(self.close, MessageBox, _("A silent download is in progress."), MessageBox.TYPE_INFO, timeout=30)
			print("[PlutoDownload] A silent download is in progress.")
			return

		PlutoDownloadBase.downloadActive = True
		self.stop()  # is this really necessary
		self.channelsList.clear()  # DownloadSilent is a running instance so clear anything from previous run
		self.guideList.clear()  # DownloadSilent is a running instance so clear anything from previous run
		self.categories.clear()  # DownloadSilent is a running instance so clear anything from previous run
		channels = getChannels()
		guide = self.getGuidedata()
		[self.buildM3U(channel) for channel in channels]
		self.total = len(channels)

		if len(self.categories) == 0:
			self.noCategories(self)
		else:
			if self.categories[0] in self.channelsList:
				self.subtotal = len(self.channelsList[self.categories[0]])
			else:
				self.subtotal = 0
			self.key = 0
			self.chitem = 0
			[self.buildGuide(event) for event in guide]
			self.updateprogress(event=DownloadComponent.EVENT_DONE, param=0)
		PlutoDownloadBase.downloadActive = False

	def updateprogress(self, event=None, param=0, ref=None, name=None):
		if hasattr(self, "state") and self.state == 1:  # hack for exit before end
			if event == DownloadComponent.EVENT_DONE:
				self.updateProgressBar(param)  # GUI widget
				if param < self.total:
					key = self.categories[self.key]
					if self.chitem == self.subtotal:
						self.chitem = 0
						found = False
						while not found:
							self.key = self.key + 1
							key = self.categories[self.key]
							found = key in self.channelsList
						self.subtotal = len(self.channelsList[key])

					if self.chitem == 0:
						self.bouquet.append("1:64:%s:0:0:0:0:0:0:0::%s" % (self.key, self.categories[self.key]))

					channel = self.channelsList[key][self.chitem]
					self.bouquet.append("4097:0:1:%s:0:0:0:0:0:0:%s:%s" % (channel[0], quote(channel[4]), channel[2]))
					self.chitem = self.chitem + 1

					ref = "4097:0:1:%s:0:0:0:0:0:0" % channel[0]
					name = channel[2]
					self.updateStatus(name)  # GUI widget

					chevents = []
					if channel[1] in self.guideList:
						for evt in self.guideList[channel[1]]:
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


					logo = channel[3]
					self.down = DownloadComponent(param + 1, ref, name, not self.silent)
					self.down.addCallback(self.updateprogress)

					self.down.startCmd(logo)
				else:
					eDVBDB.getInstance().addOrUpdateBouquet(self.bouquetname, self.bouquetfile, self.bouquet, False)  # place at bottom if not exists
					os.makedirs(os.path.dirname(TIMER_FILE), exist_ok=True)  # create config folder recursive if not exists
					open(TIMER_FILE, "w").write(str(time.time()))
					self.salirok()
		self.start()

	def buildGuide(self, event):
		#(title, summary, start, duration, genre)
		_id = event.get("_id", "")
		if len(_id) == 0:
			return
		self.guideList[_id] = []
		timelines = event.get("timelines", [])
		chplot = (event.get("description", "") or event.get("summary", ""))
	
	
		for item in timelines:
			episode    = (item.get("episode", {})   or item)
			series     = (episode.get("series", {}) or item)
			epdur      = int(episode.get("duration", "0") or "0") // 1000 # in seconds
			epgenre    = episode.get("genre", "")
			etype      = series.get("type", "film")
	
			genre = self.convertgenre(epgenre)
	
			offset = datetime.datetime.now() - datetime.datetime.utcnow()
			try:
				starttime  = self.strpTime(item["start"]) + offset
			except:
				return
			start = time.mktime(starttime.timetuple())
			title      = (item.get("title", ""))
			tvplot     = (series.get("description", "") or series.get("summary", "") or chplot)
			epnumber   = episode.get("number", 0)
			epseason   = episode.get("season", 0)
			epname     = (episode["name"])
			epmpaa     = episode.get("rating", "")
			epplot     = (episode.get("description", "") or tvplot or epname)
	
			if len(epmpaa) > 0 and not "Not Rated" in epmpaa:
				epplot = "(%s). %s" % (epmpaa, epplot)
	
			noserie = "live film"
			if epseason > 0 and epnumber > 0 and etype not in noserie:
				title = title + " (T%d)" % epseason
				epplot = "T%d Ep.%d %s" % (epseason, epnumber, epplot)
	
			if epdur > 0:
				self.guideList[_id].append((title, epplot, start, epdur, genre))

	def buildM3U(self, channel):
		#(number, _id, name, logo, url)
		logo = (channel.get("logo", {}).get("path", None) or None)
		logo = (channel.get("solidLogoPNG", {}).get("path", None) or None) #blancos
		logo = (channel.get("colorLogoPNG", {}).get("path", None) or None)
		group = channel.get("category", "")
		_id = channel["_id"]
	
		urls  = channel.get("stitched", {}).get("urls", [])
		if len(urls) == 0: 
			return False
	
		if isinstance(urls, list):
			urls = [url["url"].replace("deviceType=&", "deviceType=web&").replace("deviceMake=&", "deviceMake=Chrome&").replace("deviceModel=&", "deviceModel=Chrome&").replace("appName=&", "appName=web&") for url in urls if url["type"].lower() == "hls"][0] # todo select quality
	
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
		if genre  in ("Classics", "Romance", "Thrillers", "Horror") or "Sci-Fi" in genre or "Action" in genre:
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
	def getGuidedata(full=False):
		start = (datetime.datetime.fromtimestamp(PlutoDownloadBase.getLocalTime()).strftime("%Y-%m-%dT%H:00:00Z"))
		stop = (datetime.datetime.fromtimestamp(PlutoDownloadBase.getLocalTime()) + datetime.timedelta(hours=24)).strftime("%Y-%m-%dT%H:00:00Z")
	
		if full:
			return getURL(GUIDE_URL %(start, stop, getUUIDstr()), header=buildHeader(), life=60 * 60)
		else:
			return sorted((getURL(BASE_GUIDE %(start, stop, getUUIDstr()), header=buildHeader(), life=60 * 60)), key=lambda x: x["number"])

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

	def salirok(self, answer=True):
		pass

	def updateProgressBar(self, param):
		pass
	
	def updateStatus(self, name):
		pass


class PlutoDownload(PlutoDownloadBase, Screen):
	skin = f"""
		<screen name="PlutoTVdownload" position="60,60" resolution="1920,1080" size="615,195" title="PlutoTV EPG Download" flags="wfNoBorder" backgroundColor="#ff000000">
		<ePixmap position="0,0" size="615,195" pixmap="{PLUGIN_FOLDER}/images/backgroundHD.png" zPosition="-1" alphatest="blend" />
		<ePixmap position="15,55" size="120,80" pixmap="{PLUGIN_FOLDER}/plutotv.png" scale="1" alphatest="blend" transparent="1" zPosition="10"/>
		<widget name="action" halign="left" valign="center" position="13,9" size="433,30" font="Regular;25" foregroundColor="#dfdfdf" transparent="1" backgroundColor="#000000" borderColor="black" borderWidth="1" noWrap="1"/>
		<widget name="progress" position="150,97" size="420,12" borderWidth="0" backgroundColor="#1143495b" pixmap="{PLUGIN_FOLDER}/images/progresoHD.png" zPosition="2" alphatest="blend" />
		<eLabel name="fondoprogreso" position="150,97" size="420,12" backgroundColor="#102a3b58" />
		<widget name="wait" valign="center" halign="center" position="150,63" size="420,30" font="Regular;22" foregroundColor="#dfdfdf" transparent="1" backgroundColor="#000000" borderColor="black" borderWidth="1" noWrap="1"/>
		<widget name="status" halign="center" valign="center" position="150,120" size="420,30" font="Regular;24" foregroundColor="#ffffff" transparent="1" backgroundColor="#000000" borderColor="black" borderWidth="1" noWrap="1"/>
		</screen>"""

	def __init__(self, session, args = ""):
		self.session = session
		Screen.__init__(self, session)
		PlutoDownloadBase.__init__(self)
		self.total = 0
		self["progress"] = ProgressBar()
		self["action"] = Label(_("EPG Download: %s Pluto TV") % args)
		self["wait"] = Label("")
		self["status"] = Label(_("Please wait..."))
		self["actions"] = ActionMap(["OkCancelActions"], {"cancel": self.salir}, -1)
		self.onFirstExecBegin.append(self.init)

	def init(self):
		self["progress"].setValue(0)
		self.TimerTemp = eTimer()
		self.TimerTemp.callback.append(self.download)
		self.TimerTemp.startLongTimer(1)

	def salir(self):
			stri = _("The download is in progress. Exit now?")
			self.session.openWithCallback(self.salirok, MessageBox, stri, MessageBox.TYPE_YESNO, timeout = 30)
			
	def salirok(self, answer=True):
		if answer:
			Silent.stop()
			Silent.start()
			self.close(True)

	def updateProgressBar(self, param):
		try:
			progress = ((param + 1) * 100) // self.total
		except:
			progress = 100
		else:
			if progress > 100:
				progress = 100
		self["progress"].setValue(progress)
		self["wait"].text = str(progress) + " %"

	def updateStatus(self, name):
		self["status"].text = _("Waiting for Channel: ") + name

	def noCategories(self):
		self.session.openWithCallback(self.salirok, MessageBox, _("There is no data, it is possible that Pluto TV is not available in your country"), type=MessageBox.TYPE_ERROR, timeout=10)

class DownloadSilent(PlutoDownloadBase):
	def __init__(self):
		PlutoDownloadBase.__init__(self)
		self.timer = eTimer()
		self.timer.timeout.get().append(self.download)

	def init(self, session):  # called on session start
		self.session = session
		bouquets = open("/etc/enigma2/bouquets.tv", "r").read()
		if "pluto_tv" in bouquets:
			self.start()

	def start(self):
		minutes = 60 * 5
		if fileExists(TIMER_FILE):
			last = float(open(TIMER_FILE, "r").read().replace("\n", "").replace("\r", ""))
			minutes -= int((time.time() - last) / 60)
			if minutes < 0:
				minutes = 1  # do we want to do this so close to reboot
		self.timer.startLongTimer(minutes * 60)

	def stop(self):
		self.timer.stop()

	def noCategories(self):
		print("[Pluto TV] There is no data, it is possible that Pluto TV is not available in your country.")
		self.stop()
		os.makedirs(os.path.dirname(TIMER_FILE), exist_ok=True)  # create config folder recursive if not exists
		open(TIMER_FILE, "w").write(str(time.time()))
		self.start()


Silent = DownloadSilent()
