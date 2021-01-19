import ast
import datetime as dt
import dateutil
import itertools
import json
import re
import requests
import sys
from typing import Dict, Iterable, List, NamedTuple, Set


class _XBoxGamePassCategoryJSInformation:
    URL = "https://www.xbox.com/en-US/xbox-game-pass/games/js/xgpcatPopulate-MWF.js"
    GUID_DICT_VARIABLE_NAME = "guidAmpt"
    # The pattern to look for in the Json that indicates where the GUID mapping is
    GUIDAMPT_REGEX_PATTERN = re.compile(GUID_DICT_VARIABLE_NAME + " = \{[^}]*}")


class _XBoxCatalogJsonInformation:
    URL_ID_PLACEHOLDER = "<SLUG_PLACEHOLDER>"
    URL_FORMAT = f"https://catalog.gamepass.com/sigls/v2?id={URL_ID_PLACEHOLDER}&language=en-us&market=US"
    ID_FIELD = "id"
    ID_FIELD_REGEX_PATTERN = re.compile('\{"id":".*"}')


class _GameDataJsonInformation:
    URL_IDS_PLACEHOLDER = "<GAMEIDS_PLACEHOLDER>"
    URL_FORMAT = f"https://displaycatalog.mp.microsoft.com/v7.0/products?bigIds={URL_IDS_PLACEHOLDER}" \
                 "&market=US&languages=en-us&MS-CV=DGU1mcuYo0WMMp+F.1"


# Mapping of what each category represents, to the GUIDs microsoft lists it under
_HUMAN_FRIENDLY_NAMES_TO_GUID_KEYS = {
    "leaving-soon": ["SubsXGPLeavingSoon"],
    "recently-added": ["XGPPMPRecentlyAdded"],
    "cloud": ["allCloud"],
    "all": ["pcgaVTaz", "allCloud", "subsxgpchannel3"],
}


class GameData(NamedTuple):
    name: str
    search_title: str
    start_date: dt.date
    end_date: dt.date
    xbox_supported: bool
    desktop_supported: bool


def get_url_contents(url: str) -> str:
    response = requests.get(url)
    if response.status_code != requests.codes.ok:
        raise requests.exceptions.HTTPError(f"lmao, failed calling url {url}, fuck microsoft")

    return response.content.decode("utf-8")


def get_guids_to_slug_ids(str, guids_filter: List[str] = None) -> Dict[str, Set[str]]:
    """
    Parse through Microsoft's XBox Gamepass categories javascript, find the guidAmpt variable that maps
    GUIDs to the url slug strings. (Cardinality: 1 GUID to 1+ slugs)

    Return that mapping as a Python dictionary.

    :param guids_filter: List of Microsoft game Global Unique identifiers to look for in the Javascript
    :return: a dictionary of a game's GUIDs to the slug IDs that construct that GUID category
    """
    js = get_url_contents(_XBoxGamePassCategoryJSInformation.URL)
    guidampt_dict_str = _XBoxGamePassCategoryJSInformation.GUIDAMPT_REGEX_PATTERN.search(js).group(0)
    guidampt_dict_str = guidampt_dict_str.split(" = ")[1]
    guidampt_dict_str = re.sub(r"\s+", '', guidampt_dict_str)  # Delete whitespaces
    guidampt_dict_str = re.sub(r"\"", "'", guidampt_dict_str)  # Replace double quote with single quote
    guids_to_slug_ids = ast.literal_eval(guidampt_dict_str)   # Convert to python dict
    for k, v in guids_to_slug_ids.items():
        guids_to_slug_ids[k] = v.split(",")  # A GUID can have multiple slug IDs; Convert to set of str

    if guids_filter:
        guids_to_slug_ids = {k: guids_to_slug_ids[k] for k in guids_to_slug_ids if k in guids_filter}

    return guids_to_slug_ids


def get_guids_to_game_ids_map(guid_to_slug_ids_map: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    """
    Each slug ID, when sent to the GamePass catalog API, returns a list of game IDs.
    The IDs map as so
    1 GUID -> 1+ Slug IDs -> 0+ Game IDs

    This function finds the Game IDs under each slug ID and condenses the mapping into
    :return: 1 GUID -> 0+ Game IDs
    """
    guids_to_game_ids = dict()
    for guid, slug_ids in guid_to_slug_ids_map.items():
        game_ids = set()
        for slug_id in slug_ids:
            game_ids = game_ids.union(get_game_ids(slug_id))
        guids_to_game_ids[guid] = game_ids
    return guids_to_game_ids


def get_game_ids(slug_id: str) -> Set[str]:
    """
    :param slug_id: ID to send to Game Pass catalog API
    :return: List of game IDs found in the Json returned after calling the Game Pass API
    """
    def catalog_url():
        return _XBoxCatalogJsonInformation.URL_FORMAT.replace(_XBoxCatalogJsonInformation.URL_ID_PLACEHOLDER, slug_id)

    contents = get_url_contents(catalog_url())

    # Filter for the IDs data in the Json. Ex output str '{"id":"9ND0CG3LM22K"},{"id":"9NJWTJSVGVLJ"}'
    game_ids = _XBoxCatalogJsonInformation.ID_FIELD_REGEX_PATTERN.search(contents).group(0)
    game_ids = ast.literal_eval(f'[{game_ids}]')  # Evaluate the str as a list of dictionaries
    game_ids = [list(x[_XBoxCatalogJsonInformation.ID_FIELD]) for x in game_ids]
    return set(game_ids)


def get_human_friendly_names_to_game_ids(
        human_friendly_names_to_guids: Dict[str, List[str]], guids_to_game_ids: Dict[str, Set[str]]
) -> Dict[str, Set[str]]:
    """
    We create a few categories and give them human-friendly name because Microsoft's GUIDs are not human-friendly, and
    there can be multiple GUIDs for a category.

    The IDs map as so
    1 human-friendly name -> 1+ GUID -> 1+ Slug IDs -> 0+ Game IDs

    This function condenses the mapping into
    :return: 1 human-friendly name -> 0+ Game IDs
    """
    hf_names_to_game_ids = dict()
    for hf_name, guids in human_friendly_names_to_guids.items():
        game_ids = set()
        for guid in guids:
            game_ids = game_ids.union(guids_to_game_ids[guid])
        hf_names_to_game_ids[hf_name] = game_ids

    return hf_names_to_game_ids


def get_game_info_json(game_ids: Iterable[str]):
    game_ids_str = ",".join(game_ids)
    game_info_url = _GameDataJsonInformation.URL_FORMAT.replace(_GameDataJsonInformation.URL_IDS_PLACEHOLDER, game_ids_str)
    products = json.loads(get_url_contents(game_info_url))["Products"]

    # for product in products:
    #     multiprocessing.Process(target=None, args=(product))
    return products


def parse_product(product: Dict):
    """
    :param product: Json for a single game product, converted into a dictionary

    The fields we want to parse are (i indicates index in list)
    * Name of game: LocalizedProperties -> 0 -> ProductTitle
    * 1st Search title: LocalizedProperties -> i -> SearchTitles -> 0 -> SearchTitleString
    * Platforms: DisplaySkuAvailabilities -> i -> Availabilities -> i -> Conditions -> ClientConditions
        -> AllowedPlatforms -> i -> PlatformName (Windows.Xbox, Windows.Desktop)
    * StartDate, EndDate: DisplaySkuAvailabilities -> i -> Availabilities -> i -> Conditions -> StartDate, EndDate
    * IsTrial: DisplaySkuAvailabilities -> i -> Sku -> Properties -> IsTrial --- We query for start/end date only from
        a sku that isn't marked as trial.
    """
    name = product["LocalizedProperties"][0]["ProductTitle"]
    search_title = product["LocalizedProperties"][0]["SearchTitles"][0]["SearchTitleString"]
    xbox = False
    desktop = False
    start_date = None
    end_date = None

    for availabilities in product["DisplaySkuAvailabilities"]:
        for avail in availabilities:
            isTrial = avail["Sku"]["Properties"]["IsTrial"]
            for platform in avail["Condition"]["ClientConditions"]["AllowedPlatforms"]:
                if platform["PlatformName"] == "Windows.Xbox":
                    xbox = True
                if platform["PlatformName"] == "Windows.Desktop":
                    desktop = True
            for condition in avail["Conditions"]:
                if not isTrial:
                    start_date = dt.dateutil.parse(condition["StartDate"])
                    break

    return GameData(
        name=name,
        search_title=search_title,
        xbox_supported=xbox,
        desktop_supported=desktop,
        start_date=start_date,
        end_date=end_date,
    )



def has_more_than_one_entry(product):
    id = product["ProductId"]
    localized_properties = product["LocalizedProperties"]
    sku_availabilities = product["DisplaySkuAvailabilities"]

    if len(localized_properties) > 1:
        print(f"{localized_properties[0]['ProductTitle']}, {id} has more than one localized property")
        print(localized_properties)
        for property in localized_properties:
            print(f"{property}")

    if len(sku_availabilities) > 1:
        print(f"{localized_properties[0]['ProductTitle']}, {id} has more than one sku availabilities".encode(sys.stdout.encoding, errors='replace'))


def main():
    guids_filter = list(itertools.chain(*_HUMAN_FRIENDLY_NAMES_TO_GUID_KEYS.values()))
    guid_to_slug_ids_map = get_guids_to_slug_ids(guids_filter=guids_filter)

    guids_to_game_ids = get_guids_to_game_ids_map(guid_to_slug_ids_map)
    mapping = get_human_friendly_names_to_game_ids(_HUMAN_FRIENDLY_NAMES_TO_GUID_KEYS, guids_to_game_ids)

    products = get_game_info_json(mapping["all"])
    for product in products:
        has_more_than_one_entry(product)


if __name__ == '__main__':
    main()
