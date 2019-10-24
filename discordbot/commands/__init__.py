import glob
import importlib
import inspect
import logging
from os import path
from typing import List, Optional

from discord.ext.commands import Bot, Command, Context
from discord.ext.commands.errors import BadArgument

from discordbot import command
from magic.models import Card


def setup(bot: Bot) -> None:
    Card.convert = CardConverter.convert
    modules = glob.glob(path.join(path.dirname(__file__), '*.py'))
    files = [path.basename(f)[:-3] for f in modules if path.isfile(f) and not f.endswith('__init__.py')]

    for mod in files:
        n = 0
        m = importlib.import_module(f'.{mod}', package=__name__)
        for name, obj in inspect.getmembers(m):
            if isinstance(obj, Command):
                print('Loaded !%s' % name)
                bot.add_command(obj)
                n += 1
        if n == 0:
            print(f'No command found in {m.__name__}')


class CardConverter:
    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> Optional[Card]:
        try:
            result, mode = command.results_from_queries([argument])[0]
            if result.has_match() and not result.is_ambiguous():
                return command.cards_from_names_with_mode([result.get_best_match()], mode)[0]
            if result.is_ambiguous():
                message = await ctx.send('{author}: Ambiguous name for {c}. Suggestions: {s}'.format(author=ctx.author.mention, c=ctx.command, s=command.disambiguation(result.get_ambiguous_matches()[0:5])))
                await command.disambiguation_reactions(message, result.get_ambiguous_matches()[0:5])
            else:
                await ctx.send('{author}: No matches.'.format(author=ctx.author.mention))
            return None
        except Exception as exc:
            raise BadArgument('Could not find card') from exc
