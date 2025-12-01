from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from datetime import datetime, timedelta, timezone
import logging
import pandas as pd
import os
import talib
import boto3

# boto3 clients for SSM and Cloudwatch
ssm = boto3.client("ssm")
cw = boto3.client("cloudwatch")

ALPACA_KEY = ssm.get_parameter(Name=os.environ["ALPACA_KEY_PARAM"], WithDecryption=True)["Parameter"]["Value"]

ALPACA_SECRET = ssm.get_parameter(Name=os.environ["ALPACA_SECRET_PARAM"], WithDecryption=True)["Parameter"]["Value"]

# Setting up paper trading client
trading_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=True)
SYMBOLS = os.environ.get('SYMBOLS').split(",")
RISK_PCT = float(os.environ.get('RISK_PCT'))
MINUTES_HISTORY = int(os.environ.get('MINUTES_HISTORY'))

# Setting up data client
data_client = StockHistoricalDataClient(ALPACA_KEY, ALPACA_SECRET)

# logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def compute_indicators(close_series: pd.Series):
    """
    Calculates RSI(14) and EMA(9) using talib and stores in pandas df
    returns: DataFrame with columns: close, rsi14, ema9
    """

    df = pd.DataFrame({"close": close_series})
    df["rsi14"] = talib.RSI(df["close"].values, timeperiod=14)
    df["ema9"] = talib.EMA(df["close"].values, timeperiod=9)
    return df

# Data fetching

def fetch_minute_bars(symbol: str, minutes: int) -> pd.DataFrame:
    """
    Fetch the last `minutes` minute-bars (close prices) up to now (ET market time)
    returns: pandas Series indexed by timestamp
    """

    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes*2)
    req = StockBarsRequest(symbol_or_symbols=[symbol], start=start.isoformat(), end=end.isoformat(),timeframe=TimeFrame.Minute)
    bars = data_client.get_stock_bars(req)
    df = bars.df

    if symbol not in df.index.get_level_values(0):
        return pd.DataFrame()
    
    df_sym = df.xs(symbol, level = 0)
    df_sym = df_sym.sort_index()
    if len(df_sym) > minutes:
        df_sym = df_sym.iloc[-minutes:]
    return df_sym.tz_convert("UTC")

# Account and orders

def get_portfolio_equity():
    """
    Helper function to get portfolio equity
    """
    acct = trading_client.get_account()
    return float(acct.equity)
    
def submit_market_notional_order(symbol: str, side: OrderSide, notional: float):
    """
    Submit a market order using notional (fractional shares). Uses TimeInForce.DAY.
    """

    order_req = MarketOrderRequest(
        symbol=symbol,
        notional=notional,
        side=side,
        time_in_force=TimeInForce.DAY)

    return trading_client.submit_order(order_data=order_req)

# Strategy

def evaluate_and_trade(symbol: str):
    """
    Sends a buy or sell signal depending on indicators
    """
    df_bars = fetch_minute_bars(symbol, MINUTES_HISTORY)
    if df_bars.empty or "close" not in df_bars.columns:
        return {"symbol": symbol, "action": "no_data"}
    
    close = df_bars["close"].astype(float)
    indicators = compute_indicators(close).dropna()
    if indicators.empty:
        return {"symbol": symbol, "action": "insufficient_data"}
    
    last = indicators.iloc[-1]
    c = float(last["close"])
    rsi = float(last["rsi14"])
    ema9 = float(last["ema9"])

    logger.info("%s -> close=%.4f rsi=%.2f ema9=%.4f", symbol, c, rsi, ema9)

    publish_metric("RSI", rsi, symbol)
    publish_metric("EMA9", ema9, symbol)
    publish_metric("Price", c, symbol)

    # BUY
    if rsi < 30 and c < ema9:
        
        equity = get_portfolio_equity()
        notional = equity * RISK_PCT

        logger.info("Buying %s using %.2f notional (equity=%.2f)", symbol, notional, equity)

        order = submit_market_notional_order(symbol, OrderSide.BUY, notional)

        publish_metric("Equity", equity, "Portfolio")
        publish_metric("TradeNotional", notional, symbol)

        publish_metric("BuySignal", 1, symbol)
        return {
            "symbol": symbol,
            "action": "buy",
            "order_id": order.id,
            "notional": notional
        }
    
    # SELL 
    if rsi > 70 and c > ema9:
        

        try:
            pos = trading_client.get_position(symbol)
            pnl = float(pos.unrealized_pl)
            qty = float(pos.qty)

            publish_metric("TradeQuantity", qty, symbol)
            publish_metric("PnL", pnl, symbol)

            order_req = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )
            order = trading_client.submit_order(order_data=order_req)
            publish_metric("SellSignal", 1, symbol)

            return {
                "symbol": symbol,
                "action": "sell",
                "order_id": order.id,
                "qty": qty
            }
        except Exception:
            # no position exists
            return {"symbol": symbol, "action": "nothing_to_sell"}
        
        # No trade
    return {
        "symbol": symbol,
        "action": "no_signal",
        "rsi": rsi,
        "close": c,
        "ema9": ema9
    }

    


def publish_metric(name, value, symbol):
    """
    Helper function to publish metrics for dashboard
    """
    dims = []
    if symbol:
        dims.append({"Name": "Symbol", "Value": symbol})

    cw.put_metric_data(
        Namespace="TradingBot",
        MetricData=[{
            "MetricName": name,
            "Dimensions": dims,
            "Value": float(value),
            "Unit": "None"
        }]
    )




def lambda_handler(event, context):
    equity = get_portfolio_equity()
    publish_metric("Equity", equity, "Portfolio")

    results = []
    for sym in SYMBOLS:
        try:
            result = evaluate_and_trade(sym.strip().upper())
            logger.info("%s -> %s", sym, result)
            results.append(result)
        except Exception as e:
            logger.exception("Error on %s", sym)
            results.append({"symbol": sym, "action": "error", "error": str(e)})

    return {"statusCode": 200, "body": results}