#!/usr/bin/python

from __future__ import with_statement
import sys
import asyncore
import socket
import time

def loop(addrs, klass, args):
	servers = []
	for bind in addrs:
		s = klass(bind[0], bind[1], args)
		servers.append(s)
	try: asyncore.loop(60)
	except KeyboardInterrupt:
		print "CTRL+C detected. Stopping."
	for server in servers:
		server.close()

class Server(asyncore.dispatcher):

	def __init__(self, addr, port, options):
		asyncore.dispatcher.__init__(self)
		self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
		self.set_reuse_addr()
		try:
			self.bind((addr, port))
		except socket.error, (eno, msg):
			raise Exception(msg)
		self.listen(5)
		self.addr = addr
		self.clients = []
		self.options = options
		self.init()
	
	def init(self): # for subclasses, easier
		pass

	def always_false(self):
		return False

	def always_true(self):
		return True

	def readable(self):
		now = time.time()
		for client in self.clients:
			idle = now - client.active
			if idle > self.options['idle']:
				client.readable = self.always_false
				client.writable = self.always_true
				client.handle_write = lambda: client.handle_close()
		return True

	def writable(self):
		return False

	def handle_client_close(self, client):
		if client in self.clients:
			self.clients.remove(client)
		client._close()

	def handle_accept(self):
		sock, addr = self.accept()
		c = self.options['channel'](sock, addr, self)
		self.clients.append(c)
		c._close = c.close
		c.close = lambda: self.handle_client_close(c)
		c.accepted()

class Channel(asyncore.dispatcher):

	def	__init__(self, sock, addr, server):
		asyncore.dispatcher.__init__(self, sock)
		self.active = time.time()
		self.addr = addr
		self.data = {'write':"", 'read':""}
		self.server = server
		self.close_when_done = False
		self.init()
	
	def init(): # for subclasses, easier
		pass

	def accepted():
		pass

	def read_buf_size(self):
		return len(self.data['read'])

	def push(self, data):
		if data is None:
			self.close_when_done = True
		if not self.close_when_done:
			self.data['write'] += data

	def push_close(self):
		self.push(None)

	def pop(self, num_bytes):
		r = self.data['read'][:num_bytes]
		self.data['read'] = self.data['read'][num_bytes:] 
		return r

	def pop_write(self, num_bytes):
		s = self.data['write'][:num_bytes]
		self.data['write'] = self.data['write'][num_bytes:] 
		return s

	def close(self):
		asyncore.dispatcher.close(self)

	def handle_close(self):
		self.close()
			
	def readable(self):
		return True

	def writable(self):
		return len(self.data['write']) > 0

	def handle_read(self): # read FROM socket
		self.active = time.time()
		x = self.recv(8192)
		self.data['read'] += x
		return len(x)

	def handle_write(self): # write TO socket
		self.active = time.time()
		sent = 0
		if self.writable():
			sent = self.send(self.data['write'])
			self.pop_write(sent)
		if not self.writable() and self.close_when_done:
			self.handle_close()
		return sent

