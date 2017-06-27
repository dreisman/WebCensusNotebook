from BlockListParser import BlockListParser
from collections import Counter, defaultdict
import collections
import csv
import itertools
import matplotlib.pyplot as plt
import numpy as np
import os
import re
import psycopg2
import utils

class CensusException(Exception):
    pass

class Cookie(object):
    """A Cookie object represents all instances of a particular (domain, name) in a crawl.
    
    Available properties:
    - Cookie.domain : The domain owning this cookie
    - Cookie.name : The name of the cookie
    - Cookie.secure : Is the cookie marked 'secure'?
    - Cookie.httponly : Is the cookie an HTTP-only cookie?
    
    """
    def __init__(self, domain, name, instances):
        self._domain = domain
        self._name = name
        self._secure = any([x[1] for x in instances])
        self._httponly = any([x[2] for x in instances])
        self._instances = instances
    
    @property
    def domain(self):
        return self._domain

    @property
    def name(self):
        return self._name
    
    @property
    def secure(self):
        return self._secure
    
    @property
    def sample_value(self):
        return self._instances[0][0]
    
    def __repr__(self):
        return "<Cookie name: " + self._name + ", owned by domain '" + self._domain + "'>"
    
class URI(object):
    """A URI object represents a single instance of a resource embedded on a FirstParty.
    
    A URI object contains:
    - URI.url : The URL of this resource.
    - URI.domain : The domain name of this resource
    - URI.first_party : The FirstParty object where this resource is located.
    - URI.third_party : A ThirdParty object for this resource's third-party domain.
    - URI.is_tracker : A boolean indicating if this resource was identified as a tracker.
    - URI.is_js : A boolean indicating if this resource is javascript.
    - URI.is_img : A boolean indicating if this resource is an image.
    - URI.is_secure : A boolean indicating if this resource was loaded via HTTPS.
    """
    def __init__(self, url, domain, is_js=None, is_img=None, is_tracker=None, first_party=None, parent_census=None):
        self._url = url
        self._domain = domain
        self._is_js = is_js
        self._is_img = is_img
        self._first_party = first_party
        self._is_tracker = is_tracker
        self._is_secure = url[:5] == 'https'
        self.census = parent_census
    
    @property
    def url(self):
        return self._url
    
    @property
    def domain(self):
        return self._domain
    
    @property
    def first_party(self):
        return self._first_party
    
    @property
    def is_secure(self):
        return self._is_secure
    
    @property
    def is_tracker(self):
        if self._is_tracker == None:
            is_el_tracker = utils.is_tracker(self._url, 
                                             is_js=self._is_js,
                                             is_img=self._is_img, 
                                             first_party='http://'+self._first_party._domain, 
                                             blocklist='easylist')
            is_ep_tracker = utils.is_tracker(self._url, 
                                             is_js=self._is_js,
                                             is_img=self._is_img, 
                                             first_party='http://'+self._first_party._domain, 
                                             blocklist='easyprivacy')
            self._is_tracker = is_el_tracker or is_ep_tracker
        return self._is_tracker
    
    @is_tracker.setter
    def is_tracker(self, val):
        self._is_tracker = val
    
    @property
    def is_js(self):
        if self._is_js == None:
            self._is_js = utils.is_js(self._url, content_type)
        return self._is_js
    
    @is_js.setter
    def is_js(self, val):
        self._is_js = val
       
    @property
    def is_img(self):
        if self._is_img == None:
            self._is_img = utils.is_img(self._url, content_type)
        return self._is_img
    
    @is_img.setter
    def is_img(self, val):
        self._is_img = val
      
    @property
    def third_party(self):
        return self.census.third_parties[self._domain]
    
    @property
    def help(self):
        print("Available properties of " + str(type(self)) + ":")
        print([p for p in dir(type(self)) if isinstance(getattr(type(self),p),property)])
    
    def __repr__(self):
        return "<URI located at '" + self.url + "'>"
    
    def __eq__(self, other):
        return other and self._url == other._url

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self._url)
    
class FirstParty(object):
    """A FirstParty object represents a first-party website visited in the census crawl.
    
    Available properties of a FirstParty are:
    - FirstParty.url : The full url visited in the crawl.
    
    - FirstParty.third_party_resources : A list of URIs belonging to third parties that
                                         were loaded on the FirstParty website.
                                 
    - FirstParty.third_parties : A container of ThirdParty objects of the third parties
                                 that were loaded.
                                 
    - FirstParty.alexa_rank : The Alexa rank of the FirstParty, at crawl time                             
    """
    def __init__(self, fp_domain, parent_census):
        self._domain = fp_domain
        self.census = parent_census
        self._third_parties = None
        self._third_party_resources = None
        self._cookie_syncs = None
        self._cookies = None
    
    class ThirdPartiesOnFirstPartyDict(collections.MutableMapping):
        """Container of third parties on a particular FirstParty.
        
        - Iterating through this object returns the ThirdParty object themselves.
        - You can check for membership of a ThirdParty on a FirstParty with:
          'thirdparty.com' in FirstParty.third_parties
        """
        def __init__(self, *args, **kwargs):
            self.store = dict()
            self.update(dict(*args, **kwargs))  # use the free update to set keys

        def __getitem__(self, key):
            return self.store[self.__keytransform__(key)]

        def __setitem__(self, key, value):
            self.store[self.__keytransform__(key)] = value

        def __delitem__(self, key):
            del self.store[self.__keytransform__(key)]

        def __iter__(self):
            return iter(self.store.values())

        def __len__(self):
            return len(self.store)
        
        def __keytransform__(self, key):
            return key
        
        def __repr__(self):
            return list(self.store.values()).__repr__().replace(',', ',\n')
        
    def _grab_third_parties(self):
        self._third_parties = FirstParty.ThirdPartiesOnFirstPartyDict()
        self._third_party_resources = []
        results = self.census.get_all_third_party_responses_by_site(self._domain, lazy=True)
        for url in results:
            tp_domain = results[url]['url_domain']
            self._third_party_resources.append(URI(url,
                                                   tp_domain,
                                                   is_js=results[url]['is_js'],
                                                   is_img=results[url]['is_img'],
                                                   first_party=self,
                                                   parent_census=self.census))
            if tp_domain not in self._third_parties:
                self._third_parties[tp_domain] = self.census.third_parties[tp_domain]
            
    @property
    def third_parties(self):
        if not self._third_parties:
            self._grab_third_parties()
        return self._third_parties
    
    @property
    def domain(self):
        return self._domain
    
    @property
    def url(self):
        return 'http://' + self._domain
    
    @property
    def alexa_rank(self):
        return self.census.first_parties._alexa_ranks[self._domain]
        
    @property
    def third_party_resources(self):
        if self._third_party_resources == None:
            self._grab_third_parties()
        return self._third_party_resources
    
    @property
    def cookies(self):
        if not self._cookies:
            cookies_dict = self.census.get_cookies_by_domain(self._domain)
            cookies = []
            for name in cookies_dict:
                cookies.append(Cookie(self._domain, name, cookies_dict[name]))
        return cookies
    
    @property
    def cookie_syncs(self):
        # TODO(dillon): Add cookie syncing logic to FirstParty
        raise CensusException("Cookie syncing not yet implemented!")

    @property
    def help(self):
        print("Available properties of " + str(type(self)) + ":")
        print([p for p in dir(type(self)) if isinstance(getattr(type(self),p),property)])
        print("(third_party_resources is a list of third-party URIs found on this FirstParty)")
    
    def __repr__(self):
        return "< FirstParty containing results for url: " + self.url + ">"
    
    def __eq__(self, other):
        return other and self._domain == other._domain

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self._domain)
    
class ThirdParty(object):
    """A ThirdParty represents a particular third-party domain seen in the census crawl.
    
    Available properties of a ThirdParty are:
    - ThirdParty.first_parties : A dict of FirstParty objects that this ThirdParty is found on,
                                 indexed by first-party domain.
    
    - ThirdParty.all_resources : A dict of FirstParty objects indexed by the full URL of 
                                 the third-party resource found on the first party.
                                 
    - ThirdParty.domain : The ThirdParty's domain.
    
    - ThirdParty.organization : The Organization owning this ThirdParty (raises exception if
                                no organization identified).           
    """
    def __init__(self, domain, parent_census):
        self._domain = domain
        self.census = parent_census
        self._organization = None
        self._first_parties = None
        self._all_resources = None
        self._prominence = None
        self._cookies = None
        
    @property
    def all_resources(self):
        if not self._all_resources:
            self._all_resources = defaultdict(set)
            results = self.census.get_sites_with_third_party_domain(self._domain)
            for fp_url, url in results:
                fp_domain = fp_url[7:]
                self._all_resources[url].add(self.census.first_parties[fp_domain])
            self._all_resources = dict(self._all_resources)
        return self._all_resources
    
    @property
    def domain(self):
        return self._domain
    
    @property
    def prominence(self):
        if self._prominence == None:
            self._prominence = self.census.third_parties._prominence[self._domain]
        return self._prominence
    
    class FirstPartiesOnThirdPartyDict(collections.MutableMapping):
        """Container of first parties on a particular ThirdParty.
        
        - Iterating through this object returns the FirstParty object themselves.
        - You can check for membership of a FirstParty on a ThirdParty with:
          'first.com' in ThirdParty.first_parties
        """
        def __init__(self, *args, **kwargs):
            self.store = dict()
            self.update(dict(*args, **kwargs))  # use the free update to set keys

        def __getitem__(self, key):
            return self.store[self.__keytransform__(key)]

        def __setitem__(self, key, value):
            self.store[self.__keytransform__(key)] = value

        def __delitem__(self, key):
            del self.store[self.__keytransform__(key)]

        def __iter__(self):
            return iter(self.store.values())

        def __len__(self):
            return len(self.store)
        
        def __keytransform__(self, key):
            return key
        
        def __repr__(self):
            return list(self.store.values()).__repr__().replace(',', ',\n')
    
    @property
    def first_parties(self):
        if not self._first_parties:
            self._first_parties = ThirdParty.FirstPartiesOnThirdPartyDict()
            results = self.census.get_sites_with_third_party_domain(self._domain)
            for fp_url, url in results:
                fp_domain = fp_url[7:]
                self._first_parties[fp_domain] = self.census.first_parties[fp_domain]
                
        return self._first_parties
        
    @property
    def organization(self):
        if not self._organization:
            self._organization = Organization(self._domain)
        return self._organization
    
    @property
    def cookies(self):
        if not self._cookies:
            cookies_dict = self.census.get_cookies_by_domain(self._domain)
            cookies = []
            for name in cookies_dict:
                cookies.append(Cookie(self._domain, name, cookies_dict[name]))
        return cookies
    
    @organization.setter
    def organization(self, val):
        self._organization = val
        
    @property
    def help(self):
        print("Available properties of " + str(type(self)) + ":")
        print([p for p in dir(type(self)) if isinstance(getattr(type(self),p),property)])
        print("(first_parties is a dictionary indexing FirstPartys that have this particular ThirdParty)")
        
    def __repr__(self):
        return "<ThirdParty with domain : '" + self._domain + "'>"
        
class Organization(object):
    """An organization represents one business entity, and contains information about
    domains they control.
    
    Available properties:
    - Organization.name : Name of the organization
    - Organization.notes : Comments about organization
    - Organization.domains : A list of domains the org. controls.
    - Organization.subsidiaries : A list of strings representing owned-subsidiaries
    """
    def __init__(self, domain=None, org_dict=None):
        if org_dict:
            self._details = org_dict
        else:
            self._details = utils.get_full_organization_details(domain)
            
        # If no organization found, provide a dummy organization object for the domain
        if not self._details:
            self._details = dict()
            self._details['organization'] = domain
            self._details['notes'] = "[No known organization found for domain]"
            self._details['domains'] = [domain]
            self._details['subsidiaries'] = []
            
        self._name = self._details['organization']
        self._notes = self._details['notes']
        self._domains = self._details['domains']
        self._subsidiaries = self._details['subsidiaries']

    @property
    def name(self):
        return self._name
    
    @property
    def notes(self):
        return self._notes
    
    @property
    def domains(self):
        return self._domains
    
    @property
    def subsidiaries(self):
        return self._subsidiaries
    
    @property
    def help(self):
        print("Available properties of " + str(type(self)) + ":")
        print([p for p in dir(type(self)) if isinstance(getattr(type(self),p),property)])
    
    def __repr__(self):
        return "<Organization : " + self.name + " >"
    
    def __eq__(self, other):
        return other and self.name == other.name

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.name)
    
class AlexaCategoryDict(collections.MutableMapping):
    """This object indexes all of the available top FirstParties for each Alexa category.
    
    For example:
    cen.first_parties.alexa_cats['news'] -> An ordered list of FirstParty objects
    """
    def __init__(self, parent_census, alexa_cats):
        self.store = dict()
        self.update(dict())  # use the free update to set keys
        self.census = parent_census
        self._alexa_cats = alexa_cats
        for key in self._alexa_cats:
            self.store[self.__keytransform__(key)] = None
        
    def __getitem__(self, key):
        if not self.store[self.__keytransform__(key)]:
            list_of_sites = self._alexa_cats[key]
            self[self.__keytransform__(key)] = []
            for site in list_of_sites:
                if site in self.census.first_parties:
                    self.store[self.__keytransform__(key)].append(self.census.first_parties[site])
            
        return self.store[self.__keytransform__(key)]

    def __setitem__(self, key, value):
        self.store[self.__keytransform__(key)] = value

    def __delitem__(self, key):
        del self.store[self.__keytransform__(key)]

    def __iter__(self):
        return iter(self.store)

    def __len__(self):
        return len(self.store)

    def __keytransform__(self, key):
        return key
    
class FirstPartyDict(collections.MutableMapping):
    """This object indexes all first parties that were visited in the census.
    To access data for the first party 'example.com', try retrieving
    first_parties['example.com']. That will return a FirstParty object.
    
    You can also iterate through the first_parties. For instance:
    cen.first_parties[:50] -> an iterator of the top 50 FirstParties ordered by Alexa rank.
        NOTE: Slicing and indexing only return sites for which the crawler didn't fail.
              Therefore, getting cen.first_parties[N] does not strictly return the Nth most
              popular Alexa site.
    
    Also includes:
    - first_parties.alexa_rankings : A list of FirstParties ordered by Alexa Rank.
         (If a given site failed during the crawl, iterating through this list may
          return an error for that site.
    - first_parties.alexa_categories : A dictionary mapping alexa categories
                                       to a set of the top sites for that category.
                                       
    """
    
    def __init__(self, parent_census):
        self.store = dict()
        self.census = parent_census
        self._all_sites = self.census.get_sites_in_census()
        self._alexa_ranks = self.census.get_alexa_rankings()
        self._site_list = [x[1] for x in self._all_sites if x[2]]
        self._site_set = set(self._site_list)
        self._failed_sites = set(x[1] for x in self._all_sites if not x[2])
        self._alexa_list = None
        alexa_cats = utils.get_alexa_categories()
        self._alexa_cats = dict()
        for cat in alexa_cats:
            self._alexa_cats[cat] = set(fp for fp in alexa_cats[cat]
                                        if fp in self._site_set)
        self._alexa_cats_fps = AlexaCategoryDict(parent_census, self._alexa_cats)

            
    def __getitem__(self, key):
        # If slice, return generator from list of top sites for which we have data
        if isinstance(key, slice):
            return itertools.islice((self[x] for x in self._site_list), key.start, key.stop, key.step)
        
        # If integer, return FirstParty by index order
        if isinstance(key, int):
            return self[self._site_list[key]]

        if 'http:' in key or 'https:' in key:
            raise CensusException("Exclude scheme (http://|https://) when checking for first party")
        if key not in self._site_set and key not in self._failed_sites:
            raise CensusException(key + " not in this census dataset")
        if key in self._failed_sites:
            raise CensusException("Data unavailable for " + key + " due to crawl error")
            
        try:
            val = self.store[self.__keytransform__(key)]
        except KeyError:
            val = FirstParty(key, self.census)
            self.store[self.__keytransform__(key)] = val
        
        return val
    
    def __setitem__(self, key, value):
        self.store[self.__keytransform__(key)] = value

    def __delitem__(self, key):
        del self.store[self.__keytransform__(key)]

    def __iter__(self):
        return iter(self[x] for x in self._site_list)

    def __contains__(self, key):
        return key in self._site_set 
    
    def __len__(self):
        return len(self._site_list)

    def __keytransform__(self, key):
        return key
    
    def __repr__(self):
        return "<FirstParties on census '" + self.census.census_name + "', indexed by site url>"
    
    @property
    def alexa_categories(self):
        """This object indexes all of the available top FirstParties for each Alexa category.

        For example:
        cen.first_parties.alexa_cats['news'] -> An ordered list of FirstParty objects
        """
        return self._alexa_cats_fps
    
    class AlexaRankingList(collections.MutableMapping):
        """FirstParties in crawl ordered strictly by Alexa ranking.
        
        Due to crawl failures, iterating through this list or accessing individual
        members might throw an exception that needs to be handled.
        
        Iterating through this object returns the FirstParty object themselves.
        """
        def __init__(self, parent_census, alexa_list):
            self._census = parent_census
            self._alexa_list = alexa_list
            self.store = dict()

        def __getitem__(self, key):
            # If slice, return generator from list in alexa order
            if isinstance(key, slice):
                return itertools.islice((self._census.first_parties[x[0]] for x in self._alexa_list),
                                        key.start, key.stop, key.step)

            # If integer, return FirstParty by Alexa rank
            if isinstance(key, int):
                return self._census.first_parties[self._alexa_list[key-1][0]]

            raise CensusException("FirstParties in alexa_rankings only accessible via index/slicing")
            
        def __setitem__(self, key, value):
            self.store[self.__keytransform__(key)] = value

        def __delitem__(self, key):
            del self.store[self.__keytransform__(key)]

        def __iter__(self):
            return iter(self._census.first_parties[x] for x in self._alexa_list)

        def __len__(self):
            return len(self._alexa_list)
        
        def __keytransform__(self, key):
            return key
        
        def __repr__(self):
            return "<FirstParties by Alexa Ranking>"
        
    @property
    def alexa_ranking(self):
        """FirstParties in crawl ordered strictly by Alexa ranking.
        
        Due to crawl failures, iterating through this list or accessing individual
        members might throw an exception that needs to be handled.
        
        Iterating through this object returns the FirstParty object themselves.
        """
        if not self._alexa_list:
            sorted_alexa = sorted(list(self._alexa_ranks.items()), key = lambda x : x[1])
            self._alexa_list = FirstPartyDict.AlexaRankingList(self.census, sorted_alexa)

        return self._alexa_list
    
    @property
    def help(self):
        print("This object indexes all first parties that were visited in the census.")
        print("To access data for the first party 'example.com', try retrieving first_parties['example.com'].")
        print("That will return a FirstParty object.")


    
class ThirdPartyDict(collections.MutableMapping):
    """This object indexes all third party domains that were seen in the census
    To access data from the crawl for the third-party domain 'example.com',
    try third_parties['example.com']. That will return a ThirdParty object.
    
    You can also iterate through the third_parties. For instance:
    cen.third_parties[:50] -> an iterator of the top 50 ThirdParties (ordered by prominence).
    """
    def __init__(self, parent_census):
        self.store = dict()
        self.census = parent_census
        self._domain_list = sorted(self.census.get_domains_in_census(), key=lambda x : x[1], reverse=True)
        self._prominence = dict()
        for domain, prom in self._domain_list:
            self._prominence[domain] = prom
        
    def __getitem__(self, key):
        if isinstance(key, slice):
            return itertools.islice((self[x[0]] for x in self._domain_list), key.start, key.stop, key.step)

        # If integer, use as index into list of ThirdParty as ordered by prominence
        if isinstance(key, int):
            return self[self._domain_list[key][0]]
        
        if 'http:' in key or 'https:' in key:
            raise CensusException("Only specify domain when checking for third party ('example.com')")
        if key not in self:
            raise CensusException("Third party not found in this census")
        try:
            val = self.store[self.__keytransform__(key)]
        except KeyError:
            val = ThirdParty(key, self.census)
            self.store[self.__keytransform__(key)] = val
        return val

    def __setitem__(self, key, value):
        self.store[self.__keytransform__(key)] = value

    def __delitem__(self, key):
        del self.store[self.__keytransform__(key)]

    def __iter__(self):
        return (self[x[0]] for x in self._domain_list)

    def __contains__(self, key):
        return key in self._prominence
    
    def __len__(self):
        return len(self._domain_list)

    def __keytransform__(self, key):
        return key
    
    def __repr__(self):
        return "<ThirdParties on census '" + self.census.census_name + "', indexed by third-party domain>"
    
    @property
    def help(self):
        print("This object indexes all third party domains that were seen in the census.")
        print("To access data from the crawl for the third-party domain 'example.com', try third_parties['example.com'].")
        print("That will return a ThirdParty object.")
              
class Census:
    """A class representing one census crawl.
    
    To start accessing data, access one of two properties:
    - Census.first_parties : A dict-like container of first parties visited in the census crawl, indexed by first-party domain.
    - Census.third_parties : A dict-like container of third parties visited in the census crawl, indexed by third-party domain.
    - Census.organizations : A dict of known Organizations, indexed by organization name.
    """
    
    def __init__(self, census_name):
        self._user = 'openwpm'
        self._password = 'Pwcpdtwca!'
        self._host = 'princeton-web-census-machine-1.cp85stjatkdd.us-east-1.rds.amazonaws.com' 
        self._db_details = 'dbname={0} user={1} password={2} host={3}'.format(census_name, self._user, self._password, self._host)
        self.census_name = census_name
        self.connection = psycopg2.connect(self._db_details)
        self.connection.set_session(readonly=True, autocommit=True)
        self.first_parties = FirstPartyDict(parent_census=self)
        self.third_parties = ThirdPartyDict(parent_census=self)
        self.organizations = dict()
        orgs = utils.get_organizations_list()
        for org in orgs:
            self.organizations[org['organization']] = Organization(org_dict=org)
    
    def __del__(self):
        self.connection.close()
    
    @property
    def help(self):
        print("A Census object represents one census crawl.")
        print("Census.third_parties indexes third-party domains seen in this census crawl.")
        print("Census.first_parties indexes first-party sites visited in this census crawl.")
    
    def __repr__(self):
        return "<Census '" + self.census_name + "'. Access first_parties or third_parties properties for more info.>"
        
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
    
    def get_alexa_rankings(self):
        """Retrieve Alexa rankings used in census as a dict mapping urls to rank.
        """
        query = "SELECT rank, top_url FROM alexa_rank"
        
        cur = self.connection.cursor()
        cur.itersize = 100000
        try:
            cur.execute(query)
        except:
            self._reconnect()
            cur = self.connection.cursor()
            cur.itersize = 100000
            cur.execute(query)
            
        rankings = dict()
        for rank, top_url in cur:
            rankings[top_url] = rank
        
        return rankings
    
    def get_sites_in_census(self):
        """Return a list of top_urls in census."""
        query = "SELECT id, top_url, crawl_success FROM site_visits"
        
        cur = self.connection.cursor()
        cur.itersize = 100000
        try:
            cur.execute(query)
        except:
            self._reconnect()
            cur = self.connection.cursor()
            cur.itersize = 100000   
            cur.execute(query)
            
        sites = []
        for vid, top_url, crawl_success in cur:
            sites.append((vid, top_url[7:], crawl_success))
        cur.close()
        return sorted(sites, key=lambda x: x[0])
    
    def get_domains_in_census(self):
        """Return a list of all domains seen in census."""
        query = "SELECT public_suffix, prominence FROM public_suffix_list"""
        
        cur = self.connection.cursor()
        cur.itersize = 100000
        try:
            cur.execute(query)
        except:
            self._reconnect()    
            cur = self.connection.cursor()
            cur.itersize = 100000  
            cur.execute(query)
            
        domains = []
        for public_suffix, prominence in cur:
            domains.append((public_suffix,prominence))
        cur.close()
        return domains
    
    def check_top_url(self, top_url):
        """Return True if a top_url is present in the census."""
        top_url = 'http://' + top_url
        check_query = "SELECT exists (SELECT * FROM site_visits WHERE top_url = %s LIMIT 1)"

        cur = self.connection.cursor()
        cur.itersize = 1
        try:
            cur.execute(check_query, (top_url,))
        except:
            self._reconnect()
            cur = self.connection.cursor()
            cur.itersize = 1
            cur.execute(check_query, (top_url,))
            
        for exists, in cur:
            return exists
        cur.close()
        return False

    def check_third_party_domain(self, domain):
        """Return True if a third-party domain is present in the census."""
        check_query = "SELECT exists (SELECT * FROM public_suffix_list WHERE public_suffix = %s LIMIT 1)"

        cur = self.connection.cursor()
        cur.itersize = 1
        try:
            cur.execute(check_query, (domain,))
        except:
            self._reconnect()
            cur = self.connection.cursor()
            cur.itersize = 1
            cur.execute(check_query, (domain,))
            
        for exists, in cur:
            return exists
        cur.close()
        return False        
    
    def get_sites_with_third_party_domain(self, tp_domain):
        """Return a list of tuples representing first_parties that have a particular embedded third party.
        
        The tuple matches a first_party to the full URL belonging to that third party.
        I.E : get_sites_with_third_party_domain('example.com')
        [('homepage.com', 'http://example.com/a_particular_resource'),
         ('homepage.com', 'http://example.com/a_different_resource')
         ('anotherpage.com', 'http://example.com/a_particular_resource')
        ]
        """

        tp_query = "SELECT response_domains.top_url, response_domains.url " \
                   "FROM response_domains LEFT JOIN public_suffix_list " \
                   "ON response_domains.ps_id = public_suffix_list.id  " \
                   "WHERE public_suffix_list.public_suffix = %s;"
        cur = self.connection.cursor()#'tp-cursor')
        cur.itersize = 100000

        try:
            cur = self.connection.cursor()#'tp-cursor')
            cur.itersize = 100000
            cur.execute(tp_query, (tp_domain,))
        except:
            self._reconnect()
            cur = self.connection.cursor()#'tp-cursor')
            cur.itersize = 100000
            cur.execute(tp_query, (tp_domain,))
            
        sites_with_tp = []
        for top_url, url in cur:
            sites_with_tp.append((top_url, url))
            
        cur.close()
        return sites_with_tp
    
    def get_all_third_party_responses_by_site(self, top_url, lazy=False):
        """Return a dictionary containing third party data loaded on given top_url."""
        top_url = 'http://' + top_url
        tp_query = "SELECT r.url, h.value FROM http_responses_view AS r " \
                   "LEFT JOIN http_response_headers_view as h ON h.response_id = r.id " \
                   " WHERE r.top_url LIKE %s AND " \
                   "url not LIKE %s and h.name = 'Content-Type'"

        try:
            top_ps = utils.get_domain(top_url)
        except AttributeError:
            print("Error while finding public suffix of %s" % top_url)
            return None
        cur = self.connection.cursor()
        cur.itersize = 100000
        try:
            cur.execute(tp_query, (top_url, top_ps))
        except:
            self._reconnect()
            cur = self.connection.cursor()
            cur.itersize = 100000
            cur.execute(tp_query, (top_url, top_ps))

        # If no responses, then clearly this was a crawl failure. Raise exception
        #if cur.rowcount <= 0:
        #    raise CensusException("No responses found: Census crawl failed to ")
        
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
            if not lazy:
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
                url_data['is_tracker'] = is_tracker

            organization = utils.get_org(url)
            
            url_data['is_js'] = is_js
            url_data['is_img'] = is_img
            url_data['organization_name'] = organization
            
            response_data[url] = url_data
        cur.close()
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
    
    def get_cookies_by_domain(self, domain):
        """Return a list of cookies set by this domain.
        
        NOTE: Currently only uses http response cookies. Cookies set by javascript
              not included.
        """
        query = "SELECT name, value, secure, httponly, domain FROM " \
                "http_response_cookies_view WHERE domain_ps = %s"
        
        cur = self.connection.cursor()
        cur.itersize = 100000
        try:
            cur.execute(query, (domain,))
        except:
            self._reconnect()    
            cur = self.connection.cursor()
            cur.itersize = 100000  
            cur.execute(query, (domain,))
            
        cookies = defaultdict(list)
        for name, value, secure, httponly, domain in cur:
            cookies[name].append((value, secure, httponly, domain))
        cur.close()
        return dict(cookies)        
    
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
        cookie_cur.close()
        res_cursor.close()
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
        cur.close()
        cookie_cur.close()
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
        cur.close()
        return urls
    
    def _reconnect(self):
        """If connection to PostGre was lost, reconnect."""
        self.connection = psycopg2.connect(self._db_details)
        self.connection.set_session(readonly=True, autocommit=True)