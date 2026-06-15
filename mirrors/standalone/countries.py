"""Minimal ISO 3166-1 alpha-2 code -> name lookup.

Replaces django_countries. The Django encoder emitted both the full
country name (`country`) and the 2-letter code (`country_code`); we keep
that contract. Unknown codes fall back to the code itself rather than
raising, so a sparse map never breaks the API. Extend as needed.
"""

# Common subset; add rows as your dataset requires.
COUNTRIES = {
    'AU': 'Australia', 'AT': 'Austria', 'BE': 'Belgium', 'BR': 'Brazil',
    'BG': 'Bulgaria', 'CA': 'Canada', 'CL': 'Chile', 'CN': 'China',
    'HR': 'Croatia', 'CZ': 'Czechia', 'DK': 'Denmark', 'EE': 'Estonia',
    'FI': 'Finland', 'FR': 'France', 'DE': 'Germany', 'GR': 'Greece',
    'HK': 'Hong Kong', 'HU': 'Hungary', 'IS': 'Iceland', 'IN': 'India',
    'ID': 'Indonesia', 'IE': 'Ireland', 'IL': 'Israel', 'IT': 'Italy',
    'JP': 'Japan', 'KZ': 'Kazakhstan', 'KR': 'South Korea', 'LV': 'Latvia',
    'LT': 'Lithuania', 'LU': 'Luxembourg', 'MX': 'Mexico', 'NL': 'Netherlands',
    'NZ': 'New Zealand', 'NO': 'Norway', 'PL': 'Poland', 'PT': 'Portugal',
    'RO': 'Romania', 'RU': 'Russia', 'RS': 'Serbia', 'SG': 'Singapore',
    'SK': 'Slovakia', 'SI': 'Slovenia', 'ZA': 'South Africa', 'ES': 'Spain',
    'SE': 'Sweden', 'CH': 'Switzerland', 'TW': 'Taiwan', 'TH': 'Thailand',
    'TR': 'Turkey', 'UA': 'Ukraine', 'GB': 'United Kingdom',
    'US': 'United States', 'VN': 'Vietnam',
}


def country_name(code):
    if not code:
        return ''
    return COUNTRIES.get(code.upper(), code)
