#!/usr/bin/env python
"""
    This file is part of ALTcointip.

    ALTcointip is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    ALTcointip is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with ALTcointip.  If not, see <http://www.gnu.org/licenses/>.
"""

import logging
import os
import smtplib
import sys
import time
import traceback
from email.mime.text import MIMEText
from socket import timeout

import praw
import yaml
from jinja2 import Environment, PackageLoader
from praw.errors import RateLimitExceeded
from requests.exceptions import ConnectionError, HTTPError, Timeout

from ctb import ctb_action, ctb_coin, ctb_db, ctb_misc, ctb_user

# Configure CointipBot logger
logging.basicConfig(
    datefmt="%H:%M:%S",
    format="%(asctime)s %(levelname)-8s %(name)-12s %(message)s",
)
logging.getLogger("bitcoin").setLevel(logging.DEBUG)
logger = logging.getLogger("ctb")
logger.setLevel(logging.DEBUG)


class CointipBot(object):
    """
    Main class for cointip bot
    """

    def parse_config(self):
        """
        Returns a Python object with CointipBot configuration
        """
        logger.debug("parse_config(): parsing config files...")

        conf = {}
        try:
            for name in [
                "coin",
                "db",
                "keywords",
                "misc",
                "reddit",
                "regex",
            ]:
                path = os.path.join("conf", f"{name}.yml")
                logger.debug("parse_config(): reading %s", path)
                with open(path) as fp:
                    conf[name] = yaml.safe_load(fp)
        except yaml.YAMLError as e:
            logger.error("parse_config(): error reading config file: %s", e)
            if hasattr(e, "problem_mark"):
                logger.error(
                    "parse_config(): error position: (line %s, column %s)",
                    e.problem_mark.line + 1,
                    e.problem_mark.column + 1,
                )
            sys.exit(1)

        logger.info("parse_config(): config files has been parsed")
        return conf

    def connect_db(self):
        """
        Returns a database connection object
        """
        logger.debug("connect_db(): connecting to database...")

        if self.conf["db"]["auth"]["user"]:
            dsn = "mysql+mysqldb://%s:%s@%s:%s/%s?charset=utf8" % (
                self.conf["db"]["auth"]["user"],
                self.conf["db"]["auth"]["password"],
                self.conf["db"]["auth"]["host"],
                self.conf["db"]["auth"]["port"],
                self.conf["db"]["auth"]["dbname"],
            )
        else:
            dsn = f"mysql+mysqldb://{self.conf['db']['auth']['host']}:{self.conf['db']['auth']['port']}/{self.conf['db']['auth']['dbname']}?charset=utf8"

        dbobj = ctb_db.CointipBotDatabase(dsn)

        try:
            conn = dbobj.connect()
        except Exception as e:
            logger.error("connect_db(): error connecting to database: %s", e)
            sys.exit(1)

        logger.info(
            "connect_db(): connected to database %s as %s",
            self.conf["db"]["auth"]["dbname"],
            self.conf["db"]["auth"]["user"] or "anonymous",
        )
        return conn

    def connect_reddit(self):
        """
        Returns a praw connection object
        """
        logger.debug("connect_reddit(): connecting to Reddit...")

        conn = praw.Reddit(
            user_agent=self.conf["reddit"]["auth"]["user"], check_for_updates=False
        )
        conn.login(
            self.conf["reddit"]["auth"]["user"],
            self.conf["reddit"]["auth"]["password"],
            disable_warning=True,
        )

        logger.info(
            "connect_reddit(): logged in to Reddit as %s",
            self.conf["reddit"]["auth"]["user"],
        )
        return conn

    def self_checks(self):
        """
        Run self-checks before starting the bot
        """

        # Ensure bot is a registered user
        b = ctb_user.CtbUser(name=self.conf["reddit"]["auth"]["user"].lower(), ctb=self)
        if not b.is_registered():
            b.register()

        # Ensure (total pending tips) < (CointipBot's balance)
        ctb_balance = user.get_balance(kind="givetip")
        pending_tips = float(0)
        actions = ctb_action.get_actions(atype="givetip", state="pending", ctb=self)
        for action in actions:
            pending_tips += action.coinval
        if (ctb_balance - pending_tips) < -0.000001:
            raise Exception(
                "self_checks(): CointipBot's balance (%s) < total pending tips (%s)"
                % (ctb_balance, pending_tips)
            )

        # Ensure coin balance is positive
        balance = float(self.coin.conn.getbalance())
        if balance < 0:
            raise Exception(f"self_checks(): negative balance: {balance}")

        # Ensure user accounts are intact and balances are not negative
        sql = "SELECT username FROM t_users ORDER BY username"
        for mysqlrow in self.db.execute(sql):
            user = ctb_user.CtbUser(name=mysqlrow["username"], ctb=self)
            if not user.is_registered():
                raise Exception(
                    f"self_checks(): user {mysqlrow['username']} is_registered() failed"
                )
            if user.get_balance(kind="givetip") < 0:
                raise Exception(
                    f"self_checks(): user {mysqlrow['username']} balance is negative"
                )

        return True

    def expire_pending_tips(self):
        """
        Decline any pending tips that have reached expiration time limit
        """

        # Calculate timestamp
        seconds = int(self.conf["misc"]["times"]["expire_pending_hours"] * 3600)
        created_before = time.mktime(time.gmtime()) - seconds
        counter = 0

        # Get expired actions and decline them
        for a in ctb_action.get_actions(
            atype="givetip",
            state="pending",
            created_utc="< " + str(created_before),
            ctb=self,
        ):
            a.expire()
            counter += 1

        # Done
        return counter > 0

    def check_inbox(self):
        """
        Evaluate new messages in inbox
        """
        logger.debug("check_inbox()")

        try:

            # Try to fetch some messages
            messages = list(
                ctb_misc.praw_call(
                    self.reddit.get_unread,
                    limit=self.conf["reddit"]["scan"]["batch_limit"],
                )
            )
            messages.reverse()

            # Process messages
            for m in messages:
                # Sometimes messages don't have an author (such as 'you are banned from' message)
                if not m.author:
                    logger.info("check_inbox(): ignoring msg with no author")
                    ctb_misc.praw_call(m.mark_as_read)
                    continue

                logger.info(
                    "check_inbox(): %s from %s",
                    "comment" if m.was_comment else "message",
                    m.author.name,
                )

                # Ignore duplicate messages (sometimes Reddit fails to mark messages as read)
                if ctb_action.check_action(msg_id=m.id, ctb=self):
                    logger.warning(
                        "check_inbox(): duplicate action detected (msg.id %s), ignoring",
                        m.id,
                    )
                    ctb_misc.praw_call(m.mark_as_read)
                    continue

                # Ignore self messages
                if (
                    m.author
                    and m.author.name.lower()
                    == self.conf["reddit"]["auth"]["user"].lower()
                ):
                    logger.debug("check_inbox(): ignoring message from self")
                    ctb_misc.praw_call(m.mark_as_read)
                    continue

                # Ignore messages from banned users
                if m.author and self.conf["reddit"]["banned_users"]:
                    logger.debug(
                        "check_inbox(): checking whether user '%s' is banned..."
                        % m.author
                    )
                    u = ctb_user.CtbUser(
                        name=m.author.name, redditobj=m.author, ctb=self
                    )
                    if u.banned:
                        logger.info(
                            "check_inbox(): ignoring banned user '%s'" % m.author
                        )
                        ctb_misc.praw_call(m.mark_as_read)
                        continue

                action = None
                if m.was_comment:
                    # Attempt to evaluate as comment / mention
                    action = ctb_action.eval_comment(m, self)
                else:
                    # Attempt to evaluate as inbox message
                    action = ctb_action.eval_message(m, self)

                # Perform action, if found
                if action:
                    logger.info(
                        "check_inbox(): %s from %s (m.id %s)",
                        action.type,
                        action.u_from.name,
                        m.id,
                    )
                    logger.debug("check_inbox(): message body: <%s>", m.body)
                    action.do()
                else:
                    logger.info("check_inbox(): no match")
                    if self.conf["reddit"]["messages"]["sorry"] and m.subject not in [
                        "post reply",
                        "comment reply",
                    ]:
                        user = ctb_user.CtbUser(
                            name=m.author.name, redditobj=m.author, ctb=self
                        )
                        tpl = self.jenv.get_template("didnt-understand.tpl")
                        msg = tpl.render(
                            user_from=user.name,
                            what="comment" if m.was_comment else "message",
                            source_link=ctb_misc.permalink(m),
                            ctb=self,
                        )
                        logger.debug("check_inbox(): %s", msg)
                        user.tell(
                            subj="What?",
                            msg=msg,
                            msgobj=m if not m.was_comment else None,
                        )

                # Mark message as read
                ctb_misc.praw_call(m.mark_as_read)

        except (HTTPError, ConnectionError, Timeout, RateLimitExceeded, timeout) as e:
            logger.warning("check_inbox(): Reddit is down (%s), sleeping", e)
            time.sleep(self.conf["misc"]["times"]["sleep_seconds"])
            pass
        except Exception as e:
            logger.exception("check_inbox(): %s", e)
            # raise
        # ^ what do we say to death?
        # 	    logger.error("^not today (^skipped raise)")
        #            raise #not sure if right number of spaces; try to quit on error
        # for now, quitting on error because of dealing with on-going issues; switch
        # back when stable

        logger.debug("check_inbox() DONE")
        return True

    def notify(self, _msg=None):
        """
        Send _msg to configured destination
        """

        # Construct MIME message
        msg = MIMEText(_msg)
        msg["Subject"] = self.conf["misc"]["notify"]["subject"]
        msg["From"] = self.conf["misc"]["notify"]["addr_from"]
        msg["To"] = self.conf["misc"]["notify"]["addr_to"]

        # Send MIME message
        server = smtplib.SMTP(self.conf["misc"]["notify"]["smtp_host"])
        if self.conf["misc"]["notify"]["smtp_tls"]:
            server.starttls()
        server.login(
            self.conf["misc"]["notify"]["smtp_username"],
            self.conf["misc"]["notify"]["smtp_password"],
        )
        server.sendmail(
            self.conf["misc"]["notify"]["addr_from"],
            self.conf["misc"]["notify"]["addr_to"],
            msg.as_string(),
        )
        server.quit()

    def __init__(
        self,
        self_checks=True,
        init_reddit=True,
        init_coins=True,
        init_exchanges=True,
        init_db=True,
    ):
        """
        Constructor. Parses configuration file and initializes bot.
        """
        logger.info("__init__()...")

        self.coin = None
        self.runtime = {"regex": []}

        # Configuration
        self.conf = self.parse_config()

        # Templating with jinja2
        self.jenv = Environment(
            trim_blocks=True, loader=PackageLoader("cointipbot", "tpl/jinja2")
        )

        # Database
        if init_db:
            self.db = self.connect_db()

        # Coins
        if init_coin:
            self.coin = ctb_coin.CtbCoin(_conf=self.conf["coin"])

        # Reddit
        if init_reddit:
            self.reddit = self.connect_reddit()
            # Regex for Reddit messages
            ctb_action.init_regex(self)

        # Self-checks
        if self_checks:
            self.self_checks()

        logger.info(
            "__init__(): DONE, batch-limit = %s, sleep-seconds = %s",
            self.conf["reddit"]["scan"]["batch_limit"],
            self.conf["misc"]["times"]["sleep_seconds"],
        )

    def __str__(self):
        """
        Return string representation of self
        """
        return "<CointipBot: sleepsec={}, batchlim={}".format(
            self.conf["misc"]["times"]["sleep_seconds"],
            self.conf["reddit"]["scan"]["batch_limit"],
        )

    def main(self):
        """
        Main loop
        """

        while True:
            try:
                logger.debug("main(): beginning main() iteration")

                # Expire pending tips first. fuck waiting for this shit.
                self.expire_pending_tips()

                # Check personal messages
                self.check_inbox()

                # Sleep
                logger.debug(
                    "main(): sleeping for %s seconds...",
                    self.conf["misc"]["times"]["sleep_seconds"],
                )
                time.sleep(self.conf["misc"]["times"]["sleep_seconds"])

            except Exception as e:
                logger.error("main(): exception: %s", e)
                tb = traceback.format_exc()
                logger.error("main(): traceback: %s", tb)
                # Send a notification, if enabled
                if self.conf["misc"]["notify"]["enabled"]:
                    self.notify(_msg=tb)
                sys.exit(1)
