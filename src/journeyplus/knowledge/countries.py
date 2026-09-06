"""Explicit country aliases only; unresolved labels never imply inequality."""
import unicodedata

_GROUPS=(
 ('CA','CAN','Canada','加拿大'),('US','USA','United States','United States of America','美国'),
 ('GB','GBR','UK','United Kingdom','英国'),('CN','CHN','China','中国'),
 ('HK','HKG','Hong Kong','香港'),('TW','TWN','Taiwan','台湾'),
 ('GR','GRC','Greece','希腊'),('BR','BRA','Brazil','巴西'),('AR','ARG','Argentina','阿根廷'),
 ('CL','CHL','Chile','智利'),('CO','COL','Colombia','哥伦比亚'),('CR','CRI','Costa Rica','哥斯达黎加'),
 ('EC','ECU','Ecuador','厄瓜多尔'),('PY','PRY','Paraguay','巴拉圭'),('PE','PER','Peru','秘鲁'),('UY','URY','Uruguay','乌拉圭'),
 ('FR','FRA','France','法国'),('DE','DEU','Germany','德国'),('IT','ITA','Italy','意大利'),
 ('ES','ESP','Spain','西班牙'),('PT','PRT','Portugal','葡萄牙'),('NL','NLD','Netherlands','荷兰'),
 ('AT','AUT','Austria','奥地利'),('AU','AUS','Australia','澳大利亚'),('BE','BEL','Belgium','比利时'),
 ('DK','DNK','Denmark','丹麦'),('SE','SWE','Sweden','瑞典'),('CH','CHE','Switzerland','瑞士'),
 ('JP','JPN','Japan','日本'),('IN','IND','India','印度'),('SG','SGP','Singapore','新加坡'),
 ('TH','THA','Thailand','泰国'),('VN','VNM','Vietnam','越南'),('MY','MYS','Malaysia','马来西亚'),
 ('ID','IDN','Indonesia','印度尼西亚'),('PH','PHL','Philippines','菲律宾'),('KH','KHM','Cambodia','柬埔寨'),
 ('LA','LAO','Laos','老挝'),('MM','MMR','Myanmar','缅甸'),('KR','KOR','South Korea','韩国'),
 ('KE','KEN','Kenya','肯尼亚'),('ZA','ZAF','South Africa','南非'),('EG','EGY','Egypt','埃及'),
 ('AE','ARE','UAE','United Arab Emirates','阿联酋'),('SA','SAU','Saudi Arabia','沙特阿拉伯'),
 ('JO','JOR','Jordan','约旦'),('LB','LBN','Lebanon','黎巴嫩'),('BH','BHR','Bahrain','巴林'),
 ('KW','KWT','Kuwait','科威特'),('QA','QAT','Qatar','卡塔尔'),('TR','TUR','Turkey','Türkiye','土耳其'),
)


def key(value):return ' '.join(unicodedata.normalize('NFKC',value).casefold().split())

_ALIASES={key(name):group[0] for group in _GROUPS for name in group}


def country_equal(left,right):
    if not isinstance(left,str) or not isinstance(right,str):return None
    if key(left)==key(right):return True
    a,b=_ALIASES.get(key(left)),_ALIASES.get(key(right))
    return a==b if a is not None and b is not None else None


def country_in(actual,expected):
    results=[country_equal(actual,value) for value in expected]
    if True in results:return True
    return None if None in results else False
