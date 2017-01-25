from BlockListParser import BlockListParser
from collections import defaultdict

import os
import re
import psycopg2
import utils

class CensusException(Exception):
    pass

class Census:
    """A class representing one census crawl.
    """
    
    def __init__(self, census_name):
        user = 'openwpm'
        password = 'Pwcpdtwca!'
        host = 'princeton-web-census-machine-1.cp85stjatkdd.us-east-1.rds.amazonaws.com' 
        db_details = 'dbname={0} user={1} password={2} host={3}'.format(census_name, user, password, host)
        self.connection = psycopg2.connect(db_details)

    def check_top_url(self, top_url):
        """Return True if a top_url is present in the census."""
        check_query = "SELECT exists (SELECT * FROM site_visits WHERE top_url = %s LIMIT 1)"

        cur = self.connection.cursor()
        cur.itersize = 1

        cur.execute(check_query, (top_url,))

        for exists, in cur:
            return exists

        return False

    def get_top_urls_with_third_party_domain(self, tp_domain):
        """Return a dictionary mapping top_url -> list(tp_urls_from_tp_domain)"""
        tp_query = "SELECT top_url, url FROM http_responses_view " \
                   "WHERE url LIKE '%%' || %s || '%%'"
        cur = self.connection.cursor()
        cur.itersize = 100000

        cur.execute(tp_query, (tp_domain,))

        sites_with_tp = defaultdict(list)
        for top_url, url in cur:
            if utils.should_ignore(url):
                continue

            # Check to make sure URL properly matches domain, and is not a false positive
            url_domain = utils.get_host_plus_ps(url)

            if url_domain == tp_domain:
                sites_with_tp[top_url].append(url)

        return dict(sites_with_tp)

    def get_third_party_responses_by_domain(self, top_url):
        """Return a dictionary containing third party data loaded on given top_url."""
        tp_query = "SELECT r.url, h.value FROM http_responses_view AS r " \
                   "LEFT JOIN http_response_headers_view as h ON h.response_id = r.id " \
                   " WHERE r.top_url LIKE %s AND " \
                   "url not LIKE %s and h.name = 'Content-Type'"
        cur = self.connection.cursor()
        cur.itersize = 100000
        try:
            top_ps = utils.get_host_plus_ps(top_url)
        except AttributeError:
            print("Error while finding public suffix of %s" % top_url)
            return None

        cur.execute(tp_query, (top_url, top_ps))

        el_parser = BlockListParser('easylist.txt')
        ep_parser = BlockListParser('easyprivacy.txt')
        response_data = defaultdict(dict)
        for url, content_type in cur:
            if utils.should_ignore(url):
                continue

            url_data = dict()

            url_ps = utils.get_host_plus_ps(url)
            if url_ps == top_ps:
                continue
            url_data['url_ps'] = url_ps

            is_js = utils.is_js(url, content_type)
            is_img = utils.is_img(url, content_type)
            is_el_tracker = utils.is_tracker(url, 
                                             is_js=is_js,
                                             is_img=is_img, 
                                             first_party=top_url, 
                                             blocklist_parser=el_parser)
            is_ep_tracker = utils.is_tracker(url, 
                                             is_js=is_js,
                                             is_img=is_img, 
                                             first_party=top_url, 
                                             blocklist_parser=ep_parser)
            is_tracker = is_el_tracker or is_ep_tracker

            url_data['is_js'] = is_js
            url_data['is_img'] = is_img
            url_data['is_tracker'] = is_tracker
            response_data[url] = url_data

        return dict(response_data)

    def get_cookie_syncs_v2(self, top_url, cookie_length=8):
        """Get all 'cookie sync' events on a given top_url.

        Returns a dict mapping receiving urls to the domain sending the cookie, 
        and the value of the cookie being shared

        Note: This method does not isolate 'identifying cookies', it identifies
        all cookies that are shared from one domain to a URL not in that domain
        that are >= cookie_length.
        """

        # Select all url, name, value from response_cookies_view by top_url
        query = "SELECT DISTINCT res.url, v1.name, v1.value FROM " \
                "http_responses_view as res " \
                "LEFT JOIN http_response_cookies_view as v1 " \
                "ON v1.response_id = res.id " \
                "WHERE res.top_url = %s AND v1.name != ''" \
                " union " \
                "SELECT DISTINCT req.url, v2.name, v2.value FROM " \
                "http_requests_view as req " \
                "LEFT JOIN http_request_cookies_view as v2 " \
                "ON v2.request_id = req.id " \
                "WHERE req.top_url = %s AND v2.name != ''" 
        cookie_cur = self.connection.cursor()
        try:
            cookie_cur.execute(query, (top_url,top_url))
        except:
            self.connection.rollback()
            return None

        cookie_syncs = defaultdict(set)
        i = 0
        check_responses_query = "SELECT url, referrer, location FROM http_responses_view " \
                                "WHERE top_url = %s " 

        res_cursor = self.connection.cursor()
        try:
            res_cursor.execute(check_responses_query, (top_url, ))
        except:
            self.connection.rollback()
            return None
        rows = res_cursor.fetchall()
        for cookie_url, name, value in cookie_cur:

            i += 1
            if len(value) < cookie_length:
                continue
            try:
                cookie_ps = utils.get_host_plus_ps(cookie_url)
            except AttributeError:
                print("Error while finding public suffix of %s" % cookie_ps)
                continue

            for url, referrer, location in rows:
                try:
                    url_ps = utils.get_host_plus_ps(url)
                except AttributeError:
                    print("Error while finding public suffix of %s" % url)
                    continue                
                if url_ps == cookie_ps:
                    continue

                if referrer and (value in referrer):
                    receiving_url = url
                    sending_url = utils.get_host_plus_ps(referrer)
                elif location and (value in location):
                    receiving_url = location
                    sending_url = url_ps
                elif value in url:
                    receiving_url = url
                    sending_url = cookie_ps
                else:
                    continue
                cookie_syncs[receiving_url].add((sending_url, value))

        return dict(cookie_syncs)


    def get_cookie_syncs_on_domain(self, top_url):
        """DEPRECATED: old method to find cookie syncs."""
        redirect_query = "SELECT url, referrer, location FROM http_responses_view " \
                         "WHERE location IS NOT NULL AND location != '' AND " \
                         "top_url = %s; "
        ID_SIZE = 8

        cur = self.connection.cursor()
        cookie_cur = self.connection.cursor()

        print(redirect_query % top_url)
        cur.execute(redirect_query, (top_url,))
        print("DONE WITH FIRST QUERY")
        cookie_syncs = defaultdict(set)
        for url, referrer, location in cur:
            print("PROCESSING NEW LOCATION: " + location)
            try:
                url_ps = utils.get_host_plus_ps(url)
            except AttributeError:
                print("Error while finding public suffix of %s" % url)
                continue

            try:
                location_ps = utils.get_host_plus_ps(location)
            except AttributeError:
                print("Error while finding public suffix of %s" % location)
                continue

            if location_ps == url_ps :
                continue

            tokens = re.split('[/&=?]+' ,location)
            synced_cookies = set()
            synced_cookie_name = ''
            synced_cookie_value = ''
            tokens = filter(lambda x: len(x) >= ID_SIZE, tokens)
            token_boolean = "v.value LIKE '%%%%' || '%s' || '%%%%'"
            token_booleans = []
            for token in tokens :
                token_booleans.append(token_boolean % token.replace('%', '%%'))
            all_tokens_boolean = ' OR '.join(token_booleans)
            requests_query = "SELECT r.url, v.name, v.value FROM " \
                             "http_requests_view as r " \
                             "LEFT JOIN http_request_cookies_view as v " \
                             "ON v.request_id = r.id " \
                             "WHERE r.url LIKE '%%' || %s || '%%' AND "
            requests_query = requests_query + '(' + all_tokens_boolean + ')'
            try:
                cookie_cur.execute(requests_query, (url,))
            except:
                self.connection.rollback()
                continue
            for cookie_url, name, value in cookie_cur :
                synced_cookies.add((name, value))
                synced_cookie_name = name
                synced_cookie_value = value
                print(cookie_url)
                print(name)
                print(value)
            responses_query = "SELECT r.url, v.name, v.value FROM " \
                              "http_responses_view as r " \
                              "LEFT JOIN http_response_cookies_view as v " \
                              "ON v.response_id = r.id " \
                              "WHERE r.url LIKE '%%' || %s || '%%' AND "
            responses_query = responses_query + '(' + all_tokens_boolean + ')'
            try:
                cookie_cur.execute(responses_query, (url,))
            except:
                self.connection.rollback()
                continue
            for cookie_url, name, value in cookie_cur :
                synced_cookies.add((name, value))
                synced_cookie_name = name
                synced_cookie_value = value
                print(cookie_url)
                print(name)
                print(value)

            if len(synced_cookies) > 0 :
                cookie_syncs[location].add((url, synced_cookie_name, synced_cookie_value))
        return dict(cookie_syncs)

    def get_urls_with(self, top_url, symbol):
        """ Returns javascript urls which call these symbols on a given top_url"""
        print("Grabbing scripts with %s" % symbol)
        urls = set()

        cur = self.connection.cursor()
        cur.execute("select top_url, script_url from javascript_view where symbol = %s and top_url = %s",(symbol, top_url))
        for top_url, script_url in cur:
            urls.add(script_url)

        return urls