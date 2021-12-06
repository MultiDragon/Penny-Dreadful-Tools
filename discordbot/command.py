import collections
import datetime
import logging
import re
from copy import copy
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple, Union

import attr
from dis_snek import Snake
from dis_snek.annotations.argument_annotations import CMD_BODY
from dis_snek.models.application_commands import (InteractionCommand, OptionTypes, Permission, PermissionTypes,
                                                  slash_option, slash_permission)
from dis_snek.models.context import (AutocompleteContext, Context, InteractionContext,
                                     MessageContext)
from dis_snek.models.command import MessageCommand, message_command
from dis_snek.models.discord_objects.channel import TYPE_MESSAGEABLE_CHANNEL
from dis_snek.models.discord_objects.message import Message
from dis_snek.models.discord_objects.user import Member
from dis_snek.models.enums import ChannelTypes
from dis_snek.models.file import File
from dis_snek.models.scale import Scale

from discordbot import emoji
from discordbot.shared import SendableContext, channel_id, guild_id
from magic import card, card_price, fetcher, image_fetcher, oracle
from magic.models import Card
from magic.whoosh_search import SearchResult, WhooshSearcher
from shared import configuration, dtutil
from shared.lazy import lazy_property
from shared.settings import with_config_file

DEFAULT_CARDS_SHOWN = 4
MAX_CARDS_SHOWN = 10
DISAMBIGUATION_EMOJIS = [':one:', ':two:', ':three:', ':four:', ':five:']
DISAMBIGUATION_EMOJIS_BY_NUMBER = {1: '1⃣', 2: '2⃣', 3: '3⃣', 4: '4⃣', 5: '5⃣'}
DISAMBIGUATION_NUMBERS_BY_EMOJI = {'1⃣': 1, '2⃣': 2, '3⃣': 3, '4⃣': 4, '5⃣': 5}

HELP_GROUPS: Set[str] = set()

@lazy_property
def searcher() -> WhooshSearcher:
    return WhooshSearcher()

async def respond_to_card_names(message: Message, client: Snake) -> None:
    # Don't parse messages with Gatherer URLs because they use square brackets in the querystring.
    if 'gatherer.wizards.com' in message.content.lower():
        return
    compat = False and message.channel.type == ChannelTypes.GUILD_TEXT and await client.get_user(268547439714238465) in message.channel.members  # see #7074
    queries = parse_queries(message.content, compat)
    if len(queries) > 0:
        await message.channel.trigger_typing()
        results = results_from_queries(queries)
        cards = []
        for i in results:
            (r, mode, preferred_printing) = i
            if r.has_match() and not r.is_ambiguous():
                cards.extend(cards_from_names_with_mode([r.get_best_match()], mode, preferred_printing))
            elif r.is_ambiguous():
                cards.extend(cards_from_names_with_mode(r.get_ambiguous_matches(), mode, preferred_printing))
        await post_cards(client, cards, message.channel, message.author)

def parse_queries(content: str, scryfall_compatability_mode: bool) -> List[str]:
    to_scan = re.sub('`{1,3}[^`]*?`{1,3}', '', content, re.DOTALL)  # Ignore angle brackets inside backticks. It's annoying in #code.
    if scryfall_compatability_mode:
        queries = re.findall(r'(?<!\[)\[([^\]]*)\](?!\])', to_scan)  # match [card] but not [[card]]
    else:
        queries = re.findall(r'\[?\[([^\]]*)\]\]?', to_scan)
    return [card.canonicalize(query) for query in queries if len(query) > 2]

def cards_from_names_with_mode(cards: Sequence[Optional[str]], mode: str, preferred_printing: Optional[str] = None) -> List[Card]:
    return [copy_with_mode(oracle.load_card(c), mode, preferred_printing) for c in cards if c is not None]

def copy_with_mode(oracle_card: Card, mode: str, preferred_printing: str = None) -> Card:
    c = copy(oracle_card)
    c['mode'] = mode
    c['preferred_printing'] = preferred_printing
    return c

def parse_mode(query: str) -> Tuple[str, str, Optional[str]]:
    mode = ''
    preferred_printing = None
    if query.startswith('$'):
        mode = '$'
        query = query[1:]
    if '|' in query:
        query, preferred_printing = query.split('|')
        preferred_printing = preferred_printing.lower().strip()
    return (mode, query, preferred_printing)

def results_from_queries(queries: List[str]) -> List[Tuple[SearchResult, str, Optional[str]]]:
    all_results = []
    for query in queries:
        mode, query, preferred_printing = parse_mode(query)
        result = searcher().search(query)
        all_results.append((result, mode, preferred_printing))
    return all_results

def complex_search(query: str) -> List[Card]:
    if query == '':
        return []
    _, cardnames = fetcher.search_scryfall(query)
    cbn = oracle.cards_by_name()
    return [cbn[name] for name in cardnames if cbn.get(name) is not None]

def roughly_matches(s1: str, s2: str) -> bool:
    return simplify_string(s1).find(simplify_string(s2)) >= 0

def simplify_string(s: str) -> str:
    s = ''.join(s.split())
    return re.sub(r'[\W_]+', '', s).lower()

def disambiguation(cards: List[str]) -> str:
    if len(cards) > 5:
        return ','.join(cards)
    return ' '.join([' '.join(x) for x in zip(DISAMBIGUATION_EMOJIS, cards)])

async def disambiguation_reactions(message: Message, cards: List[str]) -> None:
    for i in range(1, len(cards) + 1):
        await message.add_reaction(DISAMBIGUATION_EMOJIS_BY_NUMBER[i])

async def single_card_or_send_error(channel: TYPE_MESSAGEABLE_CHANNEL, args: str, author: Member, command: str) -> Optional[Card]:
    if not args:
        await send(channel, '{author}: Please specify a card name.'.format(author=author.mention))
        return None
    result, mode, preferred_printing = results_from_queries([args])[0]
    if result.has_match() and not result.is_ambiguous():
        return cards_from_names_with_mode([result.get_best_match()], mode, preferred_printing)[0]
    if result.is_ambiguous():
        message = await send(channel, '{author}: Ambiguous name for {c}. Suggestions: {s} (click number below)'.format(author=author.mention, c=command, s=disambiguation(result.get_ambiguous_matches()[0:5])))
        await disambiguation_reactions(message, result.get_ambiguous_matches()[0:5])
    else:
        await send(channel, '{author}: No matches.'.format(author=author.mention))
    return None

# pylint: disable=too-many-arguments
async def single_card_text(client: Snake, channel: TYPE_MESSAGEABLE_CHANNEL, args: str, author: Member, f: Callable[[Card], str], command: str, show_legality: bool = True) -> None:
    c = await single_card_or_send_error(channel, args, author, command)
    if c is not None:
        name = c.name
        info_emoji = emoji.info_emoji(c, show_legality=show_legality)
        text = emoji.replace_emoji(f(c), client)
        message = f'**{name}** {info_emoji} {text}'
        await send(channel, message)


async def post_cards(
        client: Snake,
        cards: List[Card],
        channel: Union[TYPE_MESSAGEABLE_CHANNEL, Context],
        replying_to: Optional[Member] = None,
        additional_text: str = '',
) -> None:
    if len(cards) == 0:
        await post_nothing(channel, replying_to)
        return

    with with_config_file(guild_id(channel)), with_config_file(channel_id(channel)):
        legality_format = configuration.legality_format.value
    not_pd = configuration.get_list('not_pd')
    if str(channel_id(channel)) in not_pd or str(guild_id(channel)) in not_pd:  # This needs to be migrated
        legality_format = 'Unknown'
    cards = uniqify_cards(cards)
    if len(cards) > MAX_CARDS_SHOWN:
        cards = cards[:DEFAULT_CARDS_SHOWN]
    if len(cards) == 1:
        text = single_card_text_internal(client, cards[0], legality_format)
    else:
        text = ', '.join('{name} {legal} {price}'.format(name=card.name, legal=((emoji.info_emoji(card, legality_format=legality_format))), price=((card_price.card_price_string(card, True)) if card.get('mode', None) == '$' else '')) for card in cards)
    if len(cards) > MAX_CARDS_SHOWN:
        image_file = None
    else:
        if isinstance(channel, InteractionContext):
            await channel.defer()
        elif isinstance(channel, MessageContext):
            await channel.channel.trigger_typing()
        else:
            await channel.trigger_typing()
        image_file = await image_fetcher.download_image_async(cards)
    if image_file is None:
        text += '\n\n'
        if len(cards) == 1:
            text += emoji.replace_emoji(cards[0].oracle_text, client)
        else:
            text += 'No image available.'
    text += additional_text
    if image_file is None:
        await send(channel, text)
    else:
        await send_image_with_retry(channel, image_file, text)

async def post_nothing(channel: Union[Context, TYPE_MESSAGEABLE_CHANNEL], replying_to: Optional[Member] = None) -> None:
    if replying_to is not None:
        text = '{author}: No matches.'.format(author=replying_to.mention)
    else:
        text = 'No matches.'
    message = await send(channel, text)
    await message.add_reaction('❎')


async def send(channel: Union[Context, TYPE_MESSAGEABLE_CHANNEL], content: str, file: Optional[File] = None) -> Message:
    new_s = escape_underscores(content)
    return await channel.send(file=file, content=new_s)

async def send_image_with_retry(channel: Union[Context, TYPE_MESSAGEABLE_CHANNEL], image_file: str, text: str = '') -> None:
    message = await send(channel, file=File(image_file), content=text)
    if message and message.attachments and message.attachments[0].size == 0:
        logging.warning('Message size is zero so resending')
        await message.delete()
        await send(channel, file=File(image_file), content=text)

def single_card_text_internal(client: Snake, requested_card: Card, legality_format: str) -> str:
    mana = emoji.replace_emoji('|'.join(requested_card.mana_cost or []), client)
    mana = mana.replace('|', ' // ')
    legal = ' — ' + emoji.info_emoji(requested_card, verbose=True, legality_format=legality_format)
    if requested_card.get('mode', None) == '$':
        text = '{name} {legal} — {price}'.format(name=requested_card.name, price=card_price.card_price_string(requested_card), legal=legal)
    else:
        text = '{name} {mana} — {type}{legal}'.format(name=requested_card.name, mana=mana, type=requested_card.type_line, legal=legal)
    if requested_card.bugs:
        for bug in requested_card.bugs:
            text += '\n:lady_beetle:{rank} bug: {bug}'.format(bug=bug['description'], rank=bug['classification'])
            if bug['last_confirmed'] < (dtutil.now() - datetime.timedelta(days=60)):
                time_since_confirmed = (dtutil.now() - bug['last_confirmed']).total_seconds()
                text += ' (Last confirmed {time} ago.)'.format(time=dtutil.display_time(time_since_confirmed, 1))
    return text

# See #5532 and #5566.
def escape_underscores(s: str) -> str:
    new_s = ''
    in_url, in_emoji = False, False
    for char in s:
        if char == ':':
            in_emoji = True
        elif char not in 'abcdefghijklmnopqrstuvwxyz_':
            in_emoji = False
        if char == '<':
            in_url = True
        elif char == '>':
            in_url = False
        if char == '_' and not in_url and not in_emoji:
            new_s += '\\_'
        else:
            new_s += char
    return new_s

# Given a list of cards return one (aribtrarily) for each unique name in the list.
def uniqify_cards(cards: List[Card]) -> List[Card]:
    # Remove multiple printings of the same card from the result set.
    results: Dict[str, Card] = collections.OrderedDict()
    for c in cards:
        results[card.canonicalize(c.name)] = c
    return list(results.values())

def slash_card_option(param: str = 'card') -> Callable:
    """Predefined Slash command argument `card`"""

    def wrapper(func: Callable) -> Callable:
        return slash_option(
            name=param,
            description='Name of a Card',
            required=True,
            opt_type=OptionTypes.STRING,
            autocomplete=False,
        )(func)

    return wrapper

def slash_permission_pd_mods() -> Callable:
    """Restrict this command to Mods in the PD server"""

    def wrapper(func: Callable) -> Callable:
        return slash_permission(Permission(id=226785937970036748, guild_id=207281932214599682, type=PermissionTypes.ROLE))(func)

    return wrapper

def make_choice(value: str, name: Optional[str] = None) -> Dict[str, str]:
    return {
        'name': name or value,
        'value': value,
    }

async def autocomplete_card(scale: Scale, ctx: AutocompleteContext, card: str) -> None:
    if not card:
        await ctx.send(choices=[])
        return
    choices = []
    results = searcher().search(card)
    choices.extend(results.exact)
    choices.extend(results.prefix_whole_word)
    choices.extend(results.other_prefixed)
    choices.extend(results.fuzzy)

    await ctx.send(choices=[make_choice(c) for c in choices])

def alias_message_command_to_slash_command(command: InteractionCommand, param: str = 'card', name: Optional[str] = None) -> MessageCommand:
    """
    This is a horrible hack.  Use it if a slash command takes one multiword argument
    """

    async def wrapper(_scale: Scale, ctx: MtgMessageContext, body: CMD_BODY) -> None:
        ctx.kwargs[param] = body
        await command.call_callback(command.callback, ctx)

    if name is None:
        name = command.name
    return message_command(name)(wrapper)

class MtgMixin:
    async def send_image_with_retry(self: SendableContext, image_file: str, text: str = '') -> None:
        message = await self.send(file=File(image_file), content=text)
        if message and message.attachments and message.attachments[0].size == 0:
            logging.warning('Message size is zero so resending')
            await message.delete()
            await self.send(file=File(image_file), content=text)

    async def single_card_text(self: SendableContext, c: Card, f: Callable, show_legality: bool = True) -> None:
        if c is None:
            return

        not_pd = configuration.get_list('not_pd')
        if str(self.channel.id) in not_pd or (getattr(self.channel, 'guild', None) is not None and str(self.channel.guild.id) in not_pd):
            show_legality = False

        name = c.name
        info_emoji = emoji.info_emoji(c, show_legality=show_legality)
        text = emoji.replace_emoji(f(c), self.bot)
        message = f'**{name}** {info_emoji} {text}'
        await self.send(message)

    async def post_cards(self: SendableContext, cards: List[Card], replying_to: Optional[Member] = None, additional_text: str = '') -> None:
        # this feels awkward, but shrug
        await post_cards(self.bot, cards, self, replying_to, additional_text)

    async def post_nothing(self: SendableContext) -> None:
        await post_nothing(self.channel)


# Some hackery here.  The classes below don't actually exist.  They just appear to do so for type-checking.
# In reality, we're adding the above mixin as a parent to the appropriate classes
InteractionContext.__bases__ += (MtgMixin,)
MessageContext.__bases__ += (MtgMixin,)

@attr.define
class MtgInteractionContext(InteractionContext, MtgMixin):
    pass

@attr.define
class MtgMessageContext(MessageContext, MtgMixin):
    pass


MtgContext = Union[MtgMessageContext, MtgInteractionContext]
