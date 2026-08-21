# 第一阶段人工金标审核清单

生成时间：`2026-08-20T09:40:36+00:00`

范围：30篇指定文章 + FFB列表35个顶层条目，共65份文档。StatusMatcher未纳入。

冻结状态：本数据集已于2026-08-21经人工确认并冻结；后续修改必须发布新的数据集版本。

时间边界：标签只判断正文是否描述会籍获取机会，不判断活动在采集、审核或测评时是否仍然有效。即使活动已经截止，仍可标为`STATUS_OPPORTUNITY`；截止时间提取、有效期筛选、过期状态和归档不属于本阶段金标。

当前只标注文档是否属于会籍机会以及文档内活动归并；`relationships`和`facts`均为空，尚未运行测评。

## 汇总

| 标签 | 数量 |
|---|---:|
| 是 / `STATUS_OPPORTUNITY` | 49 |
| 否 / `NONE` | 16 |
| 不确定 / `UNCERTAIN` | 0 |
| 合计 | 65 |

## 指定文章

| # | 文档 | 标签 | 活动数量 | 活动归并名 | 理由 | 规范正文字符数 |
|---:|---|---|---:|---|---|---:|
| 1 | [Kenya Airways Asante Rewards SkyTeam paid status match](https://blog.frequentflyerbonuses.com/2026/08/kenya-airways-asante-rewards-skyteam-paid-status-match.html) | 是 | 1 | `kenya-airways-asante-rewards-paid-status-match-2026` | 报道肯尼亚航空付费会籍匹配的具体更新。 | 8822 |
| 2 | [Receive up to a 50% bonus when you buy Marriott Bonvoy points](https://blog.frequentflyerbonuses.com/2026/08/receive-up-to-a-50-bonus-when-you-buy-marriott-bonvoy-points.html) | 否 | 0 | — | 买分加赠不直接授予、升级或延长会籍。 | 1950 |
| 3 | [Air Canada Aeroplan earn up to 3.5x points](https://blog.frequentflyerbonuses.com/2026/07/air-canada-aeroplan-earn-up-to-3-5x-points.html) | 否 | 0 | — | 积分倍数奖励不直接产生会籍。 | 5447 |
| 4 | [Air France KLM Flying Blue paid elite status match](https://blog.frequentflyerbonuses.com/2026/06/last-chance-air-france-klm-flying-blue-paid-elite-status-match.html) | 是 | 1 | `flying-blue-paid-status-match-2026` | 文章主体是Flying Blue付费匹配；越航仅作为错过活动后的替代选择顺带提及。 | 2894 |
| 5 | [World of Hyatt Globalist guide](https://awardwallet.com/hotels/world-of-hyatt/hyatt-globalist/) | 否 | 0 | — | 长期会籍权益与获取教学，不是具体活动报道。 | 19889 |
| 6 | [Delta SkyMiles guide](https://awardwallet.com/airlines/delta-skymiles/) | 否 | 0 | — | 长期项目教学，不是具体会籍活动报道。 | 34936 |
| 7 | [Kenya Airways status match offer](https://awardwallet.com/airlines/kenya-airways-status-match-offer/) | 是 | 1 | `kenya-airways-asante-rewards-paid-status-match-2026` | 具体报道肯尼亚航空付费会籍匹配。 | 14776 |
| 8 | [Alaska corporate status challenge](https://awardwallet.com/news/alaska-atmos-rewards/alaska-corporate-status-challenge/) | 是 | 1 | `alaska-atmos-corporate-status-challenge-2026` | 具体报道指定企业员工的即时会籍与快速通道。 | 10874 |
| 9 | [AAdvantage elite status upgrades on premium economy tickets](https://awardwallet.com/news/american-aadvantage/elite-status-upgrades-premium-economy/) | 否 | 0 | — | 报道既有会籍权益规则变化，不提供会籍获取机会。 | 5014 |
| 10 | [Alaska Airlines buy miles bonus](https://loyaltylobby.com/2026/08/19/last-call-alaska-airlines-buy-miles-up-to-100-bonus-sale-until-august-20-2026/) | 否 | 0 | — | 购买里程促销不直接产生会籍。 | 3361 |
| 11 | [American Airlines brings back seatback screens](https://loyaltylobby.com/2026/08/18/american-airlines-brings-back-seatback-screens-on-short-haul-aircraft-from-2028/) | 否 | 0 | — | 航司产品新闻与会籍获取无关。 | 5938 |
| 12 | [United Premier Gold benefit experience on Virgin Australia](https://loyaltylobby.com/2026/08/17/united-premier-gold-elite-benefit-experience-on-virgin-australia-domestic-flights/) | 否 | 0 | — | 既有会籍权益体验，不是会籍获取机会。 | 4162 |
| 13 | [Finnair Plus and Radisson Rewards conversions and tier match](https://loyaltylobby.com/2026/08/09/finnair-plus-radisson-rewards-launch-two-way-conversions-match/) | 是 | 1 | `finnair-plus-to-radisson-rewards-status-match-2026` | 正文含Finnair Plus精英会员匹配Radisson Rewards会籍的具体活动。 | 5645 |
| 14 | [IHG One Rewards double elite night credits](https://loyaltylobby.com/2026/08/08/update-ihg-one-rewards-double-elite-night-credits-august-5-september-29-2026/) | 否 | 0 | — | 奖励精英房晚，但不直接授予、升级或延长会籍。 | 7900 |
| 15 | [Turkish Airlines reduces Oceania award pricing](https://loyaltylobby.com/2026/08/06/turkish-airlines-milessmiles-reduces-oceania-award-pricing/) | 否 | 0 | — | 积分票定价变化与会籍获取无关。 | 2844 |
| 16 | [Elite status via the Air France KLM credit card](https://frequentmiler.com/elite-status-via-the-air-france-klm-credit-card/) | 否 | 0 | — | 以长期方法总结和信用卡攻略为主要目的。 | 14549 |
| 17 | [Targeted IHG double elite night credits](https://frequentmiler.com/targeted-ihg-promo-earn-double-elite-night-credits-limit-10-bonus-elite-nights/) | 否 | 0 | — | 奖励精英房晚但不直接产生会籍。 | 4641 |
| 18 | [Airport lounge access with Accor elite status](https://frequentmiler.com/how-to-get-access-to-airport-lounges-with-accor-elite-status/) | 是 | 2 | `kenya-airways-asante-rewards-paid-status-match-2026`<br>`accor-to-qatar-privilege-club-status-match-2026` | 正文集中报道Accor会籍通往肯尼亚航空和卡塔尔航空会籍的两项当前路径。 | 5960 |
| 19 | [Southwest SWABIZ A-List and points promotion](https://frequentmiler.com/southwest-promo-earn-a-list-status-20k-bonus-points-when-booking-via-swabiz/) | 是 | 1 | `southwest-swabiz-a-list-fast-track-2026` | 即使活动可能仅向部分会员开放，完成指定航段仍可直接获得限时A-List会籍。 | 8042 |
| 20 | [Where Hyatt suite upgrade awards do not work](https://frequentmiler.com/where-hyatt-suite-upgrade-awards-dont-work/) | 否 | 0 | — | 会籍套房升级券适用规则，不是会籍获取机会。 | 6670 |
| 21 | [GHA Discovery paid status match](https://frequentmiler.com/gha-discovery-hotel-program-status-match-from-many-hotel-airline-cruise-programs/) | 是 | 1 | `gha-discovery-paid-status-match-2026` | 具体报道GHA Discovery付费会籍匹配。 | 9467 |
| 22 | [雅高A+促销，温德姆钻石新增早餐权益](https://www.verylvke.com/2026/08/17/accor-plus-wyndham-benefits-enhanced/) | 否 | 0 | — | 会员卡促销和既有会籍权益变化，不直接产生会籍。 | 713 |
| 23 | [克拉科夫喜来登与老城英迪格入住体验](https://www.verylvke.com/2026/08/19/stay-krakow-sheraton-grand-hotel-indigo-old-town/) | 否 | 0 | — | 酒店入住体验，不是会籍获取机会。 | 1769 |
| 24 | [璞富腾钛金匹配与Scandic兑换实战](https://www.verylvke.com/2026/08/03/iprefer-titanium-status-match-scandic-avios/) | 是 | 1 | `iprefer-rewards-email-status-match-2026` | 正文提供向iPrefer官方邮箱申请且成功获得钛金会籍的当前实测。 | 1195 |
| 25 | [雅高臻享卡促销与肯尼亚航空匹配](https://www.verylvke.com/2026/08/05/accor-all-plus-sale-kenya-airways-status-match/) | 是 | 1 | `kenya-airways-asante-rewards-paid-status-match-2026` | 只归入正文中的肯尼亚航空会籍匹配更新。 | 1027 |
| 26 | [万豪与日本航空会籍合作](https://www.verylvke.com/2026/07/14/marriott-japan-airlines-partnership/) | 是 | 1 | `marriott-bonvoy-jal-status-partnership-2026` | 万豪与日本航空双向提供会籍匹配和加速权益，作为同一项合作活动归并。 | 888 |
| 27 | [八大洲一住升金、雅典君悦好价与万豪贬值](https://www.verylvke.com/2026/07/07/badazhou-grand-hyatt-athens-marriott-devaluation/) | 是 | 1 | `badazhou-one-stay-gold-fast-track-2026` | 只归入正文中八大洲一住升级体验金卡的具体活动。 | 1366 |
| 28 | [马来西亚航空会籍匹配活动](https://www.verylvke.com/2026/07/06/malaysia-airlines-status-match/) | 是 | 2 | `malaysia-airlines-enrich-paid-status-match-2026`<br>`garuda-indonesia-gold-privilege-paid-status-2026` | 正文包含马航付费匹配和印尼鹰航付费Gold Privilege两项独立机会。 | 670 |
| 29 | [Trip夏日大促](https://www.verylvke.com/2026/07/05/trip-summer-mega-sale/) | 否 | 0 | — | 机票、酒店和门票促销，不直接产生会籍。 | 791 |
| 30 | [法航荷航和北欧航空会籍匹配](https://www.verylvke.com/2026/05/31/flying-blue-and-sas-status-match/) | 是 | 2 | `sas-eurobonus-india-paid-status-match-2026`<br>`flying-blue-paid-status-match-2026` | 正文分别报道SAS印度居民付费匹配和Flying Blue付费匹配。 | 606 |

## FFB顶层条目

容器：[FFB Status Match & Fast Track Offers](https://www.frequentflyerbonuses.com/statusmatchoffers.html)

页面快照SHA-256：`4df3d370b69868e7fb92b9395bc7bad6825b3e85e47332dfc69a16a048f4dff8`

| # | 顶层条目 | 标签 | 活动归并名 | 理由 | 规范正文字符数 |
|---:|---|---|---|---|---:|
| 1 | Vietnam Airlines Lotusmiles付费匹配 | 是 | `vietnam-airlines-lotusmiles-paid-status-match-2026` | 具体付费会籍匹配记录。 | 459 |
| 2 | Air Astana Nomad Club付费匹配 | 是 | `air-astana-nomad-club-paid-status-match-2026` | 具体付费会籍匹配记录。 | 343 |
| 3 | Flying Blue英国BA Club专场 | 是 | `flying-blue-ba-uk-paid-status-match-2026` | 英国BA Club精英会员专属匹配，与广泛资格活动分开。 | 308 |
| 4 | Flying Blue多项目付费匹配 | 是 | `flying-blue-paid-status-match-2026` | 面向多个非天合项目的付费匹配。 | 325 |
| 5 | Alaska San Diego快速通道 | 是 | `alaska-atmos-san-diego-fast-track-2025-2026` | 按圣迭戈合资格航段升级会籍。 | 491 |
| 6 | Alaska指定企业员工挑战 | 是 | `alaska-atmos-corporate-status-challenge-2026` | 公司专属链接均属于同一即时会籍与快速通道活动。 | 3442 |
| 7 | Alaska北美航司会籍匹配 | 是 | `alaska-atmos-airline-status-match-2026` | 与同项目的其他两项活动分开。 | 277 |
| 8 | American AAdvantage会籍匹配 | 是 | `american-aadvantage-status-match-2026` | 具体会籍匹配及Instant Status Pass路径。 | 269 |
| 9 | Delta Medallion匹配挑战 | 是 | `delta-skymiles-status-match-challenge-2026` | 临时匹配并通过挑战延长。 | 451 |
| 10 | Etihad印度与澳大利亚付费匹配 | 是 | `etihad-guest-india-australia-paid-status-match-2026` | 具体地区限定付费匹配。 | 330 |
| 11 | JetBlue Mosaic匹配挑战 | 是 | `jetblue-mosaic-status-match-challenge-2026` | 临时匹配及后续延期挑战属于同一活动。 | 460 |
| 12 | 肯尼亚航空Asante Rewards付费匹配 | 是 | `kenya-airways-asante-rewards-paid-status-match-2026` | 具体付费会籍匹配记录。 | 401 |
| 13 | KM Malta KM Rewards付费匹配 | 是 | `km-malta-km-rewards-paid-status-match-2026` | 条目主体和申请页均指向KM Malta；正文中的Kenya名称视为来源笔误。 | 382 |
| 14 | 马航Enrich付费匹配 | 是 | `malaysia-airlines-enrich-paid-status-match-2026` | 具体付费会籍匹配记录。 | 346 |
| 15 | Miles & More付费匹配 | 是 | `miles-and-more-paid-status-match-2026` | 具体会籍匹配记录。 | 339 |
| 16 | Royal Air Maroc Safar Flyer付费匹配 | 是 | `royal-air-maroc-safar-flyer-paid-status-match-2026` | 具体付费会籍匹配记录。 | 284 |
| 17 | Royal Jordanian Royal Club付费匹配 | 是 | `royal-jordanian-royal-club-paid-status-match-2026` | 具体付费会籍匹配记录。 | 528 |
| 18 | TAP Miles&Go欧洲付费匹配 | 是 | `tap-miles-and-go-paid-status-match-2026` | 具体地区限定付费匹配。 | 353 |
| 19 | United MileagePlus匹配挑战 | 是 | `united-mileageplus-status-match-challenge-2026` | 具体会籍匹配与快速通道记录。 | 318 |
| 20 | Virgin Atlantic Flying Club会籍匹配 | 是 | `virgin-atlantic-flying-club-status-match-2026` | 具体会籍匹配记录。 | 338 |
| 21 | Best Western Rewards普通会籍匹配 | 是 | `best-western-rewards-status-match` | 酒店会籍匹配。 | 305 |
| 22 | Best Western AARP自动金卡 | 是 | `best-western-aarp-gold-direct-grant` | AARP资格与Best Western登记是同一直接授予活动的两个步骤。 | 382 |
| 23 | Best Western美国军人自动金卡 | 是 | `best-western-us-military-gold-direct-grant` | 美国军人群体公开的直接授予活动。 | 313 |
| 24 | Best Western加拿大军人自动金卡 | 是 | `best-western-canada-military-gold-direct-grant` | 加拿大军人群体公开的直接授予活动。 | 317 |
| 25 | Choice Privileges会籍匹配 | 是 | `choice-privileges-status-match-2026` | 具体酒店会籍匹配记录。 | 450 |
| 26 | Choice美国军人终身金卡 | 是 | `choice-privileges-us-military-lifetime-gold` | 美军相关成员可直接获得终身金卡。 | 388 |
| 27 | Hilton Honors匹配挑战 | 是 | `hilton-honors-status-match-challenge-2026` | 临时会籍和房晚挑战属于同一活动。 | 535 |
| 28 | Sonesta Travel Pass会籍匹配 | 是 | `sonesta-travel-pass-status-match` | 具体酒店会籍匹配记录。 | 233 |
| 29 | WorldHotels Rewards会籍匹配 | 是 | `worldhotels-rewards-status-match` | 具体酒店会籍匹配记录。 | 235 |
| 30 | Wyndham Rewards会籍匹配 | 是 | `wyndham-rewards-status-match-2026` | 具体酒店会籍匹配记录。 | 268 |
| 31 | Avis Preferred欧洲与英国会籍匹配 | 是 | `avis-preferred-europe-uk-status-match` | 具体租车会籍匹配记录。 | 274 |
| 32 | Enterprise Plus会籍匹配 | 是 | `enterprise-plus-status-match` | 完整等级对照表属于同一匹配活动；租车预订链接不另建活动。 | 567 |
| 33 | Hertz Gold Plus Rewards会籍匹配 | 是 | `hertz-gold-plus-rewards-status-match` | 完整等级对照表属于同一匹配活动。 | 572 |
| 34 | National Emerald Club会籍匹配 | 是 | `national-emerald-club-status-match` | 具体租车会籍匹配记录。 | 227 |
| 35 | Club Avolta Platinum会籍匹配 | 是 | `club-avolta-platinum-status-match` | 其他旅行忠诚度项目的具体会籍匹配。 | 672 |

## 审核顺序

1. 先看文章表中的16个非肯定样本，确认16个“否”和0个“不确定”。
2. 再看所有多活动文章，确认一篇正文是否应当对应两个活动归并名。
3. 检查同一活动跨来源是否使用相同归并名，重点是肯尼亚航空、越航、Flying Blue、Alaska企业员工和马航。
4. 检查FFB的35个顶层边界；同一航司的不同活动保持分开，条目内多个链接不拆文档。
5. 最后抽查JSON中的`normalized_body`，确认Feed来源没有误用文章页、FFB内嵌等级表没有被拆成新文档。

本版已经冻结；如需修改标签、正文或活动归并，应创建新的数据集版本，不得覆盖本版。
