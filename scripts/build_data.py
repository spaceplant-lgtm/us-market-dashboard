#!/usr/bin/env python3
"""S&P 500 / NASDAQ-100 / Russell 2000 구성종목 수익률 Top/Bottom 20 데이터 생성기.

출력: docs/data.json  (docs/index.html 대시보드가 읽음)

데이터 소스
  - S&P 500 구성종목   : Wikipedia "List of S&P 500 companies" (실패 시 GitHub datasets CSV)
  - NASDAQ-100 구성종목: Wikipedia "List of NASDAQ-100 companies"
  - Russell 2000 구성종목: iShares Russell 2000 ETF(IWM) 보유종목 CSV (지수 공식 목록의 대용치)
  - 가격               : Yahoo Finance (yfinance), 배당·분할 반영 수정주가(auto_adjust)

수익률 정의
  - 1D : 기준일 종가 / 직전 거래일 종가 - 1
  - 1W/1M/3M/6M : 기준일 종가 / (기준일 - 1주/1·3·6개월) 이전 마지막 거래일 종가 - 1  (달력 기준)
"""
from __future__ import annotations

import datetime as dt
import io
import json
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

TOP_N = 20
MIN_COVERAGE = 0.90          # 지수별 가격 수집률이 이보다 낮으면 실패 처리(기존 data.json 유지)
CHUNK = 150
OUT = Path(__file__).resolve().parent.parent / "docs" / "data.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/126.0 Safari/537.36 us-market-dashboard/1.0"
}

URL_SP500_WIKI = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
URL_SP500_FALLBACK = ("https://raw.githubusercontent.com/datasets/"
                      "s-and-p-500-companies/main/data/constituents.csv")
URL_NDX_WIKI = "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies"
URL_IWM = ("https://www.ishares.com/us/products/239710/"
           "ishares-russell-2000-etf/latest-holdings.csv")

PERIODS = [  # (키, 한글 라벨, 달력 오프셋 — None이면 직전 거래일)
    ("1D", "1일", None),
    ("1W", "1주", pd.DateOffset(weeks=1)),
    ("1M", "1개월", pd.DateOffset(months=1)),
    ("3M", "3개월", pd.DateOffset(months=3)),
    ("6M", "6개월", pd.DateOffset(months=6)),
]


def log(msg: str) -> None:
    print(msg, flush=True)


def http_get(url: str) -> str:
    last = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            r.raise_for_status()
            return r.text
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"GET 실패: {url} ({last})")


def yahoo_symbol(ticker: str) -> str:
    """BRK.B / 'MOG A' → BRK-B / MOG-A (Yahoo 표기)."""
    return ticker.strip().upper().replace(".", "-").replace(" ", "-").replace("/", "-")


def _frame(df: pd.DataFrame, tcol: str, ncol: str, scol: str | None) -> pd.DataFrame:
    out = pd.DataFrame({
        "ticker": df[tcol].astype(str).str.strip(),
        "name": df[ncol].astype(str).str.strip(),
        "sector": df[scol].astype(str).str.strip() if scol else "",
    })
    out = out[out["ticker"].str.len() > 0]
    out["yahoo"] = out["ticker"].map(yahoo_symbol)
    return out.drop_duplicates("yahoo").reset_index(drop=True)


# ---------------------------------------------------------------- 구성종목
def get_sp500() -> tuple[pd.DataFrame, str]:
    try:
        for t in pd.read_html(io.StringIO(http_get(URL_SP500_WIKI))):
            cols = [str(c) for c in t.columns]
            if "Symbol" in cols and "GICS Sector" in cols:
                df = _frame(t, "Symbol", "Security", "GICS Sector")
                if len(df) >= 490:
                    return df, URL_SP500_WIKI
        raise RuntimeError("S&P 500 표를 찾지 못함")
    except Exception as e:  # noqa: BLE001
        log(f"  [경고] Wikipedia S&P 500 실패 → GitHub CSV 대체 ({e})")
        t = pd.read_csv(io.StringIO(http_get(URL_SP500_FALLBACK)))
        df = _frame(t, "Symbol", "Security", "GICS Sector")
        if len(df) < 490:
            raise RuntimeError(f"S&P 500 구성종목 수 이상: {len(df)}")
        return df, URL_SP500_FALLBACK


def get_ndx() -> tuple[pd.DataFrame, str]:
    for t in pd.read_html(io.StringIO(http_get(URL_NDX_WIKI))):
        cols = [str(c) for c in t.columns]
        tcol = next((c for c in ("Ticker", "Symbol") if c in cols), None)
        ncol = next((c for c in ("Company", "Security") if c in cols), None)
        if tcol and ncol and 95 <= len(t) <= 110:
            scol = next((c for c in cols if "Industry" in c or "Sector" in c), None)
            return _frame(t, tcol, ncol, scol), URL_NDX_WIKI
    raise RuntimeError("NASDAQ-100 구성종목 표를 찾지 못함")


def parse_ishares_csv(text: str) -> tuple[pd.DataFrame, str]:
    lines = text.lstrip("﻿").splitlines()
    start = next((i for i, ln in enumerate(lines)
                  if ln.lstrip('﻿"').startswith("Ticker")), None)
    if start is None:
        raise RuntimeError("iShares CSV 헤더(Ticker)를 찾지 못함")
    asof = ""
    for ln in lines[:start]:
        if "Fund Holdings as of" in ln:
            asof = ln.split(",", 1)[1].replace('"', "").strip() if "," in ln else ""
    t = pd.read_csv(io.StringIO("\n".join(lines[start:])), dtype=str, on_bad_lines="skip")
    t.columns = [str(c).strip() for c in t.columns]
    t = t[t["Asset Class"].astype(str).str.strip() == "Equity"]
    t = t[t["Ticker"].notna() & ~t["Ticker"].astype(str).str.strip().isin(["-", "", "nan"])]
    return _frame(t, "Ticker", "Name", "Sector" if "Sector" in t.columns else None), asof


def get_r2000() -> tuple[pd.DataFrame, str]:
    df, asof = parse_ishares_csv(http_get(URL_IWM))
    if len(df) < 1500:
        raise RuntimeError(f"Russell 2000(IWM) 종목 수 이상: {len(df)}")
    log(f"  IWM 보유종목 기준일: {asof}")
    return df, URL_IWM


# ---------------------------------------------------------------- 가격
def _download_chunk(symbols: list[str]) -> pd.DataFrame:
    import yfinance as yf
    for attempt in range(3):
        try:
            df = yf.download(symbols, period="9mo", interval="1d", auto_adjust=True,
                             progress=False, threads=True, group_by="column")
            if df is not None and not df.empty:
                close = df["Close"]
                if isinstance(close, pd.Series):
                    close = close.to_frame(symbols[0])
                return close.dropna(axis=1, how="all")
        except Exception as e:  # noqa: BLE001
            log(f"  [경고] 다운로드 오류(시도 {attempt + 1}): {e}")
        time.sleep(5 * (attempt + 1))
    return pd.DataFrame()


def download_prices(symbols: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    def run(batch: list[str], size: int) -> None:
        for i in range(0, len(batch), size):
            part = _download_chunk(batch[i:i + size])
            if not part.empty:
                frames.append(part)
            log(f"  가격 수집 {min(i + size, len(batch))}/{len(batch)}")
            time.sleep(1)

    run(symbols, CHUNK)
    got = {c for f in frames for c in f.columns}
    missing = [s for s in symbols if s not in got]
    if missing:                                   # 누락분 1회 재시도
        log(f"  누락 {len(missing)}종목 재시도")
        time.sleep(10)
        run(missing, 50)

    if not frames:
        raise RuntimeError("가격 데이터를 전혀 받지 못함 (Yahoo 차단 가능성)")
    prices = pd.concat(frames, axis=1)
    prices = prices.loc[:, ~prices.columns.duplicated()]
    idx = pd.to_datetime(prices.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    prices.index = idx.normalize()
    prices = prices[~prices.index.duplicated(keep="last")].sort_index()
    return prices.apply(pd.to_numeric, errors="coerce")


def settle_asof(prices: pd.DataFrame, now_ny: dt.datetime | None = None) -> pd.DataFrame:
    """장중 미확정 봉 제거 + 과반 종목에 종가가 있는 마지막 날짜까지 자르기."""
    now_ny = now_ny or dt.datetime.now(ZoneInfo("America/New_York"))
    if prices.index[-1].date() == now_ny.date() and now_ny.time() < dt.time(16, 20):
        log("  장 마감 전 실행 → 당일 미확정 봉 제외")
        prices = prices.iloc[:-1]
    cover = prices.notna().mean(axis=1)
    valid = cover[cover >= 0.5]
    if valid.empty:
        raise RuntimeError("유효한 거래일이 없음")
    return prices.loc[:valid.index[-1]]


def compute_returns(prices: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str], pd.Series]:
    """반환: (종목×기간 수익률 %, 기간별 비교 기준일, 기준일 종가)."""
    idx = prices.index
    asof = idx[-1]
    last = prices.loc[asof]                       # 기준일 종가가 없는 종목은 NaN → 제외
    filled = prices.ffill(limit=5)                # 비교 기준일의 단발성 결측만 보정
    rets, bases = {}, {}
    for key, _label, offset in PERIODS:
        if offset is None:
            base = idx[-2]
        else:
            prior = idx[idx <= asof - offset]
            if len(prior) == 0:
                raise RuntimeError(f"{key} 계산에 필요한 과거 데이터 부족")
            base = prior[-1]
        rets[key] = (last / filled.loc[base] - 1.0) * 100.0
        bases[key] = base.strftime("%Y-%m-%d")
    return pd.DataFrame(rets), bases, last


def build_index(meta: pd.DataFrame, rets: pd.DataFrame, last: pd.Series) -> dict:
    meta = meta.set_index("yahoo")
    have = [s for s in meta.index if s in rets.index and pd.notna(last.get(s))]
    sub = rets.loc[have]

    def rows(series: pd.Series) -> list[dict]:
        return [{
            "t": meta.at[s, "ticker"], "y": s, "n": meta.at[s, "name"],
            "s": meta.at[s, "sector"], "c": round(float(last[s]), 2), "r": round(float(v), 2),
        } for s, v in series.items()]

    top, bottom, stats = {}, {}, {}
    for key, _label, _off in PERIODS:
        col = sub[key].dropna()
        top[key] = rows(col.nlargest(TOP_N))
        bottom[key] = rows(col.nsmallest(TOP_N))
        stats[key] = {
            "n": int(col.size),
            "median": round(float(col.median()), 2) if col.size else None,
            "up": int((col > 0).sum()),
            "down": int((col < 0).sum()),
        }
    missing = sorted(meta.at[s, "ticker"] for s in meta.index if s not in have)
    return {"constituents": int(len(meta)), "priced": int(len(have)),
            "missing": missing, "stats": stats, "top": top, "bottom": bottom}


def main() -> int:
    universe = [
        ("sp500", "S&P 500", get_sp500, "Wikipedia"),
        ("ndx100", "NASDAQ 100", get_ndx, "Wikipedia"),
        ("r2000", "Russell 2000", get_r2000, "iShares IWM 보유종목"),
    ]
    metas: dict[str, pd.DataFrame] = {}
    sources: dict[str, str] = {}
    for key, label, fn, _src in universe:
        log(f"[구성종목] {label}")
        metas[key], sources[key] = fn()
        log(f"  {len(metas[key])}종목")

    symbols = sorted(set().union(*(m["yahoo"] for m in metas.values())))
    log(f"[가격] 총 {len(symbols)}종목 다운로드")
    prices = settle_asof(download_prices(symbols))
    rets, bases, last = compute_returns(prices)
    asof = prices.index[-1].strftime("%Y-%m-%d")

    indices, failed = {}, []
    for key, label, _fn, src in universe:
        d = build_index(metas[key], rets, last)
        d.update({"label": label, "source": src, "source_url": sources[key]})
        indices[key] = d
        cov = d["priced"] / d["constituents"]
        log(f"[결과] {label}: {d['priced']}/{d['constituents']} ({cov:.1%})")
        if cov < MIN_COVERAGE:
            failed.append(label)
    if failed:
        log(f"[실패] 가격 수집률 {MIN_COVERAGE:.0%} 미만: {failed} → data.json 갱신하지 않음")
        return 1

    payload = {
        "asof": asof,
        "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "top_n": TOP_N,
        "periods": [{"key": k, "label": lb, "base": bases[k]} for k, lb, _ in PERIODS],
        "indices": indices,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
                   encoding="utf-8")
    log(f"[완료] 기준일 {asof} → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
