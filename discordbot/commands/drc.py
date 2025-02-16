from typing import Dict, Optional
from urllib import parse

from naff.models import Embed, OptionTypes, slash_command, slash_option

from discordbot.command import (DEFAULT_CARDS_SHOWN, MAX_CARDS_SHOWN, MtgContext,
                                MtgInteractionContext)
from magic import fetcher, oracle
from shared import configuration, fetch_tools

domain = configuration.get_str('dreadrise_url')
link_domain = configuration.get_str('dreadrise_public_url')
MAX_DECKS_SHOWN = 5
MAX_DECKS_SHOWN_WITH_CONTINUATION = 3

def format_deck(x: Dict) -> Dict:
    """Formats a deck object. Returns a dictionary with name and value."""
    return {
        'name': '{name} [{src}, {wins}-{losses}]'.format(
            name=x['deck']['name'], wins=x['deck']['wins'], losses=x['deck']['losses'], src=x['competition']['name']),
        'value': '[{arch} deck by {author} ({format})]({domain}/decks/{id})'.format(
            arch=x['tags'][0]['name'], author=x['author']['nickname'],
            format=x['format'], id=x['deck']['deck_id'], domain=link_domain),
    }

@slash_command('dreadrise', description='Query Dreadrise')
async def drc(ctx: MtgContext) -> None:
    ...

@drc.subcommand('search', sub_cmd_description='Card Search using Dreadrise')
@slash_option('query', 'search query', OptionTypes.STRING, required=True)
async def cardsearch(ctx: MtgInteractionContext, query: str) -> None:
    """Card search using Dreadrise."""
    await ctx.defer()
    card_data = await fetcher.dreadrise_search_cards(query, MAX_CARDS_SHOWN, 1)
    if 'err' in card_data and card_data['err']:
        await ctx.send('Search error: `{error}`'.format(error=card_data['reason']))
        return

    card_array = [x['name'] for x in card_data['sample']]
    count = card_data['matches']
    if count < MAX_CARDS_SHOWN:
        card_data_pd_illegal = await fetcher.dreadrise_search_cards(query, MAX_CARDS_SHOWN - card_data['matches'], -1)
        card_array += [x['name'] for x in card_data_pd_illegal['sample']]
        count += card_data_pd_illegal['matches']

    cbn = oracle.cards_by_name()
    cards = [cbn[name] for name in card_array if cbn.get(name) is not None]
    if count > MAX_CARDS_SHOWN:
        cards = cards[:DEFAULT_CARDS_SHOWN]
    await ctx.post_cards(cards, ctx.author, more_results_link(query, count))

@drc.subcommand('deck')
@slash_option('query', 'search query', OptionTypes.STRING, required=True)
async def decks(ctx: MtgInteractionContext, query: str) -> None:
    """Deck search using Dreadrise."""
    await ctx.defer()
    data = await fetcher.dreadrise_search_decks(query, MAX_DECKS_SHOWN)
    if not data['success']:
        await ctx.send('Search error: `{error}`'.format(error=data['reason']))
        return
    if data['matches'] == 0:
        await ctx.post_nothing()
        return

    count = data['matches']
    embed = Embed(title='Deck search', description='Winrate: {w}%'.format(w=data['winrate']))
    if count <= MAX_DECKS_SHOWN:
        arr = [format_deck(x) for x in data['sample']]
    else:
        subsample = data['sample'][:MAX_DECKS_SHOWN_WITH_CONTINUATION]
        arr = [format_deck(x) for x in subsample]
        arr.append({'name': 'Other results', 'value': '[{n} more results found]({domain}{path}?q={query}{pd})'.format(
            domain=link_domain,
            n=count - MAX_DECKS_SHOWN_WITH_CONTINUATION,
            path='/deck-search',
            pd='&dist=penny_dreadful',
            query=parse.quote_plus(query),
        )})

    embed.set_thumbnail(url='https://api.scryfall.com/cards/named?exact={card}&format=image&version=art_crop'.format(
        card=data['sample'][0]['main_card'].replace(' ', '%20')))
    for x in arr:
        embed.add_field(name=x['name'], value=x['value'], inline=False)
    await ctx.send(embeds=[embed])

@drc.subcommand('matchups')
@slash_option('q1', 'The query for the first player', OptionTypes.STRING, required=True)
@slash_option('q2', 'The query for the second player', OptionTypes.STRING, required=False)
async def matchups(ctx: MtgInteractionContext, q1: str, q2: Optional[str]) -> None:
    """Matchup calculation using Dreadrise."""
    await ctx.defer()
    q2 = q2 or ''
    data = await fetcher.dreadrise_search_matchups(q1, q2, 1)
    if not data['success']:
        await ctx.send('Search error: `{error}`'.format(error=data['reason']))
        return
    if data['matches'] == 0:
        await ctx.post_nothing()
        return

    ans = '{length} matches found. Winrate: {wr}%\n{domain}{path}?q1={q1}&q2={q2}{pd}'.format(
        domain=link_domain,
        length=data['matches'],
        wr=data['winrate'],
        path='/deck-search/matchups',
        pd='&dist=penny_dreadful',
        q1=parse.quote_plus(q1),
        q2=parse.quote_plus(q2),
    )
    await ctx.send(ans)

def more_results_link(args: str, total: int) -> str:
    return 'and {n} more.\n<{d}/cards/find?q={q}>'.format(
        n=total - DEFAULT_CARDS_SHOWN, q=fetch_tools.escape(args), d=link_domain) if total > MAX_CARDS_SHOWN else ''
