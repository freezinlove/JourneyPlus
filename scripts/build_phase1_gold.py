from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import feedparser
import httpx

from journeyplus.content.cleaner import lightly_clean
from journeyplus.content.urls import canonicalize_url
from journeyplus.contracts import DocumentLabel, RawDocument
from journeyplus.evaluation.schema import GoldDataset
from journeyplus.sources.catalog import parse_catalog_records


ROOT = Path(__file__).resolve().parents[1]
GOLD_PATH = ROOT / "gold" / "status_opportunity_phase1_v1.json"
REVIEW_PATH = ROOT / "gold" / "status_opportunity_phase1_v1_review.md"
FFB_CATALOG_URL = "https://www.frequentflyerbonuses.com/statusmatchoffers.html"


@dataclass(frozen=True, slots=True)
class ArticleSpec:
    source_id: str
    url: str
    title: str
    label: DocumentLabel
    event_keys: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class CatalogSpec:
    program: str
    title: str
    event_key: str
    reason: str


ARTICLES = (
    ArticleSpec(
        "ffb_elite_status_feed",
        "https://blog.frequentflyerbonuses.com/2026/08/kenya-airways-asante-rewards-skyteam-paid-status-match.html",
        "Kenya Airways Asante Rewards SkyTeam paid status match",
        DocumentLabel.STATUS_OPPORTUNITY,
        ("kenya-airways-asante-rewards-paid-status-match-2026",),
        "报道肯尼亚航空付费会籍匹配的具体更新。",
    ),
    ArticleSpec(
        "ffb_elite_status_feed",
        "https://blog.frequentflyerbonuses.com/2026/08/receive-up-to-a-50-bonus-when-you-buy-marriott-bonvoy-points.html",
        "Receive up to a 50% bonus when you buy Marriott Bonvoy points",
        DocumentLabel.NONE,
        (),
        "买分加赠不直接授予、升级或延长会籍。",
    ),
    ArticleSpec(
        "ffb_elite_status_feed",
        "https://blog.frequentflyerbonuses.com/2026/07/air-canada-aeroplan-earn-up-to-3-5x-points.html",
        "Air Canada Aeroplan earn up to 3.5x points",
        DocumentLabel.NONE,
        (),
        "积分倍数奖励不直接产生会籍。",
    ),
    ArticleSpec(
        "ffb_elite_status_feed",
        "https://blog.frequentflyerbonuses.com/2026/06/last-chance-air-france-klm-flying-blue-paid-elite-status-match.html",
        "Air France KLM Flying Blue paid elite status match",
        DocumentLabel.STATUS_OPPORTUNITY,
        (
            "flying-blue-paid-status-match-2026",
            "vietnam-airlines-lotusmiles-paid-status-match-2026",
        ),
        "正文同时给出Flying Blue活动截止更新及越航付费匹配替代路径。",
    ),
    ArticleSpec(
        "awardwallet_elite_status_feed",
        "https://awardwallet.com/hotels/world-of-hyatt/hyatt-globalist/",
        "World of Hyatt Globalist guide",
        DocumentLabel.NONE,
        (),
        "长期会籍权益与获取教学，不是具体活动报道。",
    ),
    ArticleSpec(
        "awardwallet_elite_status_feed",
        "https://awardwallet.com/airlines/delta-skymiles/",
        "Delta SkyMiles guide",
        DocumentLabel.NONE,
        (),
        "长期项目教学，不是具体会籍活动报道。",
    ),
    ArticleSpec(
        "awardwallet_elite_status_feed",
        "https://awardwallet.com/airlines/kenya-airways-status-match-offer/",
        "Kenya Airways status match offer",
        DocumentLabel.STATUS_OPPORTUNITY,
        ("kenya-airways-asante-rewards-paid-status-match-2026",),
        "具体报道肯尼亚航空付费会籍匹配。",
    ),
    ArticleSpec(
        "awardwallet_elite_status_feed",
        "https://awardwallet.com/news/alaska-atmos-rewards/alaska-corporate-status-challenge/",
        "Alaska corporate status challenge",
        DocumentLabel.STATUS_OPPORTUNITY,
        ("alaska-atmos-corporate-status-challenge-2026",),
        "具体报道指定企业员工的即时会籍与快速通道。",
    ),
    ArticleSpec(
        "awardwallet_elite_status_feed",
        "https://awardwallet.com/news/american-aadvantage/elite-status-upgrades-premium-economy/",
        "AAdvantage elite status upgrades on premium economy tickets",
        DocumentLabel.NONE,
        (),
        "报道既有会籍权益规则变化，不提供会籍获取机会。",
    ),
    ArticleSpec(
        "loyaltylobby_feed",
        "https://loyaltylobby.com/2026/08/19/last-call-alaska-airlines-buy-miles-up-to-100-bonus-sale-until-august-20-2026/",
        "Alaska Airlines buy miles bonus",
        DocumentLabel.NONE,
        (),
        "购买里程促销不直接产生会籍。",
    ),
    ArticleSpec(
        "loyaltylobby_feed",
        "https://loyaltylobby.com/2026/08/18/american-airlines-brings-back-seatback-screens-on-short-haul-aircraft-from-2028/",
        "American Airlines brings back seatback screens",
        DocumentLabel.NONE,
        (),
        "航司产品新闻与会籍获取无关。",
    ),
    ArticleSpec(
        "loyaltylobby_feed",
        "https://loyaltylobby.com/2026/08/17/united-premier-gold-elite-benefit-experience-on-virgin-australia-domestic-flights/",
        "United Premier Gold benefit experience on Virgin Australia",
        DocumentLabel.NONE,
        (),
        "既有会籍权益体验，不是会籍获取机会。",
    ),
    ArticleSpec(
        "loyaltylobby_feed",
        "https://loyaltylobby.com/2026/08/09/finnair-plus-radisson-rewards-launch-two-way-conversions-match/",
        "Finnair Plus and Radisson Rewards conversions and tier match",
        DocumentLabel.STATUS_OPPORTUNITY,
        ("finnair-plus-to-radisson-rewards-status-match-2026",),
        "正文含Finnair Plus精英会员匹配Radisson Rewards会籍的具体活动。",
    ),
    ArticleSpec(
        "loyaltylobby_feed",
        "https://loyaltylobby.com/2026/08/08/update-ihg-one-rewards-double-elite-night-credits-august-5-september-29-2026/",
        "IHG One Rewards double elite night credits",
        DocumentLabel.NONE,
        (),
        "奖励精英房晚，但不直接授予、升级或延长会籍。",
    ),
    ArticleSpec(
        "loyaltylobby_feed",
        "https://loyaltylobby.com/2026/08/06/turkish-airlines-milessmiles-reduces-oceania-award-pricing/",
        "Turkish Airlines reduces Oceania award pricing",
        DocumentLabel.NONE,
        (),
        "积分票定价变化与会籍获取无关。",
    ),
    ArticleSpec(
        "frequentmiler_elite_status_feed",
        "https://frequentmiler.com/elite-status-via-the-air-france-klm-credit-card/",
        "Elite status via the Air France KLM credit card",
        DocumentLabel.NONE,
        (),
        "以长期方法总结和信用卡攻略为主要目的。",
    ),
    ArticleSpec(
        "frequentmiler_elite_status_feed",
        "https://frequentmiler.com/targeted-ihg-promo-earn-double-elite-night-credits-limit-10-bonus-elite-nights/",
        "Targeted IHG double elite night credits",
        DocumentLabel.NONE,
        (),
        "奖励精英房晚但不直接产生会籍。",
    ),
    ArticleSpec(
        "frequentmiler_elite_status_feed",
        "https://frequentmiler.com/how-to-get-access-to-airport-lounges-with-accor-elite-status/",
        "Airport lounge access with Accor elite status",
        DocumentLabel.STATUS_OPPORTUNITY,
        (
            "kenya-airways-asante-rewards-paid-status-match-2026",
            "accor-to-qatar-privilege-club-status-match-2026",
        ),
        "正文集中报道Accor会籍通往肯尼亚航空和卡塔尔航空会籍的两项当前路径。",
    ),
    ArticleSpec(
        "frequentmiler_elite_status_feed",
        "https://frequentmiler.com/southwest-promo-earn-a-list-status-20k-bonus-points-when-booking-via-swabiz/",
        "Southwest SWABIZ A-List and points promotion",
        DocumentLabel.UNCERTAIN,
        (),
        "活动可直接授予A-List，但正文无法确认是否仅为个人定向。",
    ),
    ArticleSpec(
        "frequentmiler_elite_status_feed",
        "https://frequentmiler.com/where-hyatt-suite-upgrade-awards-dont-work/",
        "Where Hyatt suite upgrade awards do not work",
        DocumentLabel.NONE,
        (),
        "会籍套房升级券适用规则，不是会籍获取机会。",
    ),
    ArticleSpec(
        "frequentmiler_elite_status_feed",
        "https://frequentmiler.com/gha-discovery-hotel-program-status-match-from-many-hotel-airline-cruise-programs/",
        "GHA Discovery paid status match",
        DocumentLabel.STATUS_OPPORTUNITY,
        ("gha-discovery-paid-status-match-2026",),
        "具体报道GHA Discovery付费会籍匹配。",
    ),
    ArticleSpec(
        "verylvke_feed",
        "https://www.verylvke.com/2026/08/17/accor-plus-wyndham-benefits-enhanced/",
        "雅高A+促销，温德姆钻石新增早餐权益",
        DocumentLabel.NONE,
        (),
        "会员卡促销和既有会籍权益变化，不直接产生会籍。",
    ),
    ArticleSpec(
        "verylvke_feed",
        "https://www.verylvke.com/2026/08/19/stay-krakow-sheraton-grand-hotel-indigo-old-town/",
        "克拉科夫喜来登与老城英迪格入住体验",
        DocumentLabel.NONE,
        (),
        "酒店入住体验，不是会籍获取机会。",
    ),
    ArticleSpec(
        "verylvke_feed",
        "https://www.verylvke.com/2026/08/03/iprefer-titanium-status-match-scandic-avios/",
        "璞富腾钛金匹配与Scandic兑换实战",
        DocumentLabel.STATUS_OPPORTUNITY,
        ("iprefer-rewards-email-status-match-2026",),
        "正文提供向iPrefer官方邮箱申请且成功获得钛金会籍的当前实测。",
    ),
    ArticleSpec(
        "verylvke_feed",
        "https://www.verylvke.com/2026/08/05/accor-all-plus-sale-kenya-airways-status-match/",
        "雅高臻享卡促销与肯尼亚航空匹配",
        DocumentLabel.STATUS_OPPORTUNITY,
        ("kenya-airways-asante-rewards-paid-status-match-2026",),
        "只归入正文中的肯尼亚航空会籍匹配更新。",
    ),
    ArticleSpec(
        "verylvke_feed",
        "https://www.verylvke.com/2026/07/14/marriott-japan-airlines-partnership/",
        "万豪与日本航空会籍合作",
        DocumentLabel.STATUS_OPPORTUNITY,
        (
            "marriott-bonvoy-to-jal-fly-on-status-path-2026",
            "jal-diamond-metal-to-marriott-platinum-fast-track-2026",
        ),
        "双向合作包含万豪会员获得JAL定级分路径及JAL高卡十晚获得万豪白金两项机会。",
    ),
    ArticleSpec(
        "verylvke_feed",
        "https://www.verylvke.com/2026/07/07/badazhou-grand-hyatt-athens-marriott-devaluation/",
        "八大洲一住升金、雅典君悦好价与万豪贬值",
        DocumentLabel.STATUS_OPPORTUNITY,
        ("badazhou-one-stay-gold-fast-track-2026",),
        "只归入正文中八大洲一住升级体验金卡的具体活动。",
    ),
    ArticleSpec(
        "verylvke_feed",
        "https://www.verylvke.com/2026/07/06/malaysia-airlines-status-match/",
        "马来西亚航空会籍匹配活动",
        DocumentLabel.STATUS_OPPORTUNITY,
        (
            "malaysia-airlines-enrich-paid-status-match-2026",
            "garuda-indonesia-gold-privilege-paid-status-2026",
        ),
        "正文包含马航付费匹配和印尼鹰航付费Gold Privilege两项独立机会。",
    ),
    ArticleSpec(
        "verylvke_feed",
        "https://www.verylvke.com/2026/07/05/trip-summer-mega-sale/",
        "Trip夏日大促",
        DocumentLabel.NONE,
        (),
        "机票、酒店和门票促销，不直接产生会籍。",
    ),
    ArticleSpec(
        "verylvke_feed",
        "https://www.verylvke.com/2026/05/31/flying-blue-and-sas-status-match/",
        "法航荷航和北欧航空会籍匹配",
        DocumentLabel.STATUS_OPPORTUNITY,
        (
            "sas-eurobonus-india-paid-status-match-2026",
            "flying-blue-paid-status-match-2026",
        ),
        "正文分别报道SAS印度居民付费匹配和Flying Blue付费匹配。",
    ),
)


CATALOG = (
    CatalogSpec("Vietnam Airlines", "Vietnam Airlines Lotusmiles付费匹配", "vietnam-airlines-lotusmiles-paid-status-match-2026", "具体付费会籍匹配记录。"),
    CatalogSpec("Air Astana Nomad Club", "Air Astana Nomad Club付费匹配", "air-astana-nomad-club-paid-status-match-2026", "具体付费会籍匹配记录。"),
    CatalogSpec("Air France KLM", "Flying Blue英国BA Club专场", "flying-blue-ba-uk-paid-status-match-2026", "英国BA Club精英会员专属匹配，与广泛资格活动分开。"),
    CatalogSpec("Air France KLM", "Flying Blue多项目付费匹配", "flying-blue-paid-status-match-2026", "面向多个非天合项目的付费匹配。"),
    CatalogSpec("Alaska Airlines Atmos Rewards", "Alaska San Diego快速通道", "alaska-atmos-san-diego-fast-track-2025-2026", "按圣迭戈合资格航段升级会籍。"),
    CatalogSpec("Alaska Airlines Atmos Rewards", "Alaska指定企业员工挑战", "alaska-atmos-corporate-status-challenge-2026", "公司专属链接均属于同一即时会籍与快速通道活动。"),
    CatalogSpec("Alaska Airlines Atmos Rewards", "Alaska北美航司会籍匹配", "alaska-atmos-airline-status-match-2026", "与同项目的其他两项活动分开。"),
    CatalogSpec("American AAdvantage", "American AAdvantage会籍匹配", "american-aadvantage-status-match-2026", "具体会籍匹配及Instant Status Pass路径。"),
    CatalogSpec("Delta SkyMiles", "Delta Medallion匹配挑战", "delta-skymiles-status-match-challenge-2026", "临时匹配并通过挑战延长。"),
    CatalogSpec("Etihad Airways", "Etihad印度与澳大利亚付费匹配", "etihad-guest-india-australia-paid-status-match-2026", "具体地区限定付费匹配。"),
    CatalogSpec("JetBlue TrueBlue", "JetBlue Mosaic匹配挑战", "jetblue-mosaic-status-match-challenge-2026", "临时匹配及后续延期挑战属于同一活动。"),
    CatalogSpec("Kenya Airways Asante Rewards", "肯尼亚航空Asante Rewards付费匹配", "kenya-airways-asante-rewards-paid-status-match-2026", "具体付费会籍匹配记录。"),
    CatalogSpec("KM Malta Airlines KM Rewards", "KM Malta KM Rewards付费匹配", "km-malta-km-rewards-paid-status-match-2026", "条目主体和申请页均指向KM Malta；正文中的Kenya名称视为来源笔误。"),
    CatalogSpec("Malaysia Airlines Enrich", "马航Enrich付费匹配", "malaysia-airlines-enrich-paid-status-match-2026", "具体付费会籍匹配记录。"),
    CatalogSpec("Miles & More", "Miles & More付费匹配", "miles-and-more-paid-status-match-2026", "具体会籍匹配记录。"),
    CatalogSpec("Royal Air Maroc", "Royal Air Maroc Safar Flyer付费匹配", "royal-air-maroc-safar-flyer-paid-status-match-2026", "具体付费会籍匹配记录。"),
    CatalogSpec("Royal Jordanian", "Royal Jordanian Royal Club付费匹配", "royal-jordanian-royal-club-paid-status-match-2026", "具体付费会籍匹配记录。"),
    CatalogSpec("TAP Air Portugal", "TAP Miles&Go欧洲付费匹配", "tap-miles-and-go-paid-status-match-2026", "具体地区限定付费匹配。"),
    CatalogSpec("United MileagePlus", "United MileagePlus匹配挑战", "united-mileageplus-status-match-challenge-2026", "具体会籍匹配与快速通道记录。"),
    CatalogSpec("Virgin Atlantic Flying Club", "Virgin Atlantic Flying Club会籍匹配", "virgin-atlantic-flying-club-status-match-2026", "具体会籍匹配记录。"),
    CatalogSpec("Best Western Rewards", "Best Western Rewards普通会籍匹配", "best-western-rewards-status-match", "酒店会籍匹配。"),
    CatalogSpec("Best Western Rewards", "Best Western AARP自动金卡", "best-western-aarp-gold-direct-grant", "AARP资格与Best Western登记是同一直接授予活动的两个步骤。"),
    CatalogSpec("Best Western Rewards", "Best Western美国军人自动金卡", "best-western-us-military-gold-direct-grant", "美国军人群体公开的直接授予活动。"),
    CatalogSpec("Best Western Rewards", "Best Western加拿大军人自动金卡", "best-western-canada-military-gold-direct-grant", "加拿大军人群体公开的直接授予活动。"),
    CatalogSpec("Choice Privileges", "Choice Privileges会籍匹配", "choice-privileges-status-match-2026", "具体酒店会籍匹配记录。"),
    CatalogSpec("Choice Privileges", "Choice美国军人终身金卡", "choice-privileges-us-military-lifetime-gold", "美军相关成员可直接获得终身金卡。"),
    CatalogSpec("Hilton Honors", "Hilton Honors匹配挑战", "hilton-honors-status-match-challenge-2026", "临时会籍和房晚挑战属于同一活动。"),
    CatalogSpec("Sonesta Hotels Travel Pass", "Sonesta Travel Pass会籍匹配", "sonesta-travel-pass-status-match", "具体酒店会籍匹配记录。"),
    CatalogSpec("WorldHotels Rewards", "WorldHotels Rewards会籍匹配", "worldhotels-rewards-status-match", "具体酒店会籍匹配记录。"),
    CatalogSpec("Wyndham Rewards", "Wyndham Rewards会籍匹配", "wyndham-rewards-status-match-2026", "具体酒店会籍匹配记录。"),
    CatalogSpec("Avis Preferred", "Avis Preferred欧洲与英国会籍匹配", "avis-preferred-europe-uk-status-match", "具体租车会籍匹配记录。"),
    CatalogSpec("Enterprise Plus", "Enterprise Plus会籍匹配", "enterprise-plus-status-match", "完整等级对照表属于同一匹配活动；租车预订链接不另建活动。"),
    CatalogSpec("Hertz Gold Plus Rewards", "Hertz Gold Plus Rewards会籍匹配", "hertz-gold-plus-rewards-status-match", "完整等级对照表属于同一匹配活动。"),
    CatalogSpec("National Emerald Club", "National Emerald Club会籍匹配", "national-emerald-club-status-match", "具体租车会籍匹配记录。"),
    CatalogSpec("Club Avolta", "Club Avolta Platinum会籍匹配", "club-avolta-platinum-status-match", "其他旅行忠诚度项目的具体会籍匹配。"),
)


FEED_PAGES = {
    "loyaltylobby_feed": (
        "https://loyaltylobby.com/feed/",
        "https://loyaltylobby.com/feed/?paged=2",
        "https://loyaltylobby.com/feed/?paged=5",
        "https://loyaltylobby.com/feed/?paged=6",
        "https://loyaltylobby.com/feed/?paged=7",
    ),
    "frequentmiler_elite_status_feed": (
        "https://frequentmiler.com/category/travel/elite-status/feed/",
        "https://frequentmiler.com/category/travel/elite-status/feed/?paged=2",
    ),
    "verylvke_feed": tuple(
        "https://www.verylvke.com/feed/"
        if page == 1
        else f"https://www.verylvke.com/feed/?paged={page}"
        for page in range(1, 10)
    ),
}


def _slug(url: str) -> str:
    path = urlsplit(url).path.strip("/")
    return path.replace("/", ":")


def _document_key(spec: ArticleSpec) -> str:
    return f"{spec.source_id}:{_slug(spec.url)}"


def _fetch_feed_bodies(client: httpx.Client) -> dict[tuple[str, str], str]:
    targets = {
        (spec.source_id, canonicalize_url(spec.url)): spec
        for spec in ARTICLES
        if spec.source_id in FEED_PAGES
    }
    found: dict[tuple[str, str], str] = {}
    for source_id, pages in FEED_PAGES.items():
        extra_drop = {"omhide"} if source_id == "loyaltylobby_feed" else set()
        for page_url in pages:
            if source_id == "loyaltylobby_feed":
                time.sleep(1)
            response = _get_with_rate_limit_retry(client, page_url)
            parsed = feedparser.parse(response.text)
            for entry in parsed.entries:
                link = canonicalize_url(
                    str(entry.get("link") or ""), extra_drop=extra_drop
                )
                key = (source_id, link)
                if key not in targets:
                    continue
                content = entry.get("content") or []
                body = (
                    str(content[0].get("value") or "")
                    if content
                    else str(entry.get("summary") or entry.get("description") or "")
                )
                if body.strip():
                    found[key] = body
    missing = sorted(set(targets) - set(found))
    if missing:
        raise RuntimeError(f"Missing requested feed entries: {missing}")
    return found


def _get_with_rate_limit_retry(
    client: httpx.Client, url: str, *, attempts: int = 3
) -> httpx.Response:
    for attempt in range(attempts):
        response = client.get(url)
        if response.status_code != 429:
            response.raise_for_status()
            return response
        if attempt + 1 < attempts:
            retry_after = response.headers.get("retry-after")
            delay = min(float(retry_after) if retry_after else 3.0, 10.0)
            time.sleep(delay)
    response.raise_for_status()
    raise AssertionError("unreachable")


def _normalized_articles(client: httpx.Client) -> list[dict[str, object]]:
    feed_bodies = _fetch_feed_bodies(client)
    documents: list[dict[str, object]] = []
    for spec in ARTICLES:
        canonical = canonicalize_url(spec.url)
        if spec.source_id in FEED_PAGES:
            body = feed_bodies[(spec.source_id, canonical)]
            content_type = "text/html"
        else:
            response = client.get(spec.url)
            response.raise_for_status()
            canonical = canonicalize_url(str(response.url))
            body = response.text
            content_type = response.headers.get("content-type", "text/html")
        raw = RawDocument(
            source_id=spec.source_id,
            external_id=_document_key(spec),
            canonical_url=canonical,
            body=body,
            content_type=content_type,
        )
        normalized = lightly_clean(raw).normalized_body
        documents.append(
            {
                "spec": spec,
                "document": {
                    "document_key": _document_key(spec),
                    "source_url": canonical,
                    "normalized_body": normalized,
                },
                "classification": {
                    "document_key": _document_key(spec),
                    "label": spec.label.value,
                    "event_keys": list(spec.event_keys),
                },
            }
        )
    return documents


def _normalized_catalog(client: httpx.Client) -> tuple[list[dict[str, object]], str]:
    response = client.get(FFB_CATALOG_URL)
    response.raise_for_status()
    records = parse_catalog_records(response.text, str(response.url))
    if len(records) != len(CATALOG):
        raise RuntimeError(
            f"Expected {len(CATALOG)} FFB top-level records, found {len(records)}"
        )
    documents: list[dict[str, object]] = []
    for index, (record, spec) in enumerate(zip(records, CATALOG, strict=True), 1):
        if record.program != spec.program:
            raise RuntimeError(
                f"FFB record {index} changed: expected {spec.program!r}, "
                f"found {record.program!r}"
            )
        document_key = f"ffb_status_match_catalog:{spec.event_key}"
        raw = RawDocument(
            source_id="ffb_status_match_catalog",
            external_id=document_key,
            canonical_url=FFB_CATALOG_URL,
            body=record.text,
            content_type="text/plain",
        )
        normalized = lightly_clean(raw).normalized_body
        documents.append(
            {
                "spec": spec,
                "document": {
                    "document_key": document_key,
                    "source_url": FFB_CATALOG_URL,
                    "normalized_body": normalized,
                },
                "classification": {
                    "document_key": document_key,
                    "label": DocumentLabel.STATUS_OPPORTUNITY.value,
                    "event_keys": [spec.event_key],
                },
            }
        )
    page_hash = hashlib.sha256(response.content).hexdigest()
    return documents, page_hash


def _case(case_id: str, notes: str, items: list[dict[str, object]]) -> dict[str, object]:
    return {
        "case_id": case_id,
        "version": 1,
        "notes": notes,
        "documents": [item["document"] for item in items],
        "classifications": [item["classification"] for item in items],
        "relationships": [],
        "facts": [],
    }


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _review_markdown(
    article_items: list[dict[str, object]],
    catalog_items: list[dict[str, object]],
    snapshot_time: str,
    catalog_hash: str,
) -> str:
    labels = {
        DocumentLabel.STATUS_OPPORTUNITY: "是",
        DocumentLabel.NONE: "否",
        DocumentLabel.UNCERTAIN: "不确定",
    }
    lines = [
        "# 第一阶段人工金标审核清单",
        "",
        f"生成时间：`{snapshot_time}`",
        "",
        "范围：30篇指定文章 + FFB列表35个顶层条目，共65份文档。StatusMatcher未纳入。",
        "",
        "当前只标注文档是否属于会籍机会以及文档内活动归并；`relationships`和`facts`均为空，尚未运行测评。",
        "",
        "## 汇总",
        "",
        "| 标签 | 数量 |",
        "|---|---:|",
        "| 是 / `STATUS_OPPORTUNITY` | 48 |",
        "| 否 / `NONE` | 16 |",
        "| 不确定 / `UNCERTAIN` | 1 |",
        "| 合计 | 65 |",
        "",
        "## 指定文章",
        "",
        "| # | 文档 | 标签 | 活动数量 | 活动归并名 | 理由 | 规范正文字符数 |",
        "|---:|---|---|---:|---|---|---:|",
    ]
    for index, item in enumerate(article_items, 1):
        spec = item["spec"]
        document = item["document"]
        assert isinstance(spec, ArticleSpec)
        assert isinstance(document, dict)
        event_keys = "<br>".join(f"`{key}`" for key in spec.event_keys) or "—"
        lines.append(
            "| "
            + " | ".join(
                (
                    str(index),
                    f"[{_markdown_cell(spec.title)}]({spec.url})",
                    labels[spec.label],
                    str(len(spec.event_keys)),
                    event_keys,
                    _markdown_cell(spec.reason),
                    str(len(str(document["normalized_body"]))),
                )
            )
            + " |"
        )
    lines.extend(
        (
            "",
            "## FFB顶层条目",
            "",
            f"容器：[FFB Status Match & Fast Track Offers]({FFB_CATALOG_URL})",
            "",
            f"页面快照SHA-256：`{catalog_hash}`",
            "",
            "| # | 顶层条目 | 标签 | 活动归并名 | 理由 | 规范正文字符数 |",
            "|---:|---|---|---|---|---:|",
        )
    )
    for index, item in enumerate(catalog_items, 1):
        spec = item["spec"]
        document = item["document"]
        assert isinstance(spec, CatalogSpec)
        assert isinstance(document, dict)
        lines.append(
            "| "
            + " | ".join(
                (
                    str(index),
                    _markdown_cell(spec.title),
                    "是",
                    f"`{spec.event_key}`",
                    _markdown_cell(spec.reason),
                    str(len(str(document["normalized_body"]))),
                )
            )
            + " |"
        )
    lines.extend(
        (
            "",
            "## 审核顺序",
            "",
            "1. 先看文章表中的17个非肯定样本，确认16个“否”和1个“不确定”。",
            "2. 再看所有多活动文章，确认一篇正文是否应当对应两个活动归并名。",
            "3. 检查同一活动跨来源是否使用相同归并名，重点是肯尼亚航空、越航、Flying Blue、Alaska企业员工和马航。",
            "4. 检查FFB的35个顶层边界；同一航司的不同活动保持分开，条目内多个链接不拆文档。",
            "5. 最后抽查JSON中的`normalized_body`，确认Feed来源没有误用文章页、FFB内嵌等级表没有被拆成新文档。",
            "",
            "审核时可以直接按“文章编号/FFB编号 + 修改意见”记录；确认后再递增相应案例版本并运行测评。",
            "",
        )
    )
    return "\n".join(lines)


def main() -> None:
    snapshot_time = datetime.now(UTC).replace(microsecond=0).isoformat()
    headers = {"User-Agent": "JourneyPlus/1.0 gold-build"}
    with httpx.Client(follow_redirects=True, timeout=45, headers=headers) as client:
        article_items = _normalized_articles(client)
        catalog_items, catalog_hash = _normalized_catalog(client)

    dataset = {
        "schema_version": "2",
        "dataset_version": 1,
        "cases": [
            _case(
                "phase1-selected-articles",
                "30篇用户指定文章；文章页来源按文章页规范化，Feed正文来源只使用Feed正文。",
                article_items,
            ),
            _case(
                "phase1-ffb-status-match-catalog",
                f"FFB列表于{snapshot_time}观察；只包含35个顶层条目；页面SHA-256={catalog_hash}。",
                catalog_items,
            ),
        ],
    }
    validated = GoldDataset.model_validate(dataset)
    GOLD_PATH.write_text(validated.model_dump_json(indent=2), encoding="utf-8")
    REVIEW_PATH.write_text(
        _review_markdown(
            article_items, catalog_items, snapshot_time, catalog_hash
        ),
        encoding="utf-8",
    )
    summary = {
        "gold_path": str(GOLD_PATH),
        "review_path": str(REVIEW_PATH),
        "documents": len(article_items) + len(catalog_items),
        "articles": len(article_items),
        "ffb_catalog_records": len(catalog_items),
        "statusmatcher_documents": 0,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
