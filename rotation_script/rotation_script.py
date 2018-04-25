import datetime
import fileinput
import os
from collections import Counter
from typing import Dict, List, Set

import ftfy

from magic import fetcher_internal, rotation
from price_grabber.parser import (PriceList, parse_cardhoarder_prices,
                                  parse_mtgotraders_prices)
from shared import configuration, dtutil, text

BLACKLIST: Set[str] = set()
WHITELIST: Set[str] = set()

TOTAL_RUNS = 168

def run() -> None:
    files = rotation.files()
    n = len(files)
    if n >= TOTAL_RUNS:
        return
    all_prices = {}
    for url in configuration.get_list('cardhoarder_urls'):
        s = fetcher_internal.fetch(url)
        s = ftfy.fix_encoding(s)
        all_prices[url] = parse_cardhoarder_prices(s)
    url = configuration.get_str('mtgotraders_url')
    if url:
        s = fetcher_internal.fetch(url)
        all_prices['mtgotraders'] = parse_mtgotraders_prices(s)

    run_number = process(all_prices)
    if run_number == TOTAL_RUNS:
        make_final_list()

def process(all_prices: Dict[str, PriceList]) -> int:
    seen_sets: Set[str] = set()
    used_sets: Set[str] = set()

    hits: Set[str] = set()
    for code in all_prices:
        prices = all_prices[code]
        for name, p, mtgo_set in prices:
            cents = int(float(p) * 100)
            seen_sets.add(mtgo_set)
            if cents <= 1 and is_good_set(mtgo_set):
                hits.add(name)
                used_sets.add(mtgo_set)
    ignored = seen_sets - used_sets
    return process_sets(seen_sets, used_sets, hits, ignored)


def process_sets(seen_sets: Set[str], used_sets: Set[str], hits: Set[str], ignored: Set[str]) -> int:
    files = rotation.files()
    n = len(files) + 1
    path = os.path.join(configuration.get_str('legality_dir'), 'Run_{n}.txt').format(n=n)
    h = open(path, mode='w', encoding='utf-8')
    for card in hits:
        line = card + '\n'
        h.write(line)
    h.close()
    print('Run {n} completed, with {ccards} cards from {csets}/{tsets} sets'.format(n=n, ccards=len(hits), csets=len(used_sets), tsets=len(seen_sets)))
    print('Used:    {sets}'.format(sets=repr(used_sets)))
    print('Missed:  {sets}'.format(sets=repr(ignored)))
    return n

def is_good_set(setname: str) -> bool:
    if not BLACKLIST and not WHITELIST:
        supplimental = (rotation.next_supplemental() - dtutil.now()) < datetime.timedelta(7)
        if supplimental:
            WHITELIST.add(rotation.last_rotation_ex()['mtgo_code'])
        else:
            BLACKLIST.add(rotation.next_rotation_ex()['mtgo_code'])
    if setname in BLACKLIST:
        return False
    elif setname in WHITELIST:
        return True
    return not WHITELIST

def make_final_list() -> None:
    files = rotation.files()
    lines: List[str] = []
    for line in fileinput.input(files):
        line = text.sanitize(line)
        lines.append(line)
    scores = Counter(lines).most_common()

    final: List[str] = []
    for name, count in scores:
        if count >= TOTAL_RUNS / 2:
            final.append(name)
    final.sort()
    h = open(os.path.join(configuration.get_str('legality_dir'), 'legal_cards.txt'), mode='w', encoding='utf-8')
    h.write(''.join(final))
    h.close()
    print('Generated legal_cards.txt.  {0}/{1} cards.'.format(len(final), len(scores)))
