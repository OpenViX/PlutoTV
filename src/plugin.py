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
from . import PlutoDownload
from .Variables import RESUMEPOINTS_FILE, TIMER_FILE, DATA_FOLDER, PLUGIN_FOLDER

from skin import applySkinFactor, fonts

from Components.ActionMap import ActionMap
from Components.AVSwitch import AVSwitch
from Components.Button import Button
from Components.config import config
from Components.Label import Label
from Components.MenuList import MenuList
from Components.MultiContent import MultiContentEntryText, MultiContentEntryPixmapAlphaBlend
from Components.Pixmap import Pixmap
from Components.ServiceEventTracker import ServiceEventTracker
from Components.Sources.StaticText import StaticText
from Plugins.Plugin import PluginDescriptor
from Screens.InfoBar import MoviePlayer
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Tools.Directories import fileExists, pathExists, isPluginInstalled, resolveFilename, SCOPE_CURRENT_SKIN
from Tools.LoadPixmap import LoadPixmap
from Tools import Notifications

from enigma import BT_KEEP_ASPECT_RATIO, BT_SCALE, eConsoleAppContainer, eListboxPythonMultiContent, ePicLoad, eServiceReference, eTimer, gFont, iPlayableService

import os
from pickle import load as pickle_load, dump as pickle_dump, HIGHEST_PROTOCOL as pickle_HIGHEST_PROTOCOL
from time import time, strftime, gmtime, localtime
from urllib.parse import quote


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
			pickle_dump(self.resumePointCache, f, pickle_HIGHEST_PROTOCOL)

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
			entry[0] = int(time()) # update LRU timestamp
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
	EVENT_DOWNLOAD = 0
	EVENT_DONE = 1
	EVENT_ERROR = 2

	def __init__(self, __type):
		self.cmd = eConsoleAppContainer()
		self.callbackList = []
		self.type = __type

	def startCmd(self, name, url):
		if not name:
			return
		os.makedirs(DATA_FOLDER, exist_ok=True)  # create data folder if not exists

		rute = 'wget'
		filename = os.path.join(DATA_FOLDER, name)
		
		rute = rute + ' -O ' + filename
		
		self.filename = filename
		rute = rute + ' ' + url

		if fileExists(filename):
			self.callCallbacks(self.EVENT_DONE, self.filename, self.type)
		else:
			self.runCmd(rute)

	def runCmd(self, cmd):
		print("[DownloadPosters] runCmand, executing", cmd)
		self.cmd.appClosed.append(self.cmdFinished)
		if self.cmd.execute(cmd):
			self.cmdFinished(-1)

	def cmdFinished(self, retval):
		self.callCallbacks(self.EVENT_DONE, self.filename, self.type)
		self.cmd.appClosed.remove(self.cmdFinished)

	def callCallbacks(self, event, filename=None, __type=None):
		for callback in self.callbackList:
			callback(event, filename, __type)

	def addCallback(self, callback):
		self.callbackList.append(callback)

	def removeCallback(self, callback):
		self.callbackList.remove(callback)

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
		res = [(name,data,_id,epid)]

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
				if self.cine_half_png and (last > 900000) and (not length  or (last < length - 900000)):
					png = self.cine_half_png
				elif self.cine_end_png and last >= length - 900000:
					png = self.cine_end_png
	
		res.append(MultiContentEntryText(pos=applySkinFactor(45, 7), size=applySkinFactor(533, 35), font=0, text=name))
		if png:
			res.append(MultiContentEntryPixmapAlphaBlend(pos=applySkinFactor(7, 9), size=applySkinFactor(20, 20), png=png, flags=BT_SCALE | BT_KEEP_ASPECT_RATIO))
		return res


class PlutoTV(Screen):
	skin = f"""
		<screen name="PlutoTV" zPosition="2" position="0,0" resolution="1920,1080" size="1920,1080" flags="wfNoBorder" title="Pluto TV" transparent="0">
		<ePixmap pixmap="{PLUGIN_FOLDER}/images/fondo.png" position="0,0" size="1920,1080" zPosition="-2" alphatest="blend" />
		<widget name="logo" position="70,30" size="300,90" zPosition="0" alphatest="blend" transparent="1" />
		<widget source="global.CurrentTime" render="Label" position="1555,48" size="300,55" font="Regular; 43" halign="right" zPosition="5" backgroundColor="#00000000" transparent="1">
			<convert type="ClockToText">Format:%H:%M</convert>
		</widget>
		<widget name="loading" position="560,440" size="800,200" font="Regular; 60" backgroundColor="#00000000" transparent="0" zPosition="10" halign="center" valign="center" />
		<widget name="playlist" render="FixedLabel" position="400,48" size="1150,55" font="Regular; 40" backgroundColor="#00000000" transparent="1" foregroundColor="#00AB2A3E" zPosition="2" halign="center" />
		<widget name="feedlist" position="70,170" size="615,728" scrollbarMode="showOnDemand" enableWrapAround="1" transparent="1" zPosition="5" foregroundColor="#00ffffff" backgroundColorSelected="#00ff0063" backgroundColor="#00000000" />
		<widget name="poster" position="772,235" size="483,675" zPosition="3" alphatest="blend" />
		<widget source="description" position="1282,270" size="517,347" render="RunningText" options="movetype=swimming,startpoint=0,direction=top,steptime=140,repeat=5,always=0,startdelay=8000,wrap" font="Regular; 28" backgroundColor="#00000000" foregroundColor="#00ffffff" transparent="0" valign="top" />
		<widget name="vtitle" position="775,180" size="1027,48" font="Regular; 37" backgroundColor="#00000000" foregroundColor="#00ffff00" transparent="1" />
		<widget name="vinfo" position="1282,235" size="517,48" font="Regular; 25" backgroundColor="#00000000" foregroundColor="#009B9B9B" transparent="1" />
		<widget name="eptitle" position="1282,627" size="517,33" font="Regular; 28" backgroundColor="#00000000" foregroundColor="#00ffff00" transparent="1" />
		<widget source="epinfo" position="1282,667" size="517,246" render="RunningText" options="movetype=swimming,startpoint=0,direction=top,steptime=140,repeat=5,always=0,startdelay=8000,wrap" font="Regular; 28" backgroundColor="#00000000" foregroundColor="#00ffffff" transparent="1" />
		<widget name="help" position="70,980" size="615,48" font="Regular; 25" backgroundColor="#00000000" foregroundColor="#009B9B9B" transparent="0" halign="center"/>
		<eLabel position="770,956" size="30,85" backgroundColor="#00FF0000" />
		<eLabel position="1100,956" size="30,85" backgroundColor="#00ffff00" />
		<eLabel position="1430,956" size="30,85" backgroundColor="#0032cd32" /> 
		<widget source="key_red" render="Label" position="810,956" size="290,85" valign="center" font="Regular; 30" backgroundColor="#00000000" foregroundColor="#00ffffff" transparent="1" />
		<widget source="key_yellow" render="Label" position="1140,956" size="290,85" valign="center" font="Regular; 30" backgroundColor="#00000000" foregroundColor="#00ffffff" transparent="1" />
		<widget source="key_green" render="Label" position="1470,956" size="425,85" valign="center" font="Regular; 30" backgroundColor="#00000000" foregroundColor="#00ffffff" transparent="0" /> 
		</screen>"""

	def __init__(self, session):
		self.session = session
		Screen.__init__(self, session)

		self['feedlist'] = PlutoList([])
		self['playlist'] = Label(_("VOD Menu"))
		self["loading"] = Label(_("Loading data... Please wait"))
		self['description'] = StaticText()
		self['vtitle'] = Label()
		self['vinfo'] = Label()
		self['eptitle'] = Label()
		self['epinfo'] = StaticText()
		self['key_red'] = StaticText(_("Exit"))
		self['key_yellow'] = StaticText()
		self.mdb = isPluginInstalled("tmdb") and "tmdb" or isPluginInstalled("IMDb") and "imdb"
		self.yellowLabel = _("TMDb Search") if self.mdb else (_("IMDb Search") if self.mdb else "")
		self['key_green'] = StaticText()
		self['poster'] = Pixmap()
		self["logo"] = Pixmap()
		self["help"] = Label(_("Press back or < to go back in the menus"))

		self['vtitle'].hide()
		self['vinfo'].hide()
		self['eptitle'].hide()
		self["help"].hide()

		self['feedlist'].onSelectionChanged.append(self.update_data)
		self.films = []
		self.menu = []
		self.history = []
		self.chapters = {}
		self.titlemenu = _("Menu")

		sc = AVSwitch().getFramebufferScale()
		self.picload = ePicLoad()
		self.picload.setPara((applySkinFactor(200), applySkinFactor(60), sc[0], sc[1], 0, 0, '#00000000'))
		self.picload.PictureData.get().append(self.showback)
		self.picload.startDecode(f"{PLUGIN_FOLDER}/images/logo.png")

		self.oldService = self.session.nav.getCurrentlyPlayingServiceReference()
		self.session.nav.stopService()

		self["actions"] = ActionMap(["SetupActions", "ColorActions", "InfobarChannelSelection"],
		{
			"ok": self.action,
			"cancel": self.exit,
			"save": self.green,
			"yellow": self.MDB,
			"historyBack": self.back,
		}, -1)

		self.updatebutton()

		self.TimerTemp = eTimer()
		self.TimerTemp.callback.append(self.getCategories)
		self.TimerTemp.startLongTimer(1)

	def showback(self, picInfo = None):
		try:
			ptr = self.picload.getData()
			if ptr != None:
				self['logo'].setPixmap(ptr.__deref__())
				self['logo'].show()
		except Exception as ex:
			print('[PlutoScreen] showImage, ERROR', ex)

	def update_data(self):
		if len(self['feedlist'].list) == 0:
			return
		index, name, __type, _id = self.getSelection()
		picname = None
		self["key_yellow"].text = ""
		if __type == "menu":
			self['poster'].hide()

		if __type in ("movie", "series"):
			film = self.films[index]
			self['description'].setText(film[2].decode('utf-8'))
			self['vtitle'].setText(film[1].decode('utf-8'))
			info = film[4].decode('utf-8') + "       "
			self["key_yellow"].text = self.yellowLabel

			if __type == "movie":
				info = info + strftime('%Hh %Mm', gmtime(int(film[5])))
			else:
				info = info + str(film[10]) + " " + _("Seasons available")
			self['vinfo'].setText(info)
			picname = film[0] + '.jpg'
			pic = film[6]
			if len(picname)>5:
				self['poster'].hide()
				down = DownloadPosters("poster")
				down.addCallback(self.downloadPostersCallback)
				down.startCmd(picname, pic)

		if __type == "seasons":
			self['eptitle'].hide()
			self['epinfo'].setText("")

		if __type == "episode":
			film = self.chapters[_id][index]
			self['epinfo'].setText(film[3].decode('utf-8'))
			self['eptitle'].setText(film[1].decode('utf-8') + "  " + strftime('%Hh %Mm', gmtime(int(film[5]))))
			self['eptitle'].show()


	def downloadPostersCallback(self, event, filename=None, __type=None):
		if __type == "poster" and filename:
			self.decodePoster(filename)

	def decodePoster(self,image):
		try:
			x, y = self['poster'].getSize()
			picture = image.replace("\n","").replace("\r","")
			sc = AVSwitch().getFramebufferScale()
			self.picload.setPara((x,
			 y,
			 sc[0],
			 sc[1],
			 0,
			 0,
			 '#00000000'))
			l = self.picload.PictureData.get()
			del l[:]
			l.append(self.showImage)
			self.picload.startDecode(picture)
		except Exception as ex:
			print('[PlutoScreen] decodeImage, ERROR', ex)

	def showImage(self, picInfo = None):
		try:
			ptr = self.picload.getData()
			if ptr != None:
				self['poster'].setPixmap(ptr.__deref__())
				self['poster'].show()
		except Exception as ex:
			print('[PlutoScreen] showImage, ERROR', ex)

	def getCategories(self):
		self.lvod = {}
		ondemand = PlutoDownload.getOndemand()
		self.menuitems = int(ondemand.get('totalCategories','0'))
		categories = ondemand.get('categories',[])
		if not categories:
			self.session.openWithCallback(self.exit, MessageBox, _('There is no data, it is possible that Pluto TV is not available in your Country'), type=MessageBox.TYPE_ERROR, timeout=10)
		else:
			[self.buildlist(category) for category in categories]
			list = []
			for key in self.menu:
				list.append(self['feedlist'].listentry(key.decode('utf-8'),"menu",""))
			self["feedlist"].setList(list)
			self["loading"].hide()

	def buildlist(self, category):
		name = category['name'].encode('utf-8')
		self.lvod[name]=[]

		self.menu.append(name)
		items = category.get('items',[])
		for item in items:
			#film = (_id,name,summary,genre,rating,duration,poster,image,type)
			itemid = item.get('_id','')
			if len(itemid) == 0:
				continue
			film = {}
			itemname = item.get('name','').encode('utf-8')
			itemsummary = item.get('summary','').encode('utf-8')
			itemgenre = item.get('genre','').encode('utf-8')
			itemrating = item.get('rating','').encode('utf-8')
			itemduration = int(item.get('duration','0') or '0') // 1000 #in seconds
			itemimgs = item.get('covers',[])
			itemtype = item.get('type','')
			seasons = len(item.get('seasonsNumbers',[]))
			itemimage = ''
			itemposter = ''
			urls = item.get('stitched',{}).get('urls',[])
			if len(urls)>0:
				url = urls[0].get('url','')
			else:
				url = ""

			if len(itemimgs)>2:
				itemimage = itemimgs[2].get('url','')
			if len(itemimgs)>1 and len(itemimage) == 0:
				itemimage = itemimgs[1].get('url','')
			if len(itemimgs)>0:
				itemposter = itemimgs[0].get('url','')
			self.lvod[name].append((itemid, itemname, itemsummary, itemgenre, itemrating, itemduration, itemposter,itemimage, itemtype, url, seasons))

	def buildchapters(self,chapters):
		self.chapters.clear()
		items = chapters.get('seasons',[])
		for item in items:
				chs = item.get('episodes',[])
				for ch in chs:
					season = str(ch.get('season',0))
					if season != '0':
						if season not in self.chapters:
							self.chapters[season] = []
						_id = ch.get('_id','')
						name = ch.get('name','').encode('utf-8')
						number = str(ch.get('number',0))
						summary = ch.get('description','').encode('utf-8')
						rating = ch.get('rating','')
						duration = ch.get('duration',0) // 1000
						genre = ch.get('genre','').encode('utf-8')
						imgs = ch.get('covers',[])
						urls = ch.get('stitched',{}).get('urls',[])
						if len(urls)>0:
							url = urls[0].get('url','')

						itemimage = ''
						itemposter = ''
						if len(imgs)>2:
							itemimage = imgs[2].get('url','')
						if len(imgs)>1 and len(itemimage) == 0:
							itemimage = imgs[1].get('url','')
						if len(imgs)>0:
							itemposter = imgs[0].get('url','')
						self.chapters[season].append((_id,name,number,summary,rating,duration,genre,itemposter,itemimage,url))


	def getSelection(self):
		index = self['feedlist'].getSelectionIndex()
		data = self['feedlist'].getCurrent()[0]
		return index, data[0], data[1], data[2]


	def action(self):
		index, name, __type, _id = self.getSelection()
		menu = []
		menuact = self.titlemenu
		if __type == "menu":
			self.films = self.lvod[self.menu[index]]
			for x in self.films:
				sname = x[1].decode('utf-8')
				stype = x[8]
				sid = x[0]
				menu.append(self['feedlist'].listentry(sname, stype, sid))
			self["feedlist"].moveToIndex(0)
			self["feedlist"].setList(menu)
			self.titlemenu = name
			self["playlist"].setText(self.titlemenu)
			self.history.append((index,menuact))
			self['vtitle'].show()
			self['vinfo'].show()
			self["help"].show()
		if __type == "series":
			chapters = PlutoDownload.getVOD(_id)
			self.buildchapters(chapters)
			for key in list(self.chapters.keys()):
				sname = key
				stype = "seasons"
				sid = key
				menu.append(self['feedlist'].listentry(_("Season") + " " + sname, stype, sid))
			self["feedlist"].setList(menu)
			self.titlemenu = name + " - " + _("Seasons")
			self["playlist"].setText(self.titlemenu)
			self.history.append((index,menuact))
			self["feedlist"].moveToIndex(0)			
		if __type == "seasons":
			for key in self.chapters[_id]:
				sname = key[1].decode('utf-8')
				stype = "episode"
				sid = key[0]
				menu.append(self['feedlist'].listentry(_("Episode") + " " + key[2] + ". " + sname, stype, _id,key[0]))
			self["feedlist"].setList(menu)
			self.titlemenu = menuact.split(" - ")[0] + " - " + name
			self["playlist"].setText(self.titlemenu)
			self.history.append((index,menuact))
			self["feedlist"].moveToIndex(0)
		if __type == "movie":
			film = self.films[index]
			sid = film[0]
			name = film[1].decode('utf-8')
			sessionid, deviceid = PlutoDownload.getUUID()
			url = film[9]
			self.playVOD(name,sid,url)
		if __type == "episode":
			film = self.chapters[_id][index]
			sid = film[0]
			name = film[1]
			sessionid, deviceid = PlutoDownload.getUUID()
			url = film[9]
			self.playVOD(name, sid, url)
			

	def back(self):
		index, name, __type, _id = self.getSelection()
		menu = []
		if self.history:
			hist = self.history[-1][0]
			histname = self.history[-1][1]
			if __type in ("movie", "series"):
				for key in self.menu:
					menu.append(self['feedlist'].listentry(key.decode('utf-8'), 'menu', ''))
				self["help"].hide()
				self['description'].setText("")
				self['vtitle'].hide()
				self['vinfo'].hide()
			if __type == "seasons":
				for x in self.films:
					sname = x[1].decode('utf-8')
					stype = x[8]
					sid = x[0]
					menu.append(self['feedlist'].listentry(sname, stype, sid))
			if __type == "episode":
				for key in list(self.chapters.keys()):
					sname = str(key)
					stype = "seasons"
					sid = str(key)
					menu.append(self['feedlist'].listentry(_("Season") + " " + sname, stype, sid))
			self["feedlist"].setList(menu)
			self.history.pop()
			self["feedlist"].moveToIndex(hist)
			self.titlemenu = histname
			self["playlist"].setText(self.titlemenu)
			if not self.history:
				self['poster'].hide()

	def playVOD(self, name, id, url=None):
#		data = PlutoDownload.getClips(id)[0]
#		if not data: return
#		url   = (data.get('url','') or data.get('sources',[])[0].get('file',''))
#		url = url.replace('siloh.pluto.tv','dh7tjojp94zlv.cloudfront.net') ## Hack for siloh.pluto.tv not access - siloh.pluto.tv redirect to dh7tjojp94zlv.cloudfront.net
		if url:
			uid, did = PlutoDownload.getUUID()
			url = url.replace("deviceModel=","deviceModel=web").replace("deviceMake=","deviceMake=chrome") + uid
			
		if url and name:
			string = '4097:0:0:0:0:0:0:0:0:0:%s:%s' % (quote(url), quote(name))
			reference = eServiceReference(string)
			if 'm3u8' in url.lower():
				self.session.openWithCallback(self.returnplayer, Pluto_Player, service=reference, sid=id)

	def green(self):
		self.session.openWithCallback(self.endupdateLive, PlutoDownload.PlutoDownload)

	def endupdateLive(self,ret=None):
		self.session.openWithCallback(self.updatebutton, MessageBox, _('You now have an updated favorites list with Pluto TV channels on your channel list.\n\nEverything will be updated automatically every 5 hours.'), type=MessageBox.TYPE_INFO, timeout=10)

	def returnplayer(self):
		menu = []
		for l in self["feedlist"].list:
			menu.append(self['feedlist'].listentry(l[0][0],l[0][1],l[0][2],l[0][3]))
		self["feedlist"].setList(menu)

	def updatebutton(self,ret=None):
		bouquets = open("/etc/enigma2/bouquets.tv","r").read()
		if fileExists(TIMER_FILE) and "pluto_tv" in bouquets:
			last = float(open(TIMER_FILE, "r").read().replace("\n", "").replace("\r", ""))
			txt = _("Last:") + strftime(' %x %H:%M', localtime(int(last)))
			self["key_green"].setText(_("Update LiveTV Bouquet") + "\n" + txt)
		else:
			self["key_green"].setText(_("Create LiveTV Bouquet"))

	def exit(self, *args, **kwargs):
		if self.history:
			self.back()
		else:
			self.session.nav.playService(self.oldService)
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


class Pluto_Player(MoviePlayer):

	ENABLE_RESUME_SUPPORT = False    # Don't use Enigma2 resume support. We use self resume support

	def __init__(self, session, service, sid):
		self.session = session
		self.mpservice = service
		self.id = sid
		MoviePlayer.__init__(self, self.session, service, sid)
		self.end = False
		self.started = False
		self.skinName = ["MoviePlayer" ]

		self.__event_tracker = ServiceEventTracker(screen=self, eventmap=
			{
				iPlayableService.evStart: self.__serviceStarted,
#				iPlayableService.evBuffering: self.__serviceStarted,
#				iPlayableService.evVideoSizeChanged: self.__serviceStarted,
				iPlayableService.evEOF: self.__evEOF,
			})


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
		ref = self.session.nav.getCurrentlyPlayingServiceReference()
		last, length = resumePointsInstance.getResumePoint(self.id)
		if last is None or seekable is None:
			return
		length = seekable.getLength() or (None,0)
		print("seekable.getLength() returns:", length)
		# Hmm, this implies we don't resume if the length is unknown...
		if (last > 900000) and (not length[1]  or (last < length[1] - 900000)):
			self.last = last
			l = last / 90000
			Notifications.AddNotificationWithCallback(self.playLastCB, MessageBox, _("Do you want to resume this playback?") + "\n" + (_("Resume position at %s") % ("%d:%02d:%02d" % (l/3600, l%3600/60, l%60))), timeout=10, default="yes" in config.usage.on_movie_start.value)

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
	PlutoDownload.Silent.init(session)

def Download_PlutoTV(session, **kwargs):
	session.open(PlutoDownload.PlutoDownload)


def system(session, **kwargs):
	session.open(PlutoTV)


def Plugins(**kwargs):
	list = []
	list.append(PluginDescriptor(name=_("PlutoTV"), where = PluginDescriptor.WHERE_PLUGINMENU, icon="plutotv.png", description=_("View Pluto TV VOD & Download Bouquet for LiveTV Channels"), fnc=system, needsRestart=True))
	list.append(PluginDescriptor(name=_("Download PlutoTV Bouquet, picons & EPG"), where = PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=Download_PlutoTV, needsRestart=True))
	list.append(PluginDescriptor(name=_("Silent Download PlutoTV"), where = PluginDescriptor.WHERE_SESSIONSTART, fnc=autostart)) 
	return list
