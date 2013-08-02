import __builtin__

class Property(object):
	ALLOWED = ['write', 'read', 'id']

	def __init__(self, opts = {}):
		for name, value in opts.items():
			if name not in self.ALLOWED:
				raise StandardError('Unknown option "%s"' % name)

		defaults = dict([(name, None) for name in self.ALLOWED])
		defaults.update(opts)

		self.__dict__.update(defaults)

	def get(self, f):
		self.read = f
		return self

	def set(self, f):
		self.write = f
		return self

	def __get__(self, instance, owner):
		if instance is None:
			return self

		if self.read:
			return self.read(instance)

		return instance.read_attribute(self.name)

	def __set__(self, instance, value):
		if self.write:
			self.write(instance, value)
		else:
			instance.write_attribute(self.name, value)

def property(**opts):
	return Property(opts)

class Properties(object):
	@classmethod
	def properties(cls):
		if not hasattr(cls, '_properties'):
			#print cls, dir(cls)

			#cls._properties = [(name, p) for name, p in cls.__dict__.items() if isinstance(p, Property)]
			cls._properties = [(name, getattr(cls, name)) for name in dir(cls) if isinstance(getattr(cls, name), Property)]

			for name, p in cls._properties:
				p.name = name
		
		return cls._properties

	@classmethod
	def has_property(cls, name):
		return not cls.get_property(name) is None

	@classmethod
	def get_property(cls, name):
		return dict(cls.properties()).get(name, None)

	@classmethod
	def id_property(cls):
		for name, p in cls.properties():
			if(p.id):
				return (name, p)

		return (None, None)

	def __init__(self, attrs = {}):
		props = dict([(name, None) for name, p in self.properties()])
		self._properties = props.copy()

		props.update(attrs)
		self.attributes = props

	def __getitem__(self, name):
		return self.read_attribute(name)

	def __setitem__(self, name, value):
		self.write_attribute(name, value)

	def __repr__(self):
		return str(self)

	def __str__(self):
		return str(self.attributes)

	@__builtin__.property
	def id(self):
		name, prop = self.id_property()
		return self.read_attribute(name) if name else None

	def read_attribute(self, name):
		return self._properties[name]

	def write_attribute(self, name, value):
		self._properties[name] = value

	@__builtin__.property
	def attributes(self):
		return dict([(name, value) for name, value in self._properties.items() if not value is None])

		#attrs = []
		#for name, p in self.properties():
		#	value = getattr(self, name)
		#	if not value is None:
		#		attrs.append((name, value))

		#return dict(attrs)
 
	@attributes.setter
	def attributes(self, attrs):
		if not isinstance(attrs, dict):
			return

		#attrs = dict([(name, value) for name, value in attrs.items() if self.has_property(name)])
		#self._properties.update(attrs)

		props = [n for n, p in self.properties()]
		for name, value in attrs.items():
			if name in props:			
				setattr(self, name, value)
