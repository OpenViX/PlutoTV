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
from . import py3, esHD, _

from Screens.Screen import Screen
from Plugins.Plugin import PluginDescriptor
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Button import Button
from Components.Pixmap import Pixmap
from Components.AVSwitch import AVSwitch
from Components.Sources.StaticText import StaticText
from Tools.Directories import fileExists, pathExists

from enigma import eServiceReference, eConsoleAppContainer, ePicLoad, eTimer, iPlayableService
import os, sys
if py3():
	from urllib.parse import quote
else:
	from urllib import quote
from Components.config import config

from . import PlutoDownload

from Components.MenuList import MenuList
from Components.MultiContent import MultiContentEntryText, MultiContentEntryPixmapAlphaBlend
from enigma import eListboxPythonMultiContent, gFont, BT_SCALE, BT_KEEP_ASPECT_RATIO
from Tools.LoadPixmap import LoadPixmap
from Components.ServiceEventTracker import ServiceEventTracker
from Screens.MessageBox import MessageBox
from Tools import Notifications
from time import time, strftime, gmtime, localtime


from Screens.InfoBar import MoviePlayer

files = os.listdir("/media/")
FOLDER = None
if "hdd" in files:
	FOLDER = "/media/hdd/PlutoTV"

if "usb" in files and FOLDER == None:
	FOLDER = "/media/usb/PlutoTV"

if FOLDER == None:
	for filename in files:
		if (filename.startswith("usb") or filename.startswith("sd") or filename.startswith("mmc")) and FOLDER == None:
			FOLDER = "/media/"+filename

if not FOLDER:
	FOLDER = "/tmp/PlutoTV"

if not pathExists(FOLDER):
	os.system("mkdir " + FOLDER)

	
def fhd(num, factor=1.5):
	if esHD():
		prod=num*factor
	else: prod=num
	return int(round(prod))

def fontHD(nombre):
	if esHD():
		fuente = nombre+"HD"
	else:
		fuente = nombre
	return fuente

def setResumePoint(session, sid=None):
	global resumePointCacheLast, resumePointCache
	service = session.nav.getCurrentService()
	ref = session.nav.getCurrentlyPlayingServiceReference()
	if (service is not None) and (ref is not None): 
		seek = service.seek()
		if seek:
			pos = seek.getPlayPosition()
			if not pos[0]:
				key = sid
				lru = int(time())
				l = seek.getLength()
				if l:
					l = l[1]
				else:
					l = None
				position = pos[1]
				resumePointCache[key] = [lru, position, l]
				saveResumePoints(session,sid)

def getResumePoint(sid):
	global resumePointCache
	resumePointCache = loadResumePoints(sid)
	if (sid is not None):
		try:
			entry = resumePointCache[sid]
			entry[0] = int(time()) # update LRU timestamp
			last = entry[1]
			length = entry[2]
		except KeyError:
			last = None
			length = 0
	return last, length

def saveResumePoints(session,sid):
	global resumePointCacheLast, resumePointCache
	service = session.nav.getCurrentService()
	name = os.path.join(FOLDER,sid)+".cue"
	import pickle
	try:
		f = open(name, 'wb')
		pickle.dump(resumePointCache, f, pickle.HIGHEST_PROTOCOL)
	except Exception as ex:
		print("[InfoBar] Failed to write resumepoints:", ex)

def loadResumePoints(sid):
	name = os.path.join(FOLDER,sid)+".cue"
	import pickle
	try:
		return pickle.load(open(name, 'rb'))
	except Exception as ex:
		print("[InfoBar] Failed to load resumepoints:", ex)
		return {}

resumePointCache = {}



class DownloadPosters:
	EVENT_DOWNLOAD = 0
	EVENT_DONE = 1
	EVENT_ERROR = 2

	def __init__(self,tipo):
		self.cmd = eConsoleAppContainer()
		self.callbackList = []
		self.tipo = tipo

	def startCmd(self, name, url):
		rute = 'wget'
		filename = os.path.join(FOLDER, name)
		if filename:
			rute = rute + ' -O '+filename
		else:
			return
		
		self.filename = filename
		rute = rute + ' ' + url

		if fileExists(filename):
			self.callCallbacks(self.EVENT_DONE, self.filename, self.tipo)
		else:
			self.runCmd(rute)

	def runCmd(self, cmd):
		print("executing", cmd)
		self.cmd.appClosed.append(self.cmdFinished)
		if self.cmd.execute(cmd):
			self.cmdFinished(-1)

	def cmdFinished(self, retval):
		self.callCallbacks(self.EVENT_DONE, self.filename, self.tipo)
		self.cmd.appClosed.remove(self.cmdFinished)



	def callCallbacks(self, event, filename= None, tipo = None):
		for callback in self.callbackList:
			callback(event, filename, tipo)

	def addCallback(self, callback):
		self.callbackList.append(callback)

	def removeCallback(self, callback):
		self.callbackList.remove(callback)

class SelList(MenuList):
	def __init__(self, list, enableWrapAround=False):
		MenuList.__init__(self, list, enableWrapAround, eListboxPythonMultiContent)
		self.l.setItemHeight(fhd(35))
		self.l.setFont(0, gFont(fontHD("Regular"), 19))

def listentry(name, data, _id, epid=0):
	res = [(name,data,_id,epid)]

	if data == "menu":
		picture = "/usr/lib/enigma2/python/Plugins/Extensions/PlutoTV/images/menu.png"
	if data == "series" or data == "seasons":
		picture = "/usr/lib/enigma2/python/Plugins/Extensions/PlutoTV/images/series.png"
	if data == "movie" or data == "episode":
		picture = "/usr/lib/enigma2/python/Plugins/Extensions/PlutoTV/images/cine.png"
		if data == "episode":
			sid = epid
		else:
			sid = _id
		last, length = getResumePoint(sid)
		if last:
			if (last > 900000) and (not length  or (last < length - 900000)):
				picture = "/usr/lib/enigma2/python/Plugins/Extensions/PlutoTV/images/cine_half.png"
			elif last >= length - 900000:
				picture = "/usr/lib/enigma2/python/Plugins/Extensions/PlutoTV/images/cine_end.png"


	res.append(MultiContentEntryText(pos=(fhd(45), fhd(7)), size=(fhd(533), fhd(35)), font=0, text=name))
	if picture != None:
		if fileExists(picture):
			png = LoadPixmap(picture)
			res.append(MultiContentEntryPixmapAlphaBlend(pos=(fhd(7), fhd(9)), size=(fhd(20), fhd(20)), png=png, flags = BT_SCALE | BT_KEEP_ASPECT_RATIO))
		
	return res


class PlutoTV(Screen):
	if esHD():
		skin = """
		<screen name="PlutoTV" zPosition="2" position="0,0" size="1920,1080" flags="wfNoBorder" title="Pluto TV" transparent="0">
		<ePixmap pixmap="/usr/lib/enigma2/python/Plugins/Extensions/PlutoTV/images/fondo.png" position="0,0" size="1920,1080" zPosition="-2" alphatest="blend" />
		<widget name="logo" position="70,30" size="300,90" zPosition="0" alphatest="blend" transparent="1" />
		<widget source="global.CurrentTime" render="Label" position="1555,48" size="300,55" font="Regular; 43" halign="right" zPosition="5" backgroundColor="#00000000" transparent="1">
			<convert type="ClockToText">Format:%H:%M</convert>
		</widget>
		<widget name="loading" position="560,440" size="800,200" font="Regular; 60" backgroundColor="#00000000" transparent="0" zPosition="10" halign="center" valign="center" />
		<widget name="playlist" render="FixedLabel" position="400,48" size="1150,55" font="Regular; 40" backgroundColor="#00000000" transparent="1" foregroundColor="#00AB2A3E" zPosition="2" halign="center" />
		<widget name="feedlist" position="70,170" size="615,743" scrollbarMode="showOnDemand" enableWrapAround="0" transparent="1" zPosition="5" foregroundColor="#00ffffff" backgroundColorSelected="#00ff0063" backgroundColor="#00000000" />
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
		<widget name="red" position="810,956" size="290,85" valign="center" font="Regular; 30" backgroundColor="#00000000" foregroundColor="#00ffffff" transparent="1" />
		<widget name="yellow" position="1140,956" size="290,85" valign="center" font="Regular; 30" backgroundColor="#00000000" foregroundColor="#00ffffff" transparent="1" />
		<widget name="green" position="1470,956" size="425,85" valign="center" font="Regular; 30" backgroundColor="#00000000" foregroundColor="#00ffffff" transparent="0" /> 
		</screen>"""
	else:
		skin = """
		<screen name="PlutoTV" zPosition="2" position="0,0" size="1280,720" flags="wfNoBorder" title="Pluto TV" transparent="0">
		<ePixmap pixmap="/usr/lib/enigma2/python/Plugins/Extensions/PlutoTV/images/fondoSD.png" position="0,0" size="1280,720" zPosition="-2" alphatest="blend" />
		<widget name="logo" position="47,20" size="200,60" zPosition="0" alphatest="blend" transparent="1" />
		<widget source="global.CurrentTime" render="Label" position="1037,32" size="200,36" font="Regular; 29" halign="right" zPosition="5" backgroundColor="#00000000" transparent="1">
			<convert type="ClockToText">Format:%H:%M</convert>
		</widget>
		<widget name="loading" position="373,293" size="533,123" font="Regular; 40" backgroundColor="#00000000" transparent="0" zPosition="10" halign="center" valign="center" />
		<widget name="playlist" render="FixedLabel" position="267,32" size="767,37" font="Regular; 28" backgroundColor="#00000000" transparent="1" foregroundColor="#00AB2A3E" zPosition="2" halign="center" />
		<widget name="feedlist" position="47,113" size="410,495" scrollbarMode="showOnDemand" enableWrapAround="0" transparent="1" zPosition="5" foregroundColor="#00ffffff" backgroundColorSelected="#00ff0063" backgroundColor="#00000000" />
		<widget name="poster" position="515,157" size="322,450" zPosition="3" alphatest="blend" />
		<widget source="description" position="855,180" size="345,231" render="RunningText" options="movetype=swimming,startpoint=0,direction=top,steptime=140,repeat=5,always=0,startdelay=8000,wrap" font="Regular; 19" backgroundColor="#00000000" foregroundColor="#00ffffff" transparent="0" valign="top" />
		<widget name="vtitle" position="517,120" size="685,32" font="Regular; 25" backgroundColor="#00000000" foregroundColor="#00ffff00" transparent="1" />
		<widget name="vinfo" position="855,157" size="345,32" font="Regular; 17" backgroundColor="#00000000" foregroundColor="#009B9B9B" transparent="1" />
		<widget name="eptitle" position="855,418" size="345,22" font="Regular; 19" backgroundColor="#00000000" foregroundColor="#00ffff00" transparent="1" />
		<widget source="epinfo" position="855,445" size="345,164" render="RunningText" options="movetype=swimming,startpoint=0,direction=top,steptime=140,repeat=5,always=0,startdelay=8000,wrap" font="Regular; 19" backgroundColor="#00000000" foregroundColor="#00ffffff" transparent="1" />
		<widget name="help" position="47,653" size="410,32" font="Regular; 17" backgroundColor="#00000000" foregroundColor="#009B9B9B" transparent="0" halign="center"/>
		<eLabel position="513,637" size="20,57" backgroundColor="#00FF0000" />
		<eLabel position="733,637" size="20,57" backgroundColor="#00ffff00" />
		<eLabel position="953,637" size="20,57" backgroundColor="#0032cd32" /> 
		<widget name="red" position="540,637" size="193,57" valign="center" font="Regular; 20" backgroundColor="#00000000" foregroundColor="#00ffffff" transparent="1" />
		<widget name="yellow" position="760,637" size="193,57" valign="center" font="Regular; 20" backgroundColor="#00000000" foregroundColor="#00ffffff" transparent="1" />
		<widget name="green" position="980,637" size="283,55" valign="center" font="Regular; 20" backgroundColor="#00000000" foregroundColor="#00ffffff" transparent="0" /> 
		</screen>"""


	def __init__(self, session):
		self.session = session
		Screen.__init__(self, session)
		self.skinName = "PlutoTV"

		self['feedlist'] = SelList([])
		self['playlist'] = Label(_("VOD Menu"))
		self["loading"] = Label(_("Loading data... Please wait"))
		self['description'] = StaticText()
		self['vtitle'] = Label()
		self['vinfo'] = Label()
		self['eptitle'] = Label()
		self['epinfo'] = StaticText()
		self['red'] = Label(_("Exit"))
		self['yellow'] = Label(_("IMDB"))
		self['green'] = Label()
		self['poster'] = Pixmap()
		self["logo"] = Pixmap()
		self["help"] = Label(_("Press back or < to go back in the menus"))

		self['vtitle'].hide()
		self['vinfo'].hide()
		self['eptitle'].hide()
		self["help"].hide()
		self["yellow"].hide()

		self['feedlist'].onSelectionChanged.append(self.update_data)
		self.films = []
		self.menu = []
		self.history = []
		self.chapters = {}
		self.titlemenu = "Menu"

		sc = AVSwitch().getFramebufferScale()
		self.picload = ePicLoad()
		self.picload.setPara((fhd(200), fhd(60), sc[0], sc[1], 0, 0, '#00000000'))
		self.picload.PictureData.get().append(self.showback)
		self.picload.startDecode("/usr/lib/enigma2/python/Plugins/Extensions/PlutoTV/images/logo.png")

		self.oldService = self.session.nav.getCurrentlyPlayingServiceReference()
		self.session.nav.stopService()

		self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "InfobarChannelSelection"],
		{
			"ok": self.action,
			"cancel": self.exit,
			"red": self.exit,
			"green": self.green,
			"red": self.exit,
			"yellow": self.imdb,
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
				self['logo'].instance.setPixmap(ptr.__deref__())
				self['logo'].instance.show()
		except Exception as ex:
			print(ex)
			print('ERROR showImage')

	def update_data(self):
		if len(self['feedlist'].list) == 0:
			return
		index, name, tipo, _id = self.getSelection()
		picname = None
		self["yellow"].hide()
		if tipo == "menu":
			self['poster'].hide()
		if tipo == "movie" or tipo == "series":
			film = self.films[index]
			if py3():
				self['description'].setText(film[2].decode('utf-8'))
				self['vtitle'].setText(film[1].decode('utf-8'))
				info = film[4].decode('utf-8') + "       "
			else:
				self['description'].setText(film[2])
				self['vtitle'].setText(film[1])
				info = film[4] + "       "

			if tipo=="movie":
				info = info + strftime('%Hh %Mm', gmtime(int(film[5])))
				if fileExists("/usr/lib/enigma2/python/Plugins/Extensions/spzIMDB/plugin.pyo") or fileExists("/usr/lib/enigma2/python/Plugins/Extensions/spzIMDB/plugin.so"):
					self["yellow"].show()
			else:
				info = info + str(film[10]) + " " + _("Seasons available")
			self['vinfo'].setText(info)
			if py3():
				picname = film[0] + '.jpg'
				pic = film[6]
			else:
				picname = film[0].encode("utf-8") + '.jpg'
				pic = film[6].encode("utf-8")
			if len(picname)>5:
				down = DownloadPosters("poster")
				down.addCallback(self.actualizaimg)
				down.startCmd(picname,pic)
		if tipo == "seasons":
			self['eptitle'].hide()
			self['epinfo'].setText("")

		if tipo == "episode":
			film = self.chapters[_id][index]
			if py3():
				self['epinfo'].setText(film[3].decode('utf-8'))
				self['eptitle'].setText(film[1].decode('utf-8') + "  " + strftime('%Hh %Mm', gmtime(int(film[5]))))
			else:
				self['epinfo'].setText(film[3])
				self['eptitle'].setText(film[1] + "  " + strftime('%Hh %Mm', gmtime(long(film[5]))))
			self['eptitle'].show()


	def actualizaimg(self, event, filename=None, tipo=None):
		if tipo == "poster" and filename:
			self.decodePoster(filename)

	def getCategories(self):
		self.lvod = {}
		ondemand = PlutoDownload.getOndemand()
		self.menuitems = int(ondemand.get('totalCategories','0'))
		categories = ondemand.get('categories',[])
		if len(categories) == 0:
			self.session.openWithCallback(self.confirmexit, MessageBox, _('There is no data, it is possible that Puto TV is not available in your Country'), type=MessageBox.TYPE_ERROR, timeout=10)
		else:
			[self.buildlist(categorie) for categorie in categories]
			list = []
			for key in self.menu:
				if py3():
					list.append(listentry(key.decode('utf-8'),"menu",""))
				else:
					list.append(listentry(key,"menu",""))
			self["feedlist"].setList(list)
			self["loading"].hide()

	def buildlist(self,categorie):
		name = categorie['name'].encode('utf-8')
		self.lvod[name]=[]

		self.menu.append(name)
		items = categorie.get('items',[])
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
			self.lvod[name].append((itemid,itemname,itemsummary,itemgenre,itemrating,itemduration,itemposter,itemimage,itemtype,url,seasons))

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
		index, name, tipo, _id = self.getSelection()
		menu = []
		menuact = self.titlemenu
		if tipo == "menu":
			self.films = self.lvod[self.menu[index]]
			for x in self.films:
				if py3():
					sname = x[1].decode('utf-8')
				else:
					sname = x[1]
				stipo = x[8]
				sid = x[0]
				menu.append(listentry(sname,stipo,sid))
			self["feedlist"].moveToIndex(0)
			self["feedlist"].setList(menu)
			self.titlemenu = name
			self["playlist"].setText(self.titlemenu)
			self.history.append((index,menuact))
			self['vtitle'].show()
			self['vinfo'].show()
			self["help"].show()
		if tipo == "series":
			chapters = PlutoDownload.getVOD(_id)
			self.buildchapters(chapters)
			for key in list(self.chapters.keys()):
				sname = key
				stipo = "seasons"
				sid = key
				menu.append(listentry(_("Season") + " " + sname,stipo,sid))
			self["feedlist"].setList(menu)
			self.titlemenu = name + " - " + _("Seasons")
			self["playlist"].setText(self.titlemenu)
			self.history.append((index,menuact))
			self["feedlist"].moveToIndex(0)			
		if tipo == "seasons":
			for key in self.chapters[_id]:
				if py3():
					sname = key[1].decode('utf-8')
				else:
					sname = key[1]
				stipo = "episode"
				sid = key[0]
				menu.append(listentry(_("Episode") + " " + key[2] + ". " + sname,stipo,_id,key[0]))
			self["feedlist"].setList(menu)
			self.titlemenu = menuact.split(" - ")[0] + " - " + name
			self["playlist"].setText(self.titlemenu)
			self.history.append((index,menuact))
			self["feedlist"].moveToIndex(0)
		if tipo == "movie":
			film = self.films[index]
			sid = film[0]
			if py3():
				name = film[1].decode('utf-8')
			else:
				name = film[1]
			sessionid, deviceid = PlutoDownload.getUUID()
			url = film[9]
			self.playVOD(name,sid,url)
		if tipo == "episode":
			film = self.chapters[_id][index]
			sid = film[0]
			name = film[1]
			sessionid, deviceid = PlutoDownload.getUUID()
			url = film[9]
			self.playVOD(name,sid,url)
			

	def back(self):
		index, name, tipo, _id = self.getSelection()
		menu = []
		if len(self.history) > 0:
			hist = self.history[-1][0]
			histname = self.history[-1][1]
			if tipo == "movie" or tipo == "series":
				for key in self.menu:
					if py3():
						menu.append(listentry(key.decode('utf-8'),'menu',''))
					else:
						menu.append(listentry(key,'menu',''))
				self["help"].hide()
				self['description'].setText("")
				self['vtitle'].hide()
				self['vinfo'].hide()
			if tipo == "seasons":
				for x in self.films:
					if py3():
						sname = x[1].decode('utf-8')
					else:
						sname = x[1]
					stipo = x[8]
					sid = x[0]
					menu.append(listentry(sname,stipo,sid))
			if tipo == "episode":
				for key in list(self.chapters.keys()):
					sname = str(key)
					stipo = "seasons"
					sid = str(key)
					menu.append(listentry(_("Season") + " " + sname,stipo,sid))
			self["feedlist"].setList(menu)
			self.history.pop()
			self["feedlist"].moveToIndex(hist)
			self.titlemenu = histname
			self["playlist"].setText(self.titlemenu)

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
				self.session.openWithCallback(self.returnplayer,Pluto_Player, service=reference, sid = id)

	def returnplayer(self):
		menu = []
		for l in self["feedlist"].list:
			menu.append(listentry(l[0][0],l[0][1],l[0][2],l[0][3]))
		self["feedlist"].setList(menu)

	def decodePoster(self,image):
		try:
			x = self['poster'].instance.size().width()
			y = self['poster'].instance.size().height()
			if py3():
				picture = image.replace("\n","").replace("\r","")
			else:
				picture = image.encode('utf-8').replace("\n","").replace("\r","")
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
			print(ex)
			print('ERROR decodeImage')

	def showImage(self, picInfo = None):
		try:
			ptr = self.picload.getData()
			if ptr != None:
				self['poster'].instance.setPixmap(ptr.__deref__())
				self['poster'].instance.show()
		except Exception as ex:
			print(ex)
			print('ERROR showImage')

	def green(self):
		self.session.openWithCallback(self.endupdateLive,PlutoDownload.PlutoDownload)

	def endupdateLive(self,ret=None):
		self.session.openWithCallback(self.updatebutton, MessageBox, _('You now have an updated favorites list with Pluto TV channels on your channel list.\n\nEverything will be updated automatically every 5 hours.'), type=MessageBox.TYPE_INFO, timeout=10)


	def updatebutton(self,ret=None):
		bouquets = open("/etc/enigma2/bouquets.tv","r").read()
		if fileExists("/etc/Plutotv.timer") and "pluto_tv" in bouquets:
			last = float(open("/etc/Plutotv.timer","r").read().replace("\n","").replace("\r",""))
			txt = _("Last:") + strftime(' %x %H:%M', localtime(int(last)))
			self["green"].setText(_("Update LIveTV Bouquet") + "\n" + txt)
		else:
			self["green"].setText(_("Create LiveTV Bouquet"))

	def exit(self):
		self.session.openWithCallback(self.confirmexit, MessageBox, _('Do you really want to leave PlutoTV?'), type=MessageBox.TYPE_YESNO)

	def confirmexit(self,ret=True):
		if ret:
			self.session.nav.playService(self.oldService)
			self.close()

	def imdb(self):
		index, name, tipo, _id = self.getSelection()
		if tipo=="movie" and (fileExists("/usr/lib/enigma2/python/Plugins/Extensions/spzIMDB/plugin.pyo") or fileExists("/usr/lib/enigma2/python/Plugins/Extensions/spzIMDB/plugin.so")):
			try:
				from Plugins.Extensions.spzIMDB.plugin import spzIMDB
				spzIMDB(self.session,tbusqueda=name)
			except:
				pass



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


		self["actions"] = ActionMap(["MoviePlayerActions", "OkCancelActions","NumberActions","EPGSelectActions"],
		{
			"cancel": self.leavePlayer,
			"exit": self.leavePlayer,
			"leavePlayer": self.leavePlayer, 
			"ok":self.toggleShow,
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
		last, length = getResumePoint(self.id)
		if last is None:
			return
		if seekable is None:
			return
		length = seekable.getLength() or (None,0)
		print("seekable.getLength() returns:", length)
		# Hmm, this implies we don't resume if the length is unknown...
		if (last > 900000) and (not length[1]  or (last < length[1] - 900000)):
			self.resume_point = last
			l = last / 90000
			Notifications.AddNotificationWithCallback(self.playLastCB, MessageBox, _("Do you want to resume this playback?") + "\n" + (_("Resume position at %s") % ("%d:%02d:%02d" % (l/3600, l%3600/60, l%60))), timeout=10, default="yes" in config.usage.on_movie_start.value)

	def leavePlayer(self):
		laref=_("Stop play and exit to list movie?")
		try:
			dei = self.session.openWithCallback(self.callbackexit,MessageBox, laref, MessageBox.TYPE_YESNO)
			dei.setTitle(_("Stop play"))				
		except:
			self.callbackexit(True)

	def callbackexit(self,respuesta):
		if respuesta:
			self.is_closing = True
			setResumePoint(self.session,self.id)
			self.close()
			
	def leavePlayerConfirmed(self, answer):
		pass

	def exit(self):
		self.callbackexit(True)


def autostart(reason, session):
	PlutoDownload.Silent.init(session)

def Download_PlutoTV(session, **kwargs):
	session.open(PlutoDownload.PlutoDownload)


def system(session, **kwargs):
	session.open(PlutoTV)


def Plugins(**kwargs):
	list = []
	list.append(PluginDescriptor(name=_("PlutoTV"), where = PluginDescriptor.WHERE_PLUGINMENU, icon="plutotv.png", description=_("View Pluto TV VOD & Download Bouquet for LiveTV Channels"), fnc=system))
	list.append(PluginDescriptor(name=_("Download PlutoTV Bouquet, picons & EPG"), where = PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=Download_PlutoTV))
	list.append(PluginDescriptor(name=_("Silent Download PlutoTV"), where = PluginDescriptor.WHERE_SESSIONSTART, fnc=autostart)) 
	return list
