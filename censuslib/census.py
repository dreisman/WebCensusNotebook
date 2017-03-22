from BlockListParser import BlockListParser
from collections import Counter, defaultdict
import collections
import csv
import matplotlib.pyplot as plt
import numpy as np
import os
import re
import psycopg2
import utils

class CensusException(Exception):
    pass

class URL(object):
    def __init__(self, url, domain, is_js=None, is_img=None, is_tracker=None, first_party=None):
        self.url = url
        self.domain = domain
        self._is_js = is_js
        self._is_img = is_img
        self.first_party = first_party
        self._is_tracker = is_tracker
        
    @property
    def is_tracker(self):
        if self._is_tracker == None:
            is_el_tracker = utils.is_tracker(self.url, 
                                             is_js=self.is_js,
                                             is_img=self.is_img, 
                                             first_party=self.first_party.domain, 
                                             blocklist='easylist')
            is_ep_tracker = utils.is_tracker(self.url, 
                                             is_js=self.is_js,
                                             is_img=self.is_img, 
                                             first_party=self.first_party.domain, 
                                             blocklist='easyprivacy')
            self._is_tracker = is_el_tracker or is_ep_tracker
        return self._is_tracker
    
    @is_tracker.setter
    def is_tracker(self, val):
        self._is_tracker = val
    
    @property
    def is_js(self):
        if self._is_js == None:
            self._is_js = utils.is_js(url, content_type)
        return self._is_js
    
    @is_js.setter
    def is_js(self, val):
        self._is_js = val
       
    @property
    def is_img(self):
        if self._is_img == None:
            self._is_img = utils.is_img(url, content_type)
        return self._is_img
    
    @is_img.setter
    def is_img(self, val):
        self._is_img = val
      

     
class FirstParty(object):
    def __init__(self, fp_domain, parent_census):
        self.domain = fp_domain
        self.census = parent_census
        self._third_parties = None
        
    @property
    def third_parties(self):
        if not self._third_parties:
            self._third_parties = dict()
            results = self.census.get_all_third_party_responses_by_site(self.domain)
            for url in results:
                tp_domain = results[url]['url_domain']
                if tp_domain not in self._third_parties:
                    self._third_parties[tp_domain] = EmbeddedThirdParty(tp_domain, self, self.census)
                self._third_parties[tp_domain].URIs.append(URL(url,
                                                               tp_domain,
                                                               results[url]['is_js'],
                                                               results[url]['is_img'],
                                                               results[url]['is_tracker'],
                                                               self))
        return self._third_parties
    
    def __repr__(self):
        return "< FirstParty containing results for url: " + self.domain + " >"
                             
class ThirdParty(object):
    def __init__(self, domain, parent_census):
        self.domain = domain
        self.census = parent_census
        self._organization = None
        self._first_parties = None
        
    @property
    def first_parties(self):
        if not self._first_parties:
            self._first_parties = dict()
            results = self.census.get_sites_with_third_party_domain(self.domain)
            for fp_url in results:
                fp_domain = fp_url[7:]
                self._first_parties[fp_domain] = self.census.first_parties[fp_domain]
                
        return self._first_parties
    
    @property
    def organization(self):
        if not self._organization:
            try:
                self._organization = Organization(self.domain)
            except CensusException:
                self._organization = None
        return self._organization
    
    @organization.setter
    def organization(self, val):
        self._organization = val

class EmbeddedThirdParty(ThirdParty):
    def __init__(self, tp_domain, first_party, parent_census):
        ThirdParty.__init__(self, tp_domain, parent_census)
        self.URIs = []
        self.first_party = first_party
        
class Organization(object):
    def __init__(self, domain):
        self.details = utils.get_full_organization_details(domain)
        if not self.details:
            raise CensusException("No organization found for : " + domain)
        self.name = self.details['organization']
        self.notes = self.details['notes']
        self.domains = self.details['domains']
        self.subsidiaries = self.details['subsidiaries']

class FirstPartyDict(collections.MutableMapping):
    def __init__(self, parent_census, *args):
        self.store = dict()
        self.census = parent_census
        self._site_list = self.census.get_sites_in_census()
        
    def __getitem__(self, key):
        if 'http:' in key or 'https:' in key:
            raise CensusException("Exclude scheme (http://|https://) when checking for first party")
        if key not in self._site_list:
            raise CensusException(key + " not in this census dataset")
        try:
            val = self.store[key]
        except KeyError:
            val = FirstParty(key, self.census)
            self.store[key] = val
        
        return val
    
    def __setitem__(self, key, value):
        self.store[self.__keytransform__(key)] = value

    def __delitem__(self, key):
        del self.store[self.__keytransform__(key)]

    def __iter__(self):
        return iter(self._site_list)

    def __contains__(self, key):
        return key in self._site_list
    
    def __len__(self):
        return len(self._site_list)

    def __keytransform__(self, key):
        return key
    
    def __repr__(self):
        return "< FirstParties on census '" + self.census.census_name + "', indexed by site url >"
    
class ThirdPartyDict(dict):
    def __init__(self, parent_census, *args):
        dict.__init__(self, args)
        self.census = parent_census
        
    def __getitem__(self, key):
        if 'http:' in key or 'https:' in key:
            raise CensusException("Only specify domain when checking for third party ('example.com')")
        try:
            val = dict.__getitem__(self, key)
        except KeyError:
            val = ThirdParty(key, self.census)
            dict.__setitem__(self, key, val)
        return val


class Census:
    """A class representing one census crawl.
    """
    
    def __init__(self, census_name):
        user = 'openwpm'
        password = 'Pwcpdtwca!'
        host = 'princeton-web-census-machine-1.cp85stjatkdd.us-east-1.rds.amazonaws.com' 
        db_details = 'dbname={0} user={1} password={2} host={3}'.format(census_name, user, password, host)
        self.census_name = census_name
        self.connection = psycopg2.connect(db_details)
        self.first_parties = FirstPartyDict(parent_census=self)
        self.third_parties = ThirdPartyDict(parent_census=self)
        
    def _filter_site_list(self, sites, raise_exception=False):
        """Return a list of sites, filtered to remove sites that are not present in the dataset.
        
        If raise_exception, raise an exception if any of the given sites were not found in dataset.
        Else, just print the list of sites excluded.
        """
        present_sites = []
        missing_sites = []
        for site in sites:
            if self.check_top_url(site):
                present_sites.append(site)
            else:
                missing_sites.append(site)
        
        if len(missing_sites) > 0:
            print('Following sites not found in dataset: ' + str(missing_sites))
            print('NOTE: all sites in census are indexed by http://[domain_name].[tld]')
        
            if raise_exception:
                raise CensusException("Sites were included that are not present in the dataset.")
        
        return present_sites
    
    def get_sites_in_census(self):
        """Return a list of top_urls in census."""
        query = "SELECT top_url FROM site_visits"
        
        cur = self.connection.cursor()
        cur.itersize = 100000
        cur.execute(query)
        
        sites = []
        for top_url, in cur:
            sites.append(top_url[7:])
        return sites
    
    def check_top_url(self, top_url):
        """Return True if a top_url is present in the census."""
        top_url = 'http://' + top_url
        check_query = "SELECT exists (SELECT * FROM site_visits WHERE top_url = %s LIMIT 1)"

        cur = self.connection.cursor()
        cur.itersize = 1

        cur.execute(check_query, (top_url,))

        for exists, in cur:
            return exists

        return False

    def get_sites_with_third_party_domain(self, tp_domain):
        """Return a dictionary mapping top_url -> list(tp_urls_from_tp_domain)"""
        tp_query = "SELECT top_url, url from response_domains " \
                   "WHERE public_suffix = %s"
        cur = self.connection.cursor('tp-cursor')
        cur.itersize = 100000

        cur.execute(tp_query, (tp_domain,))

        sites_with_tp = defaultdict(list)
        for top_url, url in cur:
            if utils.should_ignore(url):
                continue

            sites_with_tp[top_url].append(url)
        cur.close()
        return dict(sites_with_tp)

    def get_all_third_party_responses_by_site(self, top_url):
        """Return a dictionary containing third party data loaded on given top_url."""
        top_url = 'http://' + top_url
        tp_query = "SELECT r.url, h.value FROM http_responses_view AS r " \
                   "LEFT JOIN http_response_headers_view as h ON h.response_id = r.id " \
                   " WHERE r.top_url LIKE %s AND " \
                   "url not LIKE %s and h.name = 'Content-Type'"
        cur = self.connection.cursor()
        cur.itersize = 100000
        try:
            top_ps = utils.get_domain(top_url)
        except AttributeError:
            print("Error while finding public suffix of %s" % top_url)
            return None

        cur.execute(tp_query, (top_url, top_ps))

        response_data = defaultdict(dict)
        for url, content_type in cur:
            if utils.should_ignore(url):
                continue

            url_data = dict()

            url_ps = utils.get_domain(url)
            if url_ps == top_ps:
                continue
            url_data['url_domain'] = url_ps

            is_js = utils.is_js(url, content_type)
            is_img = utils.is_img(url, content_type)
            is_el_tracker = utils.is_tracker(url, 
                                             is_js=is_js,
                                             is_img=is_img, 
                                             first_party=top_url, 
                                             blocklist='easylist')
            is_ep_tracker = utils.is_tracker(url, 
                                             is_js=is_js,
                                             is_img=is_img, 
                                             first_party=top_url, 
                                             blocklist='easyprivacy')
            is_tracker = is_el_tracker or is_ep_tracker

            organization = utils.get_org(url)
            
            url_data['is_js'] = is_js
            url_data['is_img'] = is_img
            url_data['is_tracker'] = is_tracker
            url_data['organization_name'] = organization
            
            response_data[url] = url_data

        return dict(response_data)

    def get_third_party_organizations_by_site(self, top_url):
        """Get a list of third-party organizations found on a particular site (top_url)."""
        results = self.get_all_third_party_responses_by_site(top_url)
        third_party_orgs = [results[x]['organization_name'] for x in results
                            if results[x]['organization_name']]
        return third_party_orgs
    
    def graph_third_party_organizations_found_on_sites(self, sites, top_n=10):
        """Graph the frequency of particular third-party organizations on a given list of sites.
        
        Limit graphed output to top_n most frequent third parties
        """
        sites = self._filter_site_list(sites)
        orgs_count = Counter()
        for site in sites:
            orgs = self.get_third_party_organizations_by_site(site)
            orgs_count.update(orgs)
        plt.figure(figsize=(30,10))
        plt.bar(np.arange(top_n), [x[1] for x in orgs_count.most_common(top_n)])
        plt.xticks(np.arange(top_n), [x[0] for x in orgs_count.most_common(top_n)])
        plt.tick_params(axis='both', which='major', labelsize=22)
            
    def get_third_party_resources_for_multiple_sites(self, sites, filepath=''):
        """Get third party data loaded on multiple sites and write results to disk.
        """
        sites = self._filter_site_list(sites)
        tracker_js_by_top = defaultdict(set)
        tracker_img_by_top = defaultdict(set)
        non_tracker_js_by_top = defaultdict(set)
        non_tracker_img_by_top = defaultdict(set)

        tracker_other_by_top = defaultdict(set)
        non_tracker_other_by_top = defaultdict(set)
        for site in sites:
            tp_data = self.get_all_third_party_responses_by_site(site)
            for url in tp_data:
                url_ps = tp_data[url]['url_domain']
                is_tracker = tp_data[url]['is_tracker']
                if is_tracker:
                    if tp_data[url]['is_js']:
                        tracker_js_by_top[site].add(url_ps)
                    elif tp_data[url]['is_img']:
                        tracker_img_by_top[site].add(url_ps)
                    else:
                        tracker_other_by_top[site].add(url_ps)
                else:
                    if tp_data[url]['is_js']:
                        non_tracker_js_by_top[site].add(url_ps)
                    elif tp_data[url]['is_img']:
                        non_tracker_img_by_top[site].add(url_ps)           
                    else:
                        non_tracker_other_by_top[site].add(url_ps)
        
        # Save data to CSV's
        with open(os.path.join(filepath, 'tracker_js_by_site.csv'), 'w') as f:
            writer = csv.writer(f)
            writer.writerow(['site', 'tp_domain'])
            for top in tracker_js_by_top:
                for tp in tracker_js_by_top[top]:
                    writer.writerow([top, tp])
        with open(os.path.join(filepath, 'non_tracker_js_by_site.csv'), 'w') as f:
            writer = csv.writer(f)
            writer.writerow(['site', 'tp_domain'])
            for top in non_tracker_js_by_top:
                for tp in non_tracker_js_by_top[top]:
                    writer.writerow([top, tp])
        with open(os.path.join(filepath, 'tracker_img_by_site.csv'), 'w') as f:
            writer = csv.writer(f)
            writer.writerow(['site', 'tp_domain'])
            for top in tracker_img_by_top:
                for tp in tracker_img_by_top[top]:
                    writer.writerow([top, tp])
        with open(os.path.join(filepath, 'non_tracker_img_by_site.csv'), 'w') as f:
            writer = csv.writer(f)
            writer.writerow(['site', 'tp_domain'])
            for top in non_tracker_img_by_top:
                for tp in non_tracker_img_by_top[top]:
                    writer.writerow([top, tp])
        with open(os.path.join(filepath, 'tracker_other_by_site.csv'), 'w') as f:
            writer = csv.writer(f)
            writer.writerow(['site', 'tp_domain'])
            for top in tracker_other_by_top:
                for tp in tracker_other_by_top[top]:
                    writer.writerow([top, tp])
        with open(os.path.join(filepath, 'non_tracker_other_by_site.csv'), 'w') as f:
            writer = csv.writer(f)
            writer.writerow(['site', 'tp_domain'])
            for top in non_tracker_other_by_top:
                for tp in non_tracker_other_by_top[top]:
                    writer.writerow([top, tp])
                    
        print("Query results written to filesystem.")
        return
    
    def get_all_third_party_trackers_by_site(self, top_url):
        """Return a list of third party resources found on a top_url that are trackers.
        """
        results = self.get_all_third_party_responses_by_site(top_url)
        third_party_trackers = [x for x in results if 
                                        results[x]['is_tracker']]
        return third_party_trackers
    
    def get_all_third_party_scripts_by_site(self, top_url):
        """Return a list of third party resources on a top_url that are scripts."""
        results = self.get_all_third_party_responses_by_site(top_url)
        third_party_scripts = [x for x in results if results[x]['is_js']]
        
        return third_party_scripts
    
    def get_cookie_syncs_by_site(self, top_url, cookie_length=8):
        """Get all 'cookie sync' events on a given top_url.

        Cookies must be at least cookie_length characters long to be considered.

        Returns a dict mapping receiving urls to the domain sending the cookie, 
        and the value of the cookie being shared

        Note: This method does not isolate 'identifying cookies', it identifies
        all cookies that are shared from one domain to a URL not in that domain
        that are >= cookie_length.
        """
        top_url = 'http://' + top_url
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
                cookie_ps = utils.get_domain(cookie_url)
            except AttributeError:
                print("Error while finding public suffix of %s" % cookie_ps)
                continue

            for url, referrer, location in rows:
                try:
                    url_ps = utils.get_domain(url)
                except AttributeError:
                    print("Error while finding public suffix of %s" % url)
                    continue                
                if url_ps == cookie_ps:
                    continue

                if referrer and (value in referrer):
                    receiving_url = url
                    sending_url = utils.get_domain(referrer)
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
    
    def get_cookie_syncs_for_multiple_sites(self, sites, cookie_length=8, filepath=''):
        """Get cookie syncing data for multiple sites, and write results to disk.
        
        Cookies must be at least cookie_length characters long to be considered.
        """
        sites = self._filter_site_list(sites)
        cookie_sync_data = defaultdict(defaultdict)
        for site in sites:
            cookie_sync_data[site] = self.get_cookie_syncs_by_site(site, cookie_length=cookie_length)
            
        # Write complete output as csv
        with open(os.path.join(filepath, 'full_cookie_syncs.csv'), 'w') as f:
            writer = csv.writer(f)
            writer.writerow(['site', 'sending_domain', 'receiving_url', 'cookie_value'])
            for site in cookie_sync_data:
                for receiving_url in cookie_sync_data[site]:
                    for sending_url, cookie_value in cookie_sync_data[site][receiving_url]:
                        writer.writerow([site, sending_url, receiving_url, cookie_value])

        # Write partial output as CSV, only identifying sending domain and receiving domain
        # (rather than the full receiving URL)

        cooks_just_domains = defaultdict(defaultdict)
        for site in cookie_sync_data:
            cooks_just_domains[site] = defaultdict(set)
            for receiving_url in cookie_sync_data[site]:
                for sending_domain, value in cookie_sync_data[site][receiving_url]:
                    cooks_just_domains[site][utils.get_domain(receiving_url)].add(sending_domain)
        with open(os.path.join(filepath, 'condensed_cookie_syncs.csv'), 'w') as f:
            writer = csv.writer(f)
            writer.writerow(['site', 'sending_domain', 'receiving_domain'])
            for site in cooks_just_domains:
                for receiving_domain in cooks_just_domains[site]:
                    if len(cooks_just_domains[site][receiving_domain]) > 1 and 'NOT_FOUND' in cooks_just_domains[site][receiving_domain]:
                        cooks_just_domains[site][receiving_domain].discard('NOT_FOUND')
                    for sending_domain in cooks_just_domains[site][receiving_domain]:
                        writer.writerow([site, sending_domain, receiving_domain])

    def _old_get_cookie_syncs_on_domain(self, top_url):
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
                url_ps = utils.get_domain(url)
            except AttributeError:
                print("Error while finding public suffix of %s" % url)
                continue

            try:
                location_ps = utils.get_domain(location)
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
        top_url = 'http://' + top_url
        print("Grabbing scripts with %s" % symbol)
        urls = set()

        cur = self.connection.cursor()
        cur.execute("select top_url, script_url from javascript_view where symbol = %s and top_url = %s",(symbol, top_url))
        for top_url, script_url in cur:
            urls.add(script_url)

        return urls