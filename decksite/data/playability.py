from typing import Dict, List

from decksite.data import preaggregation, query
from decksite.database import db
from shared.container import Container
from shared.decorators import retry_after_calling


def preaggregate() -> None:
    preaggregate_season_count()
    preaggregate_season_archetype_count()
    preaggregate_season_card_count()
    preaggregate_season_archetype_card_count()
    preaggregate_season_archetype_playability()
    preaggregate_archetype_count()
    preaggregate_card_count()
    preaggregate_archetype_card_count()
    preaggregate_archetype_playability()
    preaggregate_season_playability()
    preaggregate_playability()

# Map of archetype_id => cardname where cardname is the key card for that archetype for the supplied season, or all time if 0 supplied as season_id.
@retry_after_calling(preaggregate)
def key_cards(season_id: int) -> Dict[int, str]:
    if season_id:
        table = '_season_archetype_playability'
        where = f'p.season_id = {season_id}'
    else:
        table = '_archetype_playability'
        where = 'TRUE'
    sql = f"""
        SELECT
            p.archetype_id,
            p.name
        FROM
            {table} AS p
        INNER JOIN (
            SELECT
                archetype_id, MAX(playability) AS playability
            FROM
                {table} AS p
            WHERE
                {where}
            GROUP BY
                archetype_id
        ) AS pm ON p.archetype_id = pm.archetype_id AND p.playability = pm.playability
        WHERE
            {where}
        ORDER BY
            p.name
    """
    return {r['archetype_id']: r['name'] for r in db().select(sql)}

@retry_after_calling(preaggregate)
def playability() -> Dict[str, float]:
    sql = """
        SELECT
            name,
            playability
        FROM
            _playability
    """
    return {r['name']: r['playability'] for r in db().select(sql)}

@retry_after_calling(preaggregate)
def season_playability(season_id: int) -> List[Container]:
    # This is a temporary thing used to generate banners.
    # Feel free to replace it with something better.
    sql = f"""
        SELECT
            name,
            playability
        FROM
            _season_playability
        WHERE
            season_id = {season_id}
        ORDER BY `playability` DESC
        LIMIT 100
    """
    return [Container(r) for r in db().select(sql)]

@retry_after_calling(preaggregate)
def rank() -> Dict[str, int]:
    sql = """
        SELECT
            name,
            ROW_NUMBER() OVER (ORDER BY playability DESC) as rank
        FROM
            _playability
    """
    return {r['name']: r['rank'] for r in db().select(sql)}

def preaggregate_season_count() -> None:
    table = '_season_count'
    season_join = query.season_join()
    sql = f"""
        CREATE TABLE IF NOT EXISTS _new{table} (
            season_id INT,
            num_decks INT,
            PRIMARY KEY (season_id),
            FOREIGN KEY (season_id) REFERENCES season (id) ON UPDATE CASCADE ON DELETE CASCADE
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci AS
        SELECT
            season.season_id,
            COUNT(*) AS num_decks
        FROM
            deck AS d
        {season_join}
        WHERE
            d.archetype_id IS NOT NULL
        GROUP BY
            season.season_id
    """
    preaggregation.preaggregate(table, sql)

def preaggregate_season_archetype_count() -> None:
    table = '_season_archetype_count'
    season_join = query.season_join()
    sql = f"""
        CREATE TABLE IF NOT EXISTS _new{table} (
            season_id INT,
            archetype_id INT,
            num_decks INT,
            PRIMARY KEY (season_id, archetype_id),
            FOREIGN KEY (season_id) REFERENCES season (id) ON UPDATE CASCADE ON DELETE CASCADE,
            FOREIGN KEY (archetype_id) REFERENCES archetype (id) ON UPDATE CASCADE ON DELETE CASCADE
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci AS
        SELECT
            season.season_id,
            d.archetype_id,
            COUNT(*) AS num_decks
        FROM
            deck AS d
        {season_join}
        WHERE
            d.archetype_id IS NOT NULL
        GROUP BY
            season.season_id,
            d.archetype_id
    """
    preaggregation.preaggregate(table, sql)

def preaggregate_season_card_count() -> None:
    table = '_season_card_count'
    season_join = query.season_join()
    sql = f"""
        CREATE TABLE IF NOT EXISTS _new{table} (
            name VARCHAR(190),
            season_id INT,
            num_decks INT,
            PRIMARY KEY (name, season_id),
            FOREIGN KEY (season_id) REFERENCES season (id) ON UPDATE CASCADE ON DELETE CASCADE
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci AS
        SELECT
            card AS name,
            season.season_id,
            COUNT(*) AS num_decks
        FROM
            deck AS d
        INNER JOIN
            deck_card AS dc ON d.id = dc.deck_id
        {season_join}
        WHERE
            NOT dc.sideboard
        AND
            d.archetype_id IS NOT NULL
        GROUP BY
            dc.card,
            season.season_id
    """
    preaggregation.preaggregate(table, sql)

def preaggregate_season_archetype_card_count() -> None:
    table = '_season_archetype_card_count'
    season_join = query.season_join()
    sql = f"""
        CREATE TABLE IF NOT EXISTS _new{table} (
            name VARCHAR(190),
            season_id INT,
            archetype_id INT,
            num_decks INT,
            PRIMARY KEY (name, season_id, archetype_id),
            FOREIGN KEY (season_id) REFERENCES season (id) ON UPDATE CASCADE ON DELETE CASCADE,
            FOREIGN KEY (archetype_id) REFERENCES archetype (id) ON UPDATE CASCADE ON DELETE CASCADE
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci AS
        SELECT
            card AS name,
            season.season_id,
            d.archetype_id,
            COUNT(*) AS num_decks
        FROM
            deck AS d
        INNER JOIN
            deck_card AS dc ON d.id = dc.deck_id
        {season_join}
        WHERE
            NOT dc.sideboard
        AND
            d.archetype_id IS NOT NULL
        GROUP BY
            dc.card,
            d.archetype_id,
            season.season_id
    """
    preaggregation.preaggregate(table, sql)

def preaggregate_season_archetype_playability() -> None:
    table = '_season_archetype_playability'
    sql = f"""
        CREATE TABLE IF NOT EXISTS _new{table} (
            name VARCHAR(190) NOT NULL,
            season_id INT NOT NULL,
            archetype_id INT NOT NULL,
            playability DECIMAL(6,5) NOT NULL,
            PRIMARY KEY (name, season_id, archetype_id),
            FOREIGN KEY (season_id) REFERENCES season (id) ON UPDATE CASCADE ON DELETE CASCADE,
            FOREIGN KEY (archetype_id) REFERENCES archetype (id) ON UPDATE CASCADE ON DELETE CASCADE
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci AS
        SELECT
            sacc.name,
            sacc.season_id,
            sacc.archetype_id,
            (
                -- num decks playing this card in this archetype in this season
                sacc.num_decks
                    /
                -- num decks in this archetype in this season
                sac.num_decks
            )
                *
            (
                1.0
                    -
                (
                    -- num decks playing this card in this season
                    scc.num_decks
                        /
                    -- num decks in this season
                    sc.num_decks
                )
            ) AS playability
        FROM
            _season_archetype_card_count AS sacc
        INNER JOIN
            _season_archetype_count AS sac ON sac.archetype_id = sacc.archetype_id AND sac.season_id = sacc.season_id
        INNER JOIN
            _season_card_count AS scc ON scc.name = sacc.name AND scc.season_id = sacc.season_id
        INNER JOIN
            _season_count AS sc ON sc.season_id = sacc.season_id
    """
    preaggregation.preaggregate(table, sql)

def preaggregate_archetype_count() -> None:
    table = '_archetype_count'
    sql = f"""
        CREATE TABLE IF NOT EXISTS _new{table} (
            archetype_id INT,
            num_decks INT,
            PRIMARY KEY (archetype_id),
            FOREIGN KEY (archetype_id) REFERENCES archetype (id) ON UPDATE CASCADE ON DELETE CASCADE
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci AS
        SELECT
            d.archetype_id,
            COUNT(*) AS num_decks
        FROM
            deck AS d
        WHERE
            d.archetype_id IS NOT NULL
        GROUP BY
            d.archetype_id
    """
    preaggregation.preaggregate(table, sql)

def preaggregate_card_count() -> None:
    table = '_card_count'
    sql = f"""
        CREATE TABLE IF NOT EXISTS _new{table} (
            name VARCHAR(190),
            num_decks INT,
            PRIMARY KEY (name)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci AS
        SELECT
            card AS name,
            COUNT(*) AS num_decks
        FROM
            deck AS d
        INNER JOIN
            deck_card AS dc ON d.id = dc.deck_id
        WHERE
            NOT dc.sideboard
        AND
            d.archetype_id IS NOT NULL
        GROUP BY
            dc.card
    """
    preaggregation.preaggregate(table, sql)

def preaggregate_archetype_card_count() -> None:
    table = '_archetype_card_count'
    sql = f"""
        CREATE TABLE IF NOT EXISTS _new{table} (
            name VARCHAR(190),
            archetype_id INT,
            num_decks INT,
            PRIMARY KEY (name, archetype_id),
            FOREIGN KEY (archetype_id) REFERENCES archetype (id) ON UPDATE CASCADE ON DELETE CASCADE
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci AS
        SELECT
            card AS name,
            d.archetype_id,
            COUNT(*) AS num_decks
        FROM
            deck AS d
        INNER JOIN
            deck_card AS dc ON d.id = dc.deck_id
        WHERE
            NOT dc.sideboard
        AND
            d.archetype_id IS NOT NULL
        GROUP BY
            dc.card,
            d.archetype_id
    """
    preaggregation.preaggregate(table, sql)

def preaggregate_archetype_playability() -> None:
    table = '_archetype_playability'
    sql = f"""
        CREATE TABLE IF NOT EXISTS _new{table} (
            name VARCHAR(190) NOT NULL,
            archetype_id INT NOT NULL,
            playability DECIMAL(6,5) NOT NULL,
            PRIMARY KEY (name, archetype_id),
            FOREIGN KEY (archetype_id) REFERENCES archetype (id) ON UPDATE CASCADE ON DELETE CASCADE
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci AS
        SELECT
            acc.name,
            acc.archetype_id,
            (
                -- num decks playing this card in this archetype
                acc.num_decks
                    /
                -- num decks in this archetype
                ac.num_decks
            )
                *
            (
                1.0
                    -
                (
                    -- num decks playing this card
                    cc.num_decks
                        /
                    -- num decks
                    (SELECT COUNT(*) FROM deck WHERE archetype_id IS NOT NULL)
                )
            ) AS playability
        FROM
            _archetype_card_count AS acc
        INNER JOIN
            _archetype_count AS ac ON ac.archetype_id = acc.archetype_id
        INNER JOIN
            _card_count AS cc ON cc.name = acc.name
    """
    preaggregation.preaggregate(table, sql)

def preaggregate_season_playability() -> None:
    table = '_season_playability'
    sql = f"""
        CREATE TABLE IF NOT EXISTS _new{table} (
            name VARCHAR(190) NOT NULL,
            season_id INT NOT NULL,
            playability DECIMAL(6,5) NOT NULL,
            PRIMARY KEY (name, season_id),
            FOREIGN KEY (season_id) REFERENCES season (id) ON UPDATE CASCADE ON DELETE CASCADE
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci AS
        SELECT
            scc.name,
            scc.season_id,
            (
                scc.num_decks
                    /
                (SELECT COUNT(*) FROM deck_cache WHERE season_id = scc.season_id)
            ) AS playability
        FROM
            _season_card_count AS scc
    """
    preaggregation.preaggregate(table, sql)

def preaggregate_playability() -> None:
    table = '_playability'
    sql = f"""
        CREATE TABLE IF NOT EXISTS _new{table} (
            name VARCHAR(190) NOT NULL,
            playability DECIMAL(6,5) NOT NULL,
            PRIMARY KEY (name)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci AS
        SELECT
            scc.name,
            SUM(scc.num_decks) / SUM(sc.num_decks) AS playability
        FROM
            _season_card_count AS scc
        INNER JOIN
            _season_count AS sc ON scc.season_id = sc.season_id
        GROUP BY
            scc.name
    """
    preaggregation.preaggregate(table, sql)
