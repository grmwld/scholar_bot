import time
import urllib
import urllib2
import urlparse
import json
import mimetypes
import os
import httplib
import types
import datetime

from lib import properties

# TODO
# make setup.py
# update README.md
# better error handling? (GettError)

class ApiError(StandardError):
	pass

def _api_url(*url):
	if len(url) == 1:
		url = url[0]

	if isinstance(url, tuple) or isinstance(url, list):
		ids = url[1:]
		url = url[0] % ids

	return 'https://open.ge.tt/1/%s' % url

def _safe_read(resp):
	try:
		msg = resp.read()
		return json.loads(msg)['error']
	except:
		return ''

def _request(url, token = None):
	url = _api_url(url)

	query = {}
	if token:
		if hasattr(token, 'token'):
			token = token.token

		query['accesstoken'] = token

	url = url + '?' + urllib.urlencode(query)

	req = urllib2.Request(url)
	req.add_header('User-Aget', 'pett-gett')

	#print url

	return req

def _response(req):
	try:
		resp = urllib2.urlopen(req)
	except urllib2.HTTPError as err:
		raise ApiError('Unexpected HTTP status code received %s %s' % (err.code, _safe_read(err)))
	except IOError as err:
		raise ApiError(err.message)

	headers = resp.info()

	if 'application/json' in headers['Content-Type']:
		return json.loads(resp.read())

	return resp

def _get(url, token = None):
	req = _request(url, token)
	return _response(req)

def _post(url, token = None, body = None):
	req = _request(url, token)

	if isinstance(body, dict):
		body = json.dumps(body)

	if not body is None:
		req.add_header('Content-Type', 'application/json')

	req.add_data(body or '')

	return _response(req)

class Token(properties.Properties):
	accesstoken = properties.property()
	refreshtoken = properties.property()
	expires = properties.property()

	def __str__(self):
		return self.accesstoken

	@expires.set
	def expires(self, expires):
		self.write_attribute('expires', time.time() + expires)

	def expired(self):
		return self.expires <= time.time()

class User(properties.Properties):
	share_cls = None

	class Storage(properties.Properties):
		used = properties.property()
		limit = properties.property()
		extra = properties.property()

		@classmethod
		def get(cls, user):
			user = _get(('users/me'), user)
			return cls(user['storage'])

		def limit_exceeded(self):
			return self.left() <= 0

		def left(self):
			return self.limit - self.used

	userid = properties.property(id = True)
	fullname = properties.property()
	email = properties.property()
	storage = properties.property()

	@classmethod
	def login(cls, credentials_or_refreshtoken):
		auth = credentials_or_refreshtoken

		if isinstance(credentials_or_refreshtoken, str):
			auth = { 'refreshtoken' : credentials_or_refreshtoken }
		elif isinstance(credentials_or_refreshtoken, Token):
			auth = { 'refreshtoken' : credentials_or_refreshtoken.refreshtoken }

		attrs = _post('users/login', body = auth)
		user = cls(attrs['user'])
		user.token = Token(attrs)

		return user

	@classmethod
	def login_token(cls, credentials_or_refreshtoken):
		user = cls.login(credentials_or_refreshtoken)
		return user.token

	def build_share(self, attrs = {}):
		return self.share_cls(attrs)

	@storage.set
	def storage(self, value):
		if isinstance(value, dict):
			value = User.Storage(value)

		self.write_attribute('storage', value)

	@property
	def token(self):
		if self._token.expired():
			self.refresh_token()

		return self._token

	@token.setter
	def token(self, token):
		self._token = token

	def refresh_token(self):
		self._token = self.login_token(self._token)
		return self._token

	def get_storage(self):
		self.storage = User.Storage.get(self)
		return self.storage

	def shares(self):
		shares = self.share_cls.all(self)
		
		for share in shares:
			share.user = self

		return shares

	def share(self, sharename):
		share = self.share_cls.find(sharename)
		share.user = self

		return share

	def create_share(self, attrs = {}):
		share = self.share_cls.create(self, attrs)
		share.user = self

		return share

	def update_share(self, sharename, attrs = {}):
		share = self.share_cls.update(self, sharename, attrs)
		share.user = self

		return share

	def destroy_share(self, sharename):
		self.share_cls.destroy(self, sharename)

def _created(self, value):
	self.write_attribute('created', datetime.datetime.fromtimestamp(value))

def _update_share(self, attrs = {}):
	share = self.__class__.update(self.user, self.sharename, attrs)
	self.attributes = share.attributes

	return self

def _destroy_share(self):
	self.__class__.destroy(self.user, self.sharename)

class Share(properties.Properties):
	file_cls = None

	def __new__(cls, *args, **kwargs):
		instance = super(Share, cls).__new__(cls)

		instance.update = types.MethodType(_update_share, instance, cls)
		instance.destroy = types.MethodType(_destroy_share, instance, cls)

		return instance

	sharename = properties.property(id = True)
	title = properties.property()
	readystate = properties.property()
	created = properties.property(write = _created)
	live = properties.property()
	files = properties.property()

	@classmethod
	def all(cls, token):
		shares = _get('shares', token = token)
		return [cls(s) for s in shares]

	@classmethod
	def find(cls, sharename):
		share = _get(('shares/%s', sharename))
		return cls(share)

	@classmethod
	def create(cls, token, attrs = {}):
		share = _post('shares/create', token, attrs)
		return cls(share)

	@classmethod
	def update(cls, token, sharename, attrs = {}):
		share = _post(('shares/%s/update', sharename), token, attrs)
		return cls(share)

	@classmethod
	def destroy(cls, token, sharename):
		_post(('shares/%s/destroy', sharename), token)

	def __eq__(self, other):
		if isinstance(other, self.__class__):
			return other.sharename == self.sharename

		return False

	def build_file(self, attrs = {}):
		return self.file_cls(attrs)

	@files.set
	def files(self, value):
		value = value or []
		self.write_attribute('files', [self.build_file(f) for f in value])

		#self.write_attribute('files', [File(f) for f in value])

		#for file in self.files:
		#	file.share = self

	@property
	def user(self):
		return getattr(self, '_user', None) #self._user

	@user.setter
	def user(self, user):
		self._user = user

	def file(self, fileid):
		#file = File.find(self.sharename, fileid)
		#file.share = self

		#return file

		fileid = str(fileid)

		try:
			return (f for f in self.files if f.fileid == fileid).next()
		except StopIteration:
			raise ApiError('No file with fileid %s in share %s' % (fileid, self.sharename))

	def create_file(self, attrs = {}):
		file = self.file_cls.create(self.user, self.sharename, attrs)
		file.share = self

		self.files.insert(0, file)

		return file

	def destroy_file(self, fileid):
		file = self.file(fileid)
		self.file_cls.destroy(self.user, self.sharename, fileid)

		self.files.remove(file)

	def blob_file(self, fileid):
		file = self.file(fileid)
		return file.blob()

	def write_file(self, fileid, file):
		file = self.file(fileid)
		file.write(file)

		return file

	def upload_file(self, filepath):
		file = self.file_cls.upload_file(self.user, self.sharename, filepath)
		file.share = self

		self.files.insert(0, file)

		return file

def _destroy_file(self):
	share = self.share
	self.__class__.destroy(share.user, share.sharename, self.fileid)

def _path(url):
	url = urlparse.urlparse(url)
	return url.path + '?' + url.query

def _host(url):
	url = urlparse.urlparse(url)
	return url.netloc

class File(properties.Properties):
	def __new__(cls, *args, **kwargs):
		instance = super(File, cls).__new__(cls)
		instance.destroy = types.MethodType(_destroy_file, instance, cls)

		return instance

	class Upload(properties.Properties):
		puturl = properties.property()
		posturl = properties.property()

		@classmethod
		def get(cls, token, sharename, fileid):
			upload = _get(('files/%s/%s/upload', sharename, fileid), token)
			return cls(upload)

		def putpath(self):
			return _path(self.puturl)
			#url = urlparse.urlparse(self.puturl)
			#return url.path + '?' + url.query

		def postpath(self):
			return _path(self.posturl)
			#url = urlparse.urlparse(self.posturl)
			#return url.path + '?' + url.query

		def puthost(self):
			return _host(self.puturl)

		def posthost(self):
			return _host(self.posturl)

	fileid = properties.property(id = True)
	filename = properties.property()
	sharename = properties.property()
	downloadurl = properties.property()
	readystate = properties.property()
	size = properties.property()
	downloads = properties.property()
	created = properties.property(write = _created)
	upload = properties.property()

	@classmethod
	def find(cls, sharename, fileid):
		file = _get(('files/%s/%s', sharename, fileid))
		return cls(file)

	@classmethod
	def create(cls, token, sharename, attrs = {}):
		file = _post(('files/%s/create', sharename), token, attrs)
		return cls(file)

	@classmethod
	def destroy(cls, token, sharename, fileid):
		_post(('files/%s/%s/destroy', sharename, fileid), token)

	@classmethod
	def upload_file(cls, token, sharename, filepath):
		with open(filepath, 'rb') as f:
			mime, enc = mimetypes.guess_type(filepath)
			file = cls.create(token, sharename, { 'filename' : os.path.basename(filepath) })

			file.write(f, mime)

			return file

	def __eq__(self, other):
		if isinstance(other, self.__class__):
			return other.fileid == self.fileid and other.sharename == self.sharename

		return False

	@upload.set
	def upload(self, value):
		if value:
			if isinstance(value, dict):
				value = File.Upload(value)

			self.write_attribute('upload', value)

	@upload.get
	def upload(self):
		upload = self.read_attribute('upload')

		if upload is None:
			share = self.share
			upload = File.Upload.get(self.share.user, self.share.sharename, self.fileid)

			self.upload = upload

		return upload

	@property
	def share(self):
		return getattr(self, '_share', None) #self._share

	@share.setter
	def share(self, share):
		self.sharename = share.sharename
		self._share = share

	def write(self, file, mimetype = None):
		if not mimetype:
			mimetype = mimetypes.guess_type(self.filename) or 'application/octet-stream'
		
		headers =  { 
			'User-Agent' : 'gett-pett',
			'Content-Type' : mimetype
		}

		conn = httplib.HTTPConnection(self.upload.puthost())
		conn.request('PUT', self.upload.putpath(), file, headers)

		resp = conn.getresponse()

		if resp.status not in range(200, 300):
			raise ApiError('Unexpected HTTP status code received %s %s' % (resp.status, _safe_read(resp)))

		self.readystate = 'uploaded'

		conn.close()

	def blob(self):
		if self.readystate in ['uploading', 'uploaded'] or (self.readystate == 'remote' and self.share.live):
			return _get(('files/%s/%s/blob', self.share.sharename, self.fileid))
		else:
			raise ApiError("Wrong state, can't read file")

	def thumb(self):
		if self.readystate == 'uploaded':
			return _get(('files/%s/%s/blob/thumb', self.share.sharename, self.fileid))
		else:
			raise ApiError("Wrong state, can't retreive image thumb")

	def scale(self, width, height):
		if self.readystate == 'uploaded':
			return _get(('files/%s/%s/blob/scale?size=%sx%s', self.share.sharename, self.fileid, width, height))
		else:
			raise ApiError("Wrong state, can't retreive scaled image")

User.share_cls = Share
Share.file_cls = File
