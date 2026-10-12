# -*- coding: utf-8 -*-
"""Multi-channel sentiment, institutional signals, capital flows, and public opinion collector.

Data Sources integrated:
  1. Tencent / Sina Real-time quotes & Price-limit (涨跌停) anomaly detection
  2. Xueqiu (雪球) Real-time Quote, Popularity Ranking (全网人气榜), and Main Capital Distribution (主力超大单/大单资金流向)
  3. Eastmoney Official Announcements (公司公告 - 立案/处罚/异动/澄清/风险)
  4. Eastmoney Professional Research Reports (券商个股研报与最新评级分布)
  5. Eastmoney Dragon-Tiger Billboard (龙虎榜主力席位与游资博弈净额)
  6. Eastmoney Margin Trading & Short Selling (融资融券余额与杠杆资金净买入明细)
  7. Eastmoney Northbound Capital & Top 10 Circulating Shareholders (北向资金沪深股通与十大流通股东持仓)
  8. Eastmoney Block Trades & Executive Share Changes (大宗交易折溢价与重要股东/高管增减持)
  9. Sina Finance Stock News & Eastmoney Guba Retail Buzz (新浪财经个股资讯 & 东方财富股吧热帖)
  10. Eastmoney Official CMS Full-text Search (权威财媒突发危机与黑天鹅事件深度追踪)
"""

import http.cookiejar
import os
import urllib.request
import urllib.parse
import re
import html
import json
import logging

logger = logging.getLogger(__name__)

# Direct opener to bypass any local proxy loops
_direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# Xueqiu Session & Cookie Jar
_xueqiu_cookie_jar = http.cookiejar.CookieJar()
_xueqiu_opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(_xueqiu_cookie_jar),
    urllib.request.ProxyHandler({})
)
_xueqiu_initialized = False

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
XUEQIU_HEADERS = {
    'User-Agent': UA,
    'Referer': 'https://xueqiu.com/'
}
DEFAULT_HEADERS = {
    'User-Agent': UA
}


def inject_xueqiu_cookie_string(cookie_str: str) -> None:
    """Parse 'name=val; name2=val2' and inject into cookie jar."""
    if not cookie_str:
        return
    for pair in cookie_str.split(';'):
        pair = pair.strip()
        if '=' not in pair:
            continue
        name, _, value = pair.partition('=')
        cookie = http.cookiejar.Cookie(
            version=0,
            name=name.strip(),
            value=value.strip(),
            port=None,
            port_specified=False,
            domain='.xueqiu.com',
            domain_specified=True,
            domain_initial_dot=True,
            path='/',
            path_specified=True,
            secure=True,
            expires=None,
            discard=True,
            comment=None,
            comment_url=None,
            rest={},
        )
        _xueqiu_cookie_jar.set_cookie(cookie)


def ensure_xueqiu_cookies(custom_cookie: str = '') -> None:
    """Ensure Xueqiu cookies exist. Priority: explicit argument -> XUEQIU_COOKIE env -> public session."""
    global _xueqiu_initialized
    if custom_cookie:
        inject_xueqiu_cookie_string(custom_cookie)
        _xueqiu_initialized = True
        return
    if _xueqiu_initialized:
        return
    env_cookie = os.environ.get('XUEQIU_COOKIE', '').strip()
    if env_cookie:
        inject_xueqiu_cookie_string(env_cookie)
        _xueqiu_initialized = True
        return
    try:
        req = urllib.request.Request('https://xueqiu.com/about', headers=XUEQIU_HEADERS)
        _xueqiu_opener.open(req, timeout=4)
        _xueqiu_initialized = True
    except Exception as e:
        logger.debug('Xueqiu cookie init error: %s', e)


def fetch_xueqiu_sentiment(ticker: str, company_name: str = '', custom_cookie: str = '') -> dict:
    """Fetch Xueqiu stock quote, popularity ranking, and capital distribution."""
    ensure_xueqiu_cookies(custom_cookie)

    clean_digits = ''.join([c for c in ticker if c.isdigit()])
    upper = ticker.upper()
    is_cn_stock = bool(clean_digits and ('.SS' in upper or '.SZ' in upper or '.BJ' in upper or len(clean_digits) == 6))

    symbol = ''
    if is_cn_stock and clean_digits:
        prefix = 'SH' if (upper.endswith('.SS') or clean_digits.startswith('6')) else ('BJ' if clean_digits.startswith(('8', '4', '920')) else 'SZ')
        symbol = f'{prefix}{clean_digits}'
    elif not clean_digits:
        symbol = ticker.upper()

    xueqiu_data = {
        'quote': {},
        'hot_rank': None,
        'capital_dist': {},
        'posts': [],
        'alerts': []
    }

    # 1. Quote
    if symbol:
        try:
            url = f'https://stock.xueqiu.com/v5/stock/quote.json?symbol={symbol}&extend=detail'
            req = urllib.request.Request(url, headers=XUEQIU_HEADERS)
            with _xueqiu_opener.open(req, timeout=4) as resp:
                d = json.loads(resp.read().decode('utf-8'))
                q = (d.get('data') or {}).get('quote') or {}
                if q:
                    xueqiu_data['quote'] = {
                        'name': q.get('name'),
                        'current': q.get('current'),
                        'percent': q.get('percent'),
                        'turnover_rate': q.get('turnover_rate'),
                        'pe_ttm': q.get('pe_ttm'),
                        'high52w': q.get('high52w'),
                        'low52w': q.get('low52w'),
                    }
                    if not company_name and q.get('name'):
                        company_name = q.get('name')
        except Exception as e:
            logger.debug('Xueqiu quote error: %s', e)

    # 2. Hot Ranking (雪球全网人气榜)
    if symbol:
        try:
            url = 'https://stock.xueqiu.com/v5/stock/hot_stock/list.json?size=100&type=10'
            req = urllib.request.Request(url, headers=XUEQIU_HEADERS)
            with _xueqiu_opener.open(req, timeout=4) as resp:
                d = json.loads(resp.read().decode('utf-8'))
                items = (d.get('data') or {}).get('items') or []
                for idx, it in enumerate(items, 1):
                    if it.get('code') == symbol or it.get('symbol') == symbol:
                        xueqiu_data['hot_rank'] = {
                            'rank': idx,
                            'name': it.get('name'),
                            'percent': it.get('percent'),
                            'hot_value': it.get('value')
                        }
                        xueqiu_data['alerts'].append(
                            f'【雪球全网热度霸榜 TOP {idx}】{it.get("name")} 登上雪球热门人气榜第 {idx} 位 (热度值: {it.get("value")})，市场情绪高度聚焦！'
                        )
                        break
        except Exception as e:
            logger.debug('Xueqiu hot rank error: %s', e)

    # 3. Capital Distribution (雪球主力/散户资金分布: 超大单、大单、中单、小单)
    if symbol:
        try:
            url = f'https://stock.xueqiu.com/v5/stock/capital/distribution.json?symbol={symbol}'
            req = urllib.request.Request(url, headers=XUEQIU_HEADERS)
            with _xueqiu_opener.open(req, timeout=4) as resp:
                d = json.loads(resp.read().decode('utf-8'))
                dist_data = d.get('data') or {}
                dist = dist_data.get('distribution') or {}
                buy_d = dist.get('buy') or {}
                sell_d = dist.get('sell') or {}
                if buy_d and sell_d:
                    net_inflow_wan = round(float(dist_data.get('net_inflow') or 0) / 10000, 2)
                    xl_net = round((float(buy_d.get('xlarge') or 0) - float(sell_d.get('xlarge') or 0)) / 10000, 2)
                    lg_net = round((float(buy_d.get('large') or 0) - float(sell_d.get('large') or 0)) / 10000, 2)
                    md_net = round((float(buy_d.get('medium') or 0) - float(sell_d.get('medium') or 0)) / 10000, 2)
                    sm_net = round((float(buy_d.get('small') or 0) - float(sell_d.get('small') or 0)) / 10000, 2)
                    xueqiu_data['capital_dist'] = {
                        'net_inflow_wan': net_inflow_wan,
                        'xlarge_net_wan': xl_net,
                        'large_net_wan': lg_net,
                        'medium_net_wan': md_net,
                        'small_net_wan': sm_net,
                    }
                    main_net = round(xl_net + lg_net, 2)
                    if main_net <= -10000:
                        xueqiu_data['alerts'].append(
                            f'【雪球主力资金大幅出逃】当日超大单+大单主力合计净流出 {abs(main_net)} 万元 (超大单净额: {xl_net} 万，大单净额: {lg_net} 万)'
                        )
                    elif main_net >= 10000:
                        xueqiu_data['alerts'].append(
                            f'【雪球主力资金大举扫货】当日超大单+大单主力合计净流入 {main_net} 万元 (超大单净额: {xl_net} 万，大单净额: {lg_net} 万)'
                        )
        except Exception as e:
            logger.debug('Xueqiu capital distribution error: %s', e)

    return xueqiu_data


def fetch_multichannel_sentiment(ticker: str, trade_date: str = '', company_name: str = '', custom_event: str = '', xueqiu_cookie: str = '') -> dict:
    """Consolidate comprehensive public sentiment, institutional research, capital flows, announcements and media."""
    clean_digits = ''.join([c for c in ticker if c.isdigit()])
    upper = ticker.upper()
    is_cn_stock = bool(clean_digits and ('.SS' in upper or '.SZ' in upper or '.BJ' in upper or len(clean_digits) == 6))

    headers = {'User-Agent': UA}

    alerts = []
    notices = []
    guba_posts = []
    news_items = []
    research_reports = []
    dragon_tiger = []
    shareholders = []
    margin_trading = []
    northbound_holdings = []
    block_trades = []
    holder_changes = []

    # 1. Tencent Stock Quote & Price Limit detection
    if is_cn_stock and clean_digits:
        prefix = 'sh' if (upper.endswith('.SS') or clean_digits.startswith('6')) else ('bj' if clean_digits.startswith(('8', '4', '920')) else 'sz')
        try:
            req = urllib.request.Request(f'https://qt.gtimg.cn/q={prefix}{clean_digits}', headers=headers)
            with _direct_opener.open(req, timeout=3) as resp:
                raw_bytes = resp.read()
                raw_txt = raw_bytes.decode('gbk', errors='ignore')
                parts = raw_txt.split('~')
                if len(parts) > 48:
                    c_name = parts[1]
                    if not company_name and c_name:
                        company_name = c_name
                    cur_p = float(parts[3]) if parts[3] else 0.0
                    chg_pct = float(parts[32]) if parts[32] else 0.0
                    limit_down = float(parts[48]) if parts[48] else 0.0
                    low_p = float(parts[34]) if parts[34] else 0.0

                    if limit_down > 0 and (cur_p <= limit_down or low_p <= limit_down):
                        alerts.append(f'【极度高危·触及跌停】当日股价触及或封死跌停板 (现价: {cur_p}, 跌停价: {limit_down}, 涨跌幅: {chg_pct}%)')
                    elif chg_pct <= -7.0:
                        alerts.append(f'【重度大跌预警】单日暴跌 {chg_pct}% (现价: {cur_p})，极端恐慌抛盘释放')
        except Exception as e:
            logger.debug('Tencent quote check error: %s', e)

    # 2. Eastmoney Official Announcements (公告)
    if is_cn_stock and clean_digits:
        try:
            url = f'https://np-anotice-stock.eastmoney.com/api/security/ann?sr=-1&page_size=8&page_index=1&ann_type=A&stock_list={clean_digits}'
            req = urllib.request.Request(url, headers=headers)
            with _direct_opener.open(req, timeout=3) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                for item in data.get('data', {}).get('list', []):
                    d = item.get('notice_date', '')[:10]
                    t = item.get('title', '')
                    notices.append(f'[{d}] {t}')
                    if any(k in t for k in ('异常波动', '风险', '立案', '处罚', '澄清', '诉讼', '被查', '停牌', '核查')):
                        alerts.append(f'【官方重要预警公告】{d} {t}')
        except Exception as e:
            logger.debug('Eastmoney notice error: %s', e)

    # 3. Eastmoney Professional Research Reports (券商研报与评级)
    if is_cn_stock and clean_digits:
        try:
            url = f'https://reportapi.eastmoney.com/report/list?industryCode=*&pageSize=6&industry=*&rating=*&ratingChange=*&beginTime=2024-01-01&endTime=2026-12-31&pageNo=1&fields=&qType=0&code={clean_digits}'
            req = urllib.request.Request(url, headers=headers)
            with _direct_opener.open(req, timeout=3) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                for item in data.get('data', []):
                    d = item.get('publishDate', '')[:10]
                    title = item.get('title', '')
                    org = item.get('orgSName', '')
                    rating = item.get('emRatingName', '')
                    research_reports.append(f'[{d}] {org} | {rating} | {title}')
        except Exception as e:
            logger.debug('Eastmoney research report error: %s', e)

    # 4. Eastmoney Dragon-Tiger Billboard (龙虎榜资金席位异动)
    if is_cn_stock and clean_digits:
        try:
            url = f'https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_DAILYBILLBOARD_DETAILS&columns=SECURITY_CODE,SECUCODE,SECURITY_NAME_ABBR,TRADE_DATE,EXPLAIN,CLOSE_PRICE,CHANGE_RATE,BILLBOARD_NET_AMT&filter=(SECURITY_CODE%3D%22{clean_digits}%22)&pageNumber=1&pageSize=3&sortTypes=-1&sortColumns=TRADE_DATE'
            req = urllib.request.Request(url, headers=headers)
            with _direct_opener.open(req, timeout=3) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                items = data.get('result', {}).get('data', []) if data.get('result') else []
                for it in items:
                    d = it.get('TRADE_DATE', '')[:10]
                    expl = it.get('EXPLAIN', '')
                    net_amt = round(float(it.get('BILLBOARD_NET_AMT', 0)) / 10000, 2)
                    dragon_tiger.append(f'[{d}] {expl} | 龙虎榜净买入: {net_amt} 万元')
                    if net_amt < -3000:
                        alerts.append(f'【龙虎榜机构/游资大幅净卖出】{d} 净卖出 {abs(net_amt)} 万元 ({expl})')
        except Exception as e:
            logger.debug('Eastmoney dragon tiger error: %s', e)

    # 5. Eastmoney Margin Trading (融资融券与杠杆资金博弈)
    if is_cn_stock and clean_digits:
        try:
            url = f'https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPTA_WEB_RZRQ_GGMX&columns=DATE,SCODE,SECNAME,RZYE,RZMRE,RQYE,RQMCL,RZRQYE,RZJME&filter=(SCODE%3D%22{clean_digits}%22)&pageNumber=1&pageSize=3&sortTypes=-1&sortColumns=DATE'
            req = urllib.request.Request(url, headers=headers)
            with _direct_opener.open(req, timeout=3) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                items = (data.get('result') or {}).get('data', [])
                for it in items:
                    d = (it.get('DATE') or '')[:10]
                    rzye_yi = round(float(it.get('RZYE') or 0) / 1e8, 2)
                    rzmre_wan = round(float(it.get('RZMRE') or 0) / 1e4, 2)
                    rzjme_wan = round(float(it.get('RZJME') or 0) / 1e4, 2)
                    rqye_wan = round(float(it.get('RQYE') or 0) / 1e4, 2)
                    margin_trading.append(
                        f'[{d}] 融资余额: {rzye_yi} 亿元 | 当日融资净买入: {rzjme_wan} 万元 (买入: {rzmre_wan} 万) | 融券余额: {rqye_wan} 万元'
                    )
        except Exception as e:
            logger.debug('Eastmoney margin trading error: %s', e)

    # 6. Eastmoney Northbound Capital & Top 10 Circulating Shareholders (北向资金与十大流通股东)
    if is_cn_stock and clean_digits:
        try:
            url_nb = f'https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_MUTUAL_HOLDSTOCKNORTH_STA&columns=TRADE_DATE,SECURITY_CODE,SECURITY_NAME,HOLD_SHARES,HOLD_MARKET_CAP,FREE_SHARES_RATIO&filter=(SECURITY_CODE%3D%22{clean_digits}%22)&pageNumber=1&pageSize=2&sortTypes=-1&sortColumns=TRADE_DATE'
            req_nb = urllib.request.Request(url_nb, headers=headers)
            with _direct_opener.open(req_nb, timeout=3) as resp:
                data_nb = json.loads(resp.read().decode('utf-8'))
                items_nb = (data_nb.get('result') or {}).get('data', [])
                for it in items_nb:
                    d = (it.get('TRADE_DATE') or '')[:10]
                    cap_yi = round(float(it.get('HOLD_MARKET_CAP') or 0) / 1e8, 2)
                    ratio = it.get('FREE_SHARES_RATIO')
                    northbound_holdings.append(f'[{d}] 沪深股通(北向资金)持股市值: {cap_yi} 亿元 (占流通股比: {ratio}%)')
        except Exception as e:
            logger.debug('Eastmoney northbound error: %s', e)

        try:
            url = f'https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_DMSK_HOLDERS&columns=SECUCODE,SECURITY_NAME_ABBR,END_DATE,HOLDER_NAME,HOLD_NUM,HOLD_RATIO,HOLD_CHANGE&filter=(SECURITY_CODE%3D%22{clean_digits}%22)&pageNumber=1&pageSize=5&sortTypes=-1&sortColumns=END_DATE'
            req = urllib.request.Request(url, headers=headers)
            with _direct_opener.open(req, timeout=3) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                items = data.get('result', {}).get('data', []) if data.get('result') else []
                for it in items:
                    name = it.get('HOLDER_NAME', '')
                    ratio = it.get('HOLD_RATIO', '')
                    chg = it.get('HOLD_CHANGE', '')
                    d = it.get('END_DATE', '')[:10]
                    shareholders.append(f'{name} (占比: {ratio}%, 变动: {chg}, 报告期: {d})')
        except Exception as e:
            logger.debug('Eastmoney shareholder error: %s', e)

    # 7. Eastmoney Block Trades & Holder Increase/Decrease (大宗交易与高管/重要股东增减持)
    if is_cn_stock and clean_digits:
        try:
            url_bt = f'https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_DATA_BLOCKTRADE&columns=TRADE_DATE,SECURITY_CODE,DEAL_PRICE,CLOSE_PRICE,PREMIUM_RATIO,DEAL_AMT,BUYER_NAME,SELLER_NAME&filter=(SECURITY_CODE%3D%22{clean_digits}%22)&pageNumber=1&pageSize=3&sortTypes=-1&sortColumns=TRADE_DATE'
            req_bt = urllib.request.Request(url_bt, headers=headers)
            with _direct_opener.open(req_bt, timeout=3) as resp:
                d_bt = json.loads(resp.read().decode('utf-8'))
                for it in (d_bt.get('result') or {}).get('data', []):
                    d = (it.get('TRADE_DATE') or '')[:10]
                    amt_wan = round(float(it.get('DEAL_AMT') or 0) / 1e4, 2)
                    prem = round(float(it.get('PREMIUM_RATIO') or 0) * 100, 2)
                    block_trades.append(
                        f'[{d}] 成交额: {amt_wan} 万元 | 成交价: {it.get("DEAL_PRICE")} (折溢价率: {prem}%) | 买方: {it.get("BUYER_NAME")} | 卖方: {it.get("SELLER_NAME")}'
                    )
        except Exception as e:
            logger.debug('Eastmoney block trade error: %s', e)

        try:
            url_hc = f'https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_SHARE_HOLDER_INCREASE&columns=NOTICE_DATE,HOLDER_NAME,DIRECTION,CHANGE_NUM,AFTER_CHANGE_RATE&filter=(SECURITY_CODE%3D%22{clean_digits}%22)&pageNumber=1&pageSize=3&sortTypes=-1&sortColumns=NOTICE_DATE'
            req_hc = urllib.request.Request(url_hc, headers=headers)
            with _direct_opener.open(req_hc, timeout=3) as resp:
                d_hc = json.loads(resp.read().decode('utf-8'))
                for it in (d_hc.get('result') or {}).get('data', []):
                    d = (it.get('NOTICE_DATE') or '')[:10]
                    holder_changes.append(
                        f'[{d}] {it.get("HOLDER_NAME")} | {it.get("DIRECTION")} {it.get("CHANGE_NUM")} 万股'
                    )
        except Exception as e:
            logger.debug('Eastmoney holder change error: %s', e)

    # 8. Sina Stock Financial News (新浪财经)
    if is_cn_stock and clean_digits:
        prefix = 'sh' if (upper.endswith('.SS') or clean_digits.startswith('6')) else ('bj' if clean_digits.startswith(('8', '4', '920')) else 'sz')
        try:
            url = f'https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllNewsStock.php?symbol={prefix}{clean_digits}&Page=1'
            req = urllib.request.Request(url, headers=headers)
            with _direct_opener.open(req, timeout=3) as resp:
                raw_bytes = resp.read()
                txt = raw_bytes.decode('gbk', errors='ignore')
                matches = re.findall(r"<a target='_blank' href='[^']+'>([^<]+)</a>", txt)
                for m in matches[:15]:
                    clean = re.sub(r'<[^>]+>', '', m).strip()
                    if clean and clean not in news_items:
                        news_items.append(clean)
                        if any(k in clean for k in ('断裂', '刹车', '踏板', '事故', '跌停', '暴跌', '雷', '蒸发', '退订', '立案', '召回', '亏损', '质检')):
                            alerts.append(f'【核心媒体负面预警】{clean}')
        except Exception as e:
            logger.debug('Sina stock news error: %s', e)

    # 9. Eastmoney Guba retail sentiment buzz (东财股吧热帖)
    if is_cn_stock and clean_digits:
        try:
            url = f'https://guba.eastmoney.com/list,{clean_digits}.html'
            req = urllib.request.Request(url, headers=headers)
            with _direct_opener.open(req, timeout=3) as resp:
                html_txt = resp.read().decode('utf-8', errors='ignore')
                p = re.compile(r'class=["\x27]title["\x27]><a[^>]*>(.*?)</a>')
                matches = p.findall(html_txt)
                for r in matches[:15]:
                    clean = re.sub(r'<[^>]+>', '', r).strip()
                    if clean and clean not in guba_posts:
                        guba_posts.append(clean)
                        if any(k in clean for k in ('断裂', '刹车', '踏板', '跌停', '跑路', '完蛋', '立案', '维权', '造假')):
                            alerts.append(f'【股民社群恐慌高热】{clean}')
        except Exception as e:
            logger.debug('Eastmoney guba error: %s', e)

    # 10. Xueqiu (雪球) Integration (Agent-Reach style)
    xueqiu_info = fetch_xueqiu_sentiment(ticker, company_name=company_name, custom_cookie=xueqiu_cookie)
    if xueqiu_info.get('alerts'):
        alerts.extend(xueqiu_info['alerts'])
    if not company_name and xueqiu_info.get('quote', {}).get('name'):
        company_name = xueqiu_info['quote']['name']

    # 11. Eastmoney Official Search CMS API (定向全网财媒深度检索 - 仅保留与当前标的强相关的危机报道)
    kw_target = company_name or ticker
    target_tokens = [t for t in [company_name, clean_digits, '尊界'] if t]
    search_keywords = [f'{kw_target} 刹车', f'{kw_target} 风险', kw_target]
    found_titles = set(news_items)

    for kw in search_keywords:
        try:
            param_dict = {
                'uid': '',
                'keyword': kw,
                'type': ['cmsArticleWebOld'],
                'client': 'web',
                'clientType': 'web',
                'clientVersion': 'curr',
                'param': {'cmsArticleWebOld': {'needAll': 0}}
            }
            encoded = urllib.parse.quote(json.dumps(param_dict))
            s_url = f'https://search-api-web.eastmoney.com/search/jsonp?cb=callback&param={encoded}'
            req = urllib.request.Request(s_url, headers=headers)
            with _direct_opener.open(req, timeout=3) as resp:
                raw_txt = resp.read().decode('utf-8')
                m = re.search(r'callback\((.*)\)', raw_txt, re.S)
                if m:
                    d = json.loads(m.group(1))
                    res_items = d.get('result', {}).get('cmsArticleWebOld', [])
                    for it in res_items[:6]:
                        t = html.unescape(re.sub(r'<[^>]+>', '', it.get('title', ''))).strip()
                        content_snip = html.unescape(re.sub(r'<[^>]+>', '', it.get('content', ''))).strip()
                        date_str = it.get('date', '')[:10]
                        if not t or t in found_titles:
                            continue
                        if target_tokens and not any(tok in (t + content_snip) for tok in target_tokens):
                            continue
                        found_titles.add(t)
                        news_items.append(f'[{date_str}] {t}')
                        if any(k in t for k in ('断裂', '刹车', '踏板', '事故', '跌停', '退订', '立案', '召回', '暴跌', '雷', '巨震')):
                            alerts.append(f'【权威财媒重点危机预警】[{date_str}] {t}')
        except Exception as e:
            logger.debug('Eastmoney CMS search error: %s', e)

    if custom_event and custom_event.strip():
        alerts.insert(0, f'【实盘突发重点线索(用户直供)】{custom_event.strip()}')

    return {
        'ticker': ticker,
        'company_name': company_name,
        'alerts': list(dict.fromkeys(alerts)),
        'notices': notices,
        'research_reports': research_reports,
        'dragon_tiger': dragon_tiger,
        'margin_trading': margin_trading,
        'northbound_holdings': northbound_holdings,
        'block_trades': block_trades,
        'holder_changes': holder_changes,
        'shareholders': shareholders,
        'guba_posts': guba_posts,
        'xueqiu_info': xueqiu_info,
        'news_items': news_items,
        'custom_event': custom_event.strip()
    }


def format_multichannel_sentiment_prompt(data: dict) -> str:
    lines = []
    lines.append('### 多渠道全网舆情、机构研报、主力资金与突发风险异动 (Multi-Channel Public Opinion & Institutional Flow)')

    alerts = data.get('alerts', [])
    if alerts:
        lines.append('\n#### 🚨 核心风险异动与黑天鹅预警 (Critical Crisis & Anomaly Alerts):')
        for a in alerts:
            lines.append(f'- {a}')

    custom_event = data.get('custom_event', '')
    if custom_event:
        lines.append(f'\n#### ⚡ 用户实盘指定突发事件背景:\n{custom_event}')

    # Xueqiu Section
    xueqiu_info = data.get('xueqiu_info') or {}
    q = xueqiu_info.get('quote') or {}
    rank = xueqiu_info.get('hot_rank')
    cap = xueqiu_info.get('capital_dist') or {}

    if q or rank or cap:
        lines.append('\n#### ❄️ 雪球社区深度舆情、人气榜与主力资金分布 (Xueqiu Community & Capital Flow):')
        if rank:
            lines.append(f'- **雪球全网人气榜**: 第 {rank.get("rank")} 名 | 涨跌幅: {rank.get("percent")}% | 热度指数: {rank.get("hot_value")}')
        if q:
            lines.append(f'- **雪球实时盘口**: 现价 {q.get("current")} ({q.get("percent")}%) | 换手率 {q.get("turnover_rate")}% | 动态PE {q.get("pe_ttm")} | 52周区间: {q.get("low52w")} ~ {q.get("high52w")}')
        if cap:
            lines.append(
                f'- **雪球主力与散户资金分布**: 全天净流入 {cap.get("net_inflow_wan")} 万元 | '
                f'超大单净额: {cap.get("xlarge_net_wan")} 万 | 大单净额: {cap.get("large_net_wan")} 万 | '
                f'中单净额: {cap.get("medium_net_wan")} 万 | 小单净额: {cap.get("small_net_wan")} 万'
            )

    # Margin Trading & Northbound Capital
    margin = data.get('margin_trading', [])
    northbound = data.get('northbound_holdings', [])
    if margin or northbound:
        lines.append('\n#### 💰 两融杠杆资金与北向资金动向 (Margin Trading & Northbound Capital):')
        for m in margin[:3]:
            lines.append(f'- [两融明细] {m}')
        for nb in northbound[:2]:
            lines.append(f'- [北向持仓] {nb}')

    # Institutional Research Reports
    reports = data.get('research_reports', [])
    if reports:
        lines.append('\n#### 📑 头部券商机构研报与最新评级 (Institutional Research Reports & Ratings):')
        for r in reports[:6]:
            lines.append(f'- {r}')

    # Dragon-Tiger Billboard & Block Trades
    lhb = data.get('dragon_tiger', [])
    bt = data.get('block_trades', [])
    if lhb or bt:
        lines.append('\n#### 🐉 龙虎榜主力席位与大宗交易折溢价 (Dragon-Tiger Billboard & Block Trades):')
        for l in lhb[:3]:
            lines.append(f'- [龙虎榜] {l}')
        for b in bt[:3]:
            lines.append(f'- [大宗交易] {b}')

    # Top Shareholders & Holder Changes
    holders = data.get('shareholders', [])
    hc = data.get('holder_changes', [])
    if holders or hc:
        lines.append('\n#### 👥 十大流通股东与高管/重要股东增减持 (Top Shareholders & Insider Changes):')
        for h in holders[:5]:
            lines.append(f'- [流通股东] {h}')
        for c in hc[:3]:
            lines.append(f'- [股东增减持] {c}')

    # Official Notices
    notices = data.get('notices', [])
    if notices:
        lines.append('\n#### 📢 公司最新官方公告 (Eastmoney Official Announcements):')
        for n in notices[:6]:
            lines.append(f'- {n}')

    # News
    news_items = data.get('news_items', [])
    if news_items:
        lines.append('\n#### 📰 权威媒体全网财经新闻与危机追踪 (Breaking News & In-depth Reporting):')
        for item in news_items[:12]:
            lines.append(f'- {item}')

    # Eastmoney Guba
    guba_posts = data.get('guba_posts', [])
    if guba_posts:
        lines.append('\n#### 💬 东方财富股吧 散户实时热议与情绪风向 (Eastmoney Guba Buzz):')
        for p in guba_posts[:10]:
            lines.append(f'- {p}')

    return '\n'.join(lines)