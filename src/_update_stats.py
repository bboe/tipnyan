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

import cointipbot
from ctb import ctb_stats

logging.basicConfig()
logger = logging.getLogger("cointipbot")
logger.setLevel(logging.DEBUG)

ctb = cointipbot.CointipBot(
    self_checks=False,
    init_reddit=True,
    init_coins=False,
    init_exchanges=False,
    init_db=True,
    init_logging=False,
)

# Update stats page
result = ctb_stats.update_stats(ctb=ctb)
logger.debug(result)

# Update tips page
result = ctb_stats.update_tips(ctb=ctb)
logger.debug(result)

# This isn't needed because it happens during the tip processing
# result = ctb_stats.update_all_user_stats(ctb=ctb)
# logger.debug(result)
