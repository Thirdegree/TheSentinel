import psycopg2
import configparser
import os

from .SentinelLogger import getSentinelLogger

Config = configparser.ConfigParser()
Config.read(os.path.join(os.path.dirname(__file__), "Config.ini"))


defaultun = Config.get('Database', 'Username')
defaultpass = Config.get('Database', 'Password')
defaultdbnam = 'TheTraveler'


class Database(object):
    def __init__(self, dbname=defaultdbnam, username=defaultun, password=defaultpass):
        # Initialize the logger
        self.logger = getSentinelLogger()

        self.conn = psycopg2.connect("host='localhost' dbname='{}' user='{}' password='{}'".format(dbname, username, password))
        #self.conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)

class Blacklist(Database):
    def __init__(self):
        super(Blacklist, self).__init__()
        c = self.conn.cursor()
        c.execute("SET CLIENT_ENCODING TO 'UTF8';")
        self.logger.debug('Initialized Blacklist Database connection')




    def isBlacklisted(self, subreddit, media_author=None, media_channel_id=None, media_platform=None, **kwargs):
        if (not media_author) and (not media_channel_id):
            self.logger.warning('No Video Provided')
            raise RuntimeError("No video provided")

        if subreddit.lower() == 'videos':
            self.logger.debug(u'READ ONLY sub: {} | ChanID: {} | MediaPlatform: {}'.format(subreddit, media_channel_id, media_platform))
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
            with self.conn.cursor('isBlacklisted') as c:
                c.execute("SELECT * FROM thesentinel_view WHERE (lower(subreddit)=lower(%s) OR lower(subreddit)='yt_killer' OR lower(subreddit)='thesentinelbot') AND media_channel_id=%s AND removed!=true and blacklisted=true", (subreddit, media_channel_id))
                try:
                    fetched = c.fetchone()
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
            with self.conn.cursor('addBlacklist') as c:
                c.execute("INSERT INTO thesentinel_view (thingid, author, subreddit, thingcreated_utc, permalink, body, removed, media_author, media_channel_id, media_link, media_platform, processed, blacklisted) VALUES (%(thingid)s, %(author)s, lower(%(subreddit)s), %(thingcreated_utc)s, %(permalink)s, %(body)s, false, %(media_author)s, %(media_channel_id)s, %(media_link)s, %(media_platform)s, true, true )", kwargs)            
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
        with self.conn.cursor("removeBlacklist") as c:
            c.execute("UPDATE thesentinel_view SET blacklisted=false WHERE lower(subreddit)=lower(%s) AND (media_author=%s AND media_channel_id=%s)", (subreddit, media_author, media_channel_id))

        self.logger.info(u'Removed from Blacklist. MediaAuth: {} | ChanAuth: {}'.format(media_author, media_channel_id))
        return True

    def isProcessed(self, subreddits):
        if not subreddits:
            return []
        newcur = self.conn.cursor('isProcessed')
        args = b",".join([newcur.mogrify("%s", (x,)) for x in subreddits])
        execString = "SELECT thingid FROM thesentinel_view WHERE processed=true AND subreddit IN (" + args.decode("ascii", errors="ignore") + ")"#" ORDER BY thingcreated_utc DESC LIMIT 2000"        
        
        newcur.execute(execString)
        fetched = newcur.fetchall()
        newcur.execute("SELECT thingid FROM thesentinel_view WHERE subreddit='YT_Killer'")
        fetched += newcur.fetchall()
        newcur.commit()
        newcur.close()
        self.logger.debug("Fetched {} items for subreddits {}".format(len(fetched), subreddits))
        return [i[0] for i in fetched] # list of tuples -> list of thingids

    def markProcessed(self, kwargs_list):
        if kwargs_list:
            self.logger.debug("Adding {} things".format(len(kwargs_list)))
            with self.conn.cursor('markProcessed') as c:
                args = b",".join([c.mogrify("(%(thing_id)s, %(author)s, %(subreddit)s, %(thingcreated_utc)s, %(permalink)s, %(body)s, %(media_author)s, %(media_channel_id)s, %(media_link)s, %(media_platform)s, false, true)", x) for x in kwargs_list])

                execString = b"INSERT INTO thesentinel_view (thingid, author, subreddit, thingcreated_utc, permalink, body, media_author, media_channel_id, media_link, media_platform, removed, processed) VALUES " + args 
            #self.logger.warning("execString: {}".format(execString))
            
                c.execute(execString)
            self.logger.debug("Added {} items to the database.".format(len(kwargs_list)))
            

    def next_value(self):
        with self.conn.cursor("next_value") as c:
            c.execute("SELECT id FROM thing ORDER BY id DESC LIMIT 1")
            result = c.fetchone()
        return result[0]+1



class SlackHooks(Database):

    def __init__(self):
        super(SlackHooks, self).__init__()
        with self.conn.cursor() as c:
            c.execute("SET CLIENT_ENCODING TO 'UTF8';")
        self.logger.debug('Initialized SlackHooks Database connection')

    def getHooks(self, slackTeam=None, subreddit=None):
        with self.conn.cursor('getHooks') as c:
            if (not slackTeam) and (not subreddit):
                c.execute("SELECT srname, webhook_url, slack_channel FROM tsb_slackhooks")
                self.logger.debug(u'Fetched all slackHooks')
            else:
                c.execute("SELECT srname, webhook_url, slack_channel FROM tsb_slackhooks WHERE slack_team=%s OR srname=%s", (slackTeam, subreddit))
                self.logger.debug(u'Fetched slackHook for /r/{} | SlackTeam: {}'.format(subreddit, slackTeam))
            hooks = c.fetchall()
        return hooks

    def addHook(self, subreddit, channel, hookURL, slackTeam):
        with self.conn.cursor("addHook") as c:
            c.execute("INSERT INTO tsb_slackhooks (srname, webhook_url, slack_channel, slack_team) VALUES (%s, %s, %s, %s)", (subreddit, hookURL, channel, slackTeam))
        self.logger.debug(u'Hook added for /r/{} | SlackTeam: {}'.format(subreddit, slackTeam))

    def removeHook(self, slackTeam=None, subreddit=None):
        with self.conn.cursor("removeHook") as c:
            if subreddit and slackTeam is None:
                c.execute("DELETE FROM tsb_slackhooks WHERE srname=%s", (subreddit,))
                self.logger.debug(u'Removed hook for /r/{}'.format(subreddit))
            elif slackTeam and subreddit is None:
                c.execute("DELETE FROM tsb_slackhooks WHERE slack_team=%s", (slackTeam,))
                self.logger.debug(u'Removed hook for SlackTeam: {}'.format(slackTeam))
            else:
                self.logger.warning(u'Please provide either a Subreddit or a Slack Team, not both')
                raise RuntimeError("Please provide either a Subreddit or a Slack Team, not both")

class NSA(Database):
    def __init__(self):
        super(NSA, self).__init__()
        with self.conn.cursor() as c:
            c.execute("SET CLIENT_ENCODING TO 'UTF8';")
        self.logger.debug('Initialized NSA Database connection')

    def addUsers(self, kwargs_list):
        if kwargs_list:
            self.logger.debug("Adding {} users".format(len(kwargs_list)))
            with self.conn.cursor() as c:
                args = ",".join([c.mogrify("(%(author_id)s, %(author)s, %(permalink)s, EXTRACT(EPOCH from now()), %(thingcreated_utc)s, %(content_creator)s)", x) for x in kwargs_list])
                execString = "INSERT INTO users (authorid, author, permalink, current_utc, authorcreated_utc, iscontentcreator) VALUES " +  args + " ON CONFLICT DO NOTHING"
                c.execute(execString)
                self.logger.debug("Added {} users to the database.".format(len(kwargs_list)))

    def knownUsers(self):
        newcur = self.conn.cursor()
        execString = "SELECT authorid FROM users"
        newcur.execute(execString)
        fetched = newcur.fetchall()
        newcur.commit()
        newcur.close()
        self.logger.debug("Fetched {} users".format(len(fetched)))
        return [i[0] for i in fetched] # list of tuples -> list of thingids

class Utility(Database):
    def __init__(self, dbname='application'):
        super(Utility, self).__init__(dbname=dbname)
        with self.conn.cursor() as c:
            c.execute("SET CLIENT_ENCODING TO 'UTF8';")
        self.logger.debug('Initialized Utility Database connection')

    def add_subreddit(self, subreddit, botname, subscribers, category='tsb'):
        execString1 = "INSERT INTO sr_clients (subreddit, redditbot, category, sr_name, subscribers) VALUES (LOWER(%s), %s, %s, %s, %s)"
        updateString = "UPDATE sr_clients SET subscribers=%s where subreddit=LOWER(%s)"
        with self.conn.cursor('add_subreddit') as c:
            c.execute("SELECT * FROM sr_clients WHERE subreddit=LOWER(%s)", (subreddit,))
            fetched = c.fetchone()
            if fetched:
                c.execute(updateString, (subscribers, subreddit))
            else:
                c.execute(execString1, (subreddit, botname, category, subreddit, subscribers))

    def remove_subreddit(self, subreddit):
        execString1 = "DELETE FROM sr_client WHERE subreddit=LOWER(%s)"
        with self.conn.cursor('remove_subreddit') as c:
            c.execute(execString1, (subreddit,))

class ModloggerDB(Database):
    def __init__(self):
        super(ModloggerDB, self).__init__()
        with self.conn.cursor() as c:
            c.execute("SET CLIENT_ENCODING TO 'UTF8';")
        self.logger.debug('Initialized ModloggerDB Database connection')

    def get_subs_enabled(self):
        execString1 = "SELECT subreddit FROM sub_settings WHERE modlog_enabled=true"
        with self.conn.cursor('get_subs_enabled') as c:
            c.execute(execString1)
            fetched = c.fetchall()
        if fetched:
            return [i[0] for i in fetched]
        return []

    def get_last_seen(self, limit=1000):
        execString1 = "SELECT ModActionID from modlog limit " + str(limit)
        with self.conn.cursor('get_last_seen') as c:
            c.execute(execString1)
            fetched = c.fetchall()
        if fetched:
            self.logger.debug("Found %s items"%len(fetched))
            return [i[0] for i in fetched]
        self.logger.debug("Found 0 items")
        return []

    def log_items(self, kwargs_list):
        
        if kwargs_list:
            with self.conn.cursor('log_items') as c:
                args = b",".join([c.mogrify("(%(thing_id)s, %(mod_name)s, %(author_name)s, %(action)s, %(action_reason)s, %(permalink)s, %(thingcreated_utc)s, %(subreddit)s, %(modaction_id)s, %(title)s)", x) for x in kwargs_list])
                execString1 = b'INSERT INTO modlog (ThingID, Mod, Author, Action, ActionReason, PermaLink, ThingCreated_UTC, Subreddit, ModActionID, Title) VALUES ' + args

                c.execute(execString1)

            self.logger.info("Added {} items to modLogger database.".format(len(kwargs_list)))


    def is_logged(self, modActionID):
        with self.conn.cursor('is_logged') as c:
            c.execute('SELECT * FROM modlog WHERE ModActionID=(%s)', (modActionID,))
            return bool(c.fetchone())

class oAuthDatabase(Database):
    def __init__(self):
        super(oAuthDatabase, self).__init__()
        with self.conn.cursor() as c:
            c.execute("SET CLIENT_ENCODING TO 'UTF8';")
        self.logger.debug('Initialized oAuthDatabase Database connection')

    def get_accounts(self, id):
        with self.conn.cursor('get_accounts') as c:
            c.execute("SELECT app_id, app_secret, username, password FROM oauth_data WHERE agent_of=%s", (id,))
            self.logger.debug(u'Retreived oAuth Credentials for Username: {}'.format(id))
            return c.fetchall()
