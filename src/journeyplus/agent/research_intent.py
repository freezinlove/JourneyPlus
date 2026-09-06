"""Recognize explicit requests only for surfacing an unavailable capability."""
import re


def explicit_research_request(text):
    # This does not choose a data tool or authorize network access. Ambiguous
    # utterances remain with the Agent; quoted language tasks are not research.
    if re.search(r'不要.{0,15}(?:查|联网)|不用.{0,15}(?:查|联网)|别.{0,8}(?:查|联网)|不需要.{0,10}调查|翻译|润色|改写|造句|笑话',text):
        return False
    return bool(re.search(r'(?:查|调查|搜|看看|比较|去)[\s\S]*(?:statusmatcher|申请经验|匹配经验|成功率)|statusmatcher[\s\S]*(?:经验|案例|报告|比较|成功)|哪个.{0,20}更稳',text,re.I))
