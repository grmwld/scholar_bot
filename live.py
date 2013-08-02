import json
import socket
import ssl
import Queue
import threading
import string
import random
import inspect

import httplib
import os
import mimetypes
import time
import logging

import rest

HOST = 'open.ge.tt'
PORT = 443

SESSION = string.ascii_uppercase + string.ascii_lowercase + string.digits

def _generate_session(size = 8):
	return ''.join(random.choice(SESSION) for x in range(size))

def _call(method, params):
	args = inspect.getargspec(method).args
	args = dict([(name, params[name]) for name in args if name in params])

	return method(**args)

class JsonSocket(object):
	def __init__(self, host, port):
		sock = socket.socket();sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		sock = ssl.wrap_socket(sock)
		sock.connect((host, port))

		self._socket = sock

		self._handshake()

	def _handshake(self):
		self._socket.send('GET / HTTP/1.1\r\nUpgrade: jsonsocket\r\n\r\n')
		resp = self._read('\r\n\r\n')

	def _read(self, terminator):
		buffer = []

		while len(buffer) < 1 or terminator not in buffer[-1]:
			buffer.append(self._socket.recv(1024))

		buffer[-1] = buffer[-1].replace(terminator, '')

		return ''.join(buffer)

	def send(self, msg):
		if not isinstance(json, str):
			msg = json.dumps(msg)

		self._socket.send(msg + '\n')

	def recv(self):
		resp = None

		while not resp or resp == 'ping':
			if resp:
				self.send('pong')

			resp = self._read('\n')

		return json.loads(resp)

	def close(self):
		self._socket.close()

class Api(threading.Thread):
	def __init__(self):
		self._socket = None #JsonSocket(HOST, PORT)
		self._session = None #_generate_session()

		self._run = True

		super(Api, self).__init__()

	def connect(self, token, session = None):
		self._socket = JsonSocket(HOST, PORT)

		if not session:
			session = _generate_session()

		self._session = session

		self._socket.send({
			'type' : 'connect',
			'accesstoken' : str(token.token if hasattr(token, 'token') else token),
			'session' : session
		})

		self.start()

	@property
	def session(self):
		return self._session

	def on_download(self, sharename, fileid, filename):
		pass

	def on_storagelimit(self, sharename, fileid, filename):
		pass

	def on_filestat(self, sharename, fileid, filename, size):
		pass

	def on_violatedterms(self, sharename, fileid, filename, reason):
		pass

	def on_error(self, err):
		raise err

	def run(self):
		try:
			while self._run:
				msg = self._socket.recv()
				method = getattr(self, 'on_' + msg['type'])

				del msg['type']
				_call(method, msg)
		except (socket.error, ValueError) as err:
			self.on_error(err)


	def close(self):
		self._run = False
		self._socket.close()

BUFFER_SIZE = 65535
_logger = logging.getLogger('gett.pool')

class PoolApi(Api):
	def __init__(self, pool):
		self._pool = pool

		super(PoolApi, self).__init__()

	def on_download(self, sharename, fileid):
		_logger.debug('download received from live api for file %s in share %s', fileid, sharename)

		self._pool.api('download', sharename, fileid)
		#self._pool.download(sharename, fileid)

	def on_violatedterms(self, sharename, fileid):
		self._pool.api('violatedterms', sharename, fileid)

	def on_storagelimit(self, sharename, fileid):
		self._pool.api('storagelimit', sharename, fileid)

	def on_error(self, err):
		_logger.error('live api error %s', err)

class Uploader(threading.Thread):
	def __init__(self, filename, file, pool):
		self.filename = filename
		self.file = file
		self.pool = pool

		self.started = False
		self.uploaded = False
		self.error = False

		super(Uploader, self).__init__()

	def __eq__(self, other):
		if isinstance(other, Uploader):
			return self.file == other.file

		return False

	def __repr__(self):
		return str(self)

	def __str__(self):
		return '[{ sharename : %s, fileid : %s } started=%s uploaded=%s error=%s]' % \
			(self.file.sharename, self.file.fileid, self.started, self.uploaded, self.error)

	@property
	def running(self):
		return self.started and not (self.uploaded or self.error)

	def stop(self):
		pass

	def run(self):
		self.started = True
		_logger.info('starting upload of file %s', self.file)

		conn = None

		try:
			with open(self.filename, 'rb') as f:
				size = os.path.getsize(self.filename)
				type, enc = mimetypes.guess_type(self.filename)
				url = self.file.upload
				headers = {
					'User-Agent' : 'gett-pett-live', 
					'Content-Length' : size,
					'Content-Type' : type
				}

				conn = httplib.HTTPConnection(url.puthost())

				_logger.debug('establishing connection to %s method=%s path=%s headers=%s', 
					url.puthost(),
					'PUT', 
					url.putpath(), 
					headers
				)

				conn.request('PUT', url.putpath(), None, headers)

				read = 0
				progress = 0

				self._event('uploading', progress)

				while read < size:
					buffer = f.read(BUFFER_SIZE)
					conn.send(buffer)
					read += len(buffer)

					new_progress = int(100 * float(read) / size)

					if new_progress > progress:
						progress = new_progress
						self._event('uploading', progress)

				resp = conn.getresponse()

				if not resp.status in xrange(200, 300):
					raise IOError('Received unexpected response %s %s' % (resp.status, resp.message))

				self.uploaded = True
				_logger.info('uploaded file %s in share %s', self.file.fileid, self.file.sharename)

				self._event('upload')
		except Exception as err:
			self.error = True
			_logger.exception('error uploading file %s %s', self.file, err)

			self._event('error', err)
		finally:
			if conn:
				try:
					conn.close()
				except:
					pass
	
	def _event(self, what, *args):
		self.pool.event(what, self.file, *args)

def _find(list, fn):
	try:
		return (item for item in list if fn(item)).next()
	except StopIteration:
		return None

class Pool(threading.Thread):
	MESSAGE_PRIORITIES = ['self', 'download', 'add', 'event']

	def __init__(self, token):
		self._pool = []
		self._uploading = []

		self._pool_lock = threading.RLock()
		self._message_queue = Queue.PriorityQueue()

		self._api = PoolApi(self)
		self._api.connect(token)

		super(Pool, self).__init__()
		self.start()

		_logger.info('pool initiated for token "%s"', token)

	@property
	def session(self):
		return self._api.session

	def add(self, filename, file):
		with self._pool_lock:
			self._pool.append(Uploader(filename, file, self))

		self._message('add')

	def event(self, what, file, *args):
		self._message('event', { 'type' : what, 'args' : args, 'file' : file })

	def api(self, what, sharename, fileid):
		self._message(what, { 'sharename' : sharename, 'fileid' : fileid })

	def stop(self):
		self._message('self', { 'action' : 'stop' })

	def run(self):
		while True:
			priority, time, type, params = self._message_queue.get(True)
			active_uploads = any([u.running for u in self._uploading])

			_logger.debug('message received %s', [priority, time, type, params])

			if type == 'add' and not active_uploads and self._pool:
				with self._pool_lock:
					uploader = self._pool.pop()
					self._uploading.append(uploader)
					uploader.start()
			elif type == 'event':
				file, type = params['file'], params['type']

				if type == 'upload':
					self._message('add')

				try:
					file.emit_event(type, *params['args'])
				except Exception as err:
					_logger.info('error in event handler for file %s', file)
			elif type == 'download':
				sharename, fileid = params['sharename'], params['fileid']
				fn = lambda u: u.file.sharename == sharename and u.file.fileid == fileid

				with self._pool_lock:
					uploader = _find(self._pool, fn)

					if uploader:
						self._pool.remove(uploader)
						self._uploading.append(uploader)
						uploader.start()
					else:
						_logger.debug('file %s in share %s already being uploaded', fileid, sharename)
						uploader = _find(self._uploading, fn)

				#uploader.file.emit_event('download')
				self.event('download', uploader.file)
			elif type == 'self':
				action = params['action']

				if action == 'stop':
					self._api.close()

					for uploader in self._uploading:
						uploader.stop()

					return


	def _message(self, type, params = None):
		self._message_queue.put((Pool.MESSAGE_PRIORITIES.index(type), time.time(), type, params))

def _on_download(file):
	file.downloads += 1

def _on_uploading(file, progress):
	if progress == 0:
		file.readystate = 'uploading'

def _on_upload(file):
	file.readystate = 'uploaded'

def _pool(token, pools):
	token = str(token.token if hasattr(token, 'token') else token)
	pool = pools.get(token, None)

	if not pool:
		pool = Pool(token)
		pools[token] = pool

	return pool

class File(rest.File):
	_pools = {}

	@classmethod
	def upload_file(cls, token, sharename, filepath, callback = None):
		pool = _pool(token, cls._pools)
		file = cls.create(token, sharename, { 'filename' : os.path.basename(filepath), 'session' : pool.session })

		if callback:
			callback(file)

		pool.add(filepath, file)

		return file

	def __init__(self, *args, **kwargs):
		super(File, self).__init__(*args, **kwargs)

		self._events = { 
			'download' : [_on_download],
			'uploading' : [_on_uploading],
			'upload' : [_on_upload]
		}

	def on_event(self, event, listener):
		event_list = self._events.get(event, None)

		if not event_list:
			event_list = []
			self._events[event] = event_list

		event_list.append(listener)

	def emit_event(self, event, *args, **kwargs):
		event_list = self._events.get(event, [])

		for listener in event_list:
			listener(self, *args, **kwargs)
		
class Share(rest.Share):
	file_cls = File

	def upload_file(self, filepath, callback = None):
		file = self.file_cls.upload_file(self.user, self.sharename, filepath, callback)
		file.share = self

		self.files.insert(0, file)

		return file

class User(rest.User):
	share_cls = Share
