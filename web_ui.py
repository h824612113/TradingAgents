import os
import sys
import json
import threading
import urllib.request
import urllib.parse
import urllib.error
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ENV_PATH = Path(".env")
CONFIG_PATH = Path("web_config.json")

def load_settings():
    env_vars = {}
    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip()
    
    models = []
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if "models" in saved and isinstance(saved["models"], list):
                    models = saved["models"]
        except Exception:
            pass

    return {
        "api_key": env_vars.get("OPENAI_API_KEY", ""),
        "backend_url": env_vars.get("TRADINGAGENTS_LLM_BACKEND_URL", "https://ai.cyberhz.com/v1"),
        "deep_model": env_vars.get("TRADINGAGENTS_DEEP_THINK_LLM", ""),
        "quick_model": env_vars.get("TRADINGAGENTS_QUICK_THINK_LLM", ""),
        "language": env_vars.get("TRADINGAGENTS_OUTPUT_LANGUAGE", "zh-CN"),
        "xueqiu_cookie": env_vars.get("XUEQIU_COOKIE", ""),
        "candidate_models": models
    }

def save_settings(data):
    lines = []
    lines.append(f"OPENAI_API_KEY={data.get('api_key', '').strip()}\n")
    lines.append("TRADINGAGENTS_LLM_PROVIDER=openai\n")
    lines.append(f"TRADINGAGENTS_LLM_BACKEND_URL={data.get('backend_url', '').strip()}\n")
    lines.append(f"TRADINGAGENTS_DEEP_THINK_LLM={data.get('deep_model', '').strip()}\n")
    lines.append(f"TRADINGAGENTS_QUICK_THINK_LLM={data.get('quick_model', '').strip()}\n")
    lines.append(f"TRADINGAGENTS_OUTPUT_LANGUAGE={data.get('language', 'zh-CN').strip()}\n")
    if data.get("xueqiu_cookie") is not None:
        lines.append(f"XUEQIU_COOKIE={data.get('xueqiu_cookie', '').strip()}\n")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"models": data.get("candidate_models", [])}, f, ensure_ascii=False, indent=2)

def fetch_online_models(base_url, api_key):
    url = base_url.strip().rstrip("/")
    if url.endswith("/v1"):
        endpoint = f"{url}/models"
    else:
        endpoint = f"{url}/v1/models"

    req = urllib.request.Request(endpoint, headers={
        "Authorization": f"Bearer {api_key.strip()}",
        "User-Agent": "TradingAgents-WebUI"
    })

    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            if response.status == 200:
                body = response.read().decode("utf-8")
                data = json.loads(body)
                items = data.get("data", [])
                models = [item["id"] for item in items if isinstance(item, dict) and "id" in item]
                models.sort()
                return True, models, "成功获取模型列表"
            else:
                return False, [], f"请求失败，HTTP 状态码: {response.status}"
    except urllib.error.HTTPError as e:
        return False, [], f"HTTP 错误 {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return False, [], f"网络连接错误: {str(e.reason)}"
    except Exception as e:
        return False, [], f"解析失败: {str(e)}"


def verify_ticker_meta(raw_ticker):
    from tradingagents.dataflows.symbols import normalize_symbol

    raw = (raw_ticker or '').strip()
    if not raw:
        return {'ok': False, 'msg': '请输入股票或资产代码'}

    canonical = normalize_symbol(raw)

    cn_name = ''
    price = None
    exchange = '全球/美股'
    currency = 'USD'

    # 常见核心资产预置中文映射（零网络延迟秒级返回）
    COMMON_NAMES = {
        '600418.SS': ('江淮汽车', '上交所', 'CNY'),
        '600519.SS': ('贵州茅台', '上交所', 'CNY'),
        '000001.SZ': ('平安银行', '深交所', 'CNY'),
        '002594.SZ': ('比亚迪', '深交所', 'CNY'),
        '300750.SZ': ('宁德时代', '深交所', 'CNY'),
        '688981.SS': ('中芯国际', '科创板', 'CNY'),
        '0700.HK': ('腾讯控股', '港交所', 'HKD'),
        '3690.HK': ('美团', '港交所', 'HKD'),
        '9988.HK': ('阿里巴巴', '港交所', 'HKD'),
        'NVDA': ('英伟达 (NVIDIA)', '纳斯达克', 'USD'),
        'AAPL': ('苹果 (Apple)', '纳斯达克', 'USD'),
        'MSFT': ('微软 (Microsoft)', '纳斯达克', 'USD'),
        'TSLA': ('特斯拉 (Tesla)', '纳斯达克', 'USD'),
        'GOOGL': ('谷歌 (Alphabet)', '纳斯达克', 'USD'),
        'BTC-USD': ('比特币 (Bitcoin)', '加密货币', 'USD'),
        'ETH-USD': ('以太坊 (Ethereum)', '加密货币', 'USD'),
        'SOL-USD': ('Solana', '加密货币', 'USD'),
        'GC=F': ('黄金期货 (COMEX Gold)', '大宗商品', 'USD'),
        'CL=F': ('原油期货 (WTI Crude)', '大宗商品', 'USD'),
        '^GSPC': ('标普500指数 (S&P 500)', '全球指数', 'USD'),
        # 常见热门场内 ETF / 公募基金
        '510300.SS': ('华泰柏瑞沪深300ETF', '上交所(ETF)', 'CNY'),
        '510500.SS': ('南方中证500ETF', '上交所(ETF)', 'CNY'),
        '588000.SS': ('华夏科创50ETF', '上交所(ETF)', 'CNY'),
        '159915.SZ': ('易方达创业板ETF', '深交所(ETF)', 'CNY'),
        '159919.SZ': ('嘉实沪深300ETF', '深交所(ETF)', 'CNY'),
        '161725.SZ': ('招商中证白酒指数(LOF)', '深交所(LOF)', 'CNY'),
        '512880.SS': ('国泰中证全指证券ETF', '上交所(ETF)', 'CNY'),
        '513050.SS': ('易方达中概互联50ETF', '上交所(ETF/QDII)', 'CNY'),
        '513100.SS': ('国泰纳斯达克100ETF', '上交所(ETF/QDII)', 'CNY'),
        '512010.SS': ('易方达沪深300医药卫生ETF', '上交所(ETF)', 'CNY'),
        '512690.SS': ('鹏华中证酒ETF', '上交所(ETF)', 'CNY'),
        '159920.SZ': ('华夏恒生ETF', '深交所(ETF/QDII)', 'CNY'),
        'SPY': ('标普500ETF (SPDR S&P 500 ETF)', '美股ETF (NYSE Arca)', 'USD'),
        'QQQ': ('纳指100ETF (Invesco QQQ Trust)', '美股ETF (NASDAQ)', 'USD'),
        '000001': ('华夏成长混合 (公募场外)', '场外开放式基金', 'CNY'),
        '110011': ('易方达优质精选混合 (公募场外)', '场外开放式基金', 'CNY')
    }

    is_fund = False
    if canonical in COMMON_NAMES:
        cn_name, exchange, currency = COMMON_NAMES[canonical]
        if 'ETF' in exchange or 'LOF' in exchange or '基金' in exchange:
            is_fund = True
    elif canonical.endswith('.SS'):
        code_part = canonical.split('.')[0]
        if code_part.startswith(('51', '56', '58', '50')):
            exchange = '上交所(ETF/基金)'
            is_fund = True
        else:
            exchange = '上交所'
        currency = 'CNY'
    elif canonical.endswith('.SZ'):
        code_part = canonical.split('.')[0]
        if code_part.startswith(('159', '16', '18')):
            exchange = '深交所(ETF/LOF)'
            is_fund = True
        else:
            exchange = '深交所'
        currency = 'CNY'
    elif canonical.endswith('.BJ'):
        exchange = '北交所'
        currency = 'CNY'
    elif canonical.endswith('.HK'):
        exchange = '港交所'
        currency = 'HKD'
    elif '-' in canonical:
        exchange = '加密货币'
    elif '=F' in canonical:
        exchange = '大宗商品期货'
    elif canonical.startswith('^'):
        exchange = '全球指数'

    # 若非预置名单且包含网络可用性，快速尝试获取最新行情/净值与名称
    if not cn_name:
        if canonical.endswith('.SS') or canonical.endswith('.SZ') or canonical.endswith('.BJ'):
            code = canonical.split('.')[0]
            prefix = 'sh' if canonical.endswith('.SS') else ('sz' if canonical.endswith('.SZ') else 'bj')
            try:
                import urllib.request, ssl
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                req = urllib.request.Request(f'https://qt.gtimg.cn/q={prefix}{code}', headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, context=ctx, timeout=1.5) as resp:
                    data = resp.read().decode('gbk', errors='ignore')
                    parts = data.split('~')
                    if len(parts) > 3:
                        cn_name = parts[1]
                        try:
                            price = float(parts[3])
                        except Exception:
                            pass
            except Exception:
                pass
        # 尝试场外基金查询 (例如输入 000001, 110011 等6位纯数字)
        elif len(raw) == 6 and raw.isdigit():
            try:
                import urllib.request, ssl
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                req = urllib.request.Request(f'https://qt.gtimg.cn/q=jj{raw}', headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, context=ctx, timeout=1.5) as resp:
                    data = resp.read().decode('gbk', errors='ignore')
                    parts = data.split('~')
                    if len(parts) > 6 and parts[1]:
                        cn_name = parts[1]
                        exchange = '场外公募开放式基金'
                        currency = 'CNY'
                        is_fund = True
                        try:
                            price = float(parts[5]) # 最新单位净值
                        except Exception:
                            pass
            except Exception:
                pass

    display_name = cn_name or canonical

    return {
        'ok': True,
        'raw': raw,
        'canonical': canonical,
        'display_name': display_name,
        'cn_name': cn_name,
        'currency': currency,
        'exchange': exchange,
        'last_price': price,
        'is_fund': is_fund
    }

import time
from datetime import datetime as _dt

HISTORY_DIR = Path("analysis_history")
HISTORY_DIR.mkdir(exist_ok=True)

def _extract_sections_from_entry(entry):
    deb = entry.get("investment_debate_state") or {}
    rdeb = entry.get("risk_debate_state") or {}
    return {
        "market_report": entry.get("market_report", ""),
        "news_report": entry.get("news_report", ""),
        "sentiment_report": entry.get("sentiment_report", ""),
        "fundamentals_report": entry.get("fundamentals_report", ""),
        "bull_history": deb.get("bull_history", "") if isinstance(deb, dict) else "",
        "bear_history": deb.get("bear_history", "") if isinstance(deb, dict) else "",
        "investment_plan": entry.get("investment_plan", ""),
        "trader_investment_plan": entry.get("trader_investment_plan", ""),
        "risk_history": rdeb.get("history", "") if isinstance(rdeb, dict) else "",
        "final_trade_decision": entry.get("final_trade_decision", ""),
        "final_rating": entry.get("final_rating", "")
    }

def sync_existing_logs_to_history():
    try:
        from tradingagents.default_config import DEFAULT_CONFIG
        res_dir = Path(DEFAULT_CONFIG.get("results_dir", os.path.join(os.path.expanduser("~"), ".tradingagents", "logs")))
        if not res_dir.exists():
            return
        for log_file in res_dir.rglob("full_states_log_*.json"):
            try:
                mtime = int(log_file.stat().st_mtime)
                with open(log_file, "r", encoding="utf-8") as f:
                    entry = json.load(f)
                ticker = str(entry.get("company_of_interest") or log_file.parent.parent.name)
                tdate = str(entry.get("trade_date") or log_file.stem.replace("full_states_log_", ""))
                safe_tk = "".join(c if c.isalnum() or c in ".-_" else "_" for c in ticker)
                rec_id = f"{safe_tk}__{tdate}__legacy_{mtime}"
                # Check if already imported for same ticker + trade_date
                existing = list(HISTORY_DIR.glob(f"{safe_tk}__{tdate}__*.json"))
                if existing:
                    continue
                meta = verify_ticker_meta(ticker)
                rs = entry.get("run_settings") or {}
                record = {
                    "id": rec_id,
                    "ticker": ticker,
                    "canonical": meta.get("canonical", ticker),
                    "display_name": meta.get("display_name", ticker),
                    "exchange": meta.get("exchange", ""),
                    "trade_date": tdate,
                    "saved_at": _dt.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "deep_model": rs.get("deep_think_llm", "未知"),
                    "quick_model": rs.get("quick_think_llm", "未知"),
                    "final_rating": entry.get("final_rating") or "UNKNOWN",
                    "sections": _extract_sections_from_entry(entry)
                }
                with open(HISTORY_DIR / f"{rec_id}.json", "w", encoding="utf-8") as wf:
                    json.dump(record, wf, ensure_ascii=False, indent=2)
            except Exception:
                pass
    except Exception:
        pass

def save_run_to_history(ticker, trade_date, deep_model, quick_model, sections):
    try:
        HISTORY_DIR.mkdir(exist_ok=True)
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_tk = "".join(c if c.isalnum() or c in ".-_" else "_" for c in str(ticker))
        rec_id = f"{safe_tk}__{trade_date}__{ts}"
        meta = verify_ticker_meta(ticker)
        rating = sections.get("final_rating") or "DONE"
        record = {
            "id": rec_id,
            "ticker": ticker,
            "canonical": meta.get("canonical", ticker),
            "display_name": meta.get("display_name", ticker),
            "exchange": meta.get("exchange", ""),
            "trade_date": trade_date,
            "saved_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
            "deep_model": deep_model,
            "quick_model": quick_model,
            "final_rating": rating,
            "sections": dict(sections)
        }
        out_path = HISTORY_DIR / f"{rec_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        return rec_id, str(out_path.resolve())
    except Exception as e:
        return None, str(e)

def list_history_records():
    sync_existing_logs_to_history()
    items = []
    for fp in HISTORY_DIR.glob("*.json"):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            sec = data.get("sections") or {}
            decision_text = sec.get("final_trade_decision", "")
            summary_snip = decision_text.replace("\n", " ")[:180]
            items.append({
                "id": data.get("id", fp.stem),
                "ticker": data.get("ticker", ""),
                "canonical": data.get("canonical", ""),
                "display_name": data.get("display_name", data.get("ticker", "")),
                "exchange": data.get("exchange", ""),
                "trade_date": data.get("trade_date", ""),
                "saved_at": data.get("saved_at", ""),
                "deep_model": data.get("deep_model", ""),
                "quick_model": data.get("quick_model", ""),
                "final_rating": data.get("final_rating", "UNKNOWN"),
                "summary": summary_snip,
                "file_path": str(fp.resolve())
            })
        except Exception:
            pass
    items.sort(key=lambda x: x.get("saved_at", ""), reverse=True)
    return items

def get_history_record(rec_id):
    safe_id = Path(rec_id).name
    fp = HISTORY_DIR / f"{safe_id}.json"
    if not fp.exists():
        return None
    with open(fp, "r", encoding="utf-8") as f:
        return json.load(f)

def delete_history_record(rec_id):
    safe_id = Path(rec_id).name
    fp = HISTORY_DIR / f"{safe_id}.json"
    if fp.exists():
        fp.unlink()
        return True
    return False

current_task = {
    "running": False,
    "logs": [],
    "sections": {}
}

def run_tradingagents_task(ticker, trade_date, deep_model, quick_model, custom_event="", xueqiu_cookie=""):
    global current_task
    current_task["running"] = True
    current_task["logs"] = [f"[系统] 开始对标的 {ticker} 进行多智能体推演 (基准日期: {trade_date})..."]
    if custom_event:
        current_task["logs"].append(f"[舆情线索] 已注入定向危机/舆情检索词: {custom_event}")
    if xueqiu_cookie:
        os.environ["XUEQIU_COOKIE"] = xueqiu_cookie.strip()
        try:
            from tradingagents.dataflows.vendors.cn_sentiment import inject_xueqiu_cookie_string
            inject_xueqiu_cookie_string(xueqiu_cookie.strip())
            current_task["logs"].append("[雪球引擎] 已加载自定义雪球 Cookie 会话")
        except Exception:
            pass
    current_task["sections"] = {}

    try:
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        config = DEFAULT_CONFIG.copy()
        config["deep_think_llm"] = deep_model
        config["quick_think_llm"] = quick_model

        current_task["logs"].append(f"[配置] Deep 模型: {deep_model} | Quick 模型: {quick_model}")
        current_task["logs"].append(f"[架构] 初始化多智能体辩论图谱 (TradingAgentsGraph)...")

        ta = TradingAgentsGraph(debug=True, config=config)

        # 构造初始运行状态
        init_state = ta.create_run_state(ticker, trade_date, "stock", None)
        init_state["custom_sentiment_event"] = custom_event or ""
        args = ta.propagator.get_graph_args()

        final_state = {}
        for messages, state in ta.stream_run(ta.checkpoint_input(init_state), **args):
            if state:
                final_state.update(state)
                # 实时提取各阶段分析报告和辩论历史
                sections_update = {}
                if "market_report" in state and state["market_report"]:
                    sections_update["market_report"] = state["market_report"]
                if "news_report" in state and state["news_report"]:
                    sections_update["news_report"] = state["news_report"]
                if "sentiment_report" in state and state["sentiment_report"]:
                    sections_update["sentiment_report"] = state["sentiment_report"]
                if "fundamentals_report" in state and state["fundamentals_report"]:
                    sections_update["fundamentals_report"] = state["fundamentals_report"]
                
                # 多空辩论过程
                if "investment_debate_state" in state and state["investment_debate_state"]:
                    deb = state["investment_debate_state"]
                    sections_update["bull_history"] = deb.get("bull_history", "")
                    sections_update["bear_history"] = deb.get("bear_history", "")
                
                if "investment_plan" in state and state["investment_plan"]:
                    sections_update["investment_plan"] = state["investment_plan"]

                if "trader_investment_plan" in state and state["trader_investment_plan"]:
                    sections_update["trader_investment_plan"] = state["trader_investment_plan"]

                # 风控辩论过程
                if "risk_debate_state" in state and state["risk_debate_state"]:
                    rdeb = state["risk_debate_state"]
                    sections_update["risk_history"] = rdeb.get("history", "")

                if "final_trade_decision" in state and state["final_trade_decision"]:
                    sections_update["final_trade_decision"] = state["final_trade_decision"]
                
                if "final_rating" in state and state["final_rating"]:
                    sections_update["final_rating"] = state["final_rating"]

                current_task["sections"].update(sections_update)

            for msg in messages:
                content = getattr(msg, "content", None)
                if content and isinstance(content, str):
                    name = getattr(msg, "name", None) or type(msg).__name__
                    snippet = content[:150].replace("\n", " ")
                    current_task["logs"].append(f"[{name}] {snippet}")

        current_task["current_step"] = 5
        current_task["step_name"] = "全流程推演已完成"
        current_task["logs"].append(f"[系统] 全流程推演完成，所有智能体报告已生成！")
        ta.record_decision(ticker, trade_date, final_state)
        try:
            rec_id, save_path = save_run_to_history(ticker, trade_date, deep_model, quick_model, current_task["sections"])
            if rec_id:
                current_task["logs"].append(f"[归档] 历史档案已成功落盘至: {rec_id}.json")
        except Exception as e_hist:
            current_task["logs"].append(f"[归档] 保存历史档案失败: {e_hist}")

    except Exception as e:
        current_task["logs"].append(f"[异常] 运行中断: {str(e)}")
    finally:
        current_task["running"] = False

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TradingAgents 交易智能体控制面板</title>
    <script src="/marked.min.js"></script>
    <style>
        :root {
            --bg-main: #070b14;
            --bg-card: #101726;
            --bg-input: #0c1220;
            --accent: #38bdf8;
            --accent-hover: #0284c7;
            --bull: #10b981;
            --bear: #f43f5e;
            --gold: #f59e0b;
            --border: #1e293b;
            --text-main: #f1f5f9;
            --text-dim: #94a3b8;
        }
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        body {
            background-color: var(--bg-main);
            color: var(--text-main);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Microsoft YaHei", sans-serif;
            line-height: 1.6;
            padding: 20px 16px 60px;
        }
        .container {
            max-width: 1280px;
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: linear-gradient(135deg, #101726 0%, #0c1528 100%);
            border: 1px solid var(--border);
            border-left: 4px solid var(--accent);
            border-radius: 10px;
            padding: 18px 24px;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
        }
        .header h1 {
            font-size: 22px;
            font-weight: 700;
            color: #ffffff;
            letter-spacing: 0.3px;
            margin-bottom: 4px;
        }
        .badge {
            padding: 6px 14px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 600;
            border: 1px solid var(--border);
        }
        .badge-idle {
            background: rgba(56, 189, 248, 0.12);
            color: var(--accent);
            border-color: rgba(56, 189, 248, 0.35);
        }
        .badge-run {
            background: rgba(245, 158, 11, 0.15);
            color: var(--gold);
            border-color: rgba(245, 158, 11, 0.45);
        }
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 20px 24px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
        }
        .card h2 {
            font-size: 17px;
            font-weight: 600;
            color: #ffffff;
            margin-bottom: 16px;
            padding-bottom: 10px;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .grid-2 {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }
        @media (max-width: 768px) {
            .grid-2 {
                grid-template-columns: 1fr;
            }
        }
        .form-group {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .form-group.full {
            grid-column: 1 / -1;
        }
        label {
            font-size: 13px;
            font-weight: 500;
            color: #cbd5e1;
        }
        input[type="text"],
        input[type="password"],
        input[type="date"],
        select {
            background: var(--bg-input);
            border: 1px solid var(--border);
            color: var(--text-main);
            padding: 9px 12px;
            border-radius: 6px;
            font-size: 13px;
            outline: none;
            transition: border-color 0.2s, box-shadow 0.2s;
        }
        input:focus,
        select:focus {
            border-color: var(--accent);
            box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.15);
        }
        button {
            cursor: pointer;
            border: none;
            border-radius: 6px;
            padding: 9px 16px;
            font-size: 13px;
            font-weight: 600;
            background: var(--accent);
            color: #0b0f19;
            transition: all 0.18s ease;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
        }
        button:hover:not(:disabled) {
            filter: brightness(1.1);
            transform: translateY(-1px);
        }
        button:disabled {
            opacity: 0.55;
            cursor: not-allowed;
        }
        button.secondary {
            background: #172236;
            color: #e2e8f0;
            border: 1px solid var(--border);
        }
        button.secondary:hover:not(:disabled) {
            border-color: var(--accent);
            color: #ffffff;
        }
        .btn-row {
            margin-top: 16px;
            display: flex;
            gap: 12px;
            align-items: center;
        }
        #startBtn {
            width: 100%;
            padding: 12px 20px;
            font-size: 15px;
            font-weight: 700;
            background: linear-gradient(90deg, #0284c7 0%, #38bdf8 100%);
            color: #ffffff;
            box-shadow: 0 4px 15px rgba(56, 189, 248, 0.25);
        }
        .logs {
            margin-top: 8px;
            background: #060911;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 12px 14px;
            font-family: Consolas, "Courier New", monospace;
            font-size: 12px;
            color: #38bdf8;
            max-height: 220px;
            overflow-y: auto;
            white-space: pre-wrap;
            word-break: break-all;
        }
        .rating-banner {
            background: #0c1424;
            border: 1px solid var(--accent);
            border-left: 5px solid var(--accent);
            border-radius: 8px;
            padding: 14px 18px;
            margin-bottom: 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            font-size: 18px;
            font-weight: 700;
        }
        .tabs {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            border-bottom: 1px solid var(--border);
            padding-bottom: 12px;
            margin-bottom: 16px;
        }
        .tab-btn {
            background: #0c1220;
            color: var(--text-dim);
            border: 1px solid var(--border);
            padding: 8px 14px;
            font-size: 13px;
            font-weight: 600;
            border-radius: 6px;
        }
        .tab-btn.active {
            background: var(--accent);
            color: #0b0f19;
            border-color: var(--accent);
            box-shadow: 0 0 12px rgba(56, 189, 248, 0.3);
        }
        .tab-content {
            display: none;
            background: #0b111e;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 18px 20px;
            min-height: 200px;
            max-height: 680px;
            overflow-y: auto;
            font-size: 14px;
            color: #e2e8f0;
        }
        .tab-content.active {
            display: block;
        }
        .tab-content h1, .tab-content h2, .tab-content h3, .tab-content h4 {
            color: #ffffff;
            margin-top: 14px;
            margin-bottom: 8px;
        }
        .tab-content p {
            margin-bottom: 10px;
        }
        .tab-content ul, .tab-content ol {
            padding-left: 22px;
            margin-bottom: 12px;
        }
        .tab-content code {
            background: #162032;
            padding: 2px 6px;
            border-radius: 4px;
            color: #38bdf8;
            font-size: 12px;
        }
        .tab-content pre {
            background: #070b12;
            padding: 12px;
            border-radius: 6px;
            overflow-x: auto;
            border: 1px solid var(--border);
            margin-bottom: 12px;
        }
        .source-tag {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 3px 9px;
            border-radius: 999px;
            font-size: 11px;
            background: rgba(16, 185, 129, 0.12);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.3);
        }
    </style>
    <script>
    if (!window.marked) {
        window.marked = {
            parse: function(t) {
                if (!t) return "";
                var s = String(t);
                return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\\n/g, '<br>');
            }
        };
    }
    </script>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>TradingAgents 多智能体交易决策系统</h1>
                <p style="font-size: 13px; color: var(--text-dim);">全链路多空辩论 · 市场/基本面/情绪/新闻 四维推演过程展示</p>
            </div>
            <span id="taskStatus" class="badge badge-idle">系统就绪</span>
        </div>

        <!-- 接口与模型卡片 -->
        <div class="card">
            <h2>1. 动态接口与模型候选</h2>
            <div class="grid-2">
                <div class="form-group full">
                    <label>Base URL (中转或 OpenAI 兼容端点)</label>
                    <input type="text" id="backendUrl" placeholder="https://ai.cyberhz.com/v1">
                </div>
                <div class="form-group full">
                    <label>API Key</label>
                    <input type="password" id="apiKey" placeholder="sk-...">
                </div>
                <div class="form-group">
                    <label>Deep-Thinking 深度推理模型 (多空辩论/总决断)</label>
                    <select id="deepModel"></select>
                </div>
                <div class="form-group">
                    <label>Quick-Thinking 快速模型 (四维分析师快速研报)</label>
                    <select id="quickModel"></select>
                </div>
            </div>
            <!-- 常驻同步与搜索工具栏 -->
            <div style="display: flex; align-items: center; justify-content: space-between; background: #0c1220; border: 1px solid var(--border); padding: 12px 16px; border-radius: 8px; margin-top: 16px; gap: 12px; flex-wrap: wrap;">
                <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                    <button type="button" id="fetchModelsBtn" onclick="fetchLiveModels()" style="background: #0284c7; color: #fff; font-weight: bold; box-shadow: 0 0 10px rgba(56, 189, 248, 0.25);">
                        🔄 从该接口实时拉取模型列表
                    </button>
                    <button type="button" onclick="saveApiConfig()" style="background: #10b981; color: #0b0f19;">
                        💾 保存配置到 .env
                    </button>
                    <input type="text" id="modelSearchInput" placeholder="🔍 快速搜索过滤模型..." oninput="onSearchModels()" style="width: 200px; padding: 7px 10px; font-size: 12px; background: #151d30;">
                </div>
                <div>
                    <span id="fetchMsg" style="font-size: 13px; font-weight: 500;"></span>
                    <span id="modelCountBadge" style="font-size: 12px; background: #1e293b; padding: 4px 8px; border-radius: 4px; color: var(--text-dim); margin-left: 8px;">候选: 0</span>
                </div>
            </div>
        </div>

        <!-- 发起任务控制卡片 -->
        <div class="card">
            <h2>2. 发起推演任务 (支持全球多市场与国内A股)</h2>
            
            <!-- 运行深度与模式选择 -->
            <div style="margin-bottom: 16px;">
                <label style="display: block; margin-bottom: 6px; font-weight: 600;">选择推演深度与速度模式：</label>
                <div class="mode-selector">
                    <button type="button" class="mode-btn active" id="modeFastBtn" onclick="selectAnalysisMode('fast')">
                        <div class="mode-btn-title">⚡ 极速诊断模式 (推荐·1~3分钟)</div>
                        <div class="mode-btn-desc">四维分析师+多源热搜+F10财报穿透，最小化轮次极速出具结论</div>
                    </button>
                    <button type="button" class="mode-btn" id="modeFullBtn" onclick="selectAnalysisMode('full')">
                        <div class="mode-btn-title">🧠 深度博弈模式 (完整版·10~20分钟)</div>
                        <div class="mode-btn-desc">激活全套多空阵营激烈辩论、风控审查与多轮博弈，适合大资金决策</div>
                    </button>
                </div>
            </div>

            <!-- 5阶段状态指示进度条 -->
            <div style="margin-bottom: 16px;">
                <label style="display: block; margin-bottom: 6px; font-weight: 600;">智能体工作流阶段：</label>
                <div class="step-container" id="stepContainer">
                    <div class="step-item" id="step1">
                        <div class="step-circle">1</div>
                        <div class="step-info">
                            <span class="step-title">数据穿透</span>
                            <span class="step-desc">热搜/F10/持仓</span>
                        </div>
                    </div>
                    <div class="step-item" id="step2">
                        <div class="step-circle">2</div>
                        <div class="step-info">
                            <span class="step-title">专业研判</span>
                            <span class="step-desc">四维分析师</span>
                        </div>
                    </div>
                    <div class="step-item" id="step3">
                        <div class="step-circle">3</div>
                        <div class="step-info">
                            <span class="step-title">多空辩论</span>
                            <span class="step-desc">Bull vs Bear</span>
                        </div>
                    </div>
                    <div class="step-item" id="step4">
                        <div class="step-circle">4</div>
                        <div class="step-info">
                            <span class="step-title">风控审查</span>
                            <span class="step-desc">仓位/回撤测算</span>
                        </div>
                    </div>
                    <div class="step-item" id="step5">
                        <div class="step-circle">5</div>
                        <div class="step-info">
                            <span class="step-title">决断归档</span>
                            <span class="step-desc">评级/点位生成</span>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- 股市/资产类别选择器 -->
            <div style="margin-bottom: 14px;">
                <label style="display: block; margin-bottom: 8px;">选择目标市场 / 资产类别：</label>
                <div style="display: flex; gap: 8px; flex-wrap: wrap;" id="marketPillContainer">
                    <button type="button" class="secondary market-pill active" onclick="selectMarket('ashare', this)" style="padding: 6px 14px; font-size: 13px; background: var(--accent); color: #0b0f19;">🇨🇳 A股 (沪/深/北交)</button>
                    <button type="button" class="secondary market-pill" onclick="selectMarket('fund', this)" style="padding: 6px 14px; font-size: 13px;">📊 基金 / ETF (场内ETF·LOF)</button>
                    <button type="button" class="secondary market-pill" onclick="selectMarket('us', this)" style="padding: 6px 14px; font-size: 13px;">🇺🇸 美股 (美股科技/核心标的)</button>
                    <button type="button" class="secondary market-pill" onclick="selectMarket('hk', this)" style="padding: 6px 14px; font-size: 13px;">🇭🇰 港股 (主板/红筹)</button>
                    <button type="button" class="secondary market-pill" onclick="selectMarket('crypto', this)" style="padding: 6px 14px; font-size: 13px;">🪙 加密货币 (BTC/ETH)</button>
                    <button type="button" class="secondary market-pill" onclick="selectMarket('global', this)" style="padding: 6px 14px; font-size: 13px;">🌐 黄金/原油/大宗指数</button>
                </div>
            </div>

            <!-- 热门预设快捷填入 -->
            <div style="margin-bottom: 16px; background: #0c1220; padding: 10px 14px; border-radius: 6px; border: 1px solid var(--border);">
                <span style="font-size: 12px; color: var(--text-dim); margin-right: 8px;">📌 热门标的快捷选择：</span>
                <span id="presetContainer" style="display: inline-flex; gap: 8px; flex-wrap: wrap;"></span>
            </div>

            <div class="grid-2">
                <div class="form-group">
                    <label>分析标的代码 (支持股票如 600418、基金/ETF如 510300, 159915, 161725, SPY, QQQ)</label>
                    <div style="display: flex; gap: 8px;">
                        <input type="text" id="tickerInput" value="510300" placeholder="输入代码如 510300 (沪深300ETF), 159915, 600418, NVDA" oninput="debounceVerifyTicker()" style="flex: 1;">
                        <button type="button" class="secondary" onclick="verifyCurrentTicker()" style="padding: 0 14px; font-size: 13px;">🔍 识别资产</button>
                    </div>
                </div>
                <div class="form-group">
                    <label>基准分析日期 (Date)</label>
                    <input type="date" id="dateInput">
                </div>
            </div>

            <!-- 标的实时识别与核验卡片 -->
            <div id="tickerPreviewCard" style="margin-top: 14px; background: #0c1220; border: 1px solid var(--border); border-left: 4px solid var(--accent); padding: 12px 16px; border-radius: 6px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;">
                <div>
                    <div style="font-size: 11px; color: var(--text-dim); text-transform: uppercase;">系统已解析并核验标的</div>
                    <div style="font-size: 16px; font-weight: bold; color: #fff; margin-top: 2px;" id="previewTitle">江淮汽车 (600418.SS)</div>
                    <div style="font-size: 12px; color: var(--text-dim); margin-top: 2px;" id="previewSubtitle">交易所: SHH · 规范化请求代码: 600418.SS</div>
                </div>
                <div style="text-align: right;">
                    <div style="font-size: 20px; font-weight: bold; color: var(--accent);" id="previewPrice">--</div>
                    <div style="font-size: 11px; color: var(--text-dim);" id="previewCurrency">最新参考价格</div>
                </div>
            </div>

            <!-- 10大多渠道舆情与突发危机线索增强面版 -->
            <div style="margin-top: 14px; background: #0c1220; border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 10px;">
                    <div style="font-size: 13px; font-weight: 600; color: #fff;">
                        📡 全景 10 大多渠道舆情与资金博弈矩阵 (Agent-Reach 雪球 + 东财 + 新浪 + 腾讯)
                    </div>
                    <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                        <span class="source-tag">✔ 雪球热帖/大V/资金</span>
                        <span class="source-tag">✔ 腾讯涨跌停预警</span>
                        <span class="source-tag">✔ 东财公告/研报评级</span>
                        <span class="source-tag">✔ 龙虎榜/两融/北向/大宗</span>
                        <span class="source-tag">✔ 全网危机深度检索</span>
                    </div>
                </div>
                <div class="grid-2">
                    <div class="form-group">
                        <label>⚡ 突发黑天鹅 / 舆情危机线索 (选填，定向深挖负面或突发事件)</label>
                        <input type="text" id="customEventInput" placeholder="如：尊界刹车断裂、连续跌停、立案调查、高管减持、业绩暴雷...">
                    </div>
                    <div class="form-group">
                        <label>❄️ 雪球自定义 Cookie (选填，留空则自动免登录生成访客会话)</label>
                        <input type="password" id="xueqiuCookieInput" placeholder="xq_a_token=...; u=... (可选，用于增强雪球深度热帖抓取)">
                    </div>
                </div>
            </div>

            <div class="btn-row">
                <button type="button" id="startBtn" onclick="startAnalysis()">[RUN] 启动全流程多智能体分析</button>
            </div>
            <div style="margin-top: 14px;">
                <label>实时交互日志</label>
                <pre class="logs" id="logsBox">[就绪] 等待任务启动...</pre>
            </div>
        </div>

        <!-- 详细分析过程与决断面板 -->
        <div class="card" id="processCard">
            <h2>3. 完整分析过程与各智能体报告</h2>
            
            <div id="ratingBanner" style="display: none;" class="rating-banner">
                <span id="ratingTitle">🎯 最终交易评级：-</span>
                <span id="ratingDetail" style="font-size: 13px; font-weight: normal; color: var(--text-dim);">由投资组合经理 (Portfolio Manager) 裁定</span>
            </div>

            <div class="tabs">
                <button class="tab-btn active" onclick="switchTab(this, 'final_trade_decision')">🏛 最终投资决断</button>
                <button class="tab-btn" onclick="switchTab(this, 'debate_section')">⚔️ 多空辩论交锋 (Bull vs Bear)</button>
                <button class="tab-btn" onclick="switchTab(this, 'market_report')">📈 市场技术面分析师</button>
                <button class="tab-btn" onclick="switchTab(this, 'fundamentals_report')">📑 基本面分析师</button>
                <button class="tab-btn" onclick="switchTab(this, 'sentiment_report')">💬 市场情绪与社交舆情</button>
                <button class="tab-btn" onclick="switchTab(this, 'news_report')">📰 实时新闻宏观分析</button>
                <button class="tab-btn" onclick="switchTab(this, 'investment_plan')">📋 研究主管投资计划</button>
                <button class="tab-btn" onclick="switchTab(this, 'risk_history')">🛡️ 风控委员会评审记录</button>
            </div>

            <!-- Tab 内容区 -->
            <div id="tab-final_trade_decision" class="tab-content active">
                <p style="color: var(--text-dim);">推演启动后，最终交易执行决断将在此渲染...</p>
            </div>
            <div id="tab-debate_section" class="tab-content">
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
                    <div style="border-right: 1px solid var(--border); padding-right: 12px;">
                        <h3 style="color: var(--bull);">🟢 看多研究员 (Bull Researcher) 辩词</h3>
                        <div id="bullText" style="margin-top: 8px;">等待看多观点...</div>
                    </div>
                    <div>
                        <h3 style="color: var(--bear);">🔴 看空研究员 (Bear Researcher) 辩词</h3>
                        <div id="bearText" style="margin-top: 8px;">等待看空观点...</div>
                    </div>
                </div>
            </div>
            <div id="tab-market_report" class="tab-content">
                <p style="color: var(--text-dim);">等待市场分析师输出技术指标与量价图表...</p>
            </div>
            <div id="tab-fundamentals_report" class="tab-content">
                <p style="color: var(--text-dim);">等待基本面分析师输出财报与财务比率...</p>
            </div>
            <div id="tab-sentiment_report" class="tab-content">
                <p style="color: var(--text-dim);">等待情绪分析师输出社交平台散户舆情与指标...</p>
            </div>
            <div id="tab-news_report" class="tab-content">
                <p style="color: var(--text-dim);">等待新闻分析师输出宏观公司资讯...</p>
            </div>
            <div id="tab-investment_plan" class="tab-content">
                <p style="color: var(--text-dim);">等待研究主管整合各分析师报告制定投资计划...</p>
            </div>
            <div id="tab-risk_history" class="tab-content">
                <p style="color: var(--text-dim);">等待激进/中立/保守风控分析师辩论记录...</p>
            </div>
        </div>

        <!-- 4. 本地历史分析归档与多次对比回溯 -->
        <div class="card" id="historyCard">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 10px;">
                <h2 style="margin-bottom: 0;">4. 本地历史回溯与多次推演对比 (自动持久化)</h2>
                <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                    <input type="text" id="historyFilterInput" placeholder="🔍 按代码/名称/评级筛选..." oninput="renderHistoryTable()" style="padding: 6px 10px; font-size: 12px; width: 190px; background: #0c1220;">
                    <button type="button" class="secondary" onclick="loadHistoryList()" style="padding: 6px 12px; font-size: 12px;">🔄 刷新记录</button>
                    <button type="button" id="compareBtn" onclick="openCompareView()" style="padding: 6px 14px; font-size: 12px; background: var(--gold); color: #0b0f19;">⚖️ 对比已选记录 (0)</button>
                </div>
            </div>
            <p style="font-size: 12px; color: var(--text-dim); margin-bottom: 12px;">
                💡 每次推演完成后自动保存至本地 <code>analysis_history/</code> 目录（已自动同步历史日志）。点击 <b>📂 回溯加载</b> 可一键恢复全套8个维度的报告；勾选任意 <b>2~4 条记录</b> 点击 <b>⚖️ 对比已选记录</b> 可同屏并排横向对比不同日期、不同模型或不同标的的策略演变。
            </p>

            <div style="overflow-x: auto; border: 1px solid var(--border); border-radius: 8px; background: #0c1220; max-height: 320px; overflow-y: auto;">
                <table style="width: 100%; border-collapse: collapse; font-size: 13px; text-align: left;">
                    <thead>
                        <tr style="border-bottom: 1px solid var(--border); background: #121a2d; color: var(--text-dim);">
                            <th style="padding: 10px 12px; width: 42px; text-align: center;">对比</th>
                            <th style="padding: 10px 12px;">标的资产</th>
                            <th style="padding: 10px 12px;">基准日期</th>
                            <th style="padding: 10px 12px;">最终评级</th>
                            <th style="padding: 10px 12px;">推理模型 (Deep / Quick)</th>
                            <th style="padding: 10px 12px;">归档时间</th>
                            <th style="padding: 10px 12px; text-align: right;">操作</th>
                        </tr>
                    </thead>
                    <tbody id="historyTableBody">
                        <tr><td colspan="7" style="padding: 18px; text-align: center; color: var(--text-dim);">正在加载本地归档记录...</td></tr>
                    </tbody>
                </table>
            </div>

            <!-- 多记录并排对比工作台 -->
            <div id="compareWorkspace" style="display: none; margin-top: 18px; border-top: 1px solid var(--border); padding-top: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 10px;">
                    <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
                        <h3 style="color: var(--gold); font-size: 16px; margin: 0;">⚖️ 多次分析横向对比视图</h3>
                        <label style="font-size: 12px;">切换对比维度：</label>
                        <select id="compareSectionSelect" onchange="renderCompareColumns()" style="padding: 6px 10px; font-size: 13px; background: #0c1220;">
                            <option value="final_trade_decision">🏛 最终投资决断 (Portfolio Decision)</option>
                            <option value="bull_history">🟢 看多研究员辩词 (Bull Researcher)</option>
                            <option value="bear_history">🔴 看空研究员辩词 (Bear Researcher)</option>
                            <option value="market_report">📈 市场技术面分析 (Market Report)</option>
                            <option value="fundamentals_report">📑 基本面分析 (Fundamentals Report)</option>
                            <option value="sentiment_report">💬 市场情绪与舆情 (Sentiment Report)</option>
                            <option value="news_report">📰 实时新闻宏观分析 (News Report)</option>
                            <option value="investment_plan">📋 研究主管投资计划 (Investment Plan)</option>
                            <option value="risk_history">🛡️ 风控委员会评审记录 (Risk History)</option>
                        </select>
                    </div>
                    <button type="button" class="secondary" onclick="closeCompareView()" style="padding: 5px 12px; font-size: 12px;">✖ 收起对比视图</button>
                </div>
                <div id="compareGrid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 14px;"></div>
            </div>
        </div>
    </div>

    <script>
        let candidateModels = [];

        function initDate() {
            const today = new Date().toISOString().split('T')[0];
            document.getElementById('dateInput').value = today;
        }

        function switchTab(btn, name) {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            
            if (btn) btn.classList.add('active');
            const target = document.getElementById('tab-' + name);
            if (target) target.classList.add('active');
        }

        async function fetchSettings() {
            const res = await fetch('/api/settings');
            const data = await res.json();
            document.getElementById('backendUrl').value = data.backend_url || '';
            document.getElementById('apiKey').value = data.api_key || '';
            const xqInput = document.getElementById('xueqiuCookieInput');
            if (xqInput && data.xueqiu_cookie) xqInput.value = data.xueqiu_cookie;
            candidateModels = data.candidate_models || [];
            renderModelOptions(data.deep_model, data.quick_model);
            
            if (candidateModels.length === 0 && data.backend_url && data.api_key) {
                fetchLiveModels();
            }
        }

        let modelFilterText = '';

        function onSearchModels() {
            modelFilterText = document.getElementById('modelSearchInput').value.trim().toLowerCase();
            const deepVal = document.getElementById('deepModel').value;
            const quickVal = document.getElementById('quickModel').value;
            renderModelOptions(deepVal, quickVal);
        }

        function renderModelOptions(selectedDeep, selectedQuick) {
            const deepSel = document.getElementById('deepModel');
            const quickSel = document.getElementById('quickModel');
            deepSel.innerHTML = '';
            quickSel.innerHTML = '';

            const filtered = modelFilterText 
                ? candidateModels.filter(m => m.toLowerCase().includes(modelFilterText))
                : candidateModels;

            if (filtered.length === 0) {
                const hint = candidateModels.length === 0 ? '-- 点击上方按钮拉取模型列表 --' : '-- 无匹配模型 --';
                deepSel.add(new Option(hint, ''));
                quickSel.add(new Option(hint, ''));
            } else {
                filtered.forEach(m => {
                    deepSel.add(new Option(m, m));
                    quickSel.add(new Option(m, m));
                });
            }

            if (selectedDeep && filtered.includes(selectedDeep)) {
                deepSel.value = selectedDeep;
            } else if (filtered.length > 0) {
                deepSel.value = filtered[0];
            }

            if (selectedQuick && filtered.includes(selectedQuick)) {
                quickSel.value = selectedQuick;
            } else if (filtered.length > 0) {
                quickSel.value = filtered[0];
            }

            const countBadge = document.getElementById('modelCountBadge');
            if (countBadge) countBadge.textContent = `候选: ${candidateModels.length} 个`;
        }

        async function fetchLiveModels() {
            const url = (document.getElementById('backendUrl')?.value || '').trim();
            const key = (document.getElementById('apiKey')?.value || '').trim();
            const fetchMsg = document.getElementById('fetchMsg');
            const btn = document.getElementById('fetchModelsBtn');

            if (!url || !key) {
                alert('请先输入 Base URL 和 API Key！');
                if (fetchMsg) {
                    fetchMsg.style.color = '#f59e0b';
                    fetchMsg.textContent = '请先输入 Base URL 和 API Key！';
                }
                return;
            }

            if (btn) {
                btn.disabled = true;
                btn.textContent = '⏳ 正在拉取模型中...';
            }
            if (fetchMsg) {
                fetchMsg.style.color = 'var(--accent)';
                fetchMsg.textContent = '正在向中转接口拉取在线模型...';
            }

            try {
                const res = await fetch('/api/fetch-models', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ backend_url: url, api_key: key })
                });
                const data = await res.json();
                if (data.ok && Array.isArray(data.models) && data.models.length > 0) {
                    candidateModels = data.models;
                    const prevDeep = document.getElementById('deepModel')?.value;
                    const prevQuick = document.getElementById('quickModel')?.value;
                    renderModelOptions(prevDeep, prevQuick);
                    if (fetchMsg) {
                        fetchMsg.style.color = '#10b981';
                        fetchMsg.textContent = `成功获取 ${candidateModels.length} 个模型！`;
                    }
                    try {
                        await saveApiConfig();
                    } catch(e) {}
                } else {
                    const msg = data.msg || '未获取到模型列表';
                    alert('拉取模型失败: ' + msg);
                    if (fetchMsg) {
                        fetchMsg.style.color = '#f43f5e';
                        fetchMsg.textContent = `拉取失败: ${msg}`;
                    }
                }
            } catch (err) {
                console.error('fetchLiveModels error:', err);
                alert('请求异常: ' + err.message);
                if (fetchMsg) {
                    fetchMsg.style.color = '#f43f5e';
                    fetchMsg.textContent = `请求出错: ${err.message}`;
                }
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = '🔄 从该接口实时拉取模型列表';
                }
            }
        }

        async function saveApiConfig() {
            const payload = {
                backend_url: document.getElementById('backendUrl').value.trim(),
                api_key: document.getElementById('apiKey').value.trim(),
                deep_model: document.getElementById('deepModel').value,
                quick_model: document.getElementById('quickModel').value,
                xueqiu_cookie: (document.getElementById('xueqiuCookieInput')?.value || '').trim(),
                candidate_models: candidateModels
            };

            const res = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (res.ok) {
                const msg = document.getElementById('fetchMsg');
                msg.style.color = '#10b981';
                msg.textContent = '配置已保存到本地 .env！';
                setTimeout(() => { msg.textContent = ''; }, 3000);
            }
        }

        function resetCurrentView() {
            updateStepProgress(0);
            const banner = document.getElementById('ratingBanner');
            if (banner) {
                banner.style.display = 'none';
                banner.className = 'rating-banner';
            }
            const ratingTitle = document.getElementById('ratingTitle');
            if (ratingTitle) {
                ratingTitle.textContent = '🎯 最终评级建议: 正在研判中...';
            }
            const tabsToClear = [
                'tab-final_trade_decision',
                'tab-market_report',
                'tab-fundamentals_report',
                'tab-sentiment_report',
                'tab-news_report',
                'tab-investment_plan',
                'tab-risk_history'
            ];
            tabsToClear.forEach(tabId => {
                const el = document.getElementById(tabId);
                if (el) el.innerHTML = '<div style="color: var(--text-dim); padding: 12px;">⏳ 正在推演研判中，报告就绪后将实时展现...</div>';
            });
            const bullEl = document.getElementById('bullText');
            if (bullEl) bullEl.innerHTML = '<div style="color: var(--text-dim); padding: 12px;">⏳ 正在推演研判中...</div>';
            const bearEl = document.getElementById('bearText');
            if (bearEl) bearEl.innerHTML = '<div style="color: var(--text-dim); padding: 12px;">⏳ 正在推演研判中...</div>';

            const logsBox = document.getElementById('logsBox');
            if (logsBox) {
                logsBox.textContent = '[系统] 上一轮旧评级与推演报告已清空，正在启动新一轮任务...\\n';
            }
        }

        async function startAnalysis() {
            const startBtn = document.getElementById('startBtn');
            const logsBox = document.getElementById('logsBox');
            
            try {
                resetCurrentView();
                
                // 立即给予按钮视觉反馈
                if (startBtn) {
                    startBtn.disabled = true;
                    startBtn.textContent = '⏳ 任务启动中，正在调度各智能体...';
                }
                if (logsBox) {
                    logsBox.textContent = '[系统] 正在向后端发起多智能体推演调度请求...\n';
                }

                // 保存当前配置
                try {
                    await saveApiConfig();
                } catch (saveErr) {
                    console.warn('saveApiConfig warning:', saveErr);
                }

                const deepSelect = document.getElementById('deepModel');
                const quickSelect = document.getElementById('quickModel');
                const deep = deepSelect ? deepSelect.value : '';
                const quick = quickSelect ? quickSelect.value : '';

                if (!deep || !quick) {
                    alert('请先在第 1 部分中选择 Deep-Thinking 与 Quick-Thinking 推理模型！');
                    if (startBtn) {
                        startBtn.disabled = false;
                        startBtn.textContent = '[RUN] 启动全流程多智能体分析';
                    }
                    return;
                }

                const ticker = (document.getElementById('tickerInput')?.value || '600418').trim();
                const date = (document.getElementById('dateInput')?.value || new Date().toISOString().slice(0, 10)).trim();
                const custom_event = (document.getElementById('customEventInput')?.value || '').trim();
                const xueqiu_cookie = (document.getElementById('xueqiuCookieInput')?.value || '').trim();

                const payload = {
                    ticker: ticker,
                    date: date,
                    deep_model: deep,
                    quick_model: quick,
                    custom_event: custom_event,
                    xueqiu_cookie: xueqiu_cookie,
                    analysis_mode: typeof selectedAnalysisMode !== 'undefined' ? selectedAnalysisMode : 'fast'
                };

                const res = await fetch('/api/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (res.ok) {
                    if (logsBox) logsBox.textContent += '[系统] 后端响应成功，轮询监控进程已启动！\n';
                    pollStatus();
                } else {
                    const errText = await res.text();
                    alert('启动任务失败: ' + errText);
                    if (startBtn) {
                        startBtn.disabled = false;
                        startBtn.textContent = '[RUN] 启动全流程多智能体分析';
                    }
                }
            } catch (err) {
                console.error('startAnalysis error:', err);
                alert('启动出现异常: ' + err.message);
                if (startBtn) {
                    startBtn.disabled = false;
                    startBtn.textContent = '[RUN] 启动全流程多智能体分析';
                }
            }
        }
        let pollTimer = null;
        async function pollStatus() {
            if (pollTimer) clearInterval(pollTimer);
            pollTimer = setInterval(async () => {
                const res = await fetch('/api/status');
                const data = await res.json();
                
                const statusBadge = document.getElementById('taskStatus');
                const startBtn = document.getElementById('startBtn');
                const logsBox = document.getElementById('logsBox');

                logsBox.textContent = data.logs.join('\\n');
                logsBox.scrollTop = logsBox.scrollHeight;

                // 渲染各部分详细过程
                if (data.sections) {
                    renderSections(data.sections);
                }

                if (data.running) {
                    statusBadge.className = 'badge badge-running';
                    statusBadge.textContent = '多智能体辩论推演中...';
                    startBtn.disabled = true;
                } else {
                    statusBadge.className = 'badge badge-idle';
                    statusBadge.textContent = '系统就绪';
                    startBtn.disabled = false;
                    clearInterval(pollTimer);
                    loadHistoryList();
                }
            }, 1000);
        }

        function renderSections(sec) {
            const md = (t) => (window.marked ? window.marked.parse(t) : String(t));

            if (sec.final_rating) {
                const banner = document.getElementById('ratingBanner');
                banner.style.display = 'flex';
                banner.className = 'rating-banner rating-' + sec.final_rating.toUpperCase();
                document.getElementById('ratingTitle').textContent = `🎯 最终评级建议: ${sec.final_rating.toUpperCase()}`;
            }

            if (sec.final_trade_decision) {
                document.getElementById('tab-final_trade_decision').innerHTML = md(sec.final_trade_decision);
            }
            if (sec.bull_history) {
                document.getElementById('bullText').innerHTML = md(sec.bull_history);
            }
            if (sec.bear_history) {
                document.getElementById('bearText').innerHTML = md(sec.bear_history);
            }
            if (sec.market_report) {
                document.getElementById('tab-market_report').innerHTML = md(sec.market_report);
            }
            if (sec.fundamentals_report) {
                document.getElementById('tab-fundamentals_report').innerHTML = md(sec.fundamentals_report);
            }
            if (sec.sentiment_report) {
                document.getElementById('tab-sentiment_report').innerHTML = md(sec.sentiment_report);
            }
            if (sec.news_report) {
                document.getElementById('tab-news_report').innerHTML = md(sec.news_report);
            }
            if (sec.investment_plan) {
                document.getElementById('tab-investment_plan').innerHTML = md(sec.investment_plan);
            }
            if (sec.risk_history) {
                document.getElementById('tab-risk_history').innerHTML = md(sec.risk_history);
            }
        }

        // 预设标的库
        const MARKET_PRESETS = {
            fund: [
                { name: '沪深300ETF', code: '510300', desc: '上交所 510300.SS (华泰柏瑞)' },
                { name: '中证500ETF', code: '510500', desc: '上交所 510500.SS (南方)' },
                { name: '科创50ETF', code: '588000', desc: '上交所 588000.SS (华夏)' },
                { name: '创业板ETF', code: '159915', desc: '深交所 159915.SZ (易方达)' },
                { name: '证券ETF', code: '512880', desc: '上交所 512880.SS (国泰证券ETF)' },
                { name: '白酒LOF', code: '161725', desc: '深交所 161725.SZ (招商中证白酒)' },
                { name: '中概互联ETF', code: '513050', desc: '上交所 513050.SS (易方达中概)' },
                { name: '纳斯达克100ETF', code: '513100', desc: '上交所 513100.SS (国泰纳指)' },
                { name: '标普500ETF', code: 'SPY', desc: '美股 SPY (SPDR S&P 500)' },
                { name: '纳指QQQ', code: 'QQQ', desc: '美股 QQQ (Invesco QQQ)' }
            ],
            ashare: [
                { name: '江淮汽车', code: '600418', desc: '上交所 600418.SS' },
                { name: '贵州茅台', code: '600519', desc: '上交所 600519.SS' },
                { name: '平安银行', code: '000001', desc: '深交所 000001.SZ' },
                { name: '宁德时代', code: '300750', desc: '深交所 300750.SZ' },
                { name: '中芯国际', code: '688981', desc: '科创板 688981.SS' },
                { name: '比亚迪', code: '002594', desc: '深交所 002594.SZ' }
            ],
            us: [
                { name: '英伟达 (NVDA)', code: 'NVDA', desc: '纳斯达克 NMS' },
                { name: '苹果 (AAPL)', code: 'AAPL', desc: '纳斯达克 NMS' },
                { name: '微软 (MSFT)', code: 'MSFT', desc: '纳斯达克 NMS' },
                { name: '特斯拉 (TSLA)', code: 'TSLA', desc: '纳斯达克 NMS' }
            ],
            hk: [
                { name: '腾讯控股', code: '0700.HK', desc: '港交所 0700.HK' },
                { name: '美团', code: '3690.HK', desc: '港交所 3690.HK' },
                { name: '阿里巴巴', code: '9988.HK', desc: '港交所 9988.HK' }
            ],
            crypto: [
                { name: '比特币 (BTC)', code: 'BTC-USD', desc: 'BTC/USD' },
                { name: '以太坊 (ETH)', code: 'ETH-USD', desc: 'ETH/USD' },
                { name: 'Solana (SOL)', code: 'SOL-USD', desc: 'SOL/USD' }
            ],
            global: [
                { name: '现货黄金', code: 'GC=F', desc: 'COMEX 黄金期货' },
                { name: '原油期货', code: 'CL=F', desc: 'NYMEX WTI 原油' },
                { name: '标普500指数', code: '^GSPC', desc: 'S&P 500 Index' }
            ]
        };

        function selectMarket(marketKey, btnEl) {
            document.querySelectorAll('.market-pill').forEach(btn => {
                btn.classList.remove('active');
                btn.style.background = '#222f4c';
                btn.style.color = '#fff';
            });
            if (btnEl) {
                btnEl.classList.add('active');
                btnEl.style.background = 'var(--accent)';
                btnEl.style.color = '#0b0f19';
            }
            renderPresets(marketKey);
        }

        function renderPresets(marketKey) {
            const container = document.getElementById('presetContainer');
            if (!container) return;
            container.innerHTML = '';
            const list = MARKET_PRESETS[marketKey] || [];
            list.forEach(item => {
                const tag = document.createElement('span');
                tag.style.cssText = 'background: #1c2740; color: #cbd5e1; padding: 4px 10px; border-radius: 4px; font-size: 12px; cursor: pointer; border: 1px solid var(--border); transition: 0.15s;';
                tag.textContent = item.name + ' (' + item.code + ')';
                tag.title = item.desc;
                tag.onmouseover = () => { tag.style.borderColor = 'var(--accent)'; tag.style.color = '#fff'; };
                tag.onmouseout = () => { tag.style.borderColor = 'var(--border)'; tag.style.color = '#cbd5e1'; };
                tag.onclick = () => {
                    document.getElementById('tickerInput').value = item.code;
                    verifyCurrentTicker();
                };
                container.appendChild(tag);
            });
        }

        let verifyTimer = null;
        function debounceVerifyTicker() {
            if (verifyTimer) clearTimeout(verifyTimer);
            verifyTimer = setTimeout(verifyCurrentTicker, 500);
        }

        async function verifyCurrentTicker() {
            const raw = document.getElementById('tickerInput').value.trim();
            if (!raw) return;

            const titleEl = document.getElementById('previewTitle');
            const subEl = document.getElementById('previewSubtitle');
            const priceEl = document.getElementById('previewPrice');
            const currEl = document.getElementById('previewCurrency');

            titleEl.textContent = '🔍 正在识别标的...';
            subEl.textContent = '解析对应市场与规范化代码...';

            try {
                const res = await fetch('/api/verify-ticker', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ticker: raw })
                });
                const data = await res.json();
                if (data.ok) {
                    const badge = data.is_fund ? '<span style="background:#0284c7;color:#fff;padding:2px 6px;border-radius:4px;font-size:11px;margin-right:6px;">基金/ETF</span>' : '';
                    titleEl.innerHTML = badge + (data.display_name || data.canonical) + ' [' + data.canonical + ']';
                    subEl.textContent = '资产类别: ' + (data.exchange || '--') + ' · 货币: ' + (data.currency || 'USD') + ' · 规范代码: ' + data.canonical;
                    priceEl.textContent = data.last_price !== null && data.last_price !== undefined ? data.last_price : '--';
                    currEl.textContent = (data.is_fund && data.exchange.includes('场外') ? '最新单位净值 (' : '最新市价 (') + (data.currency || 'USD') + ')';
                } else {
                    titleEl.textContent = '代码已规范为: [' + (data.canonical || raw) + ']';
                    subEl.textContent = data.msg || '无法解析该标的元数据';
                    priceEl.textContent = '--';
                }
            } catch (err) {
                titleEl.textContent = '查询出错: ' + raw;
                subEl.textContent = err.message;
            }
        }

        let historyRecords = [];
        let selectedCompareIds = new Set();
        let loadedCompareDetails = [];

        async function loadHistoryList() {
            try {
                const res = await fetch('/api/history');
                const data = await res.json();
                historyRecords = data.records || [];
                renderHistoryTable();
            } catch (e) {
                console.error('Failed to load history:', e);
            }
        }

        function getRatingColor(rating) {
            const r = (rating || '').toUpperCase();
            if (r.includes('BUY') || r.includes('OVERWEIGHT')) return 'var(--bull)';
            if (r.includes('SELL') || r.includes('UNDERWEIGHT')) return 'var(--bear)';
            return 'var(--gold)';
        }

        function renderHistoryTable() {
            const tbody = document.getElementById('historyTableBody');
            if (!tbody) return;
            const filter = (document.getElementById('historyFilterInput')?.value || '').trim().toLowerCase();
            const list = filter
                ? historyRecords.filter(r =>
                    (r.ticker || '').toLowerCase().includes(filter) ||
                    (r.canonical || '').toLowerCase().includes(filter) ||
                    (r.display_name || '').toLowerCase().includes(filter) ||
                    (r.final_rating || '').toLowerCase().includes(filter) ||
                    (r.trade_date || '').toLowerCase().includes(filter) ||
                    (r.deep_model || '').toLowerCase().includes(filter)
                )
                : historyRecords;

            const compareBtn = document.getElementById('compareBtn');
            if (compareBtn) {
                compareBtn.textContent = `⚖️ 对比已选记录 (${selectedCompareIds.size})`;
            }

            if (list.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" style="padding: 18px; text-align: center; color: var(--text-dim);">暂无匹配的本地分析归档记录</td></tr>';
                return;
            }

            tbody.innerHTML = '';
            list.forEach(item => {
                const tr = document.createElement('tr');
                tr.style.borderBottom = '1px solid var(--border)';
                const checked = selectedCompareIds.has(item.id) ? 'checked' : '';
                const rColor = getRatingColor(item.final_rating);

                tr.innerHTML = `
                    <td style="padding: 10px 12px; text-align: center;">
                        <input type="checkbox" ${checked} onchange="toggleCompareSelect('${item.id}', this.checked)" style="cursor: pointer; width: 16px; height: 16px;">
                    </td>
                    <td style="padding: 10px 12px; font-weight: bold; color: #fff;">
                        ${item.display_name || item.ticker} <span style="color: var(--accent); font-size: 12px;">[${item.canonical || item.ticker}]</span>
                    </td>
                    <td style="padding: 10px 12px; color: #cbd5e1;">${item.trade_date}</td>
                    <td style="padding: 10px 12px;">
                        <span style="padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 12px; border: 1px solid ${rColor}; color: ${rColor};">
                            ${item.final_rating || 'DONE'}
                        </span>
                    </td>
                    <td style="padding: 10px 12px; font-size: 12px; color: var(--text-dim);">
                        ${item.deep_model || '--'} / ${item.quick_model || '--'}
                    </td>
                    <td style="padding: 10px 12px; font-size: 12px; color: var(--text-dim);">${item.saved_at || '--'}</td>
                    <td style="padding: 10px 12px; text-align: right; white-space: nowrap;">
                        <button type="button" onclick="restoreHistoryRecord('${item.id}')" style="padding: 5px 10px; font-size: 12px; margin-right: 6px;">📂 回溯加载</button>
                        <button type="button" class="secondary" onclick="removeHistoryRecord('${item.id}')" style="padding: 5px 10px; font-size: 12px; color: #f43f5e;">🗑 删除</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        }

        function toggleCompareSelect(id, isChecked) {
            if (isChecked) {
                if (selectedCompareIds.size >= 4) {
                    alert('最多同时勾选 4 条记录进行同屏对比！');
                    renderHistoryTable();
                    return;
                }
                selectedCompareIds.add(id);
            } else {
                selectedCompareIds.delete(id);
            }
            const compareBtn = document.getElementById('compareBtn');
            if (compareBtn) {
                compareBtn.textContent = `⚖️ 对比已选记录 (${selectedCompareIds.size})`;
            }
        }

        async function restoreHistoryRecord(id) {
            try {
                const res = await fetch('/api/history/detail?id=' + encodeURIComponent(id));
                const data = await res.json();
                if (!data.ok || !data.record) {
                    alert('加载记录失败！');
                    return;
                }
                const rec = data.record;
                document.getElementById('tickerInput').value = rec.ticker || rec.canonical || '';
                if (rec.trade_date) document.getElementById('dateInput').value = rec.trade_date;
                verifyCurrentTicker();

                const sec = rec.sections || {};
                if (rec.final_rating && !sec.final_rating) sec.final_rating = rec.final_rating;
                renderSections(sec);

                const detailEl = document.getElementById('ratingDetail');
                if (detailEl) {
                    detailEl.textContent = `📂 历史回溯模式 · 标的: ${rec.display_name || rec.ticker} · 基准日期: ${rec.trade_date} · 归档于: ${rec.saved_at}`;
                }
                document.getElementById('logsBox').textContent = `[回溯加载] 已从本地恢复历史归档记录: ${rec.id}\n[信息] 标的: ${rec.display_name} (${rec.canonical}) | 基准日期: ${rec.trade_date} | 模型: ${rec.deep_model}`;
                document.getElementById('processCard').scrollIntoView({ behavior: 'smooth' });
            } catch (e) {
                alert('读取失败: ' + e.message);
            }
        }

        async function removeHistoryRecord(id) {
            if (!confirm('确认从本地回溯库删除该条分析记录吗？')) return;
            try {
                await fetch('/api/history/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id })
                });
                selectedCompareIds.delete(id);
                await loadHistoryList();
                if (loadedCompareDetails.length > 0) {
                    loadedCompareDetails = loadedCompareDetails.filter(d => d.id !== id);
                    renderCompareColumns();
                }
            } catch (e) {
                alert('删除失败: ' + e.message);
            }
        }

        async function openCompareView() {
            if (selectedCompareIds.size < 2) {
                alert('请在列表中勾选至少 2 条分析记录再点击对比！');
                return;
            }
            const ids = Array.from(selectedCompareIds);
            loadedCompareDetails = [];
            for (const id of ids) {
                const res = await fetch('/api/history/detail?id=' + encodeURIComponent(id));
                const data = await res.json();
                if (data.ok && data.record) {
                    loadedCompareDetails.push(data.record);
                }
            }
            const ws = document.getElementById('compareWorkspace');
            ws.style.display = 'block';
            renderCompareColumns();
            ws.scrollIntoView({ behavior: 'smooth' });
        }

        function closeCompareView() {
            document.getElementById('compareWorkspace').style.display = 'none';
        }

        function renderCompareColumns() {
            const grid = document.getElementById('compareGrid');
            const secKey = document.getElementById('compareSectionSelect').value;
            if (!grid) return;
            grid.innerHTML = '';
            const md = (t) => (window.marked ? window.marked.parse(t) : String(t));

            loadedCompareDetails.forEach(rec => {
                const col = document.createElement('div');
                col.style.cssText = 'background: #0c1220; border: 1px solid var(--border); border-radius: 8px; padding: 14px; display: flex; flex-direction: column; gap: 10px;';
                const rColor = getRatingColor(rec.final_rating);
                const contentRaw = (rec.sections && rec.sections[secKey]) ? rec.sections[secKey] : '_（该记录中此维度无内容）_';

                col.innerHTML = `
                    <div style="border-bottom: 1px solid var(--border); padding-bottom: 10px; display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;">
                        <div>
                            <div style="font-size: 15px; font-weight: bold; color: #fff;">
                                ${rec.display_name || rec.ticker} <span style="color: var(--accent);">[${rec.canonical || rec.ticker}]</span>
                            </div>
                            <div style="font-size: 12px; color: var(--text-dim); margin-top: 2px;">
                                📅 基准日期: <b>${rec.trade_date}</b> · 🕒 归档: ${rec.saved_at}
                            </div>
                            <div style="font-size: 11px; color: var(--text-dim); margin-top: 2px;">
                                🤖 模型: ${rec.deep_model} / ${rec.quick_model}
                            </div>
                        </div>
                        <span style="padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 12px; border: 1px solid ${rColor}; color: ${rColor}; white-space: nowrap;">
                            ${rec.final_rating || 'DONE'}
                        </span>
                    </div>
                    <div class="tab-content active" style="display: block; border: none; padding: 4px 0; max-height: 480px; overflow-y: auto; background: transparent;">
                        ${md(contentRaw)}
                    </div>
                `;
                grid.appendChild(col);
            });
        }

        function initAll() {
            try { initDate(); } catch(e) { console.error('initDate error:', e); }
            try { fetchSettings(); } catch(e) { console.error('fetchSettings error:', e); }
            try { renderPresets('ashare'); } catch(e) { console.error('renderPresets error:', e); }
            try { verifyCurrentTicker(); } catch(e) { console.error('verifyCurrentTicker error:', e); }
            try { loadHistoryList(); } catch(e) { console.error('loadHistoryList error:', e); }
        }
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initAll);
        } else {
            initAll();
        }
    </script>
</body>
</html>
"""

class RequestHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        url_parsed = urllib.parse.urlparse(self.path)
        if url_parsed.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        elif url_parsed.path == "/marked.min.js":
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.end_headers()
            marked_path = Path("marked.min.js")
            if marked_path.exists():
                self.wfile.write(marked_path.read_bytes())
            else:
                self.wfile.write(b"")
        elif url_parsed.path == "/api/settings":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            settings = load_settings()
            self.wfile.write(json.dumps(settings).encode("utf-8"))
        elif url_parsed.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(current_task).encode("utf-8"))
        elif url_parsed.path == "/api/history":
            records = list_history_records()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "records": records}, ensure_ascii=False).encode("utf-8"))
        elif url_parsed.path == "/api/history/detail":
            qs = urllib.parse.parse_qs(url_parsed.query)
            rec_id = qs.get("id", [""])[0]
            record = get_history_record(rec_id)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": bool(record), "record": record}, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_error(404)

    def do_POST(self):
        url_parsed = urllib.parse.urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        data = json.loads(body.decode("utf-8")) if body else {}

        if url_parsed.path == "/api/settings":
            save_settings(data)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        elif url_parsed.path == "/api/fetch-models":
            backend_url = data.get("backend_url", "")
            api_key = data.get("api_key", "")
            ok, models, msg = fetch_online_models(backend_url, api_key)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            resp = json.dumps({"ok": ok, "models": models, "msg": msg}, ensure_ascii=False)
            self.wfile.write(resp.encode("utf-8"))
        elif url_parsed.path == "/api/verify-ticker":
            ticker_raw = data.get("ticker", "")
            res = verify_ticker_meta(ticker_raw)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(res, ensure_ascii=False).encode("utf-8"))
        elif url_parsed.path == "/api/start":
            if not current_task["running"]:
                ticker = data.get("ticker", "NVDA")
                trade_date = data.get("date", "2026-09-01")
                deep_model = data.get("deep_model", "")
                quick_model = data.get("quick_model", "")
                custom_event = data.get("custom_event", "")
                xueqiu_cookie = data.get("xueqiu_cookie", "")
                t = threading.Thread(
                    target=run_tradingagents_task,
                    args=(ticker, trade_date, deep_model, quick_model, custom_event, xueqiu_cookie),
                    daemon=True
                )
                t.start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"started"}')
        elif url_parsed.path == "/api/history/delete":
            rec_id = data.get("id", "")
            deleted = delete_history_record(rec_id)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "deleted": deleted}).encode("utf-8"))
        else:
            self.send_error(404)

def main():
    port = 8888
    server = ThreadingHTTPServer(("127.0.0.1", port), RequestHandler)
    print(f"==================================================")
    print(f"[RUN] TradingAgents 控制面板已就绪: http://127.0.0.1:{port}")
    print(f"==================================================")
    try:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{port}")
    except Exception:
        pass
    server.serve_forever()

if __name__ == "__main__":
    main()