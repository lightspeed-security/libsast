# -*- coding: utf_8 -*-
"""Choice Macher."""
import os
import sys
from pathlib import Path
from multiprocessing import (
    Pool,
)

from libsast.core_matcher.helpers import (
    get_rules,
    strip_comments,
    strip_comments2,
)
from libsast.core_matcher import choices
from libsast import (
    common,
    exceptions,
)


class ChoiceMatcher:
    def __init__(self, options: dict) -> None:
        self.scan_rules = get_rules(options.get('choice_rules'))
        self.show_progress = options.get('show_progress')
        self.alternative_path = options.get('alternative_path')
        exts = options.get('choice_extensions')
        if exts:
            self.exts = [ext.lower() for ext in exts]
        else:
            self.exts = []
        self.findings = {}

    def scan(self, paths: list) -> dict:
        """Scan file(s) or directory per rule."""
        if not (self.scan_rules and paths):
            return
        self.validate_rules()
        choice_args = []
        if self.show_progress:
            pbar = common.ProgressBar('Choice Match', len(self.scan_rules))
            self.scan_rules = pbar.progrees_loop(self.scan_rules)
        for rule in self.scan_rules:
            scan_paths = paths
            if rule['type'] != 'code' and self.alternative_path:
                # Scan only alternative path
                scan_paths = [Path(self.alternative_path)]
            choice_args.append((scan_paths, rule))

        # Multiprocess Pool
        worker_count = os.cpu_count()
        if sys.platform == 'win32':
            # Work around https://bugs.python.org/issue26903
            worker_count = min(worker_count, 61)
        with Pool(worker_count) as pool:
            results = pool.starmap(
                self.choice_matcher,
                choice_args,
                chunksize=10)
        self.add_finding(results)
        return self.findings

    def validate_rules(self):
        """Validate Rules before scanning."""
        for rule in self.scan_rules:
            if not isinstance(rule, dict):
                raise exceptions.InvalidRuleFormatError(
                    'Choice Matcher Rule format is invalid.')
            if not rule.get('id'):
                raise exceptions.TypeKeyMissingError(
                    'The rule is missing the key \'id\'')
            if not rule.get('type'):
                raise exceptions.PatternKeyMissingError(
                    'The rule is missing the key \'type\'')
            if not rule.get('choice_type'):
                raise exceptions.PatternKeyMissingError(
                    'The rule is missing the key \'choice_type\'')
            if not rule.get('selection'):
                raise exceptions.PatternKeyMissingError(
                    'The rule is missing the key \'selection\'')
            if not rule.get('choice'):
                raise exceptions.PatternKeyMissingError(
                    'The rule is missing the key \'choice\'')

    def choice_matcher(self, scan_paths, rule):
        """Run a Single Choice Matcher rule on all files."""
        results = []
        try:
            matches = set()
            all_matches = set()
            for sfile in scan_paths:
                ext = sfile.suffix.lower()
                if self.exts and ext not in self.exts:
                    continue
                if sfile.stat().st_size / 1000 / 1000 > 5:
                    # Skip scanning files greater than 5 MB
                    continue
                data = sfile.read_text('utf-8', 'ignore')
                if ext in ('.html', '.xml'):
                    data = strip_comments2(data)
                else:
                    data = strip_comments(data)
                match = choices.find_choices(data, rule)
                if match:
                    if isinstance(match, set):
                        # all
                        all_matches.update(match)
                    elif isinstance(match, list):
                        # or, and
                        matches.add(match[0])
                    results.append({
                        'rule': rule,
                        'matches': matches,
                        'all_matches': all_matches,
                    })
        except Exception:
            raise exceptions.RuleProcessingError('Rule processing error.')
        return results

    def add_finding(self, results):
        """Add Choice Findings."""
        for res_list in results:
            if not res_list:
                continue
            for match_dict in res_list:
                all_matches = match_dict['all_matches']
                matches = match_dict['matches']
                rule = match_dict['rule']
                if all_matches:
                    selection = rule['selection'].format(list(all_matches))
                elif matches:
                    select = rule['choice'][min(matches)][1]
                    selection = rule['selection'].format(select)
                elif rule.get('else'):
                    selection = rule['selection'].format(rule['else'])
                else:
                    continue
                self.findings[rule['id']] = self.get_meta(rule, selection)

    def get_meta(self, rule, selection):
        """Get Finding Meta."""
        meta_dict = {}
        meta_dict['choice'] = selection
        meta_dict['description'] = rule['message']
        for key in rule:
            if key in ('choice',
                       'message',
                       'id',
                       'type',
                       'choice_type',
                       'selection',
                       'else'):
                continue
            meta_dict[key] = rule[key]
        return meta_dict
