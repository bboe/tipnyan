#!/usr/bin/python
# -*- coding: utf-8 -*-

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
import re
import time

from . import ctb_misc

logger = logging.getLogger("ctb.stats")


def update_stats(ctb=None):
    """
    Update stats wiki page
    """

    stats = ""

    for s in sorted(ctb.conf["db"]["sql"]["globalstats"]):
        logger.debug("update_stats(): getting stats for '%s'" % s)
        sql = ctb.conf["db"]["sql"]["globalstats"][s]["query"]
        stats += "\n\n### %s\n\n" % ctb.conf["db"]["sql"]["globalstats"][s]["name"]
        stats += "%s\n\n" % ctb.conf["db"]["sql"]["globalstats"][s]["desc"]

        mysqlexec = ctb.db.execute(sql)
        if mysqlexec.rowcount <= 0:
            logger.warning(
                "update_stats(): query <%s> returned nothing"
                % ctb.conf["db"]["sql"]["globalstats"][s]["query"]
            )
            continue

        if ctb.conf["db"]["sql"]["globalstats"][s]["type"] == "line":
            m = mysqlexec.fetchone()
            k = list(mysqlexec.keys())[0]
            value = format_value(m, k, "", ctb)
            stats += "%s = **%s**\n" % (k, value)

        elif ctb.conf["db"]["sql"]["globalstats"][s]["type"] == "table":
            stats += ("|".join(mysqlexec.keys())) + "\n"
            stats += ("|".join([":---"] * len(mysqlexec.keys()))) + "\n"
            for m in mysqlexec:
                values = []
                for k in mysqlexec.keys():
                    values.append(format_value(m, k, "", ctb))
                stats += ("|".join(values)) + "\n"

        else:
            logger.error(
                "update_stats(): don't know what to do with type '%s'"
                % ctb.conf["db"]["sql"]["globalstats"][s]["type"]
            )
            return False

        stats += "\n"

    logger.debug(
        "update_stats(): updating subreddit '%s', page '%s'"
        % (
            ctb.conf["reddit"]["stats"]["subreddit"],
            ctb.conf["reddit"]["stats"]["page"],
        )
    )
    pagename = ctb.conf["reddit"]["stats"]["page"]
    wiki_page = ctb.reddit.subreddit(ctb.conf["reddit"]["stats"]["subreddit"]).wiki[
        pagename
    ]
    return ctb_misc.praw_call(
        wiki_page.edit,
        content=stats,
        reason="Update by nyantip bot",
    )


def update_tips(ctb=None):
    """
    Update page listing all tips
    """

    # Start building stats page
    tip_list = "### All Completed Tips\n\n"

    ctb.db.execute(ctb.conf["db"]["sql"]["tips"]["sql_set"])
    tips = ctb.db.execute(
        ctb.conf["db"]["sql"]["tips"]["sql_list"],
        (ctb.conf["db"]["sql"]["tips"]["limit"]),
    )
    tip_list += ("|".join(tips.keys())) + "\n"
    tip_list += ("|".join([":---"] * len(tips.keys()))) + "\n"

    # Build tips table
    for t in tips:
        values = []
        for k in tips.keys():
            values.append(format_value(t, k, "", ctb))
        tip_list += ("|".join(values)) + "\n"

    logger.debug(
        "update_tips(): updating subreddit '%s', page '%s'"
        % (
            ctb.conf["reddit"]["stats"]["subreddit"],
            ctb.conf["reddit"]["stats"]["page_tips"],
        )
    )

    pagename = ctb.conf["reddit"]["stats"]["page_tips"]
    wiki_page = ctb.reddit.subreddit(ctb.conf["reddit"]["stats"]["subreddit"]).wiki[
        pagename
    ]
    ctb_misc.praw_call(
        wiki_page.edit,
        content=tip_list,
        reason="Update by nyantip bot",
    )
    return True


def update_all_user_stats(ctb=None):
    """
    Update individual user stats for all uers
    """

    users = ctb.db.execute(ctb.conf["db"]["sql"]["userstats"]["users"])
    for u in users:
        update_user_stats(ctb=ctb, username=u["username"])


def update_user_stats(ctb=None, username=None):
    """
    Update individual user stats for given username
    """

    # List of coins
    coins_q = ctb.db.execute(ctb.conf["db"]["sql"]["userstats"]["coins"])
    coins = []
    for c in coins_q:
        coins.append(c["coin"])

    # Start building stats page
    user_stats = "### Tipping Summary for /u/%s\n\n" % username
    page = ctb.conf["reddit"]["stats"]["page"] + "_" + username

    # Total Tipped
    user_stats += "#### Total Tipped (Coins)\n\n"
    user_stats += "coin|total\n:---|---:\n"
    for c in coins:
        mysqlexec = ctb.db.execute(
            ctb.conf["db"]["sql"]["userstats"]["total_tipped_coin"], (username, c)
        )
        total_tipped_coin = mysqlexec.fetchone()
        if total_tipped_coin["total_coin"] is not None:
            user_stats += "**%s**|%s %.6f\n" % (
                c,
                ctb.conf["coin"]["symbol"],
                total_tipped_coin["total_coin"],
            )
    user_stats += "\n"

    # Total received
    user_stats += "#### Total Received (Coins)\n\n"
    user_stats += "coin|total\n:---|---:\n"
    for c in coins:
        mysqlexec = ctb.db.execute(
            ctb.conf["db"]["sql"]["userstats"]["total_received_coin"], (username, c)
        )
        total_received_coin = mysqlexec.fetchone()
        if total_received_coin["total_coin"] is not None:
            user_stats += "**%s**|%s %.6f\n" % (
                c,
                ctb.conf["coin"]["symbol"],
                total_received_coin["total_coin"],
            )
    user_stats += "\n"

    # History
    user_stats += "#### History\n\n"
    history = ctb.db.execute(
        ctb.conf["db"]["sql"]["userstats"]["history"], (username, username)
    )
    user_stats += ("|".join(history.keys())) + "\n"
    user_stats += ("|".join([":---"] * len(history.keys()))) + "\n"

    # Build history table
    num_tipped = 0
    num_received = 0
    for m in history:
        if m["state"] == "completed":
            if m["from_user"].lower() == username.lower():
                num_tipped += 1
            elif m["to_user"].lower() == username.lower():
                num_received += 1
        values = []
        for k in history.keys():
            values.append(format_value(m, k, username, ctb))
        user_stats += ("|".join(values)) + "\n"

    # Submit changes
    logger.debug(
        "update_user_stats(): updating subreddit '%s', page '%s'"
        % (ctb.conf["reddit"]["stats"]["subreddit"], page)
    )
    wiki_page = ctb.reddit.subreddit(ctb.conf["reddit"]["stats"]["subreddit"]).wiki[
        page
    ]
    ctb_misc.praw_call(
        wiki_page.edit,
        content=user_stats,
        reason="Update by nyantip bot",
    )
    return True


def format_value(m, k, username, ctb, compact=False):
    """
    Format value for display based on its type
    m[k] is the value, k is the database row name
    """

    if not m[k]:
        return "-"

    # Format cryptocoin
    if type(m[k]) == float and k.find("coin") > -1:
        coin_symbol = ctb.conf["coin"]["symbol"]
        return "%s&nbsp;%.5g" % (coin_symbol, m[k])

    # Format username
    elif k.find("user") > -1 and isinstance(m[k], str):
        if compact:
            return (
                ("**/u/%s**" % m[k])
                if m[k].lower() == username.lower()
                else ("/u/%s" % m[k])
            )
        else:
            un = ("**%s**" % m[k]) if m[k].lower() == username.lower() else m[k]
            toreturn = "[%s](/u/%s)" % (un, re.escape(m[k]))
            if m[k].lower() != username.lower():
                toreturn += "^[[stats]](/r/%s/wiki/%s_%s)" % (
                    ctb.conf["reddit"]["stats"]["subreddit"],
                    ctb.conf["reddit"]["stats"]["page"],
                    m[k],
                )
            return toreturn

    # Format address
    elif k.find("addr") > -1:
        displayaddr = m[k][:6] + "..." + m[k][-5:]
        return "[%s](%s%s)" % (
            displayaddr,
            ctb.conf["coin"]["explorer"]["address"],
            m[k],
        )

    # Format state
    elif k.find("state") > -1:
        if m[k] == "completed":
            return "✓"
        else:
            return m[k]

    # Format type
    elif k.find("type") > -1:
        if m[k] == "givetip":
            return "tip"
        if compact:
            if m[k] == "withdraw":
                return "w"

    # Format subreddit
    elif k.find("subreddit") > -1:
        return "/r/%s" % m[k]

    # Format link
    elif k.find("link") > -1:
        return "[link](%s)" % m[k]

    # Format time
    elif k.find("utc") > -1:
        return "%s" % time.strftime("%Y-%m-%d", time.localtime(m[k]))

    # It's something else
    else:
        return str(m[k])
