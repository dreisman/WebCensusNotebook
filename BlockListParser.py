import re
from FastHash import FastHash
from RegexParser import Parser

class BlockListParser:
    """Creates maps of shortcut hashes with regex of the urls"""

    def __init__(self, regex_file=None, regexes=None, shortcut_sizes=None, print_maps=False, support_hash=False):
        """Initializes the shortcut to Parser map"""
        if regex_file is None:
            regex_lines = regexes
        else:
            with open(regex_file) as f:
                regex_lines = f.readlines()
        self.regex_lines = regex_lines
        self.fast_hashes = []
        self.print_maps = print_maps
        self.support_hash = support_hash
        if shortcut_sizes:
            self.shortcut_sizes = shortcut_sizes
        else:
            self.shortcut_sizes = self._determine_shortcut_sizes(len(regex_lines))
        for shortcut_size in self.shortcut_sizes:
            self.fast_hashes.append(FastHash(shortcut_size))
        all_shortcut_url_maps, remaining_lines = self._get_all_shortcut_url_maps(regex_lines)
        self.all_shortcut_parser_maps = self._get_all_shortcut_parser_maps(all_shortcut_url_maps)
        self.remaining_regex = self._convert_to_regex(remaining_lines)

    def get_num_classes(self):
        # always supports only binary classification, blocked or not blocked
        return 2

    def get_classes_description(self):
        return ['Not Blocked', 'Blocked']

    def should_block(self, url, options=None):
        """Check if url is in the patterns"""
        if self.support_hash:
            return self._should_block_with_hash()
        blacklisted = False
        for k in xrange(len(self.shortcut_sizes)):
            shortcut_size = self.shortcut_sizes[k]
            regex_map = self.all_shortcut_parser_maps[k]
            for i in xrange(len(url) - shortcut_size + 1):
                cur_sub = url[i:i+shortcut_size]
                if cur_sub in regex_map:
                    parser = regex_map[cur_sub]
                    if blacklisted:
                        if parser.is_whitelisted(url, options):
                            return False
                    else:
                        state = parser.check(url, options)
                        if state == 1:
                            return False
                        elif state == -1:
                            blacklisted = True
        if blacklisted:
            if self.remaining_regex.is_whitelisted(url, options):
                return False
        else:
            state = self.remaining_regex.check(url, options)
            if state == 1:
                return False
            elif state == -1:
                blacklisted = True
        return blacklisted

    def should_block_and_print(self, url, options=None):
        """Check if url is in the patterns"""
        if self.support_hash:
            return self._should_block_with_hash()
        blacklisted = False
        for k in xrange(len(self.shortcut_sizes)):
            shortcut_size = self.shortcut_sizes[k]
            regex_map = self.all_shortcut_parser_maps[k]
            for i in xrange(len(url) - shortcut_size + 1):
                cur_sub = url[i:i+shortcut_size]
                cur_sub = cur_sub.lower()
                if cur_sub in regex_map:
                    parser = regex_map[cur_sub]
                    print("short: " + cur_sub)
                    if blacklisted:
                        if parser.is_whitelisted(url, options):
                            print("Whitelisted by---------")
                            parser.print_rules()
                            return False
                    else:
                        state = parser.check(url, options)
                        if state == 1:
                            print("Whitelisted by---------")
                            parser.print_rules()
                            return False
                        elif state == -1:
                            print("Blacklisted by---------")
                            parser.print_rules()
                            blacklisted = True
        if blacklisted:
            if self.remaining_regex.is_whitelisted(url, options):
                print("Whitelisted by---------")
                parser.print_rules()
                return False
        else:
            state = self.remaining_regex.check(url, options)
            if state == 1:
                print("Whitelisted by---------")
                parser.print_rules()
                return False
            elif state == -1:
                print("Blacklisted by---------")
                parser.print_rules()
                blacklisted = True
        return blacklisted

    def should_block_with_items(self, url, options=None):
        blacklisting_items = []
        blacklisted = False
        for k in xrange(len(self.shortcut_sizes)):
            shortcut_size = self.shortcut_sizes[k]
            regex_map = self.all_shortcut_parser_maps[k]
            for i in xrange(len(url) - shortcut_size + 1):
                cur_sub = url[i:i+shortcut_size]
                if cur_sub in regex_map:
                    parser = regex_map[cur_sub]
                    state, items = parser.check_with_items(url, options)
                    if state == 1:
                        return False, []
                    elif state == -1:
                        blacklisting_items += items
                        blacklisted = True
        state, items = self.remaining_regex.check_with_items(url, options)
        if state == 1:
            return False, []
        elif state == -1:
            blacklisting_items += items
            blacklisted = True
        return blacklisted, blacklisting_items

    def get_block_class(self, url, options=None):
        if self.should_block(url, options):
            return 1
        else:
            return 0

    def get_block_class_with_items(self, url, options=None):
        block, items = self.should_block_with_items(url, options)
        if block:
            return 1, items
        else:
            return 0, items

    @staticmethod
    def get_all_items(regex_file):
        with open(regex_file) as f:
            regex_lines = f.readlines()
        return regex_lines

    def _determine_shortcut_sizes(self, num_regex_lines):
        """Empirically the following returns the best value"""
        return [14, 10, 6, 4]

    def _convert_to_regex(self, lines):
        return Parser(lines)

    def _should_block_with_hash(self, url, options):
        blacklisted = False
        for k in xrange(len(self.shortcut_sizes)):
            fast_hash = self.fast_hashes[k]
            shortcut_size = self.shortcut_sizes[k]
            regex_map = self.all_shortcut_parser_maps[k]
            prev_hash = -1
            for i in xrange(len(url) - shortcut_size + 1):
                cur_hash = fast_hash.extend_hash(url, i, prev_hash)
                if cur_hash in regex_map:
                    parser = regex_map[cur_hash]
                    if blacklisted:
                        if parser.is_whitelisted(url, options):
                            return False
                    else:
                        state = parser.check(url, options)
                        if state == 1:
                            return False
                        elif state == -1:
                            blacklisted = True
                prev_hash = cur_hash
        if blacklisted:
            if self.remaining_regex.is_whitelisted(url, options):
                return False
        else:
            state = self.remaining_regex.check(url, options)
            if state == 1:
                return False
            elif state == -1:
                blacklisted = True
        return blacklisted

    def _print_num_map(self, shortcut_url_map):
        num_shortcuts = {}
        num_shortcuts_stored = {}
        for shortcut in shortcut_url_map:
            num = len(shortcut_url_map[shortcut])
            if num in num_shortcuts:
                num_shortcuts[num] += 1
                num_shortcuts_stored[num].append(shortcut)
            else:
                num_shortcuts[num] = 1
                num_shortcuts_stored[num] = [shortcut]
        print(num_shortcuts)

    def _print_statistics_of_map(self, shortcut_size, total_rules, total_comments,
                                 total_shortcuts, total_secondary_lines, shortcut_url_map):
        print("**********     Shortcut size is %d     **********" % shortcut_size)
        print("Number of rules = ", total_rules, ", comments = ", total_comments)
        print("Shortcuts found for ", total_shortcuts, " rules")
        print("Shortcuts not found for ", total_secondary_lines, " rules")
        print("Number map is")
        self._print_num_map(shortcut_url_map)
        print("")

    def _get_shortcut_url_map(self, pat, lines, shortcut_size):
        shortcut_url_map = {}
        secondary_lines = []
        total_rules = 0
        total_comments = 0
        total_shortcuts = 0
        for line in lines:
            line.strip()
            if line[0] == '!':
                total_comments += 1
                continue
            total_rules += 1
            url = re.split(r'\$+', line)[0]
            searches = pat.findall(url)
            flag = 0
            if searches:
                total_shortcuts += 1
            else:
                secondary_lines.append(line)
                continue
            min_count = -1
            for s in searches:
                s = s.lower()
                for i in xrange(len(s) - shortcut_size+1):
                    cur_s = s[i:i+shortcut_size]
                    if cur_s not in shortcut_url_map:
                        shortcut_url_map[cur_s] = [line]
                        flag = 1
                        break
                    if min_count == -1 or len(shortcut_url_map[cur_s]) < min_count:
                        min_count = len(shortcut_url_map[cur_s])
                        min_s = cur_s
                if flag == 1:
                    break
            if flag == 0:
                shortcut_url_map[min_s].append(line)
        if self.print_maps:
            self._print_statistics_of_map(shortcut_size, total_rules, total_comments,
                                          total_shortcuts, len(secondary_lines), shortcut_url_map)
        return shortcut_url_map, secondary_lines

    def _get_all_shortcut_url_maps(self, lines):
        all_shortcut_url_maps = []
        for shortcut_size in self.shortcut_sizes:
            pat = re.compile(r'[\w\/\=\.\-\?\;\,\&]{%d,}' % shortcut_size)
            shortcut_url_map, lines = self._get_shortcut_url_map(pat, lines, shortcut_size)
            all_shortcut_url_maps.append(shortcut_url_map)
        return all_shortcut_url_maps, lines

    def _get_shortcut_parser_map(self, fast_hash, shortcut_url_map):
        shortcut_parser_map = {}
        if self.support_hash:
            for shortcut in shortcut_url_map:
                hash_value = fast_hash.compute_hash(shortcut)
                if hash_value in shortcut_parser_map:
                    shortcut_parser_map[hash_value].append(shortcut_url_map[shortcut])
                else:
                    shortcut_parser_map[hash_value] = shortcut_url_map[shortcut]
            for hash_key in shortcut_parser_map:
                shortcut_parser_map[hash_key] = self._convert_to_regex(shortcut_parser_map[hash_key])
        else:
            for shortcut in shortcut_url_map:
                shortcut_parser_map[shortcut] = self._convert_to_regex(shortcut_url_map[shortcut])
        return shortcut_parser_map

    def _get_all_shortcut_parser_maps(self, all_shortcut_url_maps):
        all_shortcut_parser_maps = []
        for fast_hash, shortcut_url_map in zip(self.fast_hashes, all_shortcut_url_maps):
            all_shortcut_parser_maps.append(self._get_shortcut_parser_map(fast_hash, shortcut_url_map))
        return all_shortcut_parser_maps
