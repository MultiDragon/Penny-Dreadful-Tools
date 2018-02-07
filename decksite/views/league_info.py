from flask import url_for
from flask_babel import gettext

from decksite.view import View
from decksite import league

# pylint: disable=no-self-use
class LeagueInfo(View):
    def __init__(self):
        self.current = league.active_league()
        self.end_date = custom_strftime('%B {S}', self.current.end_date)
        self.signup_url = url_for('signup')
        self.report_url = url_for('report')
        self.records_url = url_for('current_league')
        self.retire_url = url_for('retire')

    def subtitle(self):
        return 'League'

    def TT_SIGN_UP_LINK(self):
        return gettext('Sign Up Here')

    def TT_LEAGUE_LASTS_A_MONTH(self):
        return gettext('Each league lasts roughly a month.')

def suffix(d):
    return 'th' if 11 <= d <= 13 else {1:'st', 2:'nd', 3:'rd'}.get(d % 10, 'th')

def custom_strftime(fmt, t):
    return t.strftime(fmt).replace('{S}', str(t.day) + suffix(t.day))
