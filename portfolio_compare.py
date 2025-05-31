import yfinance as yf
import pandas as pd
import requests
from datetime import date
import json
import os
from flask import Flask, jsonify, send_from_directory
import threading
import time

app = Flask(__name__)

START_DATE = "2025-05-19"

PORTFOLIO_WEIGHTS = {
    'AAPL': 0.029413, 'AMZN': 0.029396, 'ARKK': 0.054294, 'ARKQ': 0.024354,
    'AVAV': 0.034471, 'BOTZ': 0.026206, 'BRK-B': 0.025727, 'BSV': 0.036768,
    'CIBR': 0.019763, 'CRWD': 0.029413, 'EEM': 0.058821, 'GLD': 0.034459,
    'GOOGL': 0.039547, 'ICLN': 0.009655, 'LIT': 0.009654, 'LMT': 0.039530,
    'META': 0.024333, 'MSFT': 0.058797, 'NOC': 0.039059, 'NVDA': 0.088717,
    'PATH': 0.036562, 'PAVE': 0.011171, 'PLTR': 0.087785, 'QQQ': 0.039065,
    'SMCI': 0.014707, 'SMH': 0.019759, 'TSLA': 0.019304, 'TSM': 0.039569
}

BENCHMARK_TICKER = 'SPY'

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")  # Add your API key as env var

def fetch_from_finnhub(ticker):
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_API_KEY}"
        response = requests.get(url)
        data = response.json()
        return data['c']  # Current price
    except Exception as e:
        print(f"❌ שגיאה ב-Finnhub עבור {ticker}: {e}")
        return None

def fetch_and_calculate():
    try:
        print("🔄 משיכת נתוני שוק מ-Yahoo Finance...")
        end_date = date.today().strftime('%Y-%m-%d')
        all_tickers = list(PORTFOLIO_WEIGHTS.keys()) + [BENCHMARK_TICKER]

        data = yf.download(
            tickers=all_tickers,
            start=START_DATE,
            end=end_date,
            progress=False,
            threads=False,
            group_by='ticker',
            timeout=10
        )

        if data is None or data.empty:
            print("⚠️ yfinance נכשל — מנסה לגבות מ-Finnhub...")
            fallback_data = {}
            for ticker in all_tickers:
                price = fetch_from_finnhub(ticker)
                if price is not None:
                    fallback_data[ticker] = price

            if len(fallback_data) < len(PORTFOLIO_WEIGHTS):
                print("❌ גם Finnhub נכשל — הפסקת חישוב")
                return None

            df = pd.DataFrame([fallback_data], index=[date.today().strftime('%Y-%m-%d')])
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()
            data = df

        # אם הורדנו מ-yfinance, נשתמש ב-["Adj Close"]
        if "Adj Close" in data:
            data = data["Adj Close"]

        portfolio_value = sum(data[ticker] * weight for ticker, weight in PORTFOLIO_WEIGHTS.items())
        portfolio_return = (portfolio_value.iloc[-1] - portfolio_value.iloc[0]) / portfolio_value.iloc[0] * 100
        spy_return = (data[BENCHMARK_TICKER].iloc[-1] - data[BENCHMARK_TICKER].iloc[0]) / data[BENCHMARK_TICKER].iloc[0] * 100

        output = pd.DataFrame({
            "Date": data.index.strftime('%Y-%m-%d'),
            "AI_Core": portfolio_value.values,
            "SPY": data[BENCHMARK_TICKER].values
        })

        if not os.path.exists('static'):
            os.makedirs('static')

        output.to_csv("static/performance_data.csv", index=False)

        print(f"✅ S&P 500: {spy_return:.2f}%")
        print(f"✅ AI Core: {portfolio_return:.2f}%")
        print(f"✅ הפרש: {portfolio_return - spy_return:.2f}%")

        return {
            'spy_return': spy_return,
            'portfolio_return': portfolio_return,
            'difference': portfolio_return - spy_return
        }

    except Exception as e:
        print(f"❌ שגיאה כללית: {e}")
        return None

@app.route('/')
def index():
    return send_from_directory('static', 'ai_core_vs_sp500.html')

@app.route('/performance_data.csv')
def get_csv():
    return send_from_directory('static', 'performance_data.csv')

@app.route('/api/performance')
def get_performance():
    data = fetch_and_calculate()
    if data:
        return jsonify(data)
    else:
        return jsonify({'error': 'Failed to fetch data'}), 500

def update_data_periodically():
    while True:
        fetch_and_calculate()
        time.sleep(900)

if __name__ == "__main__":
    fetch_and_calculate()
    update_thread = threading.Thread(target=update_data_periodically, daemon=True)
    update_thread.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
