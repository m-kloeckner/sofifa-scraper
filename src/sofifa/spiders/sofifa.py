import scrapy
from scrapy.utils.project import get_project_settings
import requests
import json
from .utils import *


class SofifaSpider(scrapy.Spider):
    name = "sofifa"
    allowed_domains = ["sofifa.com"]

    teams_cache = dict()

    def __init__(self, fifa_version="140002", remap_columns="True"):
        self.fifa_version = fifa_version
        self.remap_columns = remap_columns.lower() in ("true", "yes", "y", "1")
        self.start_urls = [self.__build_request_url()]

    def __build_request_url(self) -> str:
        return f"{PLAYERS_BASE_URL}&r={self.fifa_version}&set=true"

    def start_requests(self):
        request = scrapy.Request(self.start_urls[0])
        request.cookies["r"] = self.fifa_version
#        request.meta["proxy"] = "http://172.16.1.5:8118"
        self.logger.info(f"Scraping version {self.fifa_version}")
        yield request

    def parse(self, response):

        for player in response.css("table > tbody > tr"):
            club_name = player.css("td:nth-child(6) a::text").get()
            team_url = player.css("td:nth-child(6) a::attr(href)").get()
            player_url = player.css("td:nth-child(2) a::attr(href)").get()

            if club_name is None or str.isdecimal(club_name):
                # skip fake players or players that do not play in any club
                self.logger.info(f"Skipping fake player.")
                continue

            item = dict()

            # get player ids and version
            player_ids = {
                "sofifa_id": player.css("td:nth-child(7)::text").get(),
                "fifa_version": self.fifa_version,
                "sofifa_club_id": team_url.split('/')[2],
                "club_name": club_name,
                "league": self.parse_team(team_url),
            }
            item.update(player_ids)

            # get player details from player page
            item.update(self.parse_player_details(player_url))

            # get player data placed in the first columns of player search
            more_player_data = {
                "player_positions": [player.css("td:nth-child(2) span::text").get()],
                "potential": player.css("td:nth-child(5) em::text").get(),
                "overall_rating": player.css("td:nth-child(4) em::text").get()
            }
            item.update(more_player_data)

            # get the remaining columns of player search
            props_headers = response.css("table thead tr th ::text").extract()[8:]
            props_headers = list(map(clean_string, [_ for _ in props_headers]))
            if self.remap_columns:
                props_headers = rename_columns(props_headers)
            props_values = []
            for p in player.css("td")[9:]:
                value = p.css(" ::text").get()
                if value is None:
                    value = ""
                props_values.append(value.strip())
                item.update(dict(zip(props_headers, props_values)))

            yield item

        for next_page in response.css(".pagination a::attr(href)"):
            offset = next_page.get().split("offset=")[1]
            yield response.follow(next_page, self.parse)

    def parse_team(self, team_url):
        if team_url in self.teams_cache.keys():
            return self.teams_cache[team_url]

        settings = get_project_settings()
        cookies = {"r": self.fifa_version}
        proxies = {
            "http": settings.get('HTTP_PROXY'),
            "https": settings.get('HTTPS_PROXY')
            }
        headers = {
            "User-Agent": settings.get('USER_AGENT')
        }

        req = requests.get(
            SITE_BASE_URL + team_url + "?r=" + self.fifa_version,
            cookies=cookies,
            headers=headers,
#            proxies=proxies
        )

        resp = scrapy.Selector(req)

        # the item is something like `English Premier League (1)`
        league_name = resp.css("div.profile.clearfix a::text").get()

        self.teams_cache[team_url] = league_name
        return league_name
    
    def parse_player_details(self, player_url):

        settings = get_project_settings()
        cookies = {"r": self.fifa_version}
        proxies = {
            "http": settings.get('HTTP_PROXY'),
            "https": settings.get('HTTPS_PROXY')
            }
        headers = {
            "User-Agent": settings.get('USER_AGENT')
        }

        req = requests.get(
            SITE_BASE_URL + player_url,
            cookies=cookies,
            headers=headers,
 #           proxies=proxies
        )

        resp = scrapy.Selector(req)

        # get player profile json
        player_profile = json.loads(resp.xpath('//head/script[contains(text(), "birthDate")]/text()').get())
        player_details = {
            "given_name": player_profile['givenName'],
            "family_name": player_profile['familyName'],
            "birth_date": player_profile['birthDate'],
            "image": player_profile['image'],
            "height": player_profile['height'],
            "weight": player_profile['weight'],
            "nationality": player_profile['nationality']
        }

        # get lineup strengths
        props_headers = resp.css("div.lineup div div.pos::text").extract()
        props_headers = list(map(clean_string, [_ for _ in props_headers]))
        props_values = []
        for p in resp.css("div.lineup div div.pos"):
            value = p.css(" em::text").get()
            if value is None:
                value = ""
            props_values.append(value.strip())
        player_details.update(dict(zip(props_headers, props_values)))

        return player_details
