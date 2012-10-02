#TODO: resize images
#TODO: test worthiness of submission with challenge problem (factoring?)
#TODO: pagination 
#TODO: make a way to activate/deactivate the voting without re-deploying app.
#add user management, at least at the cookie level to allow them to take their stuff down if they want 
import webapp2
import jinja2
from google.appengine.api import images
from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.api import memcache
import logging
import os
import hashlib
import hmac
import random

#by default reset all cookies if the hmac is not consistent, this will allow for easily expiring cookies
#if login is used, its better to have a different secret for non-volatile data like that.
SECRET = "you've been trusted with this secret :)"
MEMCACHE_ART_PREFIX = "Art_"
MEMCACHE_TOP_ART_KEY = "top"
VOTING_EVENT = "1"
VOTES_ACTIVE = True
def getMemcacheArtID(art):
    return MEMCACHE_ART_PREFIX + str(art.key())

def getArtByID(art_id):
    keyStr = str(art_id)
    cache_image_key = MEMCACHE_ART_PREFIX + keyStr
    art = None
    inMemCache = memcache.get(cache_image_key)
    if inMemCache:
        art = inMemCache
    else:
        logging.info('db get by id')#is this an expensive query? know gets are much cheaper writes, but is this counted on quota?
        art = db.get(keyStr)
        memcache.set(cache_image_key, art)
    return art

def hash_str(s):
    #return hashlib.sha256(s).hexdigest();
    return hmac.new(SECRET,s, hashlib.sha256).hexdigest()

def make_secure_val(s):
    return "%s|%s" % (s, hash_str(s))
def check_secure_val(h):
    if h:
        val = h.split("|")[0]
        if h == make_secure_val(val):
            return val


template_dir = os.path.join(os.path.dirname(__file__), 'templates')
jinja_env = jinja2.Environment(loader = jinja2.FileSystemLoader(template_dir), autoescape=True)


class Handler(webapp2.RequestHandler):
    def write(self, *a, **kw):
        self.response.out.write(*a, **kw)
    def render_str(self, template, **params):
        t = jinja_env.get_template(template)
        return t.render(params)
    def render(self, template, **kw):
        self.write(self.render_str(template, **kw))
    def resetVotedCookies(self):
        new_cookie_val = ""
        self.response.headers.add_header("Set-Cookie", "voted%s=%s;Path=/vote;" % (VOTING_EVENT,new_cookie_val))
        self.response.headers.add_header("Set-Cookie", "voted%s=%s;Path=/;"%  (VOTING_EVENT,new_cookie_val))
       
class Art(db.Model):
    """Art db model"""
    title = db.StringProperty(required = True)
    created = db.DateTimeProperty(auto_now_add = True)
    pic = db.BlobProperty()
    votes = db.IntegerProperty(default = 0)

def safeMemcacheUpdate(key, val):
    client = memcache.Client()
    i=0;
    tries = 100
    while i<tries:#retry loop
        counter = client.gets(key)
        assert counter is not None, 'Uninitialized counter'
        if client.cas(key, val):
            return True
        i+=1
    return False
        
def updateTopMemcacheKeys(keys):
    return safeMemcacheUpdate(MEMCACHE_TOP_ART_KEY, keys)
    
        
def updateArtMemcache(art):
    artID = getMemcacheArtID(art)
    return safeMemcacheUpdate(artID, art)
    
def incrementDBvote(key, amount):
    art = db.get(key)
    art.votes += amount
    art.put()

def incrementVote(key, amount):
    db.run_in_transaction(incrementDBvote, key, amount)
    art = db.get(key)
    updateArtMemcache(art)
    topArts(True)
    
def topArts(update=False):
    key = "top"
    keys = memcache.get(key)
    if keys is None or update:
        logging.info('DB Query')
        arts = db.GqlQuery("select * FROM Art ORDER BY created") #DESC LIMIT 10")
        arts = list(arts)
        keys = [a.key() for a in arts]
        for a in arts:
            if a.pic:
                memcache.set(getMemcacheArtID(a), a)
        memcache.set(MEMCACHE_TOP_ART_KEY, keys)
    return keys

class GetImage(Handler):
    def get(self):
        artID = self.request.get('img_id')
        art = getArtByID(artID)
            
        if art and art.pic:
            self.response.headers['Content-Type'] = 'image/png'
            self.response.out.write(art.pic)
        else:
            self.response.out.write('No image')
            
class MainPage(Handler):
    def render_front(self, error="", canVote = False):
        keys = topArts()#db.GqlQuery("SELECT * FROM Art ORDER BY created DESC LIMIT 10")
        #arts = list(arts)
        logging.info('see value in main ' + str(len(keys)))
        arts = []
        for k in keys:
            #self.write(repr(a.pic))
            a = getArtByID(k)
            arts.append(a)
        canVote = canVote and VOTES_ACTIVE
        self.render("front.html", error = error, arts = arts, canVote = canVote)
    
    def get(self):
        visits = 1;
        visit_cookie_str = self.request.cookies.get('visits')
        
        if visit_cookie_str:
            cookie_val = check_secure_val(str(visit_cookie_str))
            logging.info('cookie_val: %s' % cookie_val)
            if cookie_val:
                visits = int(cookie_val)+1
        new_cookie_val = make_secure_val(str(visits))
        canVote = not check_secure_val(self.request.cookies.get('voted%s' % VOTING_EVENT))
        self.response.headers.add_header("Set-Cookie", "visits=%s" % new_cookie_val)
        self.render_front(canVote = canVote)
    def post(self):
        title = self.request.get("title")
        art = self.request.get("art")
        pic = self.request.get("pic")
        
        if len(title) > 500:
            error = "title should be less than 500 characters"
            self.render(title,error)
        elif title and pic:
            resizedPic = images.resize(pic, 500, 300)
            picBlob = db.Blob(resizedPic)
            a = Art(title = title, pic=picBlob)
            a.put()
            topArts(True)
            self.redirect("/")
        else:
            error = "we need both a title and some artwork!"
            self.render_front(title,error)


class Vote(Handler):
    def setVotedCookies(self):
        new_cookie_val = make_secure_val(str(random.randint(0,2000000000000)))
        self.response.headers.add_header("Set-Cookie", "voted%s=%s;Path=/vote;" % (VOTING_EVENT,new_cookie_val))
        self.response.headers.add_header("Set-Cookie", "voted%s=%s;Path=/;"%  (VOTING_EVENT,new_cookie_val))
        
    def doVote(self):
        #if()
        artID = self.request.get('vote')
        #art = getArtByID(artID)
        incrementVote(artID, 1)
        
    def post(self):
        if not VOTES_ACTIVE:
            logging.info('voting is not active, but got a request to vote, vote not counted')
            self.redirect('/')
            return
        voted_cookie_str = self.request.cookies.get('voted%s'%(VOTING_EVENT))
        
        if not voted_cookie_str:
            self.doVote()
        else:
            cookie_val = check_secure_val(str(voted_cookie_str))
            if not cookie_val:
                logging.info('Corrupt voting cookie')
                self.doVote()
            else:
                logging.info('posted vote with cookie already voted, not counted')
        self.setVotedCookies();
        self.redirect('/')
                


logging.info('before starting app')
app = webapp2.WSGIApplication([('/', MainPage),
                               ('/getImg',GetImage),
                               ('/vote', Vote)
                               ], debug=True)
logging.info('app started')