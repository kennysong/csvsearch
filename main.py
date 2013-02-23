import webapp2
import jinja2
import csv
import os
import hashlib
import logging
from django.utils import simplejson
import StringIO

from google.appengine.api import files
from google.appengine.api import urlfetch
from google.appengine.ext import db

template_dir = os.path.join(os.path.dirname(__file__), 'templates')
jinja_env = jinja2.Environment(loader = jinja2.FileSystemLoader(template_dir), autoescape=True)

# stores dictionaries as JSON objects in datastore
class JsonProperty(db.TextProperty):
	def validate(self, value):
		return value

	def get_value_for_datastore(self, model_instance):
		'''creates value for datastore'''
		result = super(JsonProperty, self).get_value_for_datastore(model_instance)
		result = simplejson.dumps(result)
		return db.Text(result)

	def make_value_from_datastore(self, value):
		'''makes value for dictionary'''
		try:
			value = simplejson.loads(str(value))
		except:
			pass
		return super(JsonProperty, self).make_value_from_datastore(value)

class Programs(db.Model):
	category = db.StringProperty()
	organization = db.StringProperty()
	program = db.StringProperty()
	city = db.StringProperty()
	state = db.StringProperty()
	region = db.StringProperty()
	days = db.StringProperty()
	weeks = db.StringProperty()
	cost = db.StringProperty()
	cost_range = db.StringProperty()
	finaid = db.StringProperty()
	notes = db.StringProperty()
	deadline = db.StringProperty()
	age = db.StringProperty()
	website = db.StringProperty()
	contact = db.StringProperty()
	md5_hash = db.StringProperty()
	keywords = db.StringListProperty()

class Index(db.Model):
	index = JsonProperty()

class BaseHandler(webapp2.RequestHandler):
	'''Parent class for all handlers, shortens functions'''
	def write(self, content):
		return self.response.out.write(content)

	def rget(self, name):
		'''Gets a HTTP parameter'''
		return self.request.get(name)

	def render(self, template, params={}):
		template = jinja_env.get_template(template)
		self.response.out.write(template.render(params))

	def set_cookie(self, cookie):
		self.response.headers.add_header('Set-Cookie', cookie)

	def delete_cookie(self, cookie):
		self.response.headers.add_header('Set-Cookie', '%s=; Path=/' % cookie)

class MainHandler(BaseHandler):
	def get(self):
		query = self.rget('q')

		if not query:
			self.render('search.html')
		else:
			q = filt_query(query)
			index = get_index()

			if not index:
				self.write('Index is empty. <a href="/">Return Home</a>')
				return

			rankings = get_rankings(q, index)
			# remove all 0 scores
			# {key1:rank1, key2:rank2, ...}
			rankings = {key: rankings[key] for key in rankings if rankings[key] >= 1}

			# list all keys, retrieve programs
			keys = rankings.keys()
			programs = Programs.get(keys)

			# replace keys with actual program entities	
			results = []
			for i in range(len(programs)):
				program = programs[i]
				score = rankings[str(program.key())]
				results.append((program, score))

			# sorted [(program1, rank1), (program2, rank2), ...]
			results_final = sorted(results, key=lambda x: x[1], reverse=True)

			# self.write(repr(results_final))

			self.render('search_results.html', {'results':results_final, 'search':query})

	def post(self):
		url = self.rget('file')
		if not url:
			self.write('No file uploaded. <a href="/">Return Home</a>')
			return

		updated_count = parse_CSV(get_CSV(url))

		self.write('Updated %s entries. <a href="/">Return Home</a>'%updated_count)

def get_CSV(url):
	'''Returns file object (StringIO) from url to csv'''
	result = urlfetch.fetch(url)
	content = result.content.decode('utf-8', 'ignore')
	return StringIO.StringIO(content)

def parse_CSV(f):
	'''Takes a csv file object and adds its contents to the database, returns num updated'''
	reader = csv.reader(f)
	updated_count = 0
	for row in reader:
		if not row[0]: # skip over empty rows
			continue

		# checks if entry exists already using hash
		md5_hash = hashlib.md5(repr(row)).hexdigest()
		if Programs.all().filter('md5_hash =', md5_hash).get():
			continue

		keywords = create_keywords(row)
		p = Programs(category=row[0], organization=row[1], program=row[2], city=row[3], state=row[4], 
			region=row[5], days=row[6], weeks=row[7], cost=row[8], cost_range=row[9], finaid=row[10], 
			notes=row[11], deadline=row[12], age=row[13], website=row[14], contact=row[15], 
			md5_hash=md5_hash, keywords=keywords)

		p.put()
		add_to_index(p)

		updated_count += 1

	return updated_count

def create_keywords(row):
	'''returns list of keywords for row'''
	keywords = row[16].replace(',',' ').split() # parse initial keywords row

	for i in range(15):
		words = row[i].replace(',',' ').split()
		keywords += words

	keywords_lower = [k.lower() for k in keywords]

	return keywords_lower

def add_to_index(program):
	'''adds a program to the index'''
	index_obj = Index.all().get()
	if index_obj:
		index = simplejson.loads(str(index_obj.index))
	else:
		index = dict()

	keywords = program.keywords
	key = str(program.key())

	index[key] = keywords

	if index_obj:
		index_obj.index = simplejson.dumps(index)
		index_obj.put()
	else:
		i = Index(index=simplejson.dumps(index))
		i.put()

def get_index():
	'''returns index as dictionary'''
	q = Index.all().get()
	if q:
		return simplejson.loads(str(q.index))
	else:
		return None

ERROR_CHARS = """'"\\`~!@#$%^&*()-_=+/|[]{};:<>.,?"""

ABBREVIATIONS = {'bio':'biology', 'chem':'chemistry', 'calc':'calculus', 'vocab':'vocabulary',
				'lit':'literature', 'econ':'economics', 'stat':'statistics', 'stats':'statistics',
				'tech':'technology'}

NUM_MAPPING = {'1':'one', '2':'two', '3':'three', '4':'four', '5':'five', '6':'six', '7':'seven', 
			   '8':'eight', '9':'nine', '10':'ten', '11':'eleven', '12':'twelve', '13':'thirteen',
			   '14':'fourteen', '15':'fifteen', '16':'sixteen', '17':'seventeen', '18':'eighteen',
			   '19':'nineteen', '20':'twenty', '30':'thirty', '40':'forty', '50':'fifty',
			   '60':'sixty', '70':'seventy', '80':'eighteen', '90':'ninety'}

COMMON_WORDS = {'the', 'a', 'or', 'and', 'to', 'that', 'of', 'is', 'it', 'for', 'from', 'but', 'an'}

def filt_query(query):
	"""Returns a filtered query with assumptions, i.e. remove CHARS from string, lowercaseify"""
	query = query.lower()

	for char in ERROR_CHARS: 
		query = query.replace(char, '')
	
	# split into list for word analysis
	query = query.split()

	# replace words in query
	for i in range(len(query)):
		word = query[i]
		if word in ABBREVIATIONS:
			query[i] = ABBREVIATIONS[word]
		elif word in COMMON_WORDS:
			query[i] = ''
		elif word in NUM_MAPPING:
			query[i] = NUM_MAPPING[word]

	query = filter(lambda x: x, set(query))

	return ' '.join(query)

def get_rankings(query, index):
	"""Ranks programs given a query and all db entries.
	   Returns dictionary of {guide_key:score}
	"""
	query_words = query.split()
	rankings = dict()

	for key in index:
		tags = index[key]
		rank = 0
		for tag in tags:
			if tag in query:
				# full word match				
				if tag in query_words:	
					rank += 1
				# partial word match	
				elif len(tag) > 3:
					rank += 0.5
		rankings[key] = rank		
	return rankings

app = webapp2.WSGIApplication([('/', MainHandler)],
							  debug=True)
