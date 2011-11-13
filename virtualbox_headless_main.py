#!/usr/bin/python

import vboxapi
import sys

import threading
import ctypes

sys.path.append(vboxapi.VboxSdkDir+'/bindings/xpcom/python/')
import xpcom.vboxxpcom
import xpcom
import xpcom.components
import xpcom.nsError

vbox_constants = vboxapi.VirtualBoxReflectionInfo(None)

class IFramebuffer:
	_com_interfaces_ = [xpcom.components.interfaces.IFramebuffer]

class Framebuffer(IFramebuffer):
	def __init__(self, console, screen = 0):
		self.screen = screen
		self.console = console
		self.mutex = threading.Lock()

		self.width = 0
		self.height = 0
		self.bitsPerPixel = 0
		self.bytesPerLine = 0
		self.pixelFormat = vbox_constants.FramebufferPixelFormat_Opaque
		self.heightReduction = 0
		self.overlay = 0
		self.winId = 0

		self.rgb_buffer = None
		self.host_vram = None

		self.rfb_server.keyboard_event = self.keyboard
		self.rfb_server.keyboard_release = self.keyboard_release
		self.rfb_server.mouse_event = self.mouse

		vram, bpp, Bpl = 0, 0, 0
		self.requestResize(self.screen, vbox_constants.FramebufferPixelFormat_Opaque, 
				vram, bpp, Bpl, self.width, self.height)

	def keyboard(self):
		pass

	def keyboard_release(self):
		pass

	def mouse(self):
		pass

	def Get_usesGuestVRAM(self):
		return self.rgb_buffer is None

	def lock(self):
		self.mutex.acquire()

	def unlock(self):
		self.mutex.release()

	def copy_pixel(self, dst, src):
		ctypes.memmove(dst, src+2, 1)
		ctypes.memmove(dst+1, src+1, 1)
		ctypes.memmove(dst+2, src, 1)

	def notifyUpdate(self, x, y, width, height):
		print "notifyUpdate %s %s %s %s" % (x, y, width, height)
		if not self.address or not self.screen_buffer:
			return

		bytesPerPixel = self.bitsPerPixel / 8
		sb_addr = ctypes.addressof(self.screen_buffer)
		joff = y * self.bytesPerLine + x * bytesPerPixel
		for j in xrange(joff, joff + h + self.bytesPerLine, self.bytesPerLine):
			for i in xrange(j, j + w * bytesPerPixel, bytesPerPixel):
				self.copy_pixel(sb_addr + i, self.address + i)

		self.rfb_server.add_rect(x, y, x+w, y+h)
		
	def requestResize(self, screenId, pixelFormat, vram, bpp, Bpl, w, h):
		print "requestResize %s %s %s %s %s %s %s" % 
			(screenId, pixelFormat, vram, bpp, Bpl, w, h)

		self.width = w
		self.height = h
		self.pixelFormat = FramebufferPixelFormat_FOURCC_RGB
		self.bitsPerPixel = 32
		self.rgb_buffer = None

		if pixelFormat == vbox_constants.FramebufferPixelFormat_FOURCC_RGB && bpp == 32:
			assert vram is not None, "vram is None"
			assert vram != 0, "vram is NULL"
			print "Setting buffer address to vram: %s" % vram
			self.address = vram
			self.bytesPerLine = Bpl
		else:
			self.bytesPerLine = w * 4
			self.rgb_buffer = ctypes.create_string_buffer(self.bytesPerLine * h)
			self.address = ctypes.addressof(self.rgb_buffer)
			print "Using my own buffer: %s" % self.address

		old_buffer = self.screen_buffer
		self.screen_buffer = ctypes.create_string_buffer(self.bytesPerLine * h)
		sb_addr = ctypes.addressof(self.screen_buffer)
		for i in xrange(0, self.bytesPerLine * h, 4):
			self.copy_pixel(sb_addr + i, self.address + i)

		bits_per_sample = 8
		samples_per_pixel = 3
		self.rfb_server.set_frame_buffer(sb_addr, w, h, bits_per_sample, samples_per_pixel, self.bitsPerPixel / 8)

		return True

	def videoModeSupported(self, width, height, bpp):
		print "videoModeSupported %s %s %s" % (width, height, bpp)
		return not (width%4) && bpp == 8

	def getVisibleRegion(self, rectangles, count):
		print "getVisibleRegion %s" % count
		count_copied = 0
		return count_copied 

	def setVisibleRegion(self, rectangles, count):
		print "setVisibleRegion %s" % count

	def processVHWACommand(self, command):
		print "processVHWACommand"

	def set_as_framebuffer(self):
		self.console.display.setFramebuffer(self.screen, self)

	def __getattr__(self, name):
		print ">> __getattr__ %s" % name
		if not self.__dict__.has_key(name):
			raise AttributeError, name
		return self.__dict__[name]

	def __setattr__(self, name, value):
		print ">> __setattr__ %s %s" % (name, value)
		self.__dict__[name] = value

# getresuid and setresuid aren't available
# until Python 2.7
#if sys.hexversion < 0x2070000:
#	def getresuid():
#		ctypes.cdll.LoadLibrary("libc.so.6")
#		libc = ctypes.CDLL("libc.so.6")
#		uid = ctypes.c_int()
#		euid = ctypes.c_int()
#		suid = ctypes.c_int()
#		libc.getresuid(ctypes.byref(uid), ctypes.byref(euid), ctypes.byref(suid))
#		return uid.value, euid.value, suid.value
#
#	def setresuid(uid, euid, suid):
#		ctypes.cdll.LoadLibrary("libc.so.6")
#		libc = ctypes.CDLL("libc.so.6")
#		return libc.setresuid(ctypes.c_int(uid), ctypes.c_int(euid), ctypes.c_int(suid))
#else:
#	import os
#	getresuid = os.getresuid
#	setresuid = os.setresuid 
#
#def getloginuid():
#	import os
#	import pwd
#	return pwd.getpwnam(os.getlogin()).pw_uid
#
#def lower_privileges():
#	import os
#	if os.getuid() == 0:
#		uid = getloginuid()
#		setresuid(uid, uid, uid)
#		return True
#	return False
#
#def raise_privileges():
#	import os
#	os.setuid(0)
#	os.seteuid(0)

def main(argv):

	#print getresuid()
	#started_as_root = lower_privileges()
	#print getresuid()

	manager = vboxapi.VirtualBoxManager(None, None)
	virtualbox = manager.vbox
	session_manager = manager.mgr
	session = session_manager.getSessionObject(virtualbox)

	machine = virtualbox.findMachine(argv[1])

	virtualbox.openSession(session, machine.id)

	console = session.console

	fb = Framebuffer(console)
	fb.set_as_framebuffer()

	console_cb = manager.createCallback('IConsoleCallback', GuestMonitor, machine)
	isMscom = (manager.type == 'MSCOM')
	virtualbox_cb = manager.createCallback('IVirtualBoxCallback', VBoxMonitor, [virtualbox, isMscom])

	console.registerCallback(console_cb)
	virtualbox.registerCallback(virtualbox_cb)

	print "Powering up!"
	#if started_as_root:
	#	raise_privileges()

	progress = console.powerUp()
	while True:
		try:
			while not progress.completed:
				print "%s %%\r" % str(progress.percent), # ending comma is critical
				sys.stdout.flush()
				progress.waitForCompletion(1000)
				manager.waitForEvents(0)
			break
		except KeyboardInterrupt:
			print "Interrupted."
			if progress.cancelable:
				print "Canceling task (%s)" % progress.description
				progress.cancel()
				return
			else:
				print "Task cannot be canceled (%s)" % progress.description

	assert progress.completed == True
	assert int(progress.resultCode) == 0, progress.resultCode

	print "Event loop"
	try:
		while True:
			manager.waitForEvents(1)
	except KeyboardInterrupt:
		pass
	print "Shutting down"

	if console_cb is not None:
		console.unregisterCallback(console_cb)
	console_cb = None
	
	console = None
	if session is not None:
		session.close()
		session = None
	
	if virtualbox_cb is not None:
		virtualbox.unregisterCallback(virtualbox_cb)
	virtualbox_cb = None
	virtualbox = None

	print "Done"

#end/main

class GuestMonitor:
	def __init__(self, mach):
			self.mach = mach

	def onMousePointerShapeChange(self, visible, alpha, xHot, yHot, width, height, shape):
			print  "%s: onMousePointerShapeChange: visible=%d shape=%d bytes" %(self.mach.name, visible,len(shape))

	def onMouseCapabilityChange(self, supportsAbsolute, supportsRelative, needsHostCursor):
			print  "%s: onMouseCapabilityChange: supportsAbsolute = %d, supportsRelative = %d, needsHostCursor = %d" %(self.mach.name, supportsAbsolute, supportsRelative, needsHostCursor)

	def onKeyboardLedsChange(self, numLock, capsLock, scrollLock):
			print  "%s: onKeyboardLedsChange capsLock=%d"  %(self.mach.name, capsLock)

	def onStateChange(self, state):
			print  "%s: onStateChange state=%d" %(self.mach.name, state)

	def onAdditionsStateChange(self):
			print  "%s: onAdditionsStateChange" %(self.mach.name)

	def onNetworkAdapterChange(self, adapter):
			print  "%s: onNetworkAdapterChange" %(self.mach.name)

	def onSerialPortChange(self, port):
			print  "%s: onSerialPortChange" %(self.mach.name)

	def onParallelPortChange(self, port):
			print  "%s: onParallelPortChange" %(self.mach.name)

	def onStorageControllerChange(self):
			print  "%s: onStorageControllerChange" %(self.mach.name)

	def onMediumChange(self, attachment):
			print  "%s: onMediumChange" %(self.mach.name)

	def onVRDPServerChange(self):
			print  "%s: onVRDPServerChange" %(self.mach.name)

	def onUSBControllerChange(self):
			print  "%s: onUSBControllerChange" %(self.mach.name)

	def onUSBDeviceStateChange(self, device, attached, error):
			print  "%s: onUSBDeviceStateChange" %(self.mach.name)

	def onSharedFolderChange(self, scope):
			print  "%s: onSharedFolderChange" %(self.mach.name)

	def onRuntimeError(self, fatal, id, message):
			print  "%s: onRuntimeError fatal=%d message=%s" %(self.mach.name, fatal, message)

	def onCanShowWindow(self):
			print  "%s: onCanShowWindow" %(self.mach.name)
			return False

	def onShowWindow(self, winId):
			print  "%s: onShowWindow: %d" %(self.mach.name, winId)

class VBoxMonitor:
    def __init__(self, params):
        self.vbox = params[0]
        self.isMscom = params[1]
        pass

    def onMachineStateChange(self, id, state):
        print "onMachineStateChange: %s %d" %(id, state)

    def onMachineDataChange(self,id):
        print "onMachineDataChange: %s" %(id)

    def onExtraDataCanChange(self, id, key, value):
        print "onExtraDataCanChange: %s %s=>%s" %(id, key, value)
        # Witty COM bridge thinks if someone wishes to return tuple, hresult
        # is one of values we want to return
        if self.isMscom:
            return "", 0, True
        else:
            return True, ""

    def onExtraDataChange(self, id, key, value):
        print "onExtraDataChange: %s %s=>%s" %(id, key, value)

    def onMediaRegistered(self, id, type, registered):
        print "onMediaRegistered: %s" %(id)

    def onMachineRegistered(self, id, registred):
        print "onMachineRegistered: %s" %(id)

    def onSessionStateChange(self, id, state):
        print "onSessionStateChange: %s %d" %(id, state)

    def onSnapshotTaken(self, mach, id):
        print "onSnapshotTaken: %s %s" %(mach, id)

    def onSnapshotDeleted(self, mach, id):
        print "onSnapshotDeleted: %s %s" %(mach, id)

    def onSnapshotChange(self, mach, id):
        print "onSnapshotChange: %s %s" %(mach, id)

    def onGuestPropertyChange(self, id, name, newValue, flags):
       print "onGuestPropertyChange: %s: %s=%s" %(id, name, newValue)

if __name__ == '__main__':
	main(sys.argv)

