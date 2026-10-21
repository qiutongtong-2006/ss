import re
import unicodedata


CHINESE_DIGITS = {
    '零': '0',
    '一': '1',
    '二': '2',
    '两': '2',
    '三': '3',
    '四': '4',
    '五': '5',
    '六': '6',
    '七': '7',
    '八': '8',
    '九': '9',
}


def chinese_number_to_arabic(text):
    """把一至九十九的中文数字转成阿拉伯数字。"""
    if '十' in text:
        tens_text, _, ones_text = text.partition('十')
        tens = CHINESE_DIGITS.get(tens_text, '1') if tens_text else '1'
        ones = CHINESE_DIGITS.get(ones_text, '0') if ones_text else '0'
        return str(int(tens) * 10 + int(ones))
    return ''.join(CHINESE_DIGITS.get(char, char) for char in text)


def normalize_building_name(value):
    """统一楼栋写法，例如二号楼、2栋、2幢都转成 2号楼。"""
    value = unicodedata.normalize('NFKC', value or '').strip()
    value = re.sub(r'\s+', '', value).replace('第', '')
    value = re.sub(
        r'[零一二两三四五六七八九十]+',
        lambda match: chinese_number_to_arabic(match.group()),
        value,
        count=1,
    )

    core = re.sub(r'(宿舍楼|号楼|楼|栋|幢)$', '', value)
    core = re.sub(r'号$', '', core)
    if re.fullmatch(r'(?:[A-Za-z]+\d*|\d+)', core):
        return f'{core}号楼'
    return value
