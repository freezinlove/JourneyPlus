# 第一阶段正文提取审计

生成时间：`2026-08-20T09:40:36+00:00`

口径：文章页来源的“原始”是完整网页HTML，“提取”是正文容器HTML；Feed来源的原始输入本来就是Feed正文；FFB列表按顶层条目计算。最终正文不保留图片URL，只在图片没有图注且alt有实际信息时保留`[图片：说明]`。

## 来源汇总

| 来源 | 文档 | 原始字符 | 正文容器字符 | 最终正文字符 | 原始链接 | 保留链接 | 丢弃链接 | 异常标记 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `ffb_elite_status_feed` | 4 | 487331 | 41049 | 19113 | 351 | 18 | 333 | 0 |
| `awardwallet_elite_status_feed` | 5 | 961462 | 148629 | 85489 | 1340 | 225 | 1200 | 0 |
| `loyaltylobby_feed` | 6 | 40534 | 39879 | 29850 | 28 | 21 | 7 | 0 |
| `frequentmiler_elite_status_feed` | 6 | 63507 | 59928 | 49329 | 65 | 52 | 14 | 0 |
| `verylvke_feed` | 9 | 52105 | 50742 | 9025 | 115 | 18 | 97 | 0 |
| `ffb_status_match_catalog` | 35 | 22980 | 16182 | 16182 | 74 | 67 | 7 | 0 |

## 与修复前草稿对比

修复前的文章正文包含整页导航、页脚、图片URL或Feed分发尾注；FFB列表则相反，因纯文本化丢失了链接。下表的基线固定为首次草稿，不随后续重新抓取改变。

| 来源 | 修复前正文字符 | 当前正文字符 | 变化 |
|---|---:|---:|---:|
| `ffb_elite_status_feed` | 41045 | 19113 | -53.4% |
| `awardwallet_elite_status_feed` | 226136 | 85489 | -62.2% |
| `loyaltylobby_feed` | 32309 | 29850 | -7.6% |
| `frequentmiler_elite_status_feed` | 52231 | 49329 | -5.6% |
| `verylvke_feed` | 26817 | 9025 | -66.3% |
| `ffb_status_match_catalog` | 11818 | 16182 | +36.9% |

## 30篇指定文章

| # | 文档 | 来源 | 原始字符 | 正文容器字符 | 最终字符 | 保留链接 | 丢弃链接 | 异常 |
|---:|---|---|---:|---:|---:|---:|---:|---|
| 1 | [Kenya Airways Asante Rewards SkyTeam paid status match](https://blog.frequentflyerbonuses.com/2026/08/kenya-airways-asante-rewards-skyteam-paid-status-match.html) | `ffb_elite_status_feed` | 129785 | 18655 | 8822 | 5 | 84 | — |
| 2 | [Receive up to a 50% bonus when you buy Marriott Bonvoy points](https://blog.frequentflyerbonuses.com/2026/08/receive-up-to-a-50-bonus-when-you-buy-marriott-bonvoy-points.html) | `ffb_elite_status_feed` | 118825 | 3950 | 1950 | 2 | 87 | — |
| 3 | [Air Canada Aeroplan earn up to 3.5x points](https://blog.frequentflyerbonuses.com/2026/07/air-canada-aeroplan-earn-up-to-3-5x-points.html) | `ffb_elite_status_feed` | 118853 | 9381 | 5447 | 8 | 80 | — |
| 4 | [Air France KLM Flying Blue paid elite status match](https://blog.frequentflyerbonuses.com/2026/06/last-chance-air-france-klm-flying-blue-paid-elite-status-match.html) | `ffb_elite_status_feed` | 119868 | 9063 | 2894 | 3 | 82 | — |
| 5 | [World of Hyatt Globalist guide](https://awardwallet.com/hotels/world-of-hyatt/hyatt-globalist/) | `awardwallet_elite_status_feed` | 187928 | 30619 | 19889 | 24 | 246 | — |
| 6 | [Delta SkyMiles guide](https://awardwallet.com/airlines/delta-skymiles/) | `awardwallet_elite_status_feed` | 230919 | 57960 | 34936 | 84 | 272 | — |
| 7 | [Kenya Airways status match offer](https://awardwallet.com/airlines/kenya-airways-status-match-offer/) | `awardwallet_elite_status_feed` | 193760 | 30642 | 14776 | 22 | 234 | — |
| 8 | [Alaska corporate status challenge](https://awardwallet.com/news/alaska-atmos-rewards/alaska-corporate-status-challenge/) | `awardwallet_elite_status_feed` | 180377 | 20664 | 10874 | 90 | 227 | — |
| 9 | [AAdvantage elite status upgrades on premium economy tickets](https://awardwallet.com/news/american-aadvantage/elite-status-upgrades-premium-economy/) | `awardwallet_elite_status_feed` | 168478 | 8744 | 5014 | 5 | 221 | — |
| 10 | [Alaska Airlines buy miles bonus](https://loyaltylobby.com/2026/08/19/last-call-alaska-airlines-buy-miles-up-to-100-bonus-sale-until-august-20-2026/) | `loyaltylobby_feed` | 4917 | 4817 | 3361 | 5 | 1 | — |
| 11 | [American Airlines brings back seatback screens](https://loyaltylobby.com/2026/08/18/american-airlines-brings-back-seatback-screens-on-short-haul-aircraft-from-2028/) | `loyaltylobby_feed` | 6996 | 6908 | 5938 | 0 | 2 | — |
| 12 | [United Premier Gold benefit experience on Virgin Australia](https://loyaltylobby.com/2026/08/17/united-premier-gold-elite-benefit-experience-on-virgin-australia-domestic-flights/) | `loyaltylobby_feed` | 5461 | 5389 | 4162 | 3 | 1 | — |
| 13 | [Finnair Plus and Radisson Rewards conversions and tier match](https://loyaltylobby.com/2026/08/09/finnair-plus-radisson-rewards-launch-two-way-conversions-match/) | `loyaltylobby_feed` | 7753 | 7688 | 5645 | 3 | 1 | — |
| 14 | [IHG One Rewards double elite night credits](https://loyaltylobby.com/2026/08/08/update-ihg-one-rewards-double-elite-night-credits-august-5-september-29-2026/) | `loyaltylobby_feed` | 9079 | 8922 | 7900 | 9 | 1 | — |
| 15 | [Turkish Airlines reduces Oceania award pricing](https://loyaltylobby.com/2026/08/06/turkish-airlines-milessmiles-reduces-oceania-award-pricing/) | `loyaltylobby_feed` | 6328 | 6155 | 2844 | 1 | 1 | — |
| 16 | [Elite status via the Air France KLM credit card](https://frequentmiler.com/elite-status-via-the-air-france-klm-credit-card/) | `frequentmiler_elite_status_feed` | 21631 | 20545 | 14549 | 14 | 4 | — |
| 17 | [Targeted IHG double elite night credits](https://frequentmiler.com/targeted-ihg-promo-earn-double-elite-night-credits-limit-10-bonus-elite-nights/) | `frequentmiler_elite_status_feed` | 5621 | 5088 | 4641 | 2 | 2 | — |
| 18 | [Airport lounge access with Accor elite status](https://frequentmiler.com/how-to-get-access-to-airport-lounges-with-accor-elite-status/) | `frequentmiler_elite_status_feed` | 7298 | 6839 | 5960 | 14 | 2 | — |
| 19 | [Southwest SWABIZ A-List and points promotion](https://frequentmiler.com/southwest-promo-earn-a-list-status-20k-bonus-points-when-booking-via-swabiz/) | `frequentmiler_elite_status_feed` | 9287 | 8695 | 8042 | 3 | 2 | — |
| 20 | [Where Hyatt suite upgrade awards do not work](https://frequentmiler.com/where-hyatt-suite-upgrade-awards-dont-work/) | `frequentmiler_elite_status_feed` | 8709 | 8251 | 6670 | 9 | 2 | — |
| 21 | [GHA Discovery paid status match](https://frequentmiler.com/gha-discovery-hotel-program-status-match-from-many-hotel-airline-cruise-programs/) | `frequentmiler_elite_status_feed` | 10961 | 10510 | 9467 | 10 | 2 | — |
| 22 | [雅高A+促销，温德姆钻石新增早餐权益](https://www.verylvke.com/2026/08/17/accor-plus-wyndham-benefits-enhanced/) | `verylvke_feed` | 2189 | 2050 | 713 | 2 | 4 | — |
| 23 | [克拉科夫喜来登与老城英迪格入住体验](https://www.verylvke.com/2026/08/19/stay-krakow-sheraton-grand-hotel-indigo-old-town/) | `verylvke_feed` | 28617 | 28352 | 1769 | 2 | 59 | — |
| 24 | [璞富腾钛金匹配与Scandic兑换实战](https://www.verylvke.com/2026/08/03/iprefer-titanium-status-match-scandic-avios/) | `verylvke_feed` | 2864 | 2715 | 1195 | 3 | 4 | — |
| 25 | [雅高臻享卡促销与肯尼亚航空匹配](https://www.verylvke.com/2026/08/05/accor-all-plus-sale-kenya-airways-status-match/) | `verylvke_feed` | 3275 | 3123 | 1027 | 1 | 5 | — |
| 26 | [万豪与日本航空会籍合作](https://www.verylvke.com/2026/07/14/marriott-japan-airlines-partnership/) | `verylvke_feed` | 3339 | 3191 | 888 | 1 | 6 | — |
| 27 | [八大洲一住升金、雅典君悦好价与万豪贬值](https://www.verylvke.com/2026/07/07/badazhou-grand-hyatt-athens-marriott-devaluation/) | `verylvke_feed` | 5195 | 5087 | 1366 | 2 | 8 | — |
| 28 | [马来西亚航空会籍匹配活动](https://www.verylvke.com/2026/07/06/malaysia-airlines-status-match/) | `verylvke_feed` | 2116 | 1983 | 670 | 2 | 4 | — |
| 29 | [Trip夏日大促](https://www.verylvke.com/2026/07/05/trip-summer-mega-sale/) | `verylvke_feed` | 2388 | 2254 | 791 | 3 | 3 | — |
| 30 | [法航荷航和北欧航空会籍匹配](https://www.verylvke.com/2026/05/31/flying-blue-and-sas-status-match/) | `verylvke_feed` | 2122 | 1987 | 606 | 2 | 4 | — |

## 文章最终保留链接

### A01 Kenya Airways Asante Rewards SkyTeam paid status match

- [K**enya Airways Asante Rewards**](https://kenya-airways.statusmatch.com/?fpr=a254z2)
- [**Air France KLM Flying Blue** **Status Match offer**](https://flyingblue.statusmatch.com/?fpr=5zlmq)
- [**Vietnam Airlines paid status match opportunity**](https://vietnamairlines.statusmatch.com/?fpr=dv1gz)
- [**Kenya Airways paid status match opportunity**](https://kenya-airways.statusmatch.com/?fpr=a254z2)
- [Click here for more details on this status match offer.](https://kenya-airways.statusmatch.com/?fpr=a254z2)

丢弃链接共84个；前8个样例：
- `Home` — `https://blog.frequentflyerbonuses.com/`
- `Flight Bonuses` — `https://blog.frequentflyerbonuses.com/2026/08/kenya-airways-asante-rewards-skyteam-paid-status-match.html`
- `By Airline` — `https://www.frequentflyerbonuses.com/airline.html`
- `By Route` — `https://www.frequentflyerbonuses.com/routebonus.html`
- `Elite Status Offers` — `https://www.frequentflyerbonuses.com/statusoffers.html#air`
- `Buy Miles/Points Offers` — `https://www.frequentflyerbonuses.com/buymilesoffers.html`
- `Discounted Rewards` — `https://www.frequentflyerbonuses.com/discounted-rewards.html`
- `Free Miles & Points` — `https://www.frequentflyerbonuses.com/freemiles.html`

### A02 Receive up to a 50% bonus when you buy Marriott Bonvoy points

- [Click here for more details and to buy Marriott Bonvoy Points](https://www.jdoqocy.com/click-1654157-11769493)
- [**You can find the latest individual Marriott property stay bonuses on our Marriott page**](https://www.frequentflyerbonuses.com/marriott.html#count)

丢弃链接共87个；前8个样例：
- `Home` — `https://blog.frequentflyerbonuses.com/`
- `Flight Bonuses` — `https://blog.frequentflyerbonuses.com/2026/08/receive-up-to-a-50-bonus-when-you-buy-marriott-bonvoy-points.html`
- `By Airline` — `https://www.frequentflyerbonuses.com/airline.html`
- `By Route` — `https://www.frequentflyerbonuses.com/routebonus.html`
- `Elite Status Offers` — `https://www.frequentflyerbonuses.com/statusoffers.html#air`
- `Buy Miles/Points Offers` — `https://www.frequentflyerbonuses.com/buymilesoffers.html`
- `Discounted Rewards` — `https://www.frequentflyerbonuses.com/discounted-rewards.html`
- `Free Miles & Points` — `https://www.frequentflyerbonuses.com/freemiles.html`

### A03 Air Canada Aeroplan earn up to 3.5x points

- [**Click here to book this offer**](https://www.aircanada.com/en-ca/?acid=EXT:EML:SummerWWSS26:PRJAC40000116:URL4372:ACsoloExtended&recdelid=379465752|590777746)
- [**Click here to book this offer**](https://www.aircanada.com/en-ca/?acid=EXT:EML:SummerWWSS26:PRJAC40000116:URL4372:ACsoloExtended&recdelid=379465752|590777746)
- [**Click here to book this offer**](https://www.aircanada.com/en-ca/?acid=EXT:EML:SummerWWSS26:PRJAC40000116:URL4372:ACsoloExtended&recdelid=379465752|590777746)
- [**Click here to book these offers**](https://www.aircanada.com/en-ca/?acid=EXT:EML:SummerWWSS26:PRJAC40000116:URL4372:ACsoloExtended&recdelid=379465752|590777746)
- [**Click here to book these offers**](https://www.aircanada.com/en-ca/?acid=EXT:EML:SummerWWSS26:PRJAC40000116:URL4372:ACsoloExtended&recdelid=379465752|590777746)
- [**Click here to book these offers**](https://www.aircanada.com/en-ca/?acid=EXT:EML:SummerWWSS26:PRJAC40000116:URL4372:ACsoloExtended&recdelid=379465752|590777746)
- [**American Express® Aeroplan®\* Reserve Card**](https://www.rewardscanada.ca/links/amexapreserve.html)
- [**TD® Aeroplan® Visa Infinite Privilege\* Card**](https://www.rewardscanada.ca/links/tdappriv.html)

丢弃链接共80个；前8个样例：
- `Home` — `https://blog.frequentflyerbonuses.com/`
- `Flight Bonuses` — `https://blog.frequentflyerbonuses.com/2026/07/air-canada-aeroplan-earn-up-to-3-5x-points.html`
- `By Airline` — `https://www.frequentflyerbonuses.com/airline.html`
- `By Route` — `https://www.frequentflyerbonuses.com/routebonus.html`
- `Elite Status Offers` — `https://www.frequentflyerbonuses.com/statusoffers.html#air`
- `Buy Miles/Points Offers` — `https://www.frequentflyerbonuses.com/buymilesoffers.html`
- `Discounted Rewards` — `https://www.frequentflyerbonuses.com/discounted-rewards.html`
- `Free Miles & Points` — `https://www.frequentflyerbonuses.com/freemiles.html`

### A04 Air France KLM Flying Blue paid elite status match

- [Click here to learn more and to apply for the Vietnam Airlines paid status match](https://vietnamairlines.statusmatch.com/?fpr=dv1gz)
- [**paid status match opportunity**](https://flyingblue.statusmatch.com/?fpr=5zlmq)
- [Click here for more details on this status match offer.](https://flyingblue.statusmatch.com/?fpr=5zlmq)

丢弃链接共82个；前8个样例：
- `Home` — `https://blog.frequentflyerbonuses.com/`
- `Flight Bonuses` — `https://blog.frequentflyerbonuses.com/2026/06/last-chance-air-france-klm-flying-blue-paid-elite-status-match.html`
- `By Airline` — `https://www.frequentflyerbonuses.com/airline.html`
- `By Route` — `https://www.frequentflyerbonuses.com/routebonus.html`
- `Elite Status Offers` — `https://www.frequentflyerbonuses.com/statusoffers.html#air`
- `Buy Miles/Points Offers` — `https://www.frequentflyerbonuses.com/buymilesoffers.html`
- `Discounted Rewards` — `https://www.frequentflyerbonuses.com/discounted-rewards.html`
- `Free Miles & Points` — `https://www.frequentflyerbonuses.com/freemiles.html`

### A05 World of Hyatt Globalist guide

- [The World of Hyatt Program — A Complete Guide](https://awardwallet.com/hotels/world-of-hyatt/)
- [earn Hyatt qualifying nights](https://awardwallet.com/hotels/world-of-hyatt/elite-night-credits/)
- [World of Hyatt program](https://awardwallet.com/hotels/world-of-hyatt/)
- [The World of Hyatt Credit Card](https://awardwallet.com/credit-cards/world-of-hyatt/chase-hyatt-card/)
- [Category 1–4 free night certificate](https://awardwallet.com/hotels/world-of-hyatt/hyatt-category-4/)
- [Rates & Fees](https://click.linksynergy.com/fs-bin/click?id=g3lR0xvjyAU&offerid=1753725.10005136&type=3&u1=747755f113fb7e8f1fd70bf7bce645e0&subid=639396)
- [Show more](https://awardwallet.com/hotels/world-of-hyatt/hyatt-globalist/#more)
- [World of Hyatt Business Credit Card](https://awardwallet.com/credit-cards/world-of-hyatt/hyatt-business-card/)
- [Rates & Fees](https://click.linksynergy.com/fs-bin/click?id=g3lR0xvjyAU&offerid=1753725.10005137&type=3&u1=277ab54e929fcfa22a99508c775de755&subid=639396)
- [Show more](https://awardwallet.com/hotels/world-of-hyatt/hyatt-globalist/#more)
- [Four Ways To Score Free Breakfast at Hyatt Hotels](https://awardwallet.com/hotels/world-of-hyatt/free-breakfast/)
- [Hyatt doesn't regularly offer a standing status match](https://awardwallet.com/hotels/world-of-hyatt/elite-status-shortcuts/)
- [Hotel Elite Status Made Easy: Status Matches, Fast Tracks, and Credit Card Perks](https://awardwallet.com/hotels/status-match-offers/)
- [Advance booking access](https://awardwallet.com/hotels/world-of-hyatt/advance-award-access/)
- [Sweet Spots for World of Hyatt Award Redemptions](https://awardwallet.com/hotels/world-of-hyatt/best-hyatt-redemptions/)
- [revamped Milestone Rewards tiers](https://awardwallet.com/hotels/world-of-hyatt/milestone-rewards/)
- [FIND experience](https://experiences.hyatt.com/)
- [Guest of Honor awards](https://awardwallet.com/hotels/world-of-hyatt/guest-of-honor/)
- [Free Night Award](https://awardwallet.com/hotels/world-of-hyatt/using-the-right-hyatt-certificate/)
- [Suite Upgrade Awards](https://awardwallet.com/hotels/world-of-hyatt/hyatt-suite-upgrade-award/)
- [Hyatt Business Card](https://awardwallet.com/credit-cards/world-of-hyatt/hyatt-business-card/)
- [World of Hyatt Card](https://awardwallet.com/credit-cards/world-of-hyatt/chase-hyatt-card/)
- [裸URL](https://awardwallet.com/blog/link/TheWorldOfHyattCreditCard?var2=pid~144394)
- [裸URL](https://awardwallet.com/blog/link/WorldOfHyattBusinessCreditCard?var2=pid~144394)

丢弃链接共246个；前8个样例：
- `空链接` — `https://awardwallet.com/learn/`
- `American AAdvantage` — `https://awardwallet.com/learn/american-aadvantage`
- `United MileagePlus` — `https://awardwallet.com/learn/united-mileageplus`
- `Delta SkyMiles` — `https://awardwallet.com/learn/delta-skymiles`
- `British Airways Club` — `https://awardwallet.com/learn/british-airways-club`
- `Southwest Rapid Rewards` — `https://awardwallet.com/learn/southwest-rapid-rewards`
- `JetBlue TrueBlue` — `https://awardwallet.com/learn/jetblue-trueblue`
- `Alaska Mileage Plan` — `https://awardwallet.com/learn/alaska-mileage-plan`

### A06 Delta SkyMiles guide

- [best suites of co-branded credit cards on the market](https://awardwallet.com/credit-cards/delta-skymiles/delta-credit-card/)
- [SkyTeam airline alliance](https://awardwallet.com/airlines/airline-alliances-and-partnerships/)
- [Delta miles don't expire](https://awardwallet.com/airlines/delta-skymiles/do-delta-miles-expire/)
- [delta.com](http://delta.com)
- [adding your Delta account number in AwardWallet](https://awardwallet.com/account/add/7)
- [link the email](https://awardwallet.com/mailboxes/)
- [How To Track Delta, Southwest, United Accounts in AwardWallet](https://awardwallet.com/features/track-delta-united-southwest-points/)
- [Delta co-branded credit cards](https://awardwallet.com/credit-cards/delta-skymiles/delta-credit-card/)
- [buy Delta miles](https://awardwallet.com/airlines/delta-skymiles/buy-delta-miles/)
- [co-branded credit card lineups](https://awardwallet.com/credit-cards/delta-skymiles/delta-credit-card/)
- [15% discount](https://awardwallet.com/credit-cards/delta-skymiles/delta-award-discount/)
- [annual companion fare certificates](https://awardwallet.com/credit-cards/delta-skymiles/delta-companion-certificate/)
- [earn Delta Medallion status](https://awardwallet.com/airlines/delta-skymiles/medallion-status/)
- [Delta SkyMiles® Blue American Express Card](https://awardwallet.com/blog/link/CR-BlueDeltaSkyMilesCreditCardfromAmericanExpress?var2=pid~101311)
- [Delta SkyMiles® Gold American Express Card](https://awardwallet.com/blog/link/CR-GoldDeltaSkyMilesCreditCardfromAmericanExpress?var2=pid~101311)
- [Delta SkyMiles® Platinum American Express Card](https://awardwallet.com/blog/link/CR-PlatinumDeltaSkyMilesCreditCardfromAmericanExpress?var2=pid~101311)
- [Delta SkyMiles® Reserve American Express Card](https://awardwallet.com/blog/link/CR-DeltaReserveCreditCardfromAmericanExpress?var2=pid~101311)
- [Delta SkyMiles® Gold Business American Express Card](https://awardwallet.com/blog/link/GoldDeltaSkyMilesBusinessCreditCardfromAmericanExpress?var2=pid~101311)
- [Delta SkyMiles® Platinum Business American Express Card](https://awardwallet.com/blog/link/PlatinumDeltaSkyMilesBusinessCreditCard?var2=pid~101311)
- [Delta SkyMiles® Reserve Business American Express Card](https://awardwallet.com/blog/link/DeltaReserveforBusinessCreditCard?var2=pid~101311)
- [once-per-lifetime rule](https://awardwallet.com/credit-cards/amex-welcome-offer-eligibility-tool/)
- [Amex added card “family” restrictions to Delta cards](https://awardwallet.com/credit-cards/delta-skymiles/delta-amex-offer-eligibility/)
- [American Express Membership Rewards transfer partner](https://awardwallet.com/credit-cards/amex-membership-rewards/amex-transfer-partners/)
- [generally instant](https://awardwallet.com/en/mile-transfer-times)
- [Membership Rewards-earning cards](https://awardwallet.com/credit-cards/amex-membership-rewards/amex-rewards-cards/)
- [American Express Platinum Card®](https://awardwallet.com/blog/link/CR-ThePlatinumCardfromAmericanExpress?var2=pid~101311)
- [comes with several Delta-specific perks](https://awardwallet.com/credit-cards/amex-membership-rewards/amex-platinum/)
- [American Express® Gold Card](https://awardwallet.com/blog/link/CR-AmericanExpressGoldCard?var2=pid~101311)
- [The Blue Business® Plus Credit Card from American Express](https://awardwallet.com/blog/link/TheBlueBusinessPlusCreditCardfromAmericanExpress?var2=pid~101311)
- [How To Transfer Amex Points: A Step-by-Step Guide](https://awardwallet.com/credit-cards/amex-membership-rewards/how-to-transfer-amex-points/)
- [Delta's partner airlines](https://www.delta.com/us/en/skymiles/how-to-earn-miles/airline-partners)
- [SkyMiles partners](https://www.delta.com/us/en/skymiles/how-to-earn-miles/skymiles-partners-offers)
- [Starbucks](https://awardwallet.com/airlines/delta-skymiles/starbucks-partnership/)
- [Uber](https://awardwallet.com/airlines/delta-skymiles/delta-uber-partnership/)
- [earn miles by booking a Delta Vacations package](https://awardwallet.com/airlines/delta-skymiles/delta-vacations/)
- [Delta and Hertz Improve Partnership With a Status Match and Enhanced Mileage Earning](https://awardwallet.com/news/delta-skymiles/delta-hertz/)
- [convert hotel points to Delta SkyMiles](https://www.delta.com/us/en/skymiles/how-to-earn-miles/convert-partner-points)
- [Accor Live Limitless](https://awardwallet.com/hotels/accor-live-limitless/)
- [Marriott Bonvoy](https://awardwallet.com/hotels/marriott-bonvoy/)
- [Hilton Honors](https://awardwallet.com/hotels/hilton-honors/)
- [IHG One Rewards](https://awardwallet.com/hotels/ihg-one-rewards/)
- [transferring Marriott points 3:1](https://awardwallet.com/hotels/marriott-bonvoy/marriott-transfer-partners/)
- [Marriott (Bonvoy)](https://awardwallet.com/hotels/marriott-bonvoy/marriott-transfer-partners/?cid=transfer-times-transfer&mid=web)
- [Delta Air Lines (SkyMiles)](https://awardwallet.com/airlines/delta-skymiles/delta-partner-airlines/?cid=transfer-times-transfer&mid=web)
- [Delta Air Lines (SkyMiles)](https://awardwallet.com/airlines/delta-skymiles/delta-partner-airlines/?cid=transfer-times-transfer&mid=web)
- [Hilton (Honors)](https://awardwallet.com/hotels/hilton-honors/transfer-hilton-points/?cid=transfer-times-transfer&mid=web)
- [Delta Air Lines (SkyMiles)](https://awardwallet.com/airlines/delta-skymiles/delta-partner-airlines/?cid=transfer-times-transfer&mid=web)
- [Delta Air Lines (SkyMiles)](https://awardwallet.com/airlines/delta-skymiles/delta-partner-airlines/?cid=transfer-times-transfer&mid=web)
- [Delta Air Lines (SkyMiles)](https://awardwallet.com/airlines/delta-skymiles/delta-partner-airlines/?cid=transfer-times-transfer&mid=web)
- [Delta Air Lines (SkyMiles)](https://awardwallet.com/airlines/delta-skymiles/delta-partner-airlines/?cid=transfer-times-transfer&mid=web)
- [online shopping portal](https://www.skymilesshopping.com/)
- [SkyMiles Dining](https://www.skymilesdining.com/)
- [buy Delta miles](https://awardwallet.com/airlines/delta-skymiles/buy-delta-miles/)
- [Gifting SkyMiles](https://www.delta.com/buygftxfer/displayGiftMiles.action)
- [see here for point and mile value data points from AwardWallet users](https://awardwallet.com/point-mile-values)
- [Alaska Airlines Mileage Plan](https://awardwallet.com/airlines/alaska-atmos-rewards/)
- [United Airlines MileagePlus](https://awardwallet.com/airlines/united-mileageplus/)
- [Southwest Airlines Rapid Rewards](https://awardwallet.com/airlines/southwest-rapid-rewards/)
- [dynamic pricing](https://awardwallet.com/travel/what-is-dynamic-pricing/)
- [unofficial Delta SkyMiles award chart](https://awardwallet.com/airlines/delta-skymiles/how-many-delta-miles-for-a-flight/)
- [the average value of each Delta SkyMile is 1.35¢](https://awardwallet.com/point-mile-values/Delta)
- [significant devaluations](https://awardwallet.com/airlines/delta-skymiles/how-many-delta-miles-for-a-flight/)
- [Delta Main Basic](https://awardwallet.com/airlines/delta-skymiles/delta-basic-economy/)
- [Delta Premium Select](https://awardwallet.com/news/delta-skymiles/premium-select-hawaii/)
- [Delta One](https://awardwallet.com/airlines/delta-skymiles/delta-one/)
- [change and cancellation fees](https://awardwallet.com/airlines/award-ticket-change-and-cancellation-policies/)
- [Airline Programs That Don't Add Fees and Surcharges to Award Flights](https://awardwallet.com/airlines/avoid-surcharges-award-flights/)
- [occasional award sales](https://awardwallet.com/news/delta-skymiles/delta-flash-sale/)
- [the best ways to use Delta SkyMiles](https://awardwallet.com/airlines/delta-skymiles/best-ways-to-use-delta-miles/)
- [Medallion Qualification Dollars](https://awardwallet.com/airlines/delta-skymiles/medallion-qualification-dollar/)
- [with the exception of Delta Main Basic](https://awardwallet.com/news/delta-skymiles/basic-economy-changes-2021/)
- [How To Status Match to Delta for Elite Perks](https://awardwallet.com/airlines/delta-skymiles/delta-status-match/)
- [Delta Reserve](https://awardwallet.com/blog/link/CR-DeltaReserveCreditCardfromAmericanExpress?var2=pid~101311)
- [Delta Platinum Amex](https://awardwallet.com/blog/link/CR-PlatinumDeltaSkyMilesCreditCardfromAmericanExpress?var2=pid~101311)
- [Delta Reserve](https://awardwallet.com/blog/link/CR-DeltaReserveCreditCardfromAmericanExpress?var2=pid~101311)
- [Delta Reserve](https://awardwallet.com/blog/link/CR-DeltaReserveCreditCardfromAmericanExpress?var2=pid~101311)
- [Delta Reserve](https://awardwallet.com/blog/link/CR-DeltaReserveCreditCardfromAmericanExpress?var2=pid~101311)
- [Delta Reserve](https://awardwallet.com/blog/link/CR-DeltaReserveCreditCardfromAmericanExpress?var2=pid~101311)
- [Delta Reserve](https://awardwallet.com/blog/link/CR-DeltaReserveCreditCardfromAmericanExpress?var2=pid~101311)
- [Choice Benefits](https://awardwallet.com/airlines/delta-skymiles/delta-choice-benefits/)
- [Delta Medallion elite status](https://awardwallet.com/airlines/delta-skymiles/medallion-status/)
- [Million Miler](https://www.delta.com/us/en/skymiles/medallion-program/million-miler)
- [China Airlines business class with my son to Taipei](https://travelupdate.com/china-airlines-777-300er-business-class-review-san-francisco-taipei/)
- [here](https://www.delta.com/us/en/need-help/support-skymiles)

丢弃链接共272个；前8个样例：
- `空链接` — `https://awardwallet.com/learn/`
- `American AAdvantage` — `https://awardwallet.com/learn/american-aadvantage`
- `United MileagePlus` — `https://awardwallet.com/learn/united-mileageplus`
- `Delta SkyMiles` — `https://awardwallet.com/learn/delta-skymiles`
- `British Airways Club` — `https://awardwallet.com/learn/british-airways-club`
- `Southwest Rapid Rewards` — `https://awardwallet.com/learn/southwest-rapid-rewards`
- `JetBlue TrueBlue` — `https://awardwallet.com/learn/jetblue-trueblue`
- `Alaska Mileage Plan` — `https://awardwallet.com/learn/alaska-mileage-plan`

### A07 Kenya Airways status match offer

- [this status match is worth looking into](https://kenya-airways.statusmatch.com/?fpr=4qmrl)
- [Asante Rewards loyalty program](https://awardwallet.com/airlines/kenya-airways-rewards/)
- [apply for the Kenya Airways status match](https://kenya-airways.statusmatch.com/?fpr=4qmrl)
- [SkyTeam Elite Plus](https://awardwallet.com/airlines/skyteam-elite-plus-status/)
- [Kenya Airways status match website](https://kenya-airways.statusmatch.com/?fpr=4qmrl)
- [click here to register](https://asante.kenya-airways.com/enrollment/quick)
- [add your Kenya Airways account to AwardWallet](https://awardwallet.com/account/add/5280)
- [Marriott Bonvoy® Gold Elite Status](https://awardwallet.com/hotels/marriott-bonvoy/gold-elite-benefits/)
- [American Express Platinum Card®](https://awardwallet.com/credit-cards/amex-membership-rewards/amex-platinum/)
- [Shortcuts to Elite Status with Airline Status Match, Fast Track](https://awardwallet.com/airlines/status-match-offers/)
- [likely code as online shopping](https://awardwallet.com/merchants/STATUSMATCH+COM_63381324)
- [Citi Double Cash® Card](https://awardwallet.com/credit-cards/citi-thankyou-rewards/citi-double-cash-card/)
- [Bilt Palladium Card](https://awardwallet.com/credit-cards/bilt-rewards/bilt-palladium-card/)
- [Rates & Fees](https://legal.cardless.com/rates_and_fees/bilt/rates_and_fees.pdf)
- [Capital One Venture Rewards Credit Card](https://awardwallet.com/credit-cards/capital-one-rewards/venture-card/)
- [Air France/KLM](https://awardwallet.com/airlines/flying-blue/)
- [Virgin Atlantic](https://awardwallet.com/airlines/virgin-atlantic-flying-club/)
- [Delta Air Lines](https://awardwallet.com/airlines/delta-skymiles/)
- [loyalty benefits calculator](https://www.skyteam.com/en/frequent-flyers/)
- [Vietnam Airlines status match](https://awardwallet.com/news/airlines/vietnam-airlines-status-match/)
- [Flying Blue status match](https://awardwallet.com/news/flying-blue/status-match-flying-blue/)
- [Here's the link to apply for Kenya Airways Asante Rewards status match](https://kenya-airways.statusmatch.com/?fpr=4qmrl)

丢弃链接共234个；前8个样例：
- `空链接` — `https://awardwallet.com/learn/`
- `American AAdvantage` — `https://awardwallet.com/learn/american-aadvantage`
- `United MileagePlus` — `https://awardwallet.com/learn/united-mileageplus`
- `Delta SkyMiles` — `https://awardwallet.com/learn/delta-skymiles`
- `British Airways Club` — `https://awardwallet.com/learn/british-airways-club`
- `Southwest Rapid Rewards` — `https://awardwallet.com/learn/southwest-rapid-rewards`
- `JetBlue TrueBlue` — `https://awardwallet.com/learn/jetblue-trueblue`
- `Alaska Mileage Plan` — `https://awardwallet.com/learn/alaska-mileage-plan`

### A08 Alaska corporate status challenge

- [Atmos Rewards](https://awardwallet.com/airlines/alaska-atmos-rewards/)
- [Atmos Gold status](https://awardwallet.com/airlines/alaska-atmos-rewards/alaska-gold-elite-status/)
- [Alaska's general status match](https://awardwallet.com/airlines/alaska-atmos-rewards/alaska-status-match/)
- [full guide to the Alaska Airlines Atmos Rewards program](https://awardwallet.com/airlines/alaska-atmos-rewards/)
- [this general status match promotion](https://awardwallet.com/airlines/alaska-atmos-rewards/alaska-status-match/)
- [裸URL](https://www.alaskaair.com/promotion/cs2332)
- [裸URL](https://www.alaskaair.com/promo/AS2374)
- [裸URL](https://www.alaskaair.com/promotion/cs2358)
- [裸URL](https://www.alaskaair.com/promo/AS2354)
- [裸URL](https://www.alaskaair.com/promo/AS2372)
- [裸URL](https://www.alaskaair.com/promotion/cs2320)
- [裸URL](https://www.alaskaair.com/promotion/cs2337)
- [裸URL](https://www.alaskaair.com/promotion/cs2349)
- [裸URL](https://www.alaskaair.com/promotion/cs2347)
- [裸URL](https://www.alaskaair.com/promotion/cs2329)
- [裸URL](https://www.alaskaair.com/promotion/cs2307)
- [裸URL](https://www.alaskaair.com/promotion/cs2326)
- [裸URL](https://www.alaskaair.com/promo/AS2368)
- [裸URL](https://www.alaskaair.com/promotion/cs2350)
- [裸URL](https://www.alaskaair.com/promotion/cs2354)
- [裸URL](https://www.alaskaair.com/promotion/cs2334)
- [裸URL](https://www.alaskaair.com/promotion/cs2319)
- [裸URL](https://www.alaskaair.com/promo/AS2345)
- [裸URL](https://www.alaskaair.com/promotion/cs2317)
- [裸URL](https://www.alaskaair.com/promo/AS2373)
- [裸URL](https://www.alaskaair.com/promotion/cs2345)
- [裸URL](https://www.alaskaair.com/promo/AS2378)
- [裸URL](https://www.alaskaair.com/promo/AS2348)
- [裸URL](https://www.alaskaair.com/promotion/cs2315)
- [裸URL](https://www.alaskaair.com/promotion/cs2316)
- [裸URL](https://www.alaskaair.com/promo/AS2370)
- [裸URL](https://www.alaskaair.com/promotion/cs2342)
- [裸URL](https://www.alaskaair.com/promotion/cs2352)
- [裸URL](https://www.alaskaair.com/promo/AS2356)
- [裸URL](https://www.alaskaair.com/promo/AS2365)
- [裸URL](https://www.alaskaair.com/promotion/cs2351)
- [裸URL](https://www.alaskaair.com/promo/AS2342)
- [裸URL](https://www.alaskaair.com/promotion/cs2346)
- [裸URL](https://www.alaskaair.com/promotion/cs2321)
- [裸URL](https://www.alaskaair.com/promotion/cs2356)
- [裸URL](https://www.alaskaair.com/promotion/cs2306)
- [裸URL](https://www.alaskaair.com/promo/AS2346)
- [裸URL](https://www.alaskaair.com/promotion/cs2323)
- [裸URL](https://www.alaskaair.com/promo/AS2375)
- [裸URL](https://www.alaskaair.com/promo/AS2367)
- [裸URL](https://www.alaskaair.com/promo/AS2351)
- [裸URL](https://www.alaskaair.com/promo/AS2366)
- [裸URL](https://www.alaskaair.com/promotion/cs2310)
- [裸URL](https://www.alaskaair.com/promo/AS2350)
- [裸URL](https://www.alaskaair.com/promo/AS2380)
- [裸URL](https://www.alaskaair.com/promotion/cs2311)
- [裸URL](https://www.alaskaair.com/promotion/cs2327)
- [裸URL](https://www.alaskaair.com/promotion/cs2308)
- [裸URL](https://www.alaskaair.com/promotion/cs2339)
- [裸URL](https://www.alaskaair.com/promotion/cs2353)
- [裸URL](https://www.alaskaair.com/promotion/cs2312)
- [裸URL](https://www.alaskaair.com/promotion/cs2302)
- [裸URL](https://www.alaskaair.com/promotion/cs2335)
- [裸URL](https://www.alaskaair.com/promo/AS2377)
- [裸URL](https://www.alaskaair.com/promotion/cs2325)
- [裸URL](https://www.alaskaair.com/promotion/cs2313)
- [裸URL](https://www.alaskaair.com/promo/AS2349)
- [裸URL](https://www.alaskaair.com/promo/AS2370)
- [裸URL](https://www.alaskaair.com/promo/AS2371)
- [裸URL](https://www.alaskaair.com/promotion/cs2314)
- [裸URL](https://www.alaskaair.com/promotion/cs2355)
- [裸URL](https://www.alaskaair.com/promo/AS2347)
- [裸URL](https://www.alaskaair.com/promotion/cs2343)
- [裸URL](https://www.alaskaair.com/promotion/cs2328)
- [裸URL](https://www.alaskaair.com/promotion/cs2318)
- [裸URL](https://www.alaskaair.com/promo/AS2343)
- [裸URL](https://www.alaskaair.com/promo/AS2344)
- [裸URL](https://www.alaskaair.com/promo/AS2369)
- [裸URL](https://www.alaskaair.com/promotion/cs2328)
- [裸URL](https://www.alaskaair.com/promotion/cs2305)
- [裸URL](https://www.alaskaair.com/promotion/cs2324)
- [裸URL](https://www.alaskaair.com/promotion/cs2330)
- [裸URL](https://www.alaskaair.com/promotion/cs2303)
- [裸URL](https://www.alaskaair.com/promotion/cs2348)
- [裸URL](https://www.alaskaair.com/promo/AS2341)
- [裸URL](https://www.alaskaair.com/promotion/cs2333)
- [裸URL](https://www.alaskaair.com/promotion/cs2344)
- [裸URL](https://www.alaskaair.com/promotion/cs2338)
- [裸URL](https://www.alaskaair.com/promotion/cs2322)
- [裸URL](https://www.alaskaair.com/promotion/cs2359)
- [裸URL](https://www.alaskaair.com/promotion/cs2304)
- [裸URL](https://www.alaskaair.com/promo/AS2355)
- [裸URL](https://www.alaskaair.com/promotion/cs2357)
- [裸URL](https://www.alaskaair.com/promotion/cs2328)
- [裸URL](https://www.alaskaair.com/promo/AS2381)

丢弃链接共227个；前8个样例：
- `空链接` — `https://awardwallet.com/learn/`
- `American AAdvantage` — `https://awardwallet.com/learn/american-aadvantage`
- `United MileagePlus` — `https://awardwallet.com/learn/united-mileageplus`
- `Delta SkyMiles` — `https://awardwallet.com/learn/delta-skymiles`
- `British Airways Club` — `https://awardwallet.com/learn/british-airways-club`
- `Southwest Rapid Rewards` — `https://awardwallet.com/learn/southwest-rapid-rewards`
- `JetBlue TrueBlue` — `https://awardwallet.com/learn/jetblue-trueblue`
- `Alaska Mileage Plan` — `https://awardwallet.com/learn/alaska-mileage-plan`

### A09 AAdvantage elite status upgrades on premium economy tickets

- [refresh of the Citi® / AAdvantage® Executive World Elite Mastercard®](https://awardwallet.com/news/american-aadvantage/citi-aadvantage-executive-card-2026-refresh/)
- [increase Admirals Club® memberships by as much as 65%](https://awardwallet.com/news/american-aadvantage/admirals-club-membership-fee-increase/)
- [AAdvantage elite members](https://awardwallet.com/airlines/american-aadvantage/elite-status/)
- [Systemwide Upgrades](https://awardwallet.com/airlines/american-aadvantage/systemwide-upgrades/)
- [How To Fly American Airlines' Best Business (and First) Class Seats Within the U.S.](https://awardwallet.com/airlines/american-aadvantage/domestic-first-class-lie-flat-seats/)

丢弃链接共221个；前8个样例：
- `空链接` — `https://awardwallet.com/learn/`
- `American AAdvantage` — `https://awardwallet.com/learn/american-aadvantage`
- `United MileagePlus` — `https://awardwallet.com/learn/united-mileageplus`
- `Delta SkyMiles` — `https://awardwallet.com/learn/delta-skymiles`
- `British Airways Club` — `https://awardwallet.com/learn/british-airways-club`
- `Southwest Rapid Rewards` — `https://awardwallet.com/learn/southwest-rapid-rewards`
- `JetBlue TrueBlue` — `https://awardwallet.com/learn/jetblue-trueblue`
- `Alaska Mileage Plan` — `https://awardwallet.com/learn/alaska-mileage-plan`

### A10 Alaska Airlines buy miles bonus

- [Buy Miles Mystery Sale](http://www.kqzyfj.com/click-7304739-11347188)
- [Alaska Airlines](http://www.kqzyfj.com/click-7304739-11347188)
- [here](http://www.kqzyfj.com/click-7304739-11347188)
- [Points.com](https://www.points.com)
- [Points.com](https://www.points.com)

丢弃链接共1个；前8个样例：
- `Source` — `https://loyaltylobby.com/2026/08/19/last-call-alaska-airlines-buy-miles-up-to-100-bonus-sale-until-august-20-2026/`

### A11 American Airlines brings back seatback screens

— 无保留链接

丢弃链接共2个；前8个样例：
- `空链接` — `https://s202.q4cdn.com/986123435/files/images/thumbs/081826-Premium-Seatback-IFE-01.jpg`
- `Source` — `https://loyaltylobby.com/2026/08/18/american-airlines-brings-back-seatback-screens-on-short-haul-aircraft-from-2028/`

### A12 United Premier Gold benefit experience on Virgin Australia

- [here](https://loyaltylobby.com/2021/12/13/virgin-australia-partners-with-united-drops-delta/)
- [here](https://www.united.com/en/us/fly/mileageplus/partners/earn-miles-on-virgin-australia.html)
- [Virgin Australia operated lounges.](https://www.virginaustralia.com/au/en/travel-info/at-the-airport/lounge/)

丢弃链接共1个；前8个样例：
- `Source` — `https://loyaltylobby.com/2026/08/17/united-premier-gold-elite-benefit-experience-on-virgin-australia-domestic-flights/`

### A13 Finnair Plus and Radisson Rewards conversions and tier match

- [here](https://www.finnairshop.com/en/radisson)
- [here](https://www.awin1.com/cread.php?awinmid=5907&awinaffid=191485&ued=https://www.radissonhotels.com/en-us/rewards/earn/radisson-rewards-finnair)
- [Finnair Shop](https://www.finnairshop.com/en/radisson)

丢弃链接共1个；前8个样例：
- `Source` — `https://loyaltylobby.com/2026/08/09/finnair-plus-radisson-rewards-launch-two-way-conversions-match/`

### A14 IHG One Rewards double elite night credits

- [here](https://loyaltylobby.com/2026/08/05/ihg-one-rewards-double-elite-qualifying-nights-max-5-august-september-30-2026/)
- [here](http://www.tkqlhce.com/click-7304739-13183673?url=https://www.ihg.com/rewardsclub/gb/en/offers/promoreg/?offerCode=78400)
- [here](http://www.tkqlhce.com/click-7304739-13183673?url=https://www.ihg.com/rewardsclub/gb/en/offers/promoreg/?offerCode=35355)
- [IHG One Rewards Rate & Bonus Points Offers](https://loyaltylobby.com/hotel-promotions/ihg-rewards-club/)
- [IHG One Rewards Membership Terms and Conditions](https://www.ihg.com/content/gb/en/customer-care/member-tc?cm_mmc=EMAIL-_-IHGRC-_-AMEA-_-en-_-LFC-_-NT0826Reg_20262844-_-SENDURLID-_-516288&mi_u=35032969&mi_ecmp=516288)
- [here](https://www.ihg.com/content/gb/en/customer-care/member-tc/2nd-page?cm_mmc=EMAIL-_-IHGRC-_-AMEA-_-en-_-LFC-_-NT0826Reg_20262844-_-SENDURLID-_-516288&mi_u=35032969&mi_ecmp=516288#milestonerewards)
- [IHG One Rewards Membership Terms and Conditions](https://www.ihg.com/content/gb/en/customer-care/member-tc?cm_mmc=EMAIL-_-IHGRC-_-AMEA-_-en-_-LFC-_-NT0826Reg_20262844-_-SENDURLID-_-516288&mi_u=35032969&mi_ecmp=516288)
- [here](https://www.ihg.com/content/gb/en/customer-care/member-tc?cm_mmc=EMAIL-_-IHGRC-_-AMEA-_-en-_-LFC-_-NT0826Reg_20262844-_-SENDURLID-_-516288&mi_u=35032969&mi_ecmp=516288)
- [‍ihgonerewards.com‍](https://www.ihg.com/onerewards/content/gb/en/home?cm_mmc=EMAIL-_-IHGRC-_-AMEA-_-en-_-LFC-_-NT0826Reg_20262844-_-SENDURLID-_-516288&mi_u=35032969&mi_ecmp=516288)

丢弃链接共1个；前8个样例：
- `Source` — `https://loyaltylobby.com/2026/08/08/update-ihg-one-rewards-double-elite-night-credits-august-5-september-29-2026/`

### A15 Turkish Airlines reduces Oceania award pricing

- [here](https://www.tkqlhce.com/click-7304739-17015243?url=https://www.turkishairlines.com/en-int/miles-and-smiles/redeem-miles/redeem-miles-on-flights/turkish-airlines-award-tickets/)

丢弃链接共1个；前8个样例：
- `Source` — `https://loyaltylobby.com/2026/08/06/turkish-airlines-milessmiles-reduces-oceania-award-pricing/`

### A16 Elite status via the Air France KLM credit card

- [Air France KLM Visa Signature® Credit Card](https://frequentmiler.com/afklm/)
- [Air France KLM Visa Signature® Credit Card](https://frequentmiler.com/afklm/)
- [Details here](https://www.flyingblue.com/en/mileshub/donate)
- [Details here](https://wwws.airfrance.fr/en/information/aeroport/options/option-environnement)
- [This SkyStatus post](https://skystatus.pro/guide/flying-blue-earn-xp-fast)
- [Air France KLM Visa Signature® Credit Card](https://frequentmiler.com/afklm/)
- [Air France KLM Visa Signature® Credit Card](https://frequentmiler.com/AFKLM/#Goto)
- [through a status match, for example](https://frequentmiler.com/flying-blue-status-match-for-us-residents/)
- [through a status match, for example](https://frequentmiler.com/flying-blue-status-match-for-us-residents/)
- [This SkyStatus post](https://skystatus.pro/guide/flying-blue-earn-xp-fast)
- [details here](https://frequentmiler.com/bilt-adds-flying-blue-gold-status-match-for-platinum-members/)
- [裸URL](https://frequentmiler.com/reasonable-redemption-values-rrvs/)
- [裸URL](https://frequentmiler.com/reasonable-redemption-values-rrvs/)
- [裸URL](https://frequentmiler.com/reasonable-redemption-values-rrvs/)

丢弃链接共4个；前8个样例：
- `ⓘ $787 1st Yr Value Estimate` — `https://frequentmiler.com/estimated-first-year-value/`
- `Learn more` — `https://frequentmiler.com/AFKLM/#Goto`
- `Elite status via the Air France KLM credit card` — `https://frequentmiler.com/elite-status-via-the-air-france-klm-credit-card/`
- `Frequent Miler` — `https://frequentmiler.com`

### A17 Targeted IHG double elite night credits

- [IHG has *another* bonus elite night promotion going on at the same time](https://frequentmiler.com/targeted-ihg-promo-earn-double-elite-night-credits/)
- [Direct link to registration](https://www.ihg.com/content/us/en/deals/member-offers/bencsq3)

丢弃链接共2个；前8个样例：
- `Targeted IHG promo: Earn double elite night credits (limit 10 bonus elite nights)` — `https://frequentmiler.com/targeted-ihg-promo-earn-double-elite-night-credits-limit-10-bonus-elite-nights/`
- `Frequent Miler` — `https://frequentmiler.com`

### A18 Airport lounge access with Accor elite status

- [episode of Frequent Miler on the Air](https://frequentmiler.com/turn-hotel-status-into-airline-status-frequent-miler-on-the-air-ep367-7-17-26/)
- [Bilt’s August Rent Day](https://frequentmiler.com/rent-day-all-accor-status-offer-for-bilt-members-with-points-transfer/)
- [Complete Guide to ALL Accor](https://frequentmiler.com/complete-guide-accor-loyalty-program/)
- [MilesTalk](https://milestalk.com/interesting-status-match-accor-gold-to-skyteam-elite-plus/)
- [See list of lounges here](https://a.storyblok.com/f/271050/x/e9b8411817/domestic-lounge-list-october-2025.pdf)
- [**Direct Link to Offer**](https://kenya-airways.statusmatch.com/?fpr=0ht6hd)
- [Link your ALL and Qatar accounts](https://www.qatarairways.com/en/Privilege-Club/our-partners/accor.html)
- [full terms](https://www.qatarairways.com/en/Privilege-Club/terms-and-conditions/accor-account-linking.html)
- [**Direct Link to Offer**](https://www.qatarairways.com/en/Privilege-Club/our-partners/accor.html)
- [Qatar’s route map here](https://www.flightconnections.com/route-map-qatar-airways-qr)
- [fifth-freedom flights](https://www.australianfrequentflyer.com.au/fifth-freedom-routes/#h-our-list-of-fifth-freedom-routes)
- [terms that Qatar publishes](https://www.qatarairways.com/en/Privilege-Club/terms-and-conditions/accor-account-linking.html)
- [recent examples](https://www.flyertalk.com/forum/accor-all-accor-live-limitless/2095715-accor-qatar-partnership-24.html?styleid=24)
- [The best credit cards for Priority Pass Lounges](https://frequentmiler.com/best-priority-pass-cards/)

丢弃链接共2个；前8个样例：
- `How to get access to airport lounges with Accor elite status` — `https://frequentmiler.com/how-to-get-access-to-airport-lounges-with-accor-elite-status/`
- `Frequent Miler` — `https://frequentmiler.com`

### A19 Southwest SWABIZ A-List and points promotion

- [Direct link to registration](https://www.southwest.com/loyalty/myaccount/promotion-detail?id=2-5LFMLAD5)
- [if you refer someone for SWABIZ](https://business.southwest.com/referacompany)
- [Southwest’s status match feature](https://www.southwest.com/rapid-rewards/promotions/status-match/)

丢弃链接共2个；前8个样例：
- `Southwest promo: Earn A-List status + 20K bonus points when booking via SWABIZ` — `https://frequentmiler.com/southwest-promo-earn-a-list-status-20k-bonus-points-when-booking-via-swabiz/`
- `Frequent Miler` — `https://frequentmiler.com`

### A20 Where Hyatt suite upgrade awards do not work

- [my perfect Hyatt mattress run](https://frequentmiler.com/the-perfect-hyatt-mattress-run/)
- [see this section for details](https://frequentmiler.com/where-hyatt-suite-upgrade-awards-dont-work/#November_2025_additions_to_the_list_of_Suite_Award_Ineligible_properties)
- [as identified by Loyalty Lobby](https://loyaltylobby.com/2025/11/03/hyatt-adds-four-additional-suite-award-ineligible-properties/)
- [award chart](https://frequentmiler.com/world-of-hyatt-complete-guide/#Free_Night_Awards)
- [As identified by Loyalty Lobby](https://loyaltylobby.com/2025/11/03/hyatt-adds-four-additional-suite-award-ineligible-properties/)
- [World of Hyatt’s terms & conditions,](https://www.hyatt.com/help/terms/world-of-hyatt)
- [World of Hyatt Complete Guide](https://frequentmiler.com/world-of-hyatt-complete-guide/)
- [裸URL](https://world.hyatt.com/content/gp/en/landing/destination-residence-awards.html)
- [裸URL](https://world.hyatt.com/content/gp/en/landing/destination-residence-awards.html"))

丢弃链接共2个；前8个样例：
- `Where Hyatt Suite Upgrade Awards don’t work (more properties added)` — `https://frequentmiler.com/where-hyatt-suite-upgrade-awards-dont-work/`
- `Frequent Miler` — `https://frequentmiler.com`

### A21 GHA Discovery paid status match

- [AwardWallet](https://awardwallet.com/news/hotels/gha-discovery-status-match/?pubDate=2026-05-07)
- [and many more](https://www.ghadiscovery.com/our-brands)
- [**Direct link to this deal**](https://ghadiscovery.statusmatch.com/)
- [Direct link to the matrix showing what matches to Platinum vs Titanium](https://ghadiscovery.statusmatch.com/faq/#matrix)
- [www.ghadiscovery.com/our-programme](https://ghadiscovery.statusmatch.com/terms/www.ghadiscovery.com/our-programme)
- [downloaded here](https://www.ghadiscovery.com/mobile-app)
- [free backdoor opportunities](https://www.headforpoints.com/2025/04/28/rotana-rewards-status-match/)
- [it got a mention in this post](https://frequentmiler.com/belgium-beer-beauty-castles-chocolate-and-fhr-and-fnc-success/)
- [full status benefits can be found here](https://www.ghadiscovery.com/gha-discovery-benefits)
- [裸URL](https://ghadiscovery.statusmatch.com/privacy)

丢弃链接共2个；前8个样例：
- `GHA Discovery status match from many hotel/airline/cruise programs is back` — `https://frequentmiler.com/gha-discovery-hotel-program-status-match-from-many-hotel-airline-cruise-programs/`
- `Frequent Miler` — `https://frequentmiler.com`

### A22 雅高A+促销，温德姆钻石新增早餐权益

- [相关页面在这里](https://www.wyndhamhotels.com/zh-cn/hotel-deals/Elite-Welcome)
- [雅高A+的新活动](https://www.verylvke.com/accor-plus)

丢弃链接共4个；前8个样例：
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/08/wyndham-diamond.jpg`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2025/08/accor-plus-explorer.png`
- `雅高A+促销，温德姆钻石新增早餐权益` — `https://www.verylvke.com/2026/08/17/accor-plus-wyndham-benefits-enhanced/`
- `飞常旅客 VERYLVKE` — `https://www.verylvke.com`

### A23 克拉科夫喜来登与老城英迪格入住体验

- [喜来登大酒店](https://www.verylvke.com/sheraton-grand-krakow)
- [老城区英迪格](https://www.verylvke.com/hotel-indigo-krakow-old-town)

丢弃链接共59个；前8个样例：
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/08/sheraton-grand-krakow-building-1.jpg`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/08/sheraton-grand-krakow-building-2.jpg`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/08/sheraton-grand-krakow-reception.jpg`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/08/sheraton-grand-krakow-lobby-1.jpg`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/08/sheraton-grand-krakow-lobby-2.jpg`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/08/sheraton-grand-krakow-lobby-3.jpg`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/08/sheraton-grand-krakow-room-1.jpg`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/08/sheraton-grand-krakow-room-2.jpg`

### A24 璞富腾钛金匹配与Scandic兑换实战

- [谴责Choice贬值](https://www.verylvke.com/2026/07/16/ihg-ruby-10k-choice-45-off/)
- [StatusMatcher网站](https://statusmatcher.com/company/preferred-hotels)
- [通过芬兰航空用Avios兑换Scandic酒店的免房券](https://www.verylvke.com/2024/05/24/finnair-avios-hotels/)

丢弃链接共4个；前8个样例：
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/07/iprefer-titanium-status-match-success.jpg`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/08/finnair-scandic-basic-voucher.png`
- `实战：璞富腾钛金匹配，Scandic免房兑换` — `https://www.verylvke.com/2026/08/03/iprefer-titanium-status-match-scandic-avios/`
- `飞常旅客 VERYLVKE` — `https://www.verylvke.com`

### A25 雅高臻享卡促销与肯尼亚航空匹配

- [肯尼亚航空会籍匹配](https://www.verylvke.com/2025/08/04/kenya-airways-status-match/)

丢弃链接共5个；前8个样例：
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/08/all-plus-china-basic-199.png`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2024/10/weixin-accor-all-plus-china.png`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/08/kenya-airways-asanta-platinum.png`
- `雅高：臻享卡促销，肯尼亚航空匹配` — `https://www.verylvke.com/2026/08/05/accor-all-plus-sale-kenya-airways-status-match/`
- `飞常旅客 VERYLVKE` — `https://www.verylvke.com`

### A26 万豪与日本航空会籍合作

- [活动页面在这里](https://www.verylvke.com/marriott-japan-airlines)

丢弃链接共6个；前8个样例：
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/07/marriott-japan-airlines.png`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/07/marriott-japan-airlines-30000-fly-on-points.png`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/07/marriott-japan-airlines-crystal-upgraded.jpg`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/07/marriott-japan-airlines-crystal-lounge-coupons.jpg`
- `万豪和日航开展合作，直升寰宇红宝石` — `https://www.verylvke.com/2026/07/14/marriott-japan-airlines-partnership/`
- `飞常旅客 VERYLVKE` — `https://www.verylvke.com`

### A27 八大洲一住升金、雅典君悦好价与万豪贬值

- [简单回顾一下](https://www.verylvke.com/2021/05/26/badazhou-silver-uk-hotels/)
- [早早爸的酒店监控披露](https://mp.weixin.qq.com/s/mtwfKarboxTuhyOew_JPOQ)

丢弃链接共8个；前8个样例：
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2024/06/badazhou-code.png`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/07/grand-hyatt-athens-63-sale.png`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/07/marriott-devaluation-zaozao-ritz-carlton-nanjing.png`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/07/marriott-devaluation-zaozao-ritz-carlton-hong-kong.jpg`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/07/marriott-devaluation-zaozao-london-edition.jpg`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/07/marriott-devaluation-zaozao-courtyard-paris-versaille.jpg`
- `八大洲一住升金，雅典君悦好价，万豪贬值` — `https://www.verylvke.com/2026/07/07/badazhou-grand-hyatt-athens-marriott-devaluation/`
- `飞常旅客 VERYLVKE` — `https://www.verylvke.com`

### A28 马来西亚航空会籍匹配活动

- [马来西亚航空](https://enrich.statusmatch.com/)
- [Gold Privilege](https://www.garuda-indonesia.com/my/en/garudamiles/tentang-garudamiles/goldprivilege)

丢弃链接共4个；前8个样例：
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2016/10/malaysia-airlines.png`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/07/garuda-gold-privilege.jpg`
- `马来西亚航空会籍匹配活动` — `https://www.verylvke.com/2026/07/06/malaysia-airlines-status-match/`
- `飞常旅客 VERYLVKE` — `https://www.verylvke.com`

### A29 Trip夏日大促

- [英国站](https://www.verylvke.com/trip-mega-uk)
- [美国站](https://www.verylvke.com/trip-mega-us)
- [我的推荐链接](https://www.verylvke.com/trip-refer)

丢弃链接共3个；前8个样例：
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2026/07/trip-summer-mega-sale.png`
- `Trip夏日大促，机票酒店迪士尼通通半价` — `https://www.verylvke.com/2026/07/05/trip-summer-mega-sale/`
- `飞常旅客 VERYLVKE` — `https://www.verylvke.com`

### A30 法航荷航和北欧航空会籍匹配

- [北欧航空的会籍匹配](https://sas.statusmatch.com/)
- [另一个就是大家的老朋友蓝翔了](https://flyingblue.statusmatch.com/)

丢弃链接共4个；前8个样例：
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2020/10/sas-gold.jpg`
- `空链接` — `https://www.verylvke.com/wp-content/uploads/sites/2/2020/03/amex-flying-blue.jpg`
- `法航荷航和北欧航空会籍匹配` — `https://www.verylvke.com/2026/05/31/flying-blue-and-sas-status-match/`
- `飞常旅客 VERYLVKE` — `https://www.verylvke.com`

## FFB列表35个顶层条目

| # | 条目 | 原始条目HTML字符 | 最终正文字符 | 保留链接 | 规则丢弃链接 | 异常 |
|---:|---|---:|---:|---:|---:|---|
| 1 | Vietnam Airlines Lotusmiles付费匹配 | 603 | 459 | 1 | 1 | — |
| 2 | Air Astana Nomad Club付费匹配 | 382 | 343 | 1 | 0 | — |
| 3 | Flying Blue英国BA Club专场 | 343 | 308 | 1 | 0 | — |
| 4 | Flying Blue多项目付费匹配 | 360 | 325 | 1 | 0 | — |
| 5 | Alaska San Diego快速通道 | 629 | 491 | 1 | 0 | — |
| 6 | Alaska指定企业员工挑战 | 6364 | 3442 | 32 | 0 | — |
| 7 | Alaska北美航司会籍匹配 | 318 | 277 | 1 | 0 | — |
| 8 | American AAdvantage会籍匹配 | 299 | 269 | 1 | 0 | — |
| 9 | Delta Medallion匹配挑战 | 552 | 451 | 1 | 0 | — |
| 10 | Etihad印度与澳大利亚付费匹配 | 367 | 330 | 1 | 0 | — |
| 11 | JetBlue Mosaic匹配挑战 | 520 | 460 | 1 | 0 | — |
| 12 | 肯尼亚航空Asante Rewards付费匹配 | 531 | 401 | 1 | 1 | — |
| 13 | KM Malta KM Rewards付费匹配 | 497 | 382 | 1 | 1 | — |
| 14 | 马航Enrich付费匹配 | 581 | 346 | 1 | 1 | — |
| 15 | Miles & More付费匹配 | 387 | 339 | 1 | 0 | — |
| 16 | Royal Air Maroc Safar Flyer付费匹配 | 333 | 284 | 1 | 0 | — |
| 17 | Royal Jordanian Royal Club付费匹配 | 583 | 528 | 1 | 0 | — |
| 18 | TAP Miles&Go欧洲付费匹配 | 523 | 353 | 1 | 1 | — |
| 19 | United MileagePlus匹配挑战 | 416 | 318 | 1 | 0 | — |
| 20 | Virgin Atlantic Flying Club会籍匹配 | 359 | 338 | 1 | 0 | — |
| 21 | Best Western Rewards普通会籍匹配 | 411 | 305 | 1 | 0 | — |
| 22 | Best Western AARP自动金卡 | 453 | 382 | 2 | 0 | — |
| 23 | Best Western美国军人自动金卡 | 328 | 313 | 1 | 0 | — |
| 24 | Best Western加拿大军人自动金卡 | 333 | 317 | 1 | 0 | — |
| 25 | Choice Privileges会籍匹配 | 666 | 450 | 1 | 1 | — |
| 26 | Choice美国军人终身金卡 | 438 | 388 | 1 | 0 | — |
| 27 | Hilton Honors匹配挑战 | 562 | 535 | 1 | 0 | — |
| 28 | Sonesta Travel Pass会籍匹配 | 238 | 233 | 1 | 0 | — |
| 29 | WorldHotels Rewards会籍匹配 | 310 | 235 | 1 | 0 | — |
| 30 | Wyndham Rewards会籍匹配 | 300 | 268 | 1 | 0 | — |
| 31 | Avis Preferred欧洲与英国会籍匹配 | 299 | 274 | 1 | 0 | — |
| 32 | Enterprise Plus会籍匹配 | 1542 | 567 | 1 | 1 | — |
| 33 | Hertz Gold Plus Rewards会籍匹配 | 1139 | 572 | 1 | 0 | — |
| 34 | National Emerald Club会籍匹配 | 238 | 227 | 1 | 0 | — |
| 35 | Club Avolta Platinum会籍匹配 | 776 | 672 | 1 | 0 | — |

## FFB最终保留链接

### F01 Vietnam Airlines Lotusmiles付费匹配

- [**paid status match opportunity**](https://vietnamairlines.statusmatch.com/?fpr=dv1gz)

规则丢弃：
- `规则丢弃` — `https://vietnamairlines.statusmatch.com/?fpr=dv1gz`

### F02 Air Astana Nomad Club付费匹配

- [**Click here for more details.**](https://airastana.statusmatch.com/?fpr=07cvd)

### F03 Flying Blue英国BA Club专场

- [**Click here for more details.**](https://flyingblue.statusmatch.com/ba/?fpr=x73nt)

### F04 Flying Blue多项目付费匹配

- [**Click here for more details.**](https://flyingblue.statusmatch.com/?fpr=5zlmq)

### F05 Alaska San Diego快速通道

- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2513)

### F06 Alaska指定企业员工挑战

- [**Click here to register for this offer**](https://www.alaskaair.com/promotion/cs2320)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2372)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2365)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2366)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2367)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2368)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2369)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2370)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2371)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2373)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2374)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2375)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2376)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2380)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2381)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2343)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2344)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2345)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2346)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2347)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2348)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2349)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2350)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2351)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2354)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2355)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2356)
- [**Click here to register for this offer**](https://www.alaskaair.com/promotion/cs2304)
- [**Click here to register for this offer**](https://www.alaskaair.com/promotion/as2377)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/CS2344)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2342)
- [**Click here to register for this offer**](https://www.alaskaair.com/promo/AS2378)

### F07 Alaska北美航司会籍匹配

- [**Register Online**](https://www.alaskaair.com/content/mileage-plan/membership-benefits/status-match)

### F08 American AAdvantage会籍匹配

- [**Click here to learn more.**](https://www.aa.com/i18n/aadvantage-program/aadvantage-status/aadvantage-status-match.jsp)

### F09 Delta Medallion匹配挑战

- [**Click here for complete details**](https://www.delta.com/us/en/skymiles/medallion-program/status-match-challenge)

### F10 Etihad印度与澳大利亚付费匹配

- [**Click here for more details**](https://etihad.statusmatch.com/?fpr=0sqav)

### F11 JetBlue Mosaic匹配挑战

- [**Click here to learn more**](https://www.jetblue.com/trueblue/mosaic/match-to-mosaic)

### F12 肯尼亚航空Asante Rewards付费匹配

- [**paid status match opportunity**](https://kenya-airways.statusmatch.com/?fpr=a254z2)

规则丢弃：
- `规则丢弃` — `https://kenya-airways.statusmatch.com/?fpr=a254z2`

### F13 KM Malta KM Rewards付费匹配

- [**paid status match opportunity**](https://kmrewards.statusmatch.com/)

规则丢弃：
- `规则丢弃` — `https://kmrewards.statusmatch.com/`

### F14 马航Enrich付费匹配

- [**paid status match opportunity**](https://enrich.statusmatch.com/?fpr=bcdpos)

规则丢弃：
- `规则丢弃` — `https://enrich.statusmatch.com/?fpr=bcdpos`

### F15 Miles & More付费匹配

- [Click here to learn more.](https://lufthansa.statusmatch.com/?fpr=bcodf)

### F16 Royal Air Maroc Safar Flyer付费匹配

- [**Click here for more details**](https://safarflyerstatusmatch.com/?fpr=ls4mk)

### F17 Royal Jordanian Royal Club付费匹配

- [Click here hore for more details](https://rj.statusmatch.com/?fpr=4vjkt)

### F18 TAP Miles&Go欧洲付费匹配

- [**paid status match opportunity**](https://tap.statusmatch.com/?fpr=zmp14)

规则丢弃：
- `规则丢弃` — `https://tap.statusmatch.com/?fpr=zmp14`

### F19 United MileagePlus匹配挑战

- [**Click here for more details**](https://www.united.com/en/us/fly/mileageplus/premier/status-match.html)

### F20 Virgin Atlantic Flying Club会籍匹配

- [Click here for complete details](https://www.anrdoezrs.net/click-1654157-13618234?url=https%3A%2F%2Fflywith.virginatlantic.com%2Fgb%2Fen%2Fflying-club%2Fmembers%2Fstatus-match.html)

### F21 Best Western Rewards普通会籍匹配

- [**Full details**](https://www.dpbolvw.net/click-1654157-11557393?sid=statusmatch&url=https%3A%2F%2Fwww.bestwestern.com%2Fen_US%2Fbest-western-rewards%2Fstatus-match.html)

### F22 Best Western AARP自动金卡

- [**Click here to join AARP**](https://aarp.pxf.io/JKKaJR)
- [**Click here to register for this offer with Best Western**](https://www.kqzyfj.com/click-1654157-14514056?url=https%3A%2F%2Fwww.bestwestern.com%2Fen_US%2Foffers%2Fhotel-discounts%2Faarp-program.html)

### F23 Best Western美国军人自动金卡

- [Full details and online registration](http://www.anrdoezrs.net/click-1654157-13825660)

### F24 Best Western加拿大军人自动金卡

- [Full details and online registration](http://www.anrdoezrs.net/click-1654157-13825656)

### F25 Choice Privileges会籍匹配

- [**Click here for more details**](https://choice.prf.hn/click/camref:1101l52I7t/destination:https%3A%2F%2Fwww.choicehotels.com%2Fen-ca%2Fchoice-privileges%2Fbenefits%2Fstatus-match)

规则丢弃：
- `规则丢弃` — `https://prf.hn/click/camref:1011l5chA/destination:https%3A//www.joinmarriottbonvoy.com/businessready`

### F26 Choice美国军人终身金卡

- [**Full details & online booking**](https://choice.prf.hn/click/camref:1101l52I7t/destination:https%3A%2F%2Fwww.choicehotels.com%2Fen-ca%2Fchoice-privileges%2Fcp-military)

### F27 Hilton Honors匹配挑战

- [**Click here to register online**](https://www.awin1.com/cread.php?awinmid=3624&awinaffid=159284&ued=https%3A//www.hiltonhonors.com/en_US/status-match/landing/)

### F28 Sonesta Travel Pass会籍匹配

- [Click here for more details](http://blog.frequentflyerbonuses.com/2015/10/sonesta-hotels-travel-pass-elite-status.html)

### F29 WorldHotels Rewards会籍匹配

- [**Full details**](https://www.worldhotels.com/content/luxury-hotels/en_US/rewards/status-match.html)

### F30 Wyndham Rewards会籍匹配

- [**Click here for more details**](https://help.wyndhamrewards.com/s/status-match?language=en_US)

### F31 Avis Preferred欧洲与英国会籍匹配

- [Click here for complete details](https://www.avis-preferred.com/statusmatch/)

### F32 Enterprise Plus会籍匹配

- [**Full details**](https://statusmatch.enterpriseplus.com/)

规则丢弃：
- `规则丢弃` — `https://partners.enterprise.com/c/350471/546121/4720`

### F33 Hertz Gold Plus Rewards会籍匹配

- [Full details](http://www.anrdoezrs.net/links/1654157/type/dlg/sid/statusmatch/https://pub.emails.hertz.com/Hertz_Status_Match)

### F34 National Emerald Club会籍匹配

- [**Click here for more details**](https://statusmatch.emeraldclub.com/usen/)

### F35 Club Avolta Platinum会籍匹配

- [**Click here to learn more and to request your status match.**](https://clubavolta.statusmatch.com/?fpr=spnmd)
