import psycopg2
import configparser
import os
import chardet

from .SentinelLogger import getSentinelLogger

Config = configparser.ConfigParser()
Config.read(os.path.join(os.path.dirname(__file__), "Config.ini"))


defaultun = Config.get('Database', 'Username')
defaultpass = Config.get('Database', 'Password')
defaultdbnam = 'TheTraveler'


class Database():
    def __init__(self, dbname=defaultdbnam, username=defaultun, password=defaultpass):
        # Initialize the logger
        self.logger = getSentinelLogger()

        self.conn = psycopg2.connect("dbname='{}' user='{}' password='{}'".format(dbname, username, password))
        self.conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        self.c = self.conn.cursor()
        self.c.execute("SET CLIENT_ENCODING TO 'UTF8';")
        self.logger.debug('Initialized Database connection')

class Blacklist(Database):

    def isBlacklisted(self, subreddit, media_author=None, media_channel_id=None, media_platform=None, **kwargs):
        if (not media_author) and (not media_channel_id):
            self.logger.warning('No Video Provided')
            raise RuntimeError("No video provided")

        if subreddit.lower() == 'videos':
            self.logger.info(u'READ ONLY sub: {} | ChanID: {} | MediaPlatform: {}'.format(subreddit, media_channel_id, media_platform))
            return False
        """
        if media_author:
            self.c.execute("SELECT * FROM thesentinel_view WHERE (lower(subreddit)=lower(%s) OR subreddit='YT_Killer' OR subreddit='TheSentinelBot') AND media_author=%s AND removed!=true and blacklisted=true", (subreddit, media_author))
            try:
                fetched = self.c.fetchone()
            except psycopg2.ProgrammingError:
                return False
            if fetched:
                self.logger.info(u'Media Author Blacklisted. Sub: {} | MediaAuth: {}'.format(subreddit, media_author))
                return True
        """
        if media_channel_id:
            self.c.execute("SELECT * FROM thesentinel_view WHERE (lower(subreddit)=lower(%s) OR subreddit='YT_Killer' OR subreddit='TheSentinelBot') AND media_channel_id=%s AND removed!=true and blacklisted=true", (subreddit, media_channel_id))
            try:
                fetched = self.c.fetchone()
            except psycopg2.ProgrammingError:
                return False            
            if fetched:
                self.logger.info(u'Media Channel Blacklisted. Sub: {} | ChanID: {} | MediaPlatform: {}'.format(subreddit, media_channel_id, media_platform))
                return True
        self.logger.debug(u'Channel not blacklisted. Sub: {} | ChanID: {} | MediaAuth: {}'.format(subreddit, media_channel_id, media_author))
        return False
        

    def addBlacklist(self, kwargs):
        if "media_channel_id" not in kwargs:
            self.logger.warning('No channel_id provided')
            raise RuntimeError("No channel_id provided")
        subreddit = kwargs['subreddit']
        if self.isBlacklisted(subreddit, media_channel_id=kwargs['media_channel_id']):
            self.logger.debug(u'Channel already blacklisted: ChanID: {}'.format(kwargs['media_channel_id']))
            return True
        try:
            self.c.execute("INSERT INTO thesentinel_view (thingid, author, subreddit, thingcreated_utc, permalink, body, removed, media_author, media_channel_id, media_link, media_platform, processed, blacklisted) VALUES (%(thingid)s, %(author)s, lower(%(subreddit)s), %(thingcreated_utc)s, %(permalink)s, %(body)s, false, %(media_author)s, %(media_channel_id)s, %(media_link)s, %(media_platform)s, true, true )", kwargs)            
            self.logger.info(u'Added to database. ThingID: {thingid} | MediaChanID: {media_channel_id} | MediaAuth: {media_author}'.format(**kwargs))
            return True
        except KeyError as e:
            self.logger.error(u'Missing required parameter - {}'.format(e))
            raise KeyError(u"Missing required parameter - {}".format(e))

    def removeBlacklist(self, subreddit, media_author=None, media_channel_id=None, media_platform=None, **kwargs):
        if (not media_author) and (not media_channel_id):
            self.logger.warning(u'No video provided')
            raise RuntimeError("No video provided")
        if not self.isBlacklisted(subreddit, media_author, media_channel_id):
            return True
        self.c.execute("UPDATE thesentinel_view SET blacklisted=false WHERE lower(subreddit)=lower(%s) AND (media_author=%s AND media_channel_id=%s)", (subreddit, media_author, media_channel_id))

        self.logger.info(u'Removed from Blacklist. MediaAuth: {} | ChanAuth: {}'.format(media_author, media_channel_id))
        return True

    def isProcessed(self, subreddits):
        if not subreddits:
            return []
        newcur = self.conn.cursor()
        args = b",".join([self.c.mogrify("%s", (x,)) for x in subreddits])
        execString = "SELECT thingid FROM thesentinel_view WHERE processed=true AND subreddit IN (" + args.decode("ascii", errors="ignore") + ")"#" ORDER BY thingcreated_utc DESC LIMIT 2000"        
        
        newcur.execute(execString)
        fetched = newcur.fetchall()
        newcur.execute("SELECT thingid FROM thesentinel_view WHERE subreddit='YT_Killer'")
        fetched += newcur.fetchall()
        newcur.close()
        self.logger.debug("Fetched {} items for subreddits {}".format(len(fetched), subreddits))
        return [i[0] for i in fetched] # list of tuples -> list of thingids

    def markProcessed(self, kwargs_list):
        if kwargs_list:
            self.logger.debug("Adding {} things".format(len(kwargs_list)))
            args = b",".join([self.c.mogrify("(%(thing_id)s, %(author)s, %(subreddit)s, %(thingcreated_utc)s, %(permalink)s, %(body)s, %(media_author)s, %(media_channel_id)s, %(media_link)s, %(media_platform)s, false, true)", x) for x in kwargs_list])

            execString = b"INSERT INTO thesentinel_view (thingid, author, subreddit, thingcreated_utc, permalink, body, media_author, media_channel_id, media_link, media_platform, removed, processed) VALUES " + args
            #self.logger.warning("execString: {}".format(execString))
            self.c.execute(execString)
            self.logger.debug("Added {} items to the database.".format(len(kwargs_list)))
            

    def next_value(self):
        self.c.execute("SELECT id FROM thing ORDER BY id DESC LIMIT 1")
        result = self.c.fetchone()
        return result[0]+1



class SlackHooks(Database):

    def getHooks(self, slackTeam=None, subreddit=None):
        if (not slackTeam) and (not subreddit):
            self.c.execute("SELECT srname, webhook_url, slack_channel FROM tsb_slackhooks")
            self.logger.debug(u'Fetched all slackHooks')
        else:
            self.c.execute("SELECT srname, webhook_url, slack_channel FROM tsb_slackhooks WHERE slack_team=%s OR srname=%s", (slackTeam, subreddit))
            self.logger.debug(u'Fetched slackHook for /r/{} | SlackTeam: {}'.format(subreddit, slackTeam))
        hooks = self.c.fetchall()
        return hooks

    def addHook(self, subreddit, channel, hookURL, slackTeam):
        self.c.execute("INSERT INTO tsb_slackhooks (srname, webhook_url, slack_channel, slack_team) VALUES (%s, %s, %s, %s)", (subreddit, hookURL, channel, slackTeam))
        self.logger.debug(u'Hook added for /r/{} | SlackTeam: {}'.format(subreddit, slackTeam))

    def removeHook(self, slackTeam=None, subreddit=None):
        if subreddit and slackTeam is None:
            self.c.execute("DELETE FROM tsb_slackhooks WHERE srname=%s", (subreddit,))
            self.logger.debug(u'Removed hook for /r/{}'.format(subreddit))
        elif slackTeam and subreddit is None:
            self.c.execute("DELETE FROM tsb_slackhooks WHERE slack_team=%s", (slackTeam,))
            self.logger.debug(u'Removed hook for SlackTeam: {}'.format(slackTeam))
        else:
            self.logger.warning(u'Please provide either a Subreddit or a Slack Team, not both')
            raise RuntimeError("Please provide either a Subreddit or a Slack Team, not both")

class NSA(Database):

    def addUsers(self, kwargs_list):
        if kwargs_list:
            self.logger.debug("Adding {} users".format(len(kwargs_list)))
            args = ",".join([self.c.mogrify("(%(author_id)s, %(author)s, %(permalink)s, EXTRACT(EPOCH from now()), %(thingcreated_utc)s, %(content_creator)s)", x) for x in kwargs_list])
            execString = "INSERT INTO users (authorid, author, permalink, current_utc, authorcreated_utc, iscontentcreator) VALUES " +  args + " ON CONFLICT DO NOTHING"
            self.c.execute(execString)
            self.logger.debug("Added {} users to the database.".format(len(kwargs_list)))

    def knownUsers(self):
        newcur = self.conn.cursor()
        execString = "SELECT authorid FROM users"
        newcur.execute(execString)
        fetched = newcur.fetchall()
        newcur.close()
        self.logger.debug("Fetched {} users".format(len(fetched)))
        return [i[0] for i in fetched] # list of tuples -> list of thingids

class oAuthDatabase(Database):

    def get_accounts(self, id):
        self.c.execute("SELECT app_id, app_secret, username, password FROM oauth_data WHERE agent_of=%s", (id,))
        self.logger.debug(u'Retreived oAuth Credentials for Username: {}'.format(id))
        return self.c.fetchall()
