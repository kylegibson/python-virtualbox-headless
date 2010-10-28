#!/usr/bin/python

import sys
import os
import signal
import struct
import time
from decimal import *

from rfb_async_server import Channel, Server

#def write_pid_file():
#	file(sys.argv[1], "w").write(str(os.getpid()))

PIXEL_FORMAT_BGR233 = {
	'bpp'					: 8, 
	'depth'				: 8,
	'big-endian'	: False, # network order is BE
	'true-color'	: True,
	'color-max'		: (7, 7, 3),
	'color-shift'	: (0, 3, 6),
}

PIXEL_FORMAT_RGB233 = {
	'bpp'					: 8, 
	'depth'				: 8,
	'big-endian'	: False, # network order is BE
	'true-color'	: True,
	'color-max'		: (7, 7, 3),
	'color-shift'	: (6, 3, 0),
}

class rfbConnection(Channel):

	def init(self):
		print "rfbConnection init"
		self.server_version = "RFB 003.008\n"

		self.security_types = {
			2 : self.vnc_des_authentication,
		}
		self.vnc_client_msg_handler = {
			0 : self.vnc_client_msg_set_pixel_format,
			2 : self.vnc_client_msg_set_encodings,
			3 : self.vnc_client_msg_framebuffer_update_request,
			4 : self.vnc_client_msg_key_event,
			5 : self.vnc_client_msg_pointer_event,
			6 : self.vnc_client_cut_text,
		}
		self.color_translation = {
			0 : self.color_translation_none,
		}

		self.vnc_des_challenge_size = 16

		self.size = (800, 600)
	
		self.pixel_format = PIXEL_FORMAT_BGR233

		self.desktop_name = "foobar!"
		self.state = {} # misc state switching info
		self.framebuffer = None
		self.set_network_byte_order()
		self.translate_color = None
		self.color_table = None
		self.client_pixel_format = None

	def set_translation(self):
		spf = self.pixel_format
		cpf = self.client_pixel_format
		sbpp = spf['bpp']
		cbpp = cpf['bpp']
		stc = spf['true-color']
		ctc	= cpf['true-color']

		if not sbpp in (8, 16, 32):
			self.push_rfb_failure_message("Server BPP must be 8, 16, or 32")
			return False

		if not cbpp in (8, 16, 32):
			self.push_rfb_failure_message("Client BPP must be 8, 16, or 32")
			return False

		if ctc and cbpp != 8:
			self.push_rfb_failure_message("Server can only handle 8-bit colormap")
			return False

		if ctc:
			if not self.set_color_map_BGR233():
				return False
			cpf = PIXEL_FORMAT_BGR233

		if cpf == spf:
			print "no translation needed"
			self.translate_color = None
			return True

		if sbpp == 8 || (stc && sbpp == 16):
			self.color_translation = self.color_translate_single_table
			if stc:
				self.init_true_color_single_table()
			else:
				self.init_color_map_single_table()
		else:
			self.color_translation = self.color_translate_rgb_tables()
			self.init_true_color_rgb_tables()

		return True

	def accepted(self):
		print "accepted"
		self.vnc_welcome()

	def bit_mirror(self, f, nbits):
		for i in range(nbits/2):
			j = nbits-i-1
			a, b = 1 << i, 1 << j
			if ((f&a) >> i) ^ ((f&b) >> j):
				f ^= (a+b)
		return f

	def encrypt_bytes(self, key, data):
		from data_encryption_standard import des
		key = "".join([chr(self.bit_mirror(ord(i), 8)) for i in key[:8]])
		padding = "\0" * (8-len(key))
		ptr = des(key + padding, pyDes.ECB)
		return ptr.encrypt(data)

	def align_byte_order_format(self, fmt):
		if fmt[0] == self.byte_order_fmt:
			return fmt
		return "%s%s" % (self.byte_order_fmt, fmt)

	def set_network_byte_order(self):
		self.byte_order_fmt = "!"

	def set_big_endian_byte_order(self):
		self.byte_order_fmt = ">"
	
	def set_little_endian_byte_order(self):
		self.byte_order_fmt = "<"

	def initialize_framebuffer(self):
		from PIL import Image
		palette = []
		for i in xrange(len(self.color_map[0])):
			r,g,b = self.color_map[0][i]
			palette.append(r)
			palette.append(g)
			palette.append(b)
		self.framebuffer = Image.new("P", self.size, 255)
		self.framebuffer.putpalette(palette)

		#im = Image.open("/home/kyle/facebook/n6604924_31331224_3807.jpg")
		#self.framebuffer.paste(im, (5, 5))

		px = self.framebuffer.load()
		for y in xrange(self.size[1]):
			for x in xrange(self.size[0]):
				px[x,y] = y % 255

	def calcsize(self, fmt):
		return struct.calcsize(self.align_byte_order_format(fmt))

	def push_pack(self, fmt, *args):
		self.push(struct.pack(self.align_byte_order_format(fmt), *args))

	def pop_unpack(self, fmt):
		fmt = self.align_byte_order_format(fmt)
		return struct.unpack(fmt, self.pop(self.calcsize(fmt)))

	def push_rfb_string(self, msg):
		print "push_rfb_string: %s" % msg 
		self.push_pack("L", len(msg))
		self.push(msg)

	def push_rfb_array(self, length_type, element_type, elements):
		self.push_pack(length_type, len(elements))
		for e in elements:
			self.push_pack(element_type, e)

	def push_rfb_failure_message(self, reason):
		self.push_rfb_string(reason)
		self.push_close()
		self.process_incoming_data = self.null_handler

	def push_rfb_failed_bit(self, t="L"):
		self.push_pack(t, 1) 

	def push_rfb_good_bit(self, t="L"):
		self.push_pack(t, 0)

	def vnc_welcome(self):
		self.push(self.server_version)
		self.process_incoming_data = self.vnc_welcome_answer

	def vnc_welcome_answer(self, rbytes):
		size = len(self.server_version)
		if self.read_buf_size() < size:
			return
		self.client_version = self.pop(size).strip()
		print "client version is '%s'" % self.client_version
		if not self.client_version != self.server_version:
			self.push_rfb_failure_message("Unsupported protocol")
		else:
			self.process_incoming_data = self.vnc_security_types_answer
			self.push_rfb_array("B", "B", self.security_types)

	def vnc_security_types_answer(self, rbytes):
		if self.read_buf_size() < 1:
			return
		type_id = self.pop_unpack('B')[0]
		assert self.read_buf_size() == 0
		security_handler = self.security_types.get(type_id, None)
		if security_handler is None:
			self.push_rfb_failure_message("Unsupported security type")
		else:
			print "Using security_handler: %s" % security_handler.__name__
			security_handler()

	def vnc_authenticate(self, response):
		assert len(response) == self.vnc_des_challenge_size
		assert len(self.challenge) == self.vnc_des_challenge_size
		enc = self.encrypt_bytes(self.password, self.challenge)
		assert len(enc) == len(self.challenge) 
		return enc == response

	def vnc_des_authentication(self):
		self.password = "abc123"
		self.challenge = os.urandom(self.vnc_des_challenge_size)
		self.push(self.challenge)
		self.process_incoming_data = self.vnc_des_authentication_answer

	def vnc_des_authentication_answer(self, rbytes):
		if self.read_buf_size() < self.vnc_des_challenge_size:
			return
		challenge_response = self.pop(self.vnc_des_challenge_size)
		assert self.read_buf_size() == 0
		if not self.vnc_authenticate(challenge_response):
			self.push_rfb_failed_bit()
			self.push_rfb_failure_message("Bad password")
		else:
			self.push_rfb_good_bit()
			self.process_incoming_data = self.vnc_client_init

	def vnc_client_init(self, rbytes):
		if self.read_buf_size() < 1:
			return
		shared_desktop = self.pop_unpack('B')[0]
		assert self.read_buf_size() == 0
		if shared_desktop == 0:
			print "client wants exclusive desktop access"
		else:
			print "client wants shared desktop access"
		self.vnc_server_init()

	def push_pixel_format(self):
		pf = self.pixel_format 
		self.push_pack("4B 3H 3B 3x", 
			pf['bpp'], pf['depth'], pf['big-endian'], pf['true-color'],
			pf['color-max'][0], pf['color-max'][1], pf['color-max'][2],
			pf['color-shift'][0], pf['color-shift'][1], pf['color-shift'][2], 
		)

	def vnc_server_init(self):
		self.push_pack("2H", *self.size)
		self.push_pixel_format()
		self.push_rfb_string(self.desktop_name)
		self.process_incoming_data = self.vnc_message_loop

	def build_color_map_BGR233(self):
		build_table = lambda nR, nG, nB, x: [(r*x/(nR-1), g*x/(nG-1), b*x/(nB-1)) for b in xrange(nB) for g in xrange(nG) for r in xrange(nR)]
		colors = build_table(8, 8, 4, 65535)
		assert len(colors) == 8*8*4
		for i in xrange(len(colors)):
			colors.extend(colors.pop(0))
		assert len(colors) == 8*8*4*3
		return colors

	def set_color_map_BGR233(self):
		if self.client_pixel_format is None:
			return False
		if self.client_pixel_format['bpp'] != 8:
			return False
		msg_type = 1
		first_color = 0
		colors = self.build_color_map_BGR233()

		ncolors = len(colors)/3
		self.push_pack("Bx2H", msg_type, 0, ncolors)
		self.push_pack("%sH" % (3*ncolors), *colors)

	#def vnc_server_set_color_map_entries(self):
	#	if self.pixel_format['true-color']:
	#		return
	#	msg_type = 1
	#	ncolors = (1 << self.pixel_format['depth'])

	#	nR, nG, nB = self.pixel_format['color-max']

	#	color_space		=	lambda i:						[Decimal(x)/(Decimal(1<<i)-1) for x in xrange(0, (1<<i))]
	#	quantize			=	lambda i, b:				int((i*b).quantize(Decimal(1), rounding=ROUND_UP))
	#	rgb_quantize	= lambda p, b:				(quantize(p[0], b), quantize(p[1], b), quantize(p[2], b))
	#	rgbXXX				= lambda R, G, B, x:	[rgb_quantize((r, g, b), x)		for r in R for g in G for b in B]

	#	R, G, B = color_space(nR), color_space(nG), color_space(nB)

	#	# these get stored locally
	#	rgb888 = rgbXXX(R, G, B, 255)

	#	assert len(rgb888) == ncolors
	#	
	#	self.color_map = [{},{}]
	#	self.color_map[0] = rgb888

	#	for i in xrange(len(rgb888)):
	#		pixel = rgb888[i]
	#		self.color_map[1][pixel] = i

	#	# these get sent
	#	rgbHHH = rgbXXX(R, G, B, 65535)

	#	assert len(rgbHHH) == ncolors

	#	# list flattener
	#	for i in xrange(ncolors):
	#		rgbHHH.extend(rgbHHH.pop(0))

	#	assert len(rgbHHH) == 3*ncolors

	#	self.push_pack("Bx2H", msg_type, 0, ncolors)
	#	self.push_pack("%sH" % (3*ncolors), *rgbHHH)

	#def get_most_used_colors(self, count):
	#	colors = self.framebuffer.getcolors(self.size[0]*self.size[1])
	#	if len(colors) <= count:
	#		return colors # save some CPU
	#	colors.sort(reverse=True)
	#	return colors[:count]

	def vnc_message_loop(self, rbytes):
		if self.read_buf_size() < 1:
			return
		msg_type = self.pop_unpack('B')[0]
		message_handler = self.vnc_client_msg_handler.get(msg_type, None)
		if message_handler is None:
			msg = "Invalid message type %s" % msg_type
			self.push_rfb_failure_message(msg)
		else:
			self.process_incoming_data = message_handler
			message_handler(rbytes)

	def vnc_client_msg_set_pixel_format(self, rbytes):
		fmt = "3x 4B 3H 3B 3x"
		size = self.calcsize(fmt)
		if self.read_buf_size() < size:
			return
		pfmt = self.pop_unpack(fmt)
		bpp, depth, bendian, tcolor, rmax, gmax, bmax, rshift, gshift, bshift = pfmt

		pixel_format = {
			'bpp'					: bpp,
			'depth'				: depth,
			'big-endian'	: bendian != 0,
			'true-color'	: tcolor != 0,
			'color-max'		: (rmax, gmax, bmax),
			'color-shift'	: (rshift, gshift, bshift)
		}
		print "set_pixel_format: %s" % pixel_format
		self.client_pixel_format = pixel_format 
		self.set_color_translation()
		self.process_incoming_data = self.vnc_message_loop

	def vnc_client_msg_set_encodings(self, rbytes):
		fmt = "xH"
		size = self.calcsize(fmt)
		if self.read_buf_size() < size:
			return
		self.state['num_encodings'] = self.pop_unpack(fmt)[0]
		self.process_incoming_data = self.vnc_client_msg_set_encodings_finish
		self.process_incoming_data(rbytes)
	
	def vnc_client_msg_set_encodings_finish(self, rbytes):
		fmt = '%sl' % self.state['num_encodings']
		size = self.calcsize(fmt)
		if self.read_buf_size() < size:
			return
		self.state['encodings'] = self.pop_unpack(fmt)
		print "set_encodings: %s" % repr(self.state['encodings'])
		self.process_incoming_data = self.vnc_message_loop
		del self.state['num_encodings']

	def vnc_client_msg_framebuffer_update_request(self, rbytes):
		size = self.calcsize('B4H')
		if self.read_buf_size() < size:
			return
		incr, x, y, w, h = self.pop_unpack('B4H')
		print "framebuffer_update_request: %s %s %s %s %s" % (incr, x, y, w, h)
		self.process_incoming_data = self.vnc_message_loop
		if incr == 0:
			self.vnc_framebuffer_update(incr, x, y, w, h)

	def vnc_framebuffer_update(self, incr, x, y, w, h):
		if self.framebuffer is None:
			self.initialize_framebuffer()
		print "vnc_framebuffer_update"
		msg_type, num_rect, raw_enc = 0, 1, 0
		self.push_pack("Bx3H", msg_type, num_rect, 0, 0)
		self.push_pack("2H", *self.size)
		self.push_pack("l", raw_enc)

		print "before"
		data = "".join([chr(c) for c in self.framebuffer.getdata()])
		self.push(data)
		print "after"

	#def find_closest_color(self, pixel):
	#	# exact match
	#	color_index = self.color_map[1].get(pixel, None)
	#	if color_index is None:
	#		color_index = 0
	#		best_weight = self.get_pixel_weight(
	#				self.get_pixel_difference(pixel, self.color_map[0][color_index]))
	#		for cpi in xrange(len(self.color_map[0])):
	#			cpx = self.color_map[0][cpi]
	#			diff = self.get_pixel_difference(pixel, cpx)
	#			weight = self.get_pixel_weight(diff)
	#			if weight == 1: # we've found the best possible match
	#				return cpi
	#			if weight < best_weight:
	#				color_index = cpi
	#				best_weight = weight

	#	return color_index

	#def get_pixel_weight(self, pixel):
	#	r,g,b = pixel
	#	return r*r + g*g + b*b

	#def get_pixel_difference(self, pa, pb):
	#	#print pa, pb
	#	r,g,b = pa
	#	R,G,B = pb
	#	return (abs(r-R), abs(g-G), abs(b-B))

	def vnc_client_msg_key_event(self, rbytes):
		fmt = "B 2x L"
		size = self.calcsize(fmt)
		if self.read_buf_size() < size:
			return
		down_flag, key = self.pop_unpack(fmt)
		print "key_event: %s %s" % (down_flag, key)
		self.process_incoming_data = self.vnc_message_loop

	def vnc_client_msg_pointer_event(self, rbytes):
		fmt = "B2H"
		size = self.calcsize(fmt)
		if self.read_buf_size() < size:
			return
		bmask, x, y = self.pop_unpack(fmt)
		print "pointer_event: %s %s %s" % (bmask, x, y)
		self.process_incoming_data = self.vnc_message_loop

	def vnc_client_cut_text(self, rbytes):
		fmt = "3xL"
		size = self.calcsize(fmt)
		if self.read_buf_size() < size:
			return
		self.state['length'] = self.pop_unpack(fmt)[0]
		self.process_incoming_data = self.vnc_client_cut_text_finish
		self.process_incoming_data(rbytes)

	def vnc_client_cut_text_finish(self, rbytes):
		if self.read_buf_size() < self.state['length']:
			return
		self.state['client-cut-text'] = self.pop(self.state['length'])
		del self.state['length']
		self.process_incoming_data = self.vnc_message_loop
		print "vnc_client_cut_text_finish: %s" % self.state['client-cut-text']

	def null_handler(self, rbytes):
		pass

	def handle_read(self):
		bufsz = self.read_buf_size()
		r = server.Channel.handle_read(self)
		if self.read_buf_size() > 0:
			self.process_incoming_data(r)

class rfbServer(Server):
	def init(self):
		pass

def main(argv):
	addrs = [('', 3000)]
	server.loop(addrs, rfbServer, {
		'channel' : rfbConnection,
		'idle' : 600,
		}
	)

#end/main

if __name__ == '__main__':
	main(sys.argv)

