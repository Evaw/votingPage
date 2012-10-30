#TODO: test worthiness of submission with challenge problem (factoring?)
#TODO: pagination 
#TODO: make a way to activate/deactivate the voting without re-deploying app.
#improve user management, use memcache
# 
#--address="1.1.1.1"

import webapp2
import jinja2
from google.appengine.api import images
from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.api import memcache
from google.appengine.api import users
import logging
import os
import hashlib
import hmac
import random
import re

#by default reset all cookies if the hmac is not consistent, this will allow for easily expiring cookies
#if login is used, its better to have a different secret for non-volatile data like that.
SECRET = "you've been trusted with this secret :)" #+ str(random.randint(0,2000000000000))
MEMCACHE_ART_PREFIX = "Art_"
MEMCACHE_TEAM_PREFIX = "Team"
MEMCACHE_TOP_ART_KEY = "top"
MEMCACHE_USER_PREFIX = "Artist_"
MEMCACHE_USERS_KEY = "Artists"
MEMCACHE_TOP_TEAM_KEY = "Teams"
VOTING_EVENT = "1"
memcache.set('app_voting_started', True) 
VOTES_ACTIVE = memcache.get('app_voting_started') 
MAX_POSTS = 20
PAGE_HEADING = "Voting Page- currently max "+str(MAX_POSTS) + "posts"

simpleStringRegex = (r'[a-zA-Z0-9]+(?:[a-zA-Z0-9 ]+[a-zA-Z0-9])*')

def getMemcacheArtIDfromKey(key):
    return MEMCACHE_ART_PREFIX + str(key)
def getMemcacheTeamIDfromKey(key):
    return MEMCACHE_TEAM_PREFIX + str(key)

def getMemcacheArtID(art):
    return getMemcacheArtIDfromKey(str(art.key()))
def getMemcacheTeamID(team):
    return getMemcacheTeamIDfromKey(str(team.key()))
def getArtByID(art_id):
    keyStr = str(art_id)
    cache_image_key = getMemcacheArtIDfromKey(art_id)#MEMCACHE_ART_PREFIX + keyStr
    art = None
    inMemCache = memcache.get(cache_image_key)
    if inMemCache:
        art = inMemCache
    else:
        logging.info('db get by id art')#is this an expensive query? know gets are much cheaper writes, but is this counted on quota?
        art = db.get(keyStr)
        memcache.set(cache_image_key, art)
    return art
def getTeamByID(teamID):
    keyStr = str(teamID)
    cache_team_key = getMemcacheTeamIDfromKey(teamID)
    team = None
    inMemcache = memcache.get(cache_team_key)
    if inMemcache:
        team = inMemcache
    else: 
        logging.info('db get by id team')#is this an expensive query? know gets are much cheaper writes, but is this counted on quota?
        team = db.get(keyStr)
        memcache.set(cache_team_key, team)
    return team
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
    artist = db.StringProperty()
    teamKey = db.StringProperty(required = True)

class Team(db.Model):
    """team db model"""
    name = db.StringProperty(required = True)
    arts = db.StringListProperty();
    created = db.DateTimeProperty(auto_now_add = True)

class Artist(db.Model):
    """user model """
    nickname = db.StringProperty(required = True)
    artistID = db.StringProperty(required = True)
    federatedProvider = db.StringProperty(required = True)
    arts = db.StringListProperty()
    


def safeMemcacheUpdate(key, val):
    client = memcache.Client()
    i=0;
    tries = 100
    while i<tries:#retry loop
        counter = client.gets(key)
        assert counter is not None, 'Uninitialized key'
        if client.cas(key, val):
            return True
        i+=1
    logging.log('could not do memcache cas')
    return False
        

def getOrCreateArtistKey(nickname, gUserID,federatedID, federatedProvider):
    if not federatedProvider:
        federatedProvider = "none-provided"
    artist = None
    
    artistID = gUserID or federatedID

    query = db.GqlQuery("SELECT __key__ FROM Artist WHERE artistID = '%s' AND federatedProvider = '%s' LIMIT 1"%(artistID, federatedProvider))
    if query:
        queryResult = list(query) #DESC LIMIT 10")
        if len(queryResult) == 1:
            artist = queryResult[0]
    if not artist:
        artistModel = Artist(nickname = nickname, artistID=artistID,  federatedProvider = federatedProvider)
        artistModel.put()
        artist = artistModel.key()
    return artist

def getOrCreateTeamKeyFromName(name):
    regexMatched = re.findall(simpleStringRegex, name)
    if len(regexMatched) <=0:
        return None
    if regexMatched[0] != name:
        return None
    team = None
    query = db.GqlQuery("SELECT __key__ FROM Team Where name = '%s'" % name)
    if query:
        queryResult = list(query)
        if len(queryResult)==1:
            team = queryResult[0]
    if not team:
        teamModel = Team(name = name, arts=[])
        teamModel.put()
        team = teamModel.key()
    return team
def getOrCreateArtistKeyFromUser(user):
    nickname = user.nickname()
    gUserID = user.user_id()
    federatedID = user.federated_identity()
    federatedProvider = user.federated_provider()
    return getOrCreateArtistKey(nickname,gUserID, federatedID, federatedProvider)
def updateTeamMemCache(team):
    memcacheTeamID = getMemcacheTeamID(team)
    safeMemcacheUpdate(memcacheTeamID, team)
    
def updateArtMemcache(art):
    memcacheArtID = getMemcacheArtID(art)
    safeMemcacheUpdate(memcacheArtID, art)
    #updateTopMemcacheKeys(memcacheArtID, art)
    topArts(True)
def removeFromArtMemcache(key):
    memcacheArtID = getMemcacheArtIDfromKey(key)
    memcache.delete(memcacheArtID)
    tops = memcache.get(MEMCACHE_TOP_ART_KEY)
    topsStr = [str(a) for a in tops]
    try:
        idx = topsStr.index(key) 
        tops.remove(tops[idx])
    except ValueError:
        pass
    else:
        memcache.set(MEMCACHE_TOP_ART_KEY, tops)


def transactionRemoveArtKeyFromTeam(teamKey, artKey):
    team = db.get(teamKey)
    artList = team.arts
    if artKey in  artList:
        artList.remove(artKey)
    team.put()
def removeArtFromTeamMemcache(teamKey, artKey):
    memcacheTeamID = getMemcacheTeamIDfromKey(teamKey)
    modifiedTeam = db.get(teamKey)
    safeMemcacheUpdate(memcacheTeamID, modifiedTeam)
def removeArtFromTeam(key, teamKey):
    
    
    #remove model itself
    
    db.run_in_transaction(transactionRemoveArtKeyFromTeam,teamKey,key)
    removeArtFromTeamMemcache(teamKey,key)
    
def deleteDBArtEntry(key):
    logging.info('DB transaction delete')
    db.delete(key)
    #art.delete()
    
def deleteArt(key):
    art = db.get(key)
    teamKey = art.teamKey
    #remove from other models
    removeArtFromTeam(key, teamKey)
    
    #remove model itself
    
    db.run_in_transaction(deleteDBArtEntry,key)
    removeFromArtMemcache(key)
    
def incrementDBvote(key, amount):
    art = db.get(key)
    art.votes += amount
    art.put()

def addArtToTeamInTransactionHelper(teamKey, artKey):
    team = db.get(teamKey)
    #arts = list(team.arts)
    
    team.arts.append(artKey)
    #team.arts = arts#check if we dont have to copy arts to a new list
    team.put()
    
def addArtToTeam(teamKey, artKey):
    db.run_in_transaction(addArtToTeamInTransactionHelper, teamKey, artKey)
    team = db.get(teamKey)
    updateTeamMemCache(team)
def incrementVote(key, amount):
    db.run_in_transaction(incrementDBvote, key, amount)
    art = db.get(key)
    updateArtMemcache(art)
    #topArts(True)

def topTeams(update=False):
    keys = memcache.get(MEMCACHE_TOP_TEAM_KEY)
    if keys is None or update:
        logging.info('DB query to team')
        teams = db.GqlQuery("select * from Team ORDER BY created")
        teams = list(teams)
        keys = [t.key() for t in teams]
        for t in teams:
            if t.arts:
                memcache.set(getMemcacheTeamID(t), t)
        memcache.set(MEMCACHE_TOP_TEAM_KEY, keys)
    return keys
        
def topArts(update=False):
    keys = memcache.get(MEMCACHE_TOP_ART_KEY)
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
    def render_front(self,title="", pageHeading = PAGE_HEADING, error="", canVote = False,
                     userManagement = {
                        'user': None,
                        'loginURL':users.create_login_url("/"),
                        'logoutURL':users.create_logout_url("/")
                        
                        }):
        keys = topArts()#db.GqlQuery("SELECT * FROM Art ORDER BY created DESC LIMIT 10")
        #arts = list(arts)
        logging.info('see value in main ' + str(len(keys)))
        arts = {}
        for k in keys:
            #self.write(repr(a.pic))
            a = getArtByID(k)
            arts[str(k)]=a
        teamKeys = topTeams()
        teams = []
        for k in teamKeys :
            t = getTeamByID(k)
            teams.append(t)
        canVote = canVote and memcache.get('app_voting_started')
        """
        for t in teams:
            logging.info(t)
            for aKey in t.arts:
                logging.info(aKey)
                logging.info(arts[aKey].pic)
                """
        self.render("front.html", teams=teams, title=title,pageHeading = pageHeading,error = error, arts = arts, canVote = canVote,userManagement=userManagement)
    
    def get(self):
        visits = 1;
        visit_cookie_str = self.request.cookies.get('visits')
        user = users.get_current_user()
        userKey = ""
        userManagement = {
            'user': user,
            'loginURL':users.create_login_url("/"),
            'logoutURL':users.create_logout_url("/"),
            } 
        if user:
            userManagement['nickname'] = user.nickname() 
            userManagement['isAdmin'] = users.is_current_user_admin();
            userKey =  getOrCreateArtistKeyFromUser(user)
            userManagement['userKey'] = str(userKey);
       
        """
        if user:
            greeting = ("Welcome, %s! (<a href=\"%s\">sign out</a>)" %
                        (user.nickname(), users.create_logout_url("/")))
        else:
            greeting = ("<a href=\"%s\">Sign in or register</a>." %
                        users.create_login_url("/"))

        self.response.out.write("<html><body>%s</body></html>" % greeting)
        return
        """    
        if visit_cookie_str:
            cookie_val = check_secure_val(str(visit_cookie_str))
            logging.info('cookie_val: %s' % cookie_val)
            if cookie_val:
                visits = int(cookie_val)+1
        new_cookie_val = make_secure_val(str(visits))
        canVote = not check_secure_val(self.request.cookies.get('voted%s' % VOTING_EVENT))
        titleAlreadyThere = self.request.get('get_title')
        errorFromPrevRequest = self.request.get('get_error')
        
        self.response.headers.add_header("Set-Cookie", "visits=%s" % new_cookie_val)
              
        self.render_front(canVote = canVote,userManagement=userManagement, title=titleAlreadyThere, error=errorFromPrevRequest)
    def post(self):
        title = self.request.get("title")
        pic = self.request.get("pic")
        team = self.request.get('team')
        user = users.get_current_user()
        error =""
        teamKey = None
        if not team:
            error = "please provide a team"
        else:
            teamKey = getOrCreateTeamKeyFromName(team)
            if teamKey == None:
                #malicious key
                error += "bad team name"
            else:
                teamKey = str(teamKey)
        #if not user:
        #    self.redirect('/')
        #    return
        artistKey = None
        if user:
            artistKey = getOrCreateArtistKeyFromUser(user)
            artistKey = str(artistKey)
        #if not artist: letting anyone submit
        #   logging.log('had some problem, could not ger artist')
        #  self.redirect('/')
        
        keys = memcache.get(MEMCACHE_TOP_ART_KEY)
        if keys and len(keys) >= MAX_POSTS:
            self.redirect('/')#only allow MAX_POSTS posts, this is going on appengine
            return
        

        #canVote = not check_secure_val(self.request.cookies.get('voted%s' % VOTING_EVENT))
        
        
        if len(title) > 500:
            error += "title should be less than 500 characters"
        if len(title) == 0:
            error += "Your artwork needs a title"
        canProceed = (not not title) and (not not pic) and (not error)
        if canProceed:
            try:
                resizedPic = images.resize(pic, 500, 300)
                picBlob = db.Blob(resizedPic)
                if artistKey:
                    a = Art(title = title, pic=picBlob, artist=artistKey, teamKey = teamKey)
                else: 
                    a= Art(title = title, pic=picBlob,teamKey = teamKey) 
                a.put()
                team = db.get(teamKey)
                
                teamMemcacheID = getMemcacheTeamIDfromKey(teamKey)
                memcache.set(teamMemcacheID, team)
                addArtToTeam(teamKey, str(a.key()))
                
                topArts(True)
                topTeams(True)
                title= "";#clear title for redirect
            except images.BadImageError:
                error += "Bad Image file"
                """
            except images.NOT_IMAGE:
                error += "no image file"
            except images.IMAGE_TOO_LARGE:
                error += "image too large, please keep it under 4MB"
                
            """
            except images.Error:
            
                error += "Sorry, the image you tried to upload could not be processed"
            #finally:
                #self.render_front(title=title,error = error, canVote=canVote)
        else:
            error+='Sorry, you need a title and a picture to submit'
        
        if title or error:
            self.redirect('/?get_title=%s&get_error=%s'%(title,error))
        else:
            self.redirect('/')
        
            
        

class Remove(Handler):
    def post(self):
        artID=self.request.get('remove')
        deleteArt(artID)
        self.redirect('/')
        
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
        if not memcache.get('app_voting_started'):
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
                               ('/vote', Vote),
                               ('/remove', Remove),
                               ], debug=True)
logging.info('app started')