###
# Copyright (c) 2014, Mike Stewart
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

###

import supybot.utils as utils
from supybot.commands import *
import supybot.plugins as plugins
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks
import supybot.schedule as schedule
import supybot.ircmsgs as ircmsgs

import re
import urllib2
import HTMLParser
import feedparser
import textwrap
from BeautifulSoup import BeautifulSoup

DEVLOG_URL = 'http://www.bay12games.com/dwarves/dev_now.rss'
CHANGELOG_URL = 'http://www.bay12games.com/dwarves/mantisbt/changelog_page.php'

class DFBugMonitor(callbacks.Plugin):
    """Simply load the plugin, and it will periodically check for DF bugfixes
    and announce them"""

    def __init__(self, irc):
        self.__parent = super(DFBugMonitor, self)
        self.__parent.__init__(irc)

        self.irc = irc

        # Get the latest devlog
        d = feedparser.parse(DEVLOG_URL)
        self.last_devlog = d.entries[0].title

        # Prepare the already-known-issues set
        self.known_issues = set()
        self.first_run = True

        # Find the latest version
        soup = BeautifulSoup(urllib2.urlopen(CHANGELOG_URL).read())

        latest_version_link = soup('tt')[0].findAll('a')[1]
        matches = re.search('\d+$', latest_version_link['href'])
        self.version_id = int(matches.group(0))

        matches = re.search('^[\d\.]+$', latest_version_link.text)
        if matches:
            # The latest listed version has already been released, so our
            # target version ID is probably one more
            self.version_id = self.version_id + 1

        print 'Starting at version %u' % (self.version_id,)

        schedule.addPeriodicEvent(self.scrape_changelog, 5*60, 'scrape')
        schedule.addPeriodicEvent(self.check_devlog, 15*60, 'check_devlog')

    def check_devlog(self):
        d = feedparser.parse(DEVLOG_URL)

        date = d.entries[0].title

        if date != self.last_devlog:
            # New devlog!
            self.last_devlog = date

            title = ircutils.bold('%s %s: ' % (d.feed.title, date))
            summary = d.entries[0].summary
            full_message = title + summary

            split_message = textwrap.wrap(full_message, 400)

            for msg in split_message:
                for channel in self.irc.state.channels:
                    self.irc.queueMsg(ircmsgs.privmsg(channel, msg))

    def scrape_changelog(self):
        changelog_url = CHANGELOG_URL+('?version_id=%u' % (self.version_id,))
        soup = BeautifulSoup(urllib2.urlopen(changelog_url).read(),
                convertEntities=BeautifulSoup.HTML_ENTITIES)


        # First check to make sure the version name hasn't changed on us
        version_name = soup('tt')[0].findAll('a')[1].text

        matches = re.search('^[\d\.]+$', version_name)
        if matches:
            # New version incoming!
            for channel in self.irc.state.channels:
                self.irc.queueMsg(ircmsgs.privmsg(channel, ircutils.bold('Dwarf Fortress v%s has been released!' % (version_name,))))
            # Prepare for the next version
            self.version_id = self.version_id + 1
            self.known_issues.clear()
            return


        # Base our scrape off of the br tags that separate issues
        lines = soup('tt')[0].findAll('br')

        for i in range(2, len(lines)):
            issue = lines[i]

            # Extract the issue ID from the link to the issue
            issue_id_link = issue.findNext('a')
            issue_id = issue_id_link.text

            if issue_id in self.known_issues:
                continue

            # Start by adding the issue to the list of known issues for this
            # version
            self.known_issues.add(issue_id)

            if self.first_run:
                # If this is the first run, just fill out the known issues set
                # but don't send any messages
                continue

            # Get the URL of the bug page
            issue_url = 'http://www.bay12games.com' + issue_id_link['href']

            # Grab the bolded category, and use it to find the description
            issue_category_b = issue.findNext('b')
            issue_category = issue_category_b.text
            issue_title = issue_category_b.nextSibling

            # Get the link to the fix author (probable Toady) for their name and
            # the resolution status
            issue_fixer_link = issue.findNext('a', {'class': None})
            issue_fixer = issue_fixer_link.text
            issue_status = issue_fixer_link.nextSibling

            # Build up the formatted message to send
            bolded_id_and_category = ircutils.bold('%s: %s' % (issue_id,
                issue_category))
            formatted_msg = '%s %s%s%s (%s)' % (bolded_id_and_category,
                    issue_title, issue_fixer, issue_status, issue_url)


            for channel in self.irc.state.channels:
                self.irc.queueMsg(ircmsgs.privmsg(channel, formatted_msg))

        self.first_run = False

    def die(self):
        schedule.removeEvent('scrape')
        schedule.removeEvent('check_devlog')


Class = DFBugMonitor


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
