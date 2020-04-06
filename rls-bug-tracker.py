#!/usr/bin/python3

import argparse
from collections import defaultdict
import datetime
import distro_info
import json
import urllib.request
import sys
import os
from launchpadlib.launchpad import Launchpad
from debian.deb822 import Deb822


URL_PATTERN = 'http://reqorts.qa.ubuntu.com/reports/rls-mgr/rls-{letter}{letter}-tracking.json'  # noqa
FINISHED_STATUS = {'Fix Committed', 'Fix Released', 'Incomplete'}
RLS_BUGS_LIST = []
USERNAMES = {
'Timo Aaltonen':'tjaalton',
'Iain Lane':'laney',
'Sebastien Bacher':'seb128',
'James Henstridge':'jamesh',
'Daniel van Vugt' : 'vanvugt',
'Till Kamppeter' : 'till-kamppeter',
'Marco Trevisan (Trevio)' : '3v1n0',
'Jean-Baptiste Lallement' : 'jibel',
'Alberto Milone':'tseliot',
'Ken VanDine': 'kenvandine',
'Robert Ancell':'robert.ancell',
'Didier Roche': 'didrocks',
'Olivier Tilloy':'oSoMoN',
'Marcus Tomlinson':'marcustomlinson',
'Martin Wimpress':'wimpress',
'Heather Ellsworth':'hellsworth',
'Patrick Wu':'callmepk'
}


class RlsTrackingBug():
    def __init__(self, bug_task,num):
        assert(bug_task)
        #print(bug_task)
        self.assignee = bug_task['assignee']
        self.title = bug_task['title']
        self.status = bug_task['status']
        self.web_link = bug_task['web_link']
        self.num = num
        self.date_task_created = datetime.datetime.strptime(bug_task['date_created'], '%A, %d. %B %Y %H:%M %Z')
    def is_in_queue(self):
        global uploads_bug_list # I decided that in the end it was easier to just use a global
        if self.num in uploads_bug_list:
            #print("Found the bug in the uploads queue!")
            return True
        return False

    def is_finished(self):
        status_finished = not bool(set([self.status]) - FINISHED_STATUS)
        return status_finished or self.is_in_queue()


class RlsTrackingBugs(dict):
    def __init__(self, release, teams):
        assert(release[0])
        assert(teams != [])

        teams = set(teams)

        url = URL_PATTERN.format(letter=release[0])

        with urllib.request.urlopen(url) as url:
            j = json.load(url)['tasks']
            for (bugno, tasks) in j.items():
                for task in tasks:
                    task_teams = set(task['team'])
                    bug = RlsTrackingBug(task,bugno)
                    if (teams & task_teams) and not bug.is_finished():
                        self[task['assignee']][bugno] = bug

    def __missing__(self, key):
        self[key] = {}
        return self[key]


def get_changes_file(changes_file_url):
    if changes_file_url is not None:
        changes_text = urllib.request.urlopen(changes_file_url).read()
        changes_dict = Deb822(changes_text)
    else:
        return

    if 'Launchpad-Bugs-Fixed' in changes_dict.keys():
        bugnum = changes_dict['Launchpad-Bugs-Fixed']
        return bugnum.split(' ') # This can be a string which has many entries
        #print("Found bug: "+bugnum)


def build_uploads_bug_list(uploads):
    #print("Looking at uploads for this release...")
    bug_list = []
    for each in uploads:
        if 'changes_file_url' in each.lp_attributes and each.changes_file_url:
            bugs = get_changes_file(each.changes_file_url)
            if bugs:
                bug_list.extend(bugs)
        else:
            # Is this a sync?
            series = each.distroseries
            pkg = each.package_name
            version = each.package_version
            source_archive = each.copy_source_archive

            try:
                spphs = source_archive.getPublishedSources(distro_series=series,
                                                           exact_match=True,
                                                           source_name=pkg,
                                                           version=version,
                                                           order_by_date=True)
                changes_file = spphs[0].changesFileUrl()
                if changes_file:
                    bugs = get_changes_file(changes_file)
                    if bugs:
                        bug_list.extend(bugs)
            except IndexError:
                # not found
                continue

    return bug_list

def main():
    print("\n\n\n\n\n\n")
    launchpad = Launchpad.login_anonymously('read-only connection', 'production', version="devel")
    ubuntu_distro_info = distro_info.UbuntuDistroInfo()

    # < artful used rls-L-incoming >= use rls-LL-incoming and those are
    # interesting to us
    available_series = [r.series for r in
                        distro_info.UbuntuDistroInfo().supported(
                            result='object')
                        if r.release >= datetime.date(2017, 4, 21)]

    parser = argparse.ArgumentParser(description='find rls bugs')
    parser.add_argument('--release', '-r', action='append',
                        metavar='RELEASE',
                        choices=available_series + ['ALL'],
                        help='release to consider, or ALL (the default) to '
                        'consider all supported releases')
    parser.add_argument('team', metavar='TEAM', type=str, nargs='+',
                        help='team to consider')

    args = parser.parse_args()

    if args.release is None or 'ALL' in args.release:
        args.release = available_series

    for rls in args.release:
        print("# %s" % (rls))
        print("---\n")
        ubuntu_series = launchpad.distributions['ubuntu'].getSeries(name_or_version=rls)
        uploads = ubuntu_series.getPackageUploads(status='Unapproved')
        global uploads_bug_list
        uploads_bug_list = set(build_uploads_bug_list(uploads))

        for (assignee, bugs) in RlsTrackingBugs(rls, args.team).items():
            for (bugno, bug) in bugs.items():
                if bugno not in RLS_BUGS_LIST and bugno not in uploads_bug_list:
                    if assignee:
                        if assignee == "Unassigned":
                            print("#### :warning: %s :warning:\n" % assignee)
                        else:
                            if assignee in USERNAMES.keys():
                                assignee = assignee+" (@" + USERNAMES[assignee]+")"
                            print("#### %s\n" % assignee)
                        assignee = False
                    age = (datetime.datetime.now() - bug.date_task_created).days
                    print("[%s](%s)\n" % (bug.title, bug.web_link))

                    print('{} {} Task created {} days ago; {}'.format(bug.status,
                                                                      ':sleeping:' if age > 7 else ':sunglasses:',
                                                                      age,
                                                                      bug.date_task_created))
                    print('\n') # Without this extra new line the discourse formatting goes to pot and everything is a heading
                    RLS_BUGS_LIST.append(bugno)
                    print("---\n")


if __name__ == '__main__':
    main()
