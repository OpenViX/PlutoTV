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
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.ProgressBar import ProgressBar
from Tools.Directories import fileExists
from Components.Pixmap import Pixmap

from enigma import eDVBDB, eEPGCache, eServiceCenter, eServiceReference, eConsoleAppContainer, eTimer
from Screens.MessageBox import MessageBox
import os, datetime, uuid, time
import json, collections, requests
if py3():
	from urllib.parse import quote
else:
	from urllib import quote
from Components.config import config

BASE_API      = 'https://api.pluto.tv'
GUIDE_URL     = 'https://service-channels.clusters.pluto.tv/v1/guide?start=%s&stop=%s&%s'
BASE_GUIDE    = BASE_API + '/v2/channels?start=%s&stop=%s&%s'
BASE_LINEUP   = BASE_API + '/v2/channels.json?%s'
BASE_VOD      = BASE_API + '/v3/vod/categories?includeItems=true&deviceType=web&%s'
SEASON_VOD    = BASE_API + '/v3/vod/series/%s/seasons?includeItems=true&deviceType=web&%s'
BASE_CLIPS    = BASE_API + '/v2/episodes/%s/clips.json'
BOUQUET       = 'userbouquet.pluto_tv.tv'

ChannelsList = {}
GuideList = {}
Categories = []

sid1_hex = str(uuid.uuid1().hex)
deviceId1_hex = str(uuid.uuid4().hex)
service_types_tv = '1:7:1:0:0:0:0:0:0:0:(type == 1) || (type == 17) || (type == 22) || (type == 25) || (type == 134) || (type == 195)'



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
		rute = 'wget'
		try:
			picon_path = config.misc.picon_path.value
		except:
			picon_path = '/usr/share/enigma2/picon'
		if not os.path.isdir(picon_path):
			os.mkdir(picon_path)
		filename = os.path.join(picon_path, self.ref.replace(":","_") + ".png")
		if filename:
			rute = rute + ' -O '+filename
			self.filename = filename
		else:
			self.filename = cmd.split('/')[-1]
		
		number = self.ref.split(":")
		if len(number[3])>3:
			rute = 'cp /usr/lib/enigma2/python/Plugins/Extensions/PlutoTV/plutotv.png ' +  filename
		else:
			rute = rute + ' ' + cmd

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



	def callCallbacks(self, event, param = None, ref = None, name = None):
		for callback in self.callbackList:
			callback(event, param, ref, name)

	def addCallback(self, callback):
		self.callbackList.append(callback)

	def removeCallback(self, callback):
		self.callbackList.remove(callback)


def sort(elem):
	return elem['number']

def getUUID():
	return sid1_hex, deviceId1_hex

def buildHeader():
	header_dict               = {}
	header_dict['Accept']     = 'application/json, text/javascript, */*; q=0.01'
	header_dict['Host']       = 'api.pluto.tv'
	header_dict['Connection'] = 'keep-alive'
	header_dict['Referer']    = 'http://pluto.tv/'
	header_dict['Origin']     = 'http://pluto.tv'
	header_dict['User-Agent'] = 'Mozilla/5.0 (Windows NT 6.2; rv:24.0) Gecko/20100101 Firefox/24.0'
	return header_dict

def getClips(epid):
	return getURL(BASE_CLIPS%(epid), header=buildHeader(), life=datetime.timedelta(hours=1))

def getVOD(epid):
	return getURL(SEASON_VOD%(epid,'sid=%s&deviceId=%s'%(getUUID())), header=buildHeader(), life=datetime.timedelta(hours=1))

def getOndemand():
	return getURL(BASE_VOD%('sid=%s&deviceId=%s'%(getUUID())), header=buildHeader(), life=datetime.timedelta(hours=1))

def getChannels():
	return sorted(getURL(BASE_LINEUP%('sid=%s&deviceId=%s'%(getUUID())), header=buildHeader(), life=datetime.timedelta(hours=1)), key=sort)

def getURL(url, param={}, header={'User-agent': 'Mozilla/5.0 (Windows NT 6.2; rv:24.0) Gecko/20100101 Firefox/24.0'}, life=datetime.timedelta(minutes=15)):
	cacheresponse = None
	if not cacheresponse:
		try:
			req = requests.get(url, param, headers=header)
			cacheresponse = req.json()
			req.close()
		except Exception as e: 
			return {}
		return cacheresponse
	else: 
		return json.loads(cacheresponse)

def getLocalTime():
	offset = (datetime.datetime.utcnow() - datetime.datetime.now())
	return time.time() + offset.total_seconds()

def getGuidedata(full=False):
	try:
		last_day = int(config.epg.maxdays.value)
	except:
		last_day = 7
	if last_day > 7:
		last_day = 7
	start = (datetime.datetime.fromtimestamp(getLocalTime()).strftime('%Y-%m-%dT%H:00:00Z'))
	stop = (datetime.datetime.fromtimestamp(getLocalTime()) + datetime.timedelta(hours=24)).strftime('%Y-%m-%dT%H:00:00Z')

	if full: return getURL(GUIDE_URL %(start,stop,'sid=%s&deviceId=%s'%(getUUID())), life=datetime.timedelta(hours=1))
	else: return sorted((getURL(BASE_GUIDE %(start,stop,'sid=%s&deviceId=%s'%(getUUID())), life=datetime.timedelta(hours=1))), key=sort)

def buildM3U(channel):
	#(number,_id,name,logo,url)
	logo  = (channel.get('logo',{}).get('path',None) or None)

	logo = (channel.get('solidLogoPNG',{}).get('path',None) or None) #blancos
	logo = (channel.get('colorLogoPNG',{}).get('path',None) or None)
	group = channel.get('category','')
	_id = channel['_id']

	urls  = channel.get('stitched',{}).get('urls',[])
	if len(urls) == 0: 
		return False

	if isinstance(urls, list):
		urls = [url['url'].replace('deviceType=&','deviceType=web&').replace('deviceMake=&','deviceMake=Chrome&').replace('deviceModel=&','deviceModel=Chrome&').replace('appName=&','appName=web&') for url in urls if url['type'].lower() == 'hls'][0] # todo select quality

	if group not in list(ChannelsList.keys()):
		ChannelsList[group] = []
		Categories.append(group)

	if int(channel['number']) == 0:
		number = _id[-4:].upper()
	else:
		number = channel['number']

	ChannelsList[group].append((str(number),_id,channel['name'],logo,urls))
	return True

def buildService():
	bqt = open("/etc/enigma2/" + BOUQUET,"w")
	bqt.write("#NAME Pluto TV\n")
	tid = 1
	for key in ChannelsList:
		bqt.write("#SERVICE 1:64:%s:0:0:0:0:0:0:0::%s\n#DESCRIPTION %s\n" % (tid,key,key))
		tid = tid+1
		for channel in ChannelsList[key]:
			bqt.write("#SERVICE 4097:0:1:%s:0:0:0:0:0:0:%s:%s\n#DESCRIPTION %s\n" % (channel[0],quote(channel[4]),channel[2],channel[2]))
	bqt.close()
	bouquets = open("/etc/enigma2/bouquets.tv","r").read()
	if not BOUQUET in bouquets:
		addBouquet()

	db = eDVBDB.getInstance()

	db.reloadServicelist()
	db.reloadBouquets()

	return True

def addBouquet():
	if config.usage.multibouquet.value:
		bouquet_rootstr = '1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "bouquets.tv" ORDER BY bouquet'
	else:
		bouquet_rootstr = '%s FROM BOUQUET "userbouquet.favourites.tv" ORDER BY bouquet'%(service_types_tv)
	bouquet_root = eServiceReference(bouquet_rootstr)
	serviceHandler = eServiceCenter.getInstance()
	mutableBouquetList = serviceHandler.list(bouquet_root).startEdit()
	if mutableBouquetList:
		str = '1:7:1:0:0:0:0:0:0:0:FROM BOUQUET \"'+BOUQUET+'\" ORDER BY bouquet'
		new_bouquet_ref = eServiceReference(str)
		if not mutableBouquetList.addService(new_bouquet_ref):
			mutableBouquetList.flushChanges()
			eDVBDB.getInstance().reloadBouquets()
			mutableBouquet = serviceHandler.list(new_bouquet_ref).startEdit()
			if mutableBouquet:
				mutableBouquet.setListName("Pluto TV")
				mutableBouquet.flushChanges()
			else:
				print("get mutable list for new created bouquet failed")

def strpTime(datestring, format='%Y-%m-%dT%H:%M:%S.%fZ'):
	try: return datetime.datetime.strptime(datestring, format)
	except TypeError: return datetime.datetime.fromtimestamp(time.mktime(time.strptime(datestring, format)))

def convertgenre(genre):
	id = 0
	if genre == "Classics" or genre == "Romance" or genre == "Thrillers" or genre == "Horror" or "Sci-Fi" in genre or "Action" in genre:
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

def buildepg(data):
	#(title,summary,start,duration,genre)
	event, name, opt = data
	_id = event.get('_id','')
	if len(_id) == 0:
		return
	GuideList[_id] = []
	timelines = event.get('timelines',[])
	chplot = (event.get('description','') or event.get('summary',''))

	for item in timelines:
		episode    = (item.get('episode',{})   or item)
		series     = (episode.get('series',{}) or item)
		epdur      = int(episode.get('duration','0') or '0') // 1000 # in seconds
		epgenre    = episode.get('genre','')
		etype      = series.get('type','film')

		genre = convertgenre(epgenre)

		offset = datetime.datetime.now() - datetime.datetime.utcnow()
		try:
			starttime  = strpTime(item['start']) + offset
		except:
			return
		start = time.mktime(starttime.timetuple())
		title      = (item.get('title',''))
		tvplot     = (series.get('description','') or series.get('summary','') or chplot)
		epnumber   = episode.get('number',0)
		epseason   = episode.get('season',0)
		epname     = (episode['name'])
		epmpaa     = episode.get('rating','')
		epplot     = (episode.get('description','') or tvplot or epname)

		if len(epmpaa) > 0 and not "Not Rated" in epmpaa:
			epplot = '(%s). %s' % (epmpaa, epplot)

		noserie = "live film"
		if epseason > 0 and epnumber > 0 and etype not in noserie:
			title = title + ' (T%d)' % epseason
			epplot = 'T%d Ep.%d %s' % (epseason, epnumber, epplot)

		if epdur > 0:
			GuideList[_id].append((title,epplot,start,epdur,genre))

def buildGuide(event):
	#(title,summary,start,duration,genre)
	_id = event.get('_id','')
	if len(_id) == 0:
		return
	GuideList[_id] = []
	timelines = event.get('timelines',[])
	chplot = (event.get('description','') or event.get('summary',''))


	for item in timelines:
		episode    = (item.get('episode',{})   or item)
		series     = (episode.get('series',{}) or item)
		epdur      = int(episode.get('duration','0') or '0') // 1000 # in seconds
		epgenre    = episode.get('genre','')
		etype      = series.get('type','film')

		genre = convertgenre(epgenre)

		offset = datetime.datetime.now() - datetime.datetime.utcnow()
		try:
			starttime  = strpTime(item['start']) + offset
		except:
			return
		start = time.mktime(starttime.timetuple())
		title      = (item.get('title',''))
		tvplot     = (series.get('description','') or series.get('summary','') or chplot)
		epnumber   = episode.get('number',0)
		epseason   = episode.get('season',0)
		epname     = (episode['name'])
		epmpaa     = episode.get('rating','')
		epplot     = (episode.get('description','') or tvplot or epname)

		if len(epmpaa) > 0 and not "Not Rated" in epmpaa:
			epplot = '(%s). %s' % (epmpaa, epplot)

		noserie = "live film"
		if epseason > 0 and epnumber > 0 and etype not in noserie:
			title = title + ' (T%d)' % epseason
			epplot = 'T%d Ep.%d %s' % (epseason, epnumber, epplot)

		if epdur > 0:
			GuideList[_id].append((title,epplot,start,epdur,genre))

def getCategories():
	# categories = sorted(self.getGuidedata(full=True).get('categories',[]), key=lambda k: k['order'])
	# for category in categories: 
	# yield (category['name'], 'categories', 0, False, {'thumb':category.get('images',[{}])[0].get('url',ICON),'fanart':category.get('images',[{},{}])[1].get('url',FANART)})

	collect= []
	data = getChannels()
	for channel in data: collect.append(channel['category'])
	counter = collections.Counter(collect)
	categories = sorted(self.getGuidedata(full=True).get('categories',[]), key=lambda k: k['order'])
	for key, value in sorted(counter.items()): 
		category = {}
		for category in categories:
			if category['name'].lower() == key.lower():
				break
		yield (key,'categories', 0, False, {'thumb':category.get('images',[{}])[0].get('url',ICON),'fanart':category.get('images',[{},{}])[1].get('url',FANART)})


class PlutoDownload(Screen):
	if esHD():
		skin = """
		<screen name="PlutoTVdownload" position="60,60" size="615,195" title="PlutoTV EPG Download" flags="wfNoBorder" backgroundColor="#ff000000">
		<ePixmap name="background" position="0,0" size="615,195" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/PlutoTV/images/backgroundHD.png" zPosition="-1" alphatest="off" />
		<widget name="picon" position="15,55" size="120,80" transparent="1" noWrap="1" alphatest="blend"/>
		<widget name="action" halign="left" valign="center" position="13,9" size="433,30" font="Regular;25" foregroundColor="#dfdfdf" transparent="1" backgroundColor="#000000" borderColor="black" borderWidth="1" noWrap="1"/>
		<widget name="progress" position="150,97" size="420,12" borderWidth="0" backgroundColor="#1143495b" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/PlutoTV/images/progresoHD.png" zPosition="2" alphatest="blend" />
		<eLabel name="fondoprogreso" position="150,97" size="420,12" backgroundColor="#102a3b58" />
		<widget name="espera" valign="center" halign="center" position="150,63" size="420,30" font="Regular;22" foregroundColor="#dfdfdf" transparent="1" backgroundColor="#000000" borderColor="black" borderWidth="1" noWrap="1"/>
		<widget name="status" halign="center" valign="center" position="150,120" size="420,30" font="Regular;24" foregroundColor="#ffffff" transparent="1" backgroundColor="#000000" borderColor="black" borderWidth="1" noWrap="1"/>
		</screen>"""
	else:
		skin = """
		<screen name="PlutoTVdownload" position="40,40" size="410,130" title="PlutoTV EPG Download" flags="wfNoBorder" backgroundColor="#ff000000">
		<ePixmap name="background" position="0,0" size="410,130" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/PlutoTV/images/background.png" zPosition="-1" alphatest="off" />
		<widget name="picon" position="10,36" size="80,53" transparent="1" noWrap="1" alphatest="blend"/>
		<widget name="action" halign="left" valign="center" position="9,6" size="289,20" font="Regular;17" foregroundColor="#dfdfdf" transparent="1" backgroundColor="#000000" borderColor="black" borderWidth="1" noWrap="1"/>
		<widget name="progress" position="100,65" size="280,8" borderWidth="0" backgroundColor="#1143495b" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/PlutoTV/images/progreso.png" zPosition="2" alphatest="blend" />
		<eLabel name="fondoprogreso" position="100,65" size="280,8" backgroundColor="#102a3b58" />
		<widget name="espera" valign="center" halign="center" position="100,42" size="240,20" font="Regular;15" foregroundColor="#dfdfdf" transparent="1" backgroundColor="#000000" borderColor="black" borderWidth="1" noWrap="1"/>
		<widget name="status" halign="center" valign="center" position="100,80" size="240,20" font="Regular;16" foregroundColor="#ffffff" transparent="1" backgroundColor="#000000" borderColor="black" borderWidth="1" noWrap="1"/>
		</screen>"""

	def __init__(self, session, args = "" ):
		self.session = session
		Screen.__init__(self, session)
		self.iprogress = 0
		self.total = 0
		self.skinName = "mhwEPG"
		self["progress"] = ProgressBar()
		self["action"] = Label(_("EPG Download: %s Pluto TV") % args)
		self["espera"] = Label("")
		self["status"] = Label(_("Wait..."))
		self["actions"] = ActionMap(["OkCancelActions"], {"cancel": self.salir}, -1)
		self["picon"] = Pixmap()
		self.epgcache = eEPGCache.getInstance()
		self.fd = None
		self.state = 1
		self.onFirstExecBegin.append(self.init)

	def init(self):
		self["picon"].instance.setScale(1)
		self["picon"].instance.setPixmapFromFile("/usr/lib/enigma2/python/Plugins/Extensions/PlutoTV/plutotv.png")
		self["progress"].setValue(0)
		self.TimerTemp = eTimer()
		self.TimerTemp.callback.append(self.download)
		self.TimerTemp.startLongTimer(1)


	def download(self):
		global ChannelsList, GuideList
		ChannelsList.clear()
		GuideList.clear()
		channels = getChannels()
		guide = getGuidedata()
		[buildM3U(channel) for channel in channels]
		self.total = len(channels)

		self.fd = open("/etc/enigma2/" + BOUQUET,"w")
		self.fd.write("#NAME Pluto TV\n")

		if len(Categories) == 0:
			self.session.openWithCallback(self.salirok, MessageBox, _('There is no data, it is possible that Puto TV is not available in your Country'), type=MessageBox.TYPE_ERROR, timeout=10)
		else:
			self.keystot = len(ChannelsList)
			if Categories[0] in ChannelsList:
				self.subtotal = len(ChannelsList[Categories[0]])
			else:
				self.subtotal = 0
			self.key = 0
			self.chitem = 0
			[buildGuide(event) for event in guide]
			self.actualizaprogreso(event=DownloadComponent.EVENT_DONE, param=0)

	def actualizaprogreso(self, event=None, param=None, ref=None, name=None):
		####### hack for exit before end
		cont = False
		try:
			if self.state == 1:
				cont = True
		except:
			pass
		#################################
		if cont:

			if event == DownloadComponent.EVENT_DONE:
				try:
					self.iprogress = ((param+1) *100) // self.total
				except:
					self.iprogress=100
				if self.iprogress > 100:
					self.iprogress = 100

				self["progress"].setValue(self.iprogress)
				self["espera"].setText(str(self.iprogress)+" %")
				if self.fd:
					if param<self.total:
						key = Categories[self.key]
						if self.chitem == self.subtotal:
							self.chitem = 0
							pase = False
							while not pase:
								self.key = self.key + 1
								key = Categories[self.key]
								pase = key in ChannelsList
							self.subtotal = len(ChannelsList[key])


						if self.chitem == 0:
							self.fd.write("#SERVICE 1:64:%s:0:0:0:0:0:0:0::%s\n#DESCRIPTION %s\n" % (self.key,Categories[self.key],Categories[self.key]))


						channel = ChannelsList[key][self.chitem]
						sref = "#SERVICE 4097:0:1:%s:0:0:0:0:0:0:%s:%s" % (channel[0],quote(channel[4]),channel[2])
						self.fd.write("%s\n#DESCRIPTION %s\n" % (sref,channel[2]))
						self.chitem = self.chitem + 1

						if py3():
							ref = "4097:0:1:%s:0:0:0:0:0:0" % channel[0]
							name = channel[2]
							self["status"].setText(_("Wait for Channel: ")+name)
						else:
							ref = "4097:0:1:%s:0:0:0:0:0:0" % channel[0].encode("utf-8")
							name = channel[2]
							self["status"].setText(_("Wait for Channel: ")+name.encode("utf-8"))

						chevents = []
						if channel[1] in GuideList:
							for evt in GuideList[channel[1]]:
								if py3():
									title = evt[0]
									summary = evt[1]
								else:
									title = evt[0].encode("utf-8")
									summary = evt[1].encode("utf-8")
								begin = int(round(evt[2]))
								duration = evt[3]
								genre = evt[4]

								chevents.append((begin,duration,title,'',summary,genre))
						if len(chevents)>0:
							iterator = iter(chevents)
							events_tuple = tuple(iterator)
							self.epgcache.importEvents(ref+":https%3a//.m3u8",events_tuple)


						logo = channel[3]
						self.down = DownloadComponent(param+1, ref, name, True)
						self.down.addCallback(self.actualizaprogreso)

						self.down.startCmd(logo)
					else:
						self.fd.close()
						self.fd = None
						bouquets = open("/etc/enigma2/bouquets.tv","r").read()
						if not BOUQUET in bouquets:
							addBouquet()

						db = eDVBDB.getInstance()
						db.reloadServicelist()
						db.reloadBouquets()
						open("/etc/Plutotv.timer","w").write(str(time.time()))
						self.salirok()
				else:
					self.TimerTemp = eTimer()
					self.TimerTemp.callback.append(self.salirok)
					self.TimerTemp.startLongTimer(1)

	def salir(self):
			stri = _("The download is in progress. Exit now?")
			self.session.openWithCallback(self.salirok, MessageBox, stri, MessageBox.TYPE_YESNO, timeout = 30)
			
	def salirok(self,answer=True):
		if answer:
			Silent.stop()
			Silent.start()
			self.close(True) 

class DownloadSilent:
	def __init__(self):
		self.epgcache = eEPGCache.getInstance()
		self.fd = None
		self.state = 1
		self.timer = eTimer()
		self.timer.timeout.get().append(self.download)

	def init(self,session):
		self.session = session
		bouquets = open("/etc/enigma2/bouquets.tv","r").read()
		if "pluto_tv" in bouquets:
			self.start()


	def start(self):
		minutes = 60 * 5
		if fileExists("/etc/Plutotv.timer"):
			last = float(open("/etc/Plutotv.timer","r").read().replace("\n","").replace("\r",""))
			minutes = minutes - int((time.time()-last)/60)
			if minutes < 0:
				minutes = 1
		self.timer.start(minutes * 60000, False)


	def stop(self):
		self.timer.stop()

	def download(self):
		global ChannelsList, GuideList
		self.stop()
		ChannelsList.clear()
		GuideList.clear()
		channels = getChannels()
		guide = getGuidedata()
		[buildM3U(channel) for channel in channels]

		self.total = len(channels)
		self.fd = open("/etc/enigma2/" + BOUQUET,"w")
		self.fd.write("#NAME Pluto TV\n")

		if len(Categories) == 0:
			print("[Pluto TV] " + _('There is no data, it is possible that Puto TV is not available in your Country'))
			self.stop()
#			os.remove("/etc/Plutotv.timer")
			open("/etc/Plutotv.timer","w").write(str(time.time()))
			self.start()
		else:
			self.keystot = len(ChannelsList)
			if Categories[0] in ChannelsList:
				self.subtotal = len(ChannelsList[Categories[0]])
			else:
				self.subtotal = 0
			self.key = 0
			self.chitem = 0
			[buildGuide(event) for event in guide]
			self.actualizaprogreso(event=DownloadComponent.EVENT_DONE, param=0)

	def actualizaprogreso(self, event=None, param=None, ref=None, name=None):
		####### hack for exit before end
		cont = False
		try:
			if self.state == 1:
				cont = True
		except:
			pass
		#################################
		if cont:

			if event == DownloadComponent.EVENT_DONE:
				if self.fd:
					if param<self.total:
						key = Categories[self.key]
						if self.chitem == self.subtotal:
							self.chitem = 0
							pase = False
							while not pase:
								self.key = self.key + 1
								key = Categories[self.key]
								pase = key in ChannelsList
							self.subtotal = len(ChannelsList[key])


						if self.chitem == 0:
							self.fd.write("#SERVICE 1:64:%s:0:0:0:0:0:0:0::%s\n#DESCRIPTION %s\n" % (self.key,Categories[self.key],Categories[self.key]))


						channel = ChannelsList[key][self.chitem]
						sref = "#SERVICE 4097:0:1:%s:0:0:0:0:0:0:%s:%s" % (channel[0],quote(channel[4]),channel[2])
						self.fd.write("%s\n#DESCRIPTION %s\n" % (sref,channel[2]))
						self.chitem = self.chitem + 1

						if py3():
							ref = "4097:0:1:%s:0:0:0:0:0:0" % channel[0]
						else:
							ref = "4097:0:1:%s:0:0:0:0:0:0" % channel[0].encode("utf-8")
						name = channel[2]


						chevents = []
						if channel[1] in GuideList:
							for evt in GuideList[channel[1]]:
								if py3():
									title = evt[0]
									summary = evt[1]
								else:
									title = evt[0].encode("utf-8")
									summary = evt[1].encode("utf-8")
								begin = int(round(evt[2]))
								duration = evt[3]
								genre = evt[4]

								chevents.append((begin,duration,title,'',summary,genre))
						if len(chevents)>0:
							iterator = iter(chevents)
							events_tuple = tuple(iterator)
							self.epgcache.importEvents(ref+":https%3a//.m3u8",events_tuple)


						logo = channel[3]
						self.down = DownloadComponent(param+1, ref, name)
						self.down.addCallback(self.actualizaprogreso)
						try:
							last_day = int(config.epg.maxdays.value) * 24 * 60
						except:
							last_day = 9999999

						self.down.startCmd(logo)
					else:
						self.fd.close()
						self.fd = None
						bouquets = open("/etc/enigma2/bouquets.tv","r").read()
						if not BOUQUET in bouquets:
							addBouquet()

						db = eDVBDB.getInstance()
						db.reloadServicelist()
						db.reloadBouquets()
						open("/etc/Plutotv.timer","w").write(str(time.time()))

		self.start()


Silent = DownloadSilent()
