import ast
import itertools
import json
import multiprocessing
import re
import requests
import sys
from typing import Dict, Iterable, List, Set


_XBOX_GAMEPASS_JS_URL = "https://www.xbox.com/en-US/xbox-game-pass/games/js/xgpcatPopulate-MWF.js"
_GUID_DICT_VARIABLE_NAME = "guidAmpt"
_GUIDAMPT_REGEX_PATTERN = re.compile(_GUID_DICT_VARIABLE_NAME + " = \{[^}]*}")
_HUMAN_FRIENDLY_NAMES_TO_GUID_KEYS = {
    "leaving-soon": ["SubsXGPLeavingSoon"],
    "recently-added": ["XGPPMPRecentlyAdded"],
    "all": ["pcgaVTaz", "subsxgpchannel3"],
}
_CATALOG_URL_FORMAT = "https://catalog.gamepass.com/sigls/v2?id=<PLACEHOLDER>&language=en-us&market=US"
_CATALOG_GAME_IDS_REGEX_PATTERN = re.compile('\{"id":".*"}')
_GAME_INFO_URL_FORMAT = "https://displaycatalog.mp.microsoft.com/v7.0/products?bigIds=<PLACEHOLDER>" \
                        "&market=US&languages=en-us&MS-CV=DGU1mcuYo0WMMp+F.1"


def get_url_contents(url: str) -> str:
    response = requests.get(url)
    if response.status_code != requests.codes.ok:
        raise requests.exceptions.HTTPError(f"lmao, failed calling url {url}, fuck microsoft")

    return response.content.decode("utf-8")


def get_guids_to_slug_ids(js: str, guids_filter: List[str] = None) -> Dict[str, List[str]]:
    dict_str = _GUIDAMPT_REGEX_PATTERN.search(js).group(0)
    dict_str = dict_str.split(" = ")[1]
    dict_str = re.sub(r"\s+", '', dict_str)
    dict_str = re.sub(r"\"", "'", dict_str)
    guids_to_slug_ids = ast.literal_eval(dict_str)
    for k, v in guids_to_slug_ids.items():
        guids_to_slug_ids[k] = v.split(",")

    if guids_filter:
        guids_to_slug_ids = {k: guids_to_slug_ids[k] for k in guids_to_slug_ids if k in guids_filter}
    return guids_to_slug_ids


def get_guids_to_game_ids_map(guid_to_slug_ids_map: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    guids_to_game_ids = dict()
    for guid, slug_ids in guid_to_slug_ids_map.items():
        game_ids = set()
        for slug_id in slug_ids:
            game_ids = game_ids.union(get_game_ids(slug_id))
        guids_to_game_ids[guid] = game_ids
    return guids_to_game_ids


def get_game_ids(slug_id: str) -> Set[str]:
    def catalog_url():
        return _CATALOG_URL_FORMAT.replace("<PLACEHOLDER>", slug_id)

    contents = get_url_contents(catalog_url())
    game_ids = _CATALOG_GAME_IDS_REGEX_PATTERN.search(contents).group(0)
    game_ids = ast.literal_eval(f'[{game_ids}]')
    game_ids = [list(x.values())[0] for x in game_ids]
    return set(game_ids)


def get_human_friendly_names_to_game_ids(
        human_friendly_names_to_guids: Dict[str, List[str]], guids_to_game_ids: Dict[str, Set[str]]
) -> Dict[str, Set[str]]:
    hf_names_to_game_ids = dict()
    for hf_name, guids in human_friendly_names_to_guids.items():
        game_ids = set()
        for guid in guids:
            game_ids = game_ids.union(guids_to_game_ids[guid])
        hf_names_to_game_ids[hf_name] = game_ids

    return hf_names_to_game_ids


def get_game_info_json(game_ids: Iterable[str]):
    def game_info_url():
        game_ids_str = ",".join(game_ids)
        return _GAME_INFO_URL_FORMAT.replace("<PLACEHOLDER>", game_ids_str)
    products = json.loads(get_url_contents(game_info_url()))["Products"]

    # for product in products:
    #     multiprocessing.Process(target=None, args=(product))

    return products


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


def parse_product(product):
    # Name of game: Products -> # -> LocalizedProperties -> # -> ProductTitle
    # 1st Search title: Products -> # -> LocalizedProperties -> # -> SearchTitles -> 0 -> SearchTitleString
    # Platforms: Products -> # -> DisplaySkuAvailabilities -> # -> Availabilities -> # -> Conditions -> ClientConditions -> AllowedPlatforms -> # -> PlatformName (Windows.Xbox, Windows.Desktop)
    # End date: Products -> # -> DisplaySkuAvailabilities -> # -> Availabilities -> # -> Conditions -> EndDate

    localized_properties = product["LocalizedProperties"]
    names = set()
    search_titles = set()
    for property in localized_properties:
        name = property["ProductTitle"]
        search_title = property["SearchTitles"][0]["SearchTitleString"]
        pass

    sku_availabilities = product["DisplaySkuAvailabilities"]
    for availability in sku_availabilities:
        name = property["Availabilities"]

    title_only_first = localized_properties[0]["ProductTitle"]
    platforms_only_first = sku_availabilities[0]["Availabilities"][0]["Conditions"]["ClientConditions"]["AllowedPlatforms"]
    pass


def main():
    js = get_url_contents(_XBOX_GAMEPASS_JS_URL)
    guids_filter = list(itertools.chain(*_HUMAN_FRIENDLY_NAMES_TO_GUID_KEYS.values()))
    guid_to_slug_ids_map = get_guids_to_slug_ids(js, guids_filter=guids_filter)
    guids_to_game_ids = get_guids_to_game_ids_map(guid_to_slug_ids_map)
    mapping = get_human_friendly_names_to_game_ids(_HUMAN_FRIENDLY_NAMES_TO_GUID_KEYS, guids_to_game_ids)

    products = get_game_info_json(mapping["all"])
    for product in products:
        has_more_than_one_entry(product)


if __name__ == '__main__':
    main()
