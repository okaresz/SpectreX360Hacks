#!/usr/bin/env python3

# script to enhance user experience on HP Spectre x360 under Ubuntu 16.10

import os, sys, subprocess, time, threading, signal
import inotifyx, re, logging
from pydbus import SessionBus
from gi.repository import GLib

Config = {
	'intelVbtnInput': '/dev/input/by-path/platform-INT33D6:00-event',
	'touchPadXinputName': "SynPS/2 Synaptics TouchPad"
}

# http://stackoverflow.com/a/23646049
def reverse_readline(filename, buf_size=8192):
    """a generator that returns the lines of a file in reverse order"""
    with open(filename) as fh:
        segment = None
        offset = 0
        fh.seek(0, os.SEEK_END)
        file_size = remaining_size = fh.tell()
        while remaining_size > 0:
            offset = min(file_size, offset + buf_size)
            fh.seek(file_size - offset)
            buffer = fh.read(min(remaining_size, buf_size))
            remaining_size -= buf_size
            lines = buffer.splitlines()
            # the first line of the buffer is probably not a complete line so
            # we'll save it and append it to the last line of the next buffer
            # we read
            if segment is not None:
                # if the previous chunk starts right from the beginning of line
                # do not concact the segment to the last line of new chunk
                # instead, yield the segment first 
                if buffer[-1] is not '\n':
                    lines[-1] += segment
                else:
                    yield segment
            segment = lines[0]
            for index in range(len(lines) - 1, 0, -1):
                if len(lines[index]):
                    yield lines[index]
        # Don't yield None if the file was empty
        if segment is not None:
            yield segment

class SpectreX360Daemon():
	def __init__(self):
		self.log = logging.getLogger('SpectreX360Daemon')
		self.log.setLevel(logging.DEBUG)
		self.log.info("SpectreX360Daemon init.")

		self.onboardProcess = None
		self.screenToolsIndicatorprocess = None

		self.changeEvent = threading.Event()
		self.stanceWatch = StanceWatcher(self.changeEvent)
		self.dockWatch = DockedWatcher(self.changeEvent)

		self.shouldStop = False
		signal.signal(signal.SIGTERM, self.sigHandler)
		signal.signal(signal.SIGINT, self.sigHandler)
	
	def stop(self):
		self.shouldStop = True
		self.stanceWatch.stop()
		self.dockWatch.stop()
		self.startStopOnboard(False)
		self.startStopScreenToolsIndicator(False)

	def sigHandler(self, sigNum, stackFrame):
		if sigNum == signal.SIGINT or sigNum == signal.SIGKILL:
			self.log.info("SIGINT/SIGKILL caught, exiting...")
			self.stop()
	
	def run(self):
		# load current mode first
		self.switchMode()

		# ...then start watchers
		self.stanceWatch.start()
		self.dockWatch.start()

		while not self.shouldStop:
			if self.changeEvent.wait(0.5):
				self.changeEvent.clear()
				self.switchMode()

		self.stanceWatch.join()
		self.dockWatch.join()

	def startStopOnboard(self,start):
		if start:
			if not self.onboardProcess:
				self.onboardProcess = subprocess.Popen(["/usr/bin/python3", "/usr/bin/onboard"])
		else:
			if self.onboardProcess:
				self.onboardProcess.kill()
				self.onboardProcess.wait()
				self.onboardProcess = None
	
	def startStopScreenToolsIndicator(self,start):
		if start:
			if not self.screenToolsIndicatorprocess:
				self.screenToolsIndicatorprocess = subprocess.Popen(["indicator-screentools-service"])
		else:
			if self.screenToolsIndicatorprocess:
				self.screenToolsIndicatorprocess.kill()
				self.screenToolsIndicatorprocess.wait()
				self.screenToolsIndicatorprocess = None

	def enableTouchPad(self,enable):
		if enable:
			subprocess.call(["xinput", "--enable", Config['touchPadXinputName']])
		else:
			subprocess.call(["xinput", "--disable", Config['touchPadXinputName']])

	def setUnityTextScale(self,factor):
		val = "{:.1f}".format(factor)
		subprocess.call(["dconf", "write", "/com/canonical/unity/interface/text-scale-factor", val])

	def setUnityWindowScale(self,factor):
		val = "{{'HDMI-1': 8, 'eDP-1': {:d}}}".format(factor)
		subprocess.call(["dconf", "write", "/com/ubuntu/user-interface/scale-factor", val])
	
	def switchMode(self):
		isDocked = self.dockWatch.isDocked()
		stance = self.stanceWatch.getStance()
		self.log.debug('switching mode to: dock=%d, stance=%s', isDocked, stance)
		
		"""order of operations is important, please use the same sequence at every case
			- touchpad
			- text scale
			- unity window scale (affects text scaling with the same amount)
			- onboard
			- screentools-indicator"""

		if isDocked:
			self.enableTouchPad(True) # why not..

			self.setUnityTextScale(1.0)
			self.setUnityWindowScale(8)

			self.startStopOnboard(False)
			self.startStopScreenToolsIndicator(False)
			self.log.info("Switched to docked mode")

		else:
			if stance == 'laptop':
				self.enableTouchPad(True)

				self.setUnityTextScale(1.3)
				self.setUnityWindowScale(8)

				self.startStopOnboard(False)
				self.startStopScreenToolsIndicator(False)
				self.log.info("Switched to %s stance.", stance)

			elif stance == 'tablet':
				self.enableTouchPad(False)

				# set text scaling first, as window scaling updates it
				self.setUnityTextScale(1.0)
				self.setUnityWindowScale(11)
				
				self.startStopOnboard(True)
				self.startStopScreenToolsIndicator(True)
				self.log.info("Switched to %s stance.", stance)

			else:
				self.log.warning("unknown stance: %s", stance)
		
######################################################################

# --- initializing some settings -------------------------------------------
#subprocess.call(["synclient", "TapFinger3=2"])
#subprocess.call(["synclient", "TapButton3=2"])


class DockedWatcher(threading.Thread):
	def __init__(self,changeEvent):
		threading.Thread.__init__(self)
		self.gMainLoop = GLib.MainLoop()

		self.log = logging.getLogger('DockedWatcher')
		self.log.setLevel(logging.DEBUG)

		self.changeEvent = changeEvent
	
	def isDocked(self):
		currDisps = self.getCurrentDisplays()
		if len(currDisps) == 1 and ('eDP-1' in currDisps.keys()):
			return False
		else:
			return True

	def stop(self):
		self.gMainLoop.quit()

	def xRandrParser(self,outStr):
		xrLines = outStr.splitlines()
		connectedScreens={};
		for line in xrLines:
			if line.find(" connected ")>=0:
				match = re.search('^(\S+).+?(\d+x\d+\+\d+\+\d+).*',line)
				if match:
					connectedScreens[match.group(1)] = {
						'respos': match.group(2),
						'primary': (line.find(" primary ")>=0)
						}
		return connectedScreens

	def getCurrentDisplays(self):
		proc = subprocess.run(['xrandr'],stdout=subprocess.PIPE,universal_newlines=True)
		return self.xRandrParser(proc.stdout)

	def dbusSigHandler(self, sender, object, iface, signal, params):
		self.log.info("Display change event!")
		time.sleep(0.3) # wait a little before letting anyone try to read current status
		self.changeEvent.set()

	def run(self):
		self.log.info('DockedWatcher started')
		bus = SessionBus()
		bus.subscribe(None, None, "EventEmitted", "/com/ubuntu/Upstart", "drm-device-changed", 0, self.dbusSigHandler)
		self.gMainLoop.run()


class StanceWatcher(threading.Thread):
	"""Currently two stance is supported: 'tablet' and 'laptop'.
	On start, the whole syslog is read until the last intel virtual button event,
	but if not found, 'laptop' stance is assumed."""
	def __init__(self,changeEvent):
		threading.Thread.__init__(self)
		self.stopEv = threading.Event()
		self.changeEvent = changeEvent
		
		self.log = logging.getLogger('StanceWatcher')
		self.log.setLevel(logging.DEBUG)

		self.stance = 'laptop'
		readStance = self.parseStanceFromSyslog(0)
		if readStance:
			self.stance = readStance

	def getStance(self):
		return self.stance
	
	def stop(self):
		self.stopEv.set()
	
	# maxLinesToCheck = 0 means check whole syslog
	def parseStanceFromSyslog(self,maxLinesToCheck=10): #we read after the event happens, no need to read a lot
		lineCounter = 0
		sysLogRevLines = reverse_readline("/var/log/syslog",4096)
		for line in sysLogRevLines:
			if line.find("INT33D6") >= 0:
				match = re.search('event index 0x(..)', line)
				if match:
					eventCodeHex = match.group(1)
					if eventCodeHex.lower() == 'cc':
						return 'tablet'
					elif eventCodeHex.lower() == 'cd':
						return 'laptop'
			lineCounter += 1
			if maxLinesToCheck > 0 and lineCounter >= maxLinesToCheck:
				break
		self.log.warning("Could not parse stance from syslog.")
		return None
	
	def run(self):
		# watch intel vbtn for event to know when to parse dmesg for what it was
		self.log.info("StanceWatcher started")
		vbtnWatchFd = inotifyx.init()
		try:
			self.log.debug("Add Watch for Intel Virtual Button input...")
			vbtnWatch = inotifyx.add_watch(vbtnWatchFd, Config['intelVbtnInput'], inotifyx.IN_ACCESS)
			
			lastEventTime = 0.0
			while not self.stopEv.is_set():
				vbtnEvent = inotifyx.get_events(vbtnWatchFd,0.8)
				if len(vbtnEvent) > 0:
					now = time.time();
					# vbtn event file is modified multiple times on a lid rotation, a quick solution to fire stance change only once
					# assuming the user won't rotate the lid very frequently (like under a second...)
					if now - lastEventTime > 0.8:
						self.log.debug("lid rotate event occurred, parse syslog...")
						time.sleep(0.2) #give time for event to appear in syslog
						readStance = self.parseStanceFromSyslog()
						if readStance:
							self.stance = readStance
							self.log.debug("Stance updated to %s", self.stance)
							self.changeEvent.set()
						else:
							self.log.warning("Got None, stance NOT updated.")
					else:
						self.log.debug("event discarded, too soon")
					lastEventTime = now
			inotifyx.rm_watch(vbtnWatchFd, vbtnWatch)
			self.log.debug("Removed watch for Intel Virtual Button input")
		finally:
			os.close(vbtnWatchFd)

#if __name__ == "__main__":

# Init Logging
rootLogger = logging.getLogger()
rootLogger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s {%(name)s}[%(levelname)s] %(message)s')
stdOutLog = logging.StreamHandler(sys.stdout)
stdOutLog.setLevel(logging.DEBUG)
stdOutLog.setFormatter(formatter)
rootLogger.addHandler(stdOutLog)

daemon = SpectreX360Daemon()
daemon.run()
