import re
from collections import defaultdict

class SingleRuleParser:

    BINARY_OPTIONS = [
        "script",
        "image",
        "stylesheet",
        "object",
        "xmlhttprequest",
        "object-subrequest",
        "subdocument",
        "document",
        "elemhide",
        "other",
        "background",
        "xbl",
        "ping",
        "dtd",
        "media",
        "third-party",
        "match-case",
        "collapse",
        "donottrack",
    ]
    OPTIONS_SPLIT_PAT = ',(?=~?(?:%s))' % ('|'.join(BINARY_OPTIONS + ["domain"]))
    OPTIONS_SPLIT_RE = re.compile(OPTIONS_SPLIT_PAT)

    def __init__(self, rule_text):
        self.raw_rule_text = rule_text
        self.regex_re = None

        rule_text = rule_text.strip()
        self.is_comment = rule_text.startswith(('!', '[Adblock'))
        if self.is_comment:
            self.is_html_rule = self.is_exception = False
        else:
            self.is_html_rule = '##' in rule_text or '#@#' in rule_text  # or rule_text.startswith('#')
            self.is_exception = rule_text.startswith('@@')
            if self.is_exception:
                rule_text = rule_text[2:]

        if not self.is_comment and '$' in rule_text:
            rule_text, options_text = rule_text.split('$', 1)
            self.raw_options = self._split_options(options_text)
            self.options = dict(self._parse_option(opt) for opt in self.raw_options)
        else:
            self.raw_options = []
            self.options = {}
        self._options_keys = frozenset(self.options.keys()) - set(['match-case'])

        self.rule_text = rule_text

        if self.is_comment or self.is_html_rule:
            # TODO: add support for HTML rules.
            # We should split the rule into URL and HTML parts,
            # convert URL part to a regex and parse the HTML part.
            self.regex = ''
        elif not rule_text:
            self.is_comment = True
            self.regex = ''
        else:
            self.regex = self.rule_to_regex(rule_text)

    def match_url(self, url, options=None):
        options = options or {}
        for optname in self.options:
            if optname == 'match-case':  # TODO
                continue

            if optname not in options:
                raise ValueError("Rule requires option %s" % optname)

            if optname == 'domain':
                if not self._domain_matches(options['domain']):
                    return False
                continue

            if options[optname] != self.options[optname]:
                return False

        return self._url_matches(url)

    def _domain_matches(self, domain):
        domain_rules = self.options['domain']
        for domain in _domain_variants(domain):
            if domain in domain_rules:
                return domain_rules[domain]
        return not any(domain_rules.values())

    def _url_matches(self, url):
        if self.regex_re is None:
            self.regex_re = re.compile(self.regex)
        return bool(self.regex_re.search(url))

    def matching_supported(self, options=None):
        if self.is_comment:
            return False

        if self.is_html_rule:  # HTML rules are not supported yet
            return False

        options = options or {}
        keys = set(options.keys())
        if not keys.issuperset(self._options_keys):
            # some of the required options are not given
            return False

        return True

    def get_html_rule(self):
        return self.is_html_rule

    def get_comment(self):
        return self.is_comment

    def get_keys(self):
        return self._options_keys

    @classmethod
    def _split_options(cls, options_text):
        return cls.OPTIONS_SPLIT_RE.split(options_text)

    @classmethod
    def _parse_domain_option(cls, text):
        domains = text[len('domain='):]
        parts = domains.replace(',', '|').split('|')
        return dict(cls._parse_option_negation(p) for p in parts)

    @classmethod
    def _parse_option_negation(cls, text):
        return (text.lstrip('~'), not text.startswith('~'))

    @classmethod
    def _parse_option(cls, text):
        if text.startswith("domain="):
            return ("domain", cls._parse_domain_option(text))
        return cls._parse_option_negation(text)

    @classmethod
    def rule_to_regex(cls, rule):
        if not rule:
            raise ValueError("Invalid rule")
            # return rule

        # escape special regex characters
        rule = re.sub(r"([.$+?{}()\[\]\\])", r"\\\1", rule)

        rule = rule.replace("^", "(?:[^\w\d_\-.%]|$)")
        rule = rule.replace("*", ".*")
        if rule[-1] == '|':
            rule = rule[:-1] + '$'

        if rule[:2] == '||':
            # XXX: it is better to use urlparse for such things,
            # but urlparse doesn't give us a single regex.
            # Regex is based on http://tools.ietf.org/html/rfc3986#appendix-B
            if len(rule) > 2:
                #          |            | complete part     |
                #          |  scheme    | of the domain     |
                rule = r"^(?:[^:/?#]+:)?(?://(?:[^/?#]*\.)?)?" + rule[2:]

        elif rule[0] == '|':
            rule = '^' + rule[1:]

        rule = re.sub("(\|)[^$]", r"\|", rule)
        return rule

    def get_rule(self):
        return self.raw_rule_text

class Parser:

    def __init__(self, rules, rule_cls=SingleRuleParser):

        self.supported_options = rule_cls.BINARY_OPTIONS + ['domain']
        self.rule_cls = rule_cls
        self.rules = []
        for r in rules:
            self.rules.append(rule_cls(r))

        advanced_rules, basic_rules = split_data(self.rules, lambda r: r.options)

        # TODO: what about ~rules? Should we match them earlier?
        domain_required_rules, non_domain_rules = split_data(
            advanced_rules,
            lambda r: (
                'domain' in r.options
                and any(r.options["domain"].values())
            )
        )

        # split rules into blacklists and whitelists
        self.blacklist, self.whitelist = self._split_bw(basic_rules)
        self.blacklist_with_options, self.whitelist_with_options = self._split_bw(non_domain_rules)
        self.blacklist_require_domain, self.whitelist_require_domain = self._split_bw_domain(domain_required_rules)

    def check(self, url, options=None):
        options = options or {}
        if self.is_whitelisted(url, options):
            return 1
        if self.is_blacklisted(url, options):
            return -1
        return 0

    def check_with_items(self, url, options=None):
        options = options or {}
        if self.is_whitelisted(url, options):
            return 1, []
        blacklisted, items = self.is_blacklisted_with_items(url, options)
        if blacklisted:
            return -1, items
        return 0, []

    def is_whitelisted(self, url, options=None):
        return self._matches(url, options, self.whitelist, self.whitelist_require_domain, self.whitelist_with_options)

    def is_blacklisted(self, url, options=None):
        return self._matches(url, options, self.blacklist, self.blacklist_require_domain, self.blacklist_with_options)

    def is_blacklisted_with_items(self, url, options=None):
        return self._matches_with_items(url, options, self.blacklist, self.blacklist_require_domain, self.blacklist_with_options)

    def _matches(self, url, options, general_rules, domain_required_rules, rules_with_options):
        rules = general_rules + rules_with_options
        if options and 'domain' in options and domain_required_rules:
            src_domain = options['domain']
            for domain in _domain_variants(src_domain):
                if domain in domain_required_rules:
                    rules.extend(domain_required_rules[domain])
        rules = [rule for rule in rules if rule.matching_supported(options)]
        return any(rule.match_url(url, options) for rule in rules)

    def _matches_with_items(self, url, options, general_rules, domain_required_rules, rules_with_options):
        rules = general_rules + rules_with_options
        if options and 'domain' in options and domain_required_rules:
            src_domain = options['domain']
            for domain in _domain_variants(src_domain):
                if domain in domain_required_rules:
                    rules.extend(domain_required_rules[domain])
        rules = [rule for rule in rules if rule.matching_supported(options)]
        matches = False
        items = []
        for rule in rules:
            if rule.match_url(url, options):
                matches = True
                items.append(rule.get_rule())
        return matches, items

    @classmethod
    def _split_bw(cls, rules):
        return split_data(rules, lambda r: not r.is_exception)

    @classmethod
    def _split_bw_domain(cls, rules):
        blacklist, whitelist = cls._split_bw(rules)
        return cls._domain_index(blacklist), cls._domain_index(whitelist)

    @classmethod
    def _domain_index(cls, rules):
        result = defaultdict(list)
        for rule in rules:
            domains = rule.options.get('domain', {})
            for domain, required in domains.items():
                if required:
                    result[domain].append(rule)
        return dict(result)

    def print_rules(self):
        for rule in self.blacklist:
            print "1:", rule.get_rule()
        for rule in self.whitelist:
            print "2:",rule.get_rule()
        for domain in self.blacklist_require_domain:
            for rule in self.blacklist_require_domain[domain]:
                print "3:", domain, ":", rule.get_rule()
        for domain in self.whitelist_require_domain:
            for rule in self.whitelist_require_domain[domain]:
                print "4:", domain, ":", rule.get_rule()
        for rule in self.blacklist_with_options:
            print "5:", rule.get_rule()
        for rule in self.whitelist_with_options:
            print "6:", rule.get_rule()


def _domain_variants(domain):
    """
    >>> list(_domain_variants("foo.bar.example.com"))
    ['foo.bar.example.com', 'bar.example.com', 'example.com']
    >>> list(_domain_variants("example.com"))
    ['example.com']
    """
    parts = domain.split('.')
    for i in range(len(parts), 1, -1):
        yield ".".join(parts[-i:])


def split_data(iterable, pred):
    """
    Split data from ``iterable`` into two lists.
    Each element is passed to function ``pred``; elements
    for which ``pred`` returns True are put into ``yes`` list,
    other elements are put into ``no`` list.

    >>> split_data(["foo", "Bar", "Spam", "egg"], lambda t: t.istitle())
    (['Bar', 'Spam'], ['foo', 'egg'])
    """
    yes, no = [], []
    for d in iterable:
        if pred(d):
            yes.append(d)
        else:
            no.append(d)
    return yes, no
