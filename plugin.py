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

import time
import re
import urllib2
import feedparser
from html2text import HTML2Text
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

        self.schedule_event(self.scrape_changelog, 'bug_poll_s', 'scrape')
        self.schedule_event(self.check_devlog, 'devlog_poll_s', 'check_devlog')

    def schedule_event(self, f, config_value, name):
        # Like schedule.addPeriodicEvent, but capture the name of our config
        # variable in the closure rather than the value
        def wrapper():
            try:
                f()
            finally:
                return schedule.addEvent(wrapper, time.time() + self.registryValue(config_value), name)

        return wrapper()

    def check_devlog(self):
        d = feedparser.parse(DEVLOG_URL)

        date = d.entries[0].title

        if date != self.last_devlog:
            # New devlog!
            self.last_devlog = date

            title = ircutils.bold('%s %s: ' % (d.feed.title, date))
            summary = d.entries[0].summary
            full_message = title + summary

            # Parse and wrap the message with html2text
            h = HTML2Text()
            h.body_width = self.registryValue('max_chars_per_line')

            # Convert the message to text, and strip empty lines
            processed_message = h.handle(full_message)
            split_message = filter(None, [x.strip() for x in processed_message.split('\n')])

            max_lines = self.registryValue('max_lines')
            if len(split_message) > max_lines:
                # The devlog is too long... give a configured number and a link
                devlog_url = d.entries[0].id

                split_message = split_message[0:max_lines]
                split_message.append('... ' + devlog_url)

            self.queue_messages(split_message)

    def scrape_changelog(self):
        changelog_url = CHANGELOG_URL+('?version_id=%u' % (self.version_id,))
        soup = BeautifulSoup(urllib2.urlopen(changelog_url).read(),
                convertEntities=BeautifulSoup.HTML_ENTITIES)

        # First check to make sure the version name hasn't changed on us
        version_name = soup('tt')[0].findAll('a')[1].text

        matches = re.search('^[\d\.]+$', version_name)
        if matches:
            # New version incoming!
            self.queue_messages([ircutils.bold('Dwarf Fortress v%s has been released!' % (version_name,))])

            # Prepare for the next version
            self.version_id = self.version_id + 1
            self.known_issues.clear()
            return


        # Prepare a list of messages to be sent
        msg_list = []

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

            # Build up the formatted message to send, and add it to the list
            bolded_id_and_category = ircutils.bold('%s: %s' % (issue_id,
                issue_category))
            msg_list.append('%s %s%s%s ( %s )' % (bolded_id_and_category,
                    issue_title, issue_fixer, issue_status, issue_url))

            # Get the closing note and add it to the list as well
            last_note_msg = self.get_closing_note(issue_url)
            if last_note_msg:
                msg_list.append(last_note_msg)

        # Now that we've processed all the issues, send out the messages
        if msg_list:
            self.queue_messages(msg_list)

        # Allow messages to be sent next time, if they were inhibited this time
        self.first_run = False

    def get_closing_note(self, issue_url):
        # Read the issue page to check for a closing note by Toady
        soup = BeautifulSoup(urllib2.urlopen(issue_url).read())
        bug_notes = soup.findAll('tr', 'bugnote')

        if not bug_notes:
            # No bug notes
            return []

        # Check the last note on the page to see who made it
        last_note = bug_notes[-1]
        last_note_author = last_note.findAll('a')[1].text

        if last_note_author == u'Toady One':
            # Grab Toady's last note on the bug
            last_note_msg = '"' + last_note.findNext('td',
                    'bugnote-note-public').text + '"'
            return last_note_msg
        else:
            # Last not wasn't from Toady
            return []

    def queue_messages(self, msg_list):
        for channel in sorted(self.irc.state.channels):
            for msg in msg_list:
                self.irc.queueMsg(ircmsgs.privmsg(channel, msg))


    def die(self):
        schedule.removeEvent('scrape')
        schedule.removeEvent('check_devlog')


Class = DFBugMonitor


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
