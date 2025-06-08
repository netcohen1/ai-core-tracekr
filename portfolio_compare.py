 import pandas as pd
from datetime import date, datetime, timedelta
import json
import os
from flask import Flask, render_template, jsonify, send_from_directory, send_file
import threading
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)

# תאריך התחלה קבוע
START_DATE = "2025-05-19"

# Alpha Vantage API Key (חינמי)
ALPHA_VANTAGE_API_KEY = "O8D8K5YZYU12CC40"  # החלף ב-API key שלך

# משקלי התיק (באחוזים)
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

def fetch_alpha_vantage_data(symbol, start_date, end_date):
    """משיכת נתונים מ-Alpha Vantage"""
    try:
        url = f"https://www.alphavantage.co/query"
        params = {
            'function': 'TIME_SERIES_DAILY',
            'symbol': symbol,
            'apikey': ALPHA_VANTAGE_API_KEY,
            'outputsize': 'full',
            'datatype': 'json'
        }
        
        print(f"🔄 משיכת {symbol} מ-Alpha Vantage...")
        response = requests.get(url, params=params, timeout=30)
        
        if response.status_code != 200:
            print(f"❌ שגיאת HTTP {response.status_code} עבור {symbol}")
            return None
            
        data = response.json()
        
        if 'Error Message' in data:
            print(f"❌ שגיאה מ-Alpha Vantage עבור {symbol}: {data['Error Message']}")
            return None
            
        if 'Note' in data:
            print(f"⚠️ הגבלת קצב עבור {symbol}: {data['Note']}")
            return None
            
        if 'Time Series (Daily)' not in data:
            print(f"❌ אין נתונים עבור {symbol}")
            return None
            
        time_series = data['Time Series (Daily)']
        
        # המרה ל-DataFrame
        df_data = []
        for date_str, values in time_series.items():
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                if start_date <= date_obj <= end_date:
                    df_data.append({
                        'Date': date_obj,
                        'Close': float(values['4. close'])
                    })
            except (ValueError, KeyError) as e:
                continue
                
        if not df_data:
            print(f"❌ אין נתונים בטווח התאריכים עבור {symbol}")
            return None
            
        df = pd.DataFrame(df_data)
        df.set_index('Date', inplace=True)
        df.sort_index(inplace=True)
        
        print(f"✅ {symbol}: {len(df)} נקודות נתונים")
        return df['Close']
        
    except Exception as e:
        print(f"❌ שגיאה במשיכת {symbol}: {str(e)}")
        return None

def fetch_polygon_data(symbol, start_date, end_date):
    """משיכת נתונים מ-Polygon.io (גיבוי)"""
    try:
        # Polygon.io מציע API חינמי מוגבל
        url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/{start_date}/{end_date}"
        params = {
            'apikey': 'demo'  # החלף ב-API key שלך
        }
        
        print(f"🔄 משיכת {symbol} מ-Polygon...")
        response = requests.get(url, params=params, timeout=30)
        
        if response.status_code != 200:
            return None
            
        data = response.json()
        
        if 'results' not in data or not data['results']:
            return None
            
        df_data = []
        for result in data['results']:
            date_obj = datetime.fromtimestamp(result['t'] / 1000).date()
            df_data.append({
                'Date': date_obj,
                'Close': result['c']
            })
            
        df = pd.DataFrame(df_data)
        df.set_index('Date', inplace=True)
        df.sort_index(inplace=True)
        
        print(f"✅ {symbol} (Polygon): {len(df)} נקודות נתונים")
        return df['Close']
        
    except Exception as e:
        print(f"❌ שגיאה ב-Polygon עבור {symbol}: {str(e)}")
        return None

def fetch_ticker_data(ticker, start_date, end_date):
    """משיכת נתונים עם מספר מקורות גיבוי"""
    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
    
    # נסיון ראשון: Alpha Vantage
    data = fetch_alpha_vantage_data(ticker, start_date_obj, end_date_obj)
    if data is not None:
        return data
    
    # נסיון שני: Polygon.io
    time.sleep(1)  # המתנה קצרה בין ספקים
    data = fetch_polygon_data(ticker, start_date, end_date)
    if data is not None:
        return data
    
    # נסיון שלישי: Yahoo Finance עם User-Agent מתקדם
    try:
        import yfinance as yf
        
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        ticker_obj = yf.Ticker(ticker, session=session)
        hist = ticker_obj.history(start=start_date, end=end_date, auto_adjust=True)
        
        if not hist.empty and 'Close' in hist.columns:
            print(f"✅ {ticker} (Yahoo גיבוי): {len(hist)} נקודות נתונים")
            return hist['Close']
            
    except Exception as e:
        print(f"❌ גם Yahoo נכשל עבור {ticker}: {str(e)}")
    
    return None

def fetch_and_calculate():
    """משיכת נתונים וחישוב ביצועים"""
    try:
        print("🚀 התחלת משיכת נתונים...")
        end_date = date.today().strftime('%Y-%m-%d')
        
        # יצירת תיקיית temp
        temp_dir = "/tmp"
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
        
        # משיכת נתונים עבור כל ticker בנפרד
        all_data = {}
        successful_tickers = []
        failed_tickers = []
        
        # משיכת SPY קודם
        print("📊 משיכת נתוני SPY...")
        spy_data = fetch_ticker_data(BENCHMARK_TICKER, START_DATE, end_date)
        if spy_data is not None:
            all_data[BENCHMARK_TICKER] = spy_data
            successful_tickers.append(BENCHMARK_TICKER)
            print(f"✅ SPY: {len(spy_data)} נקודות נתונים")
        else:
            print("❌ כישלון במשיכת נתוני SPY")
            return None
        
        # משיכת נתוני התיק
        print("💼 משיכת נתוני התיק...")
        for ticker in PORTFOLIO_WEIGHTS.keys():
            data = fetch_ticker_data(ticker, START_DATE, end_date)
            if data is not None:
                all_data[ticker] = data
                successful_tickers.append(ticker)
                time.sleep(0.5)  # המתנה קצרה בין בקשות
            else:
                failed_tickers.append(ticker)
                print(f"⚠️ נכשל: {ticker}")
        
        print(f"📈 הצלחה: {len(successful_tickers)} מתוך {len(PORTFOLIO_WEIGHTS) + 1}")
        print(f"❌ כישלונות: {len(failed_tickers)}")
        
        if len(successful_tickers) < 5:  # דרישת מינימום
            print("❌ יותר מדי כישלונות - לא ניתן לחשב ביצועים")
            return None
        
        # יצירת DataFrame מהנתונים שנמשכו בהצלחה
        df = pd.DataFrame(all_data)
        df = df.dropna()  # הסרת שורות עם נתונים חסרים
        
        if df.empty:
            print("❌ אין נתונים זמינים לאחר ניקוי")
            return None
        
        print(f"📊 נתונים סופיים: {len(df)} תאריכים")
        
        # חישוב ערך התיק (רק עם המניות שנמשכו בהצלחה)
        portfolio_value = pd.Series(0, index=df.index)
        total_weight_used = 0
        
        for ticker, weight in PORTFOLIO_WEIGHTS.items():
            if ticker in df.columns:
                portfolio_value += df[ticker] * weight
                total_weight_used += weight
        
        print(f"💰 משקל מנורמל: {total_weight_used:.4f}")
        
        # נרמול המשקלים
        if total_weight_used > 0:
            portfolio_value = portfolio_value / total_weight_used
        
        # חישוב תשואות
        portfolio_return = (portfolio_value.iloc[-1] - portfolio_value.iloc[0]) / portfolio_value.iloc[0] * 100
        spy_return = (df[BENCHMARK_TICKER].iloc[-1] - df[BENCHMARK_TICKER].iloc[0]) / df[BENCHMARK_TICKER].iloc[0] * 100
        
        # הכנת הנתונים לייצוא
        output = pd.DataFrame({
            "Date": df.index.strftime('%Y-%m-%d'),
            "AI_Core": portfolio_value.values,
            "SPY": df[BENCHMARK_TICKER].values
        })
        
        # שמירת קובץ CSV
        csv_path = "/tmp/performance_data.csv"
        output.to_csv(csv_path, index=False)
        
        print(f"✅ S&P 500: {spy_return:.2f}%")
        print(f"✅ AI Core: {portfolio_return:.2f}%")
        print(f"✅ הפרש: {portfolio_return - spy_return:.2f}%")
        print(f"📝 נשמרו {len(output)} נקודות נתונים")
        
        return {
            'spy_return': spy_return,
            'portfolio_return': portfolio_return,
            'difference': portfolio_return - spy_return,
            'data_points': len(output),
            'successful_tickers': len(successful_tickers),
            'failed_tickers': len(failed_tickers)
        }
        
    except Exception as e:
        print(f"❌ שגיאה כללית: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return None

@app.route('/')
def index():
    return send_from_directory('static', 'ai_core_vs_sp500.html')

@app.route('/performance_data.csv')
def get_csv():
    csv_path = "/tmp/performance_data.csv"
    if os.path.exists(csv_path):
        return send_file(csv_path, as_attachment=False, mimetype='text/csv')
    else:
        return "נתונים לא זמינים", 404

@app.route('/api/performance')
def get_performance():
    data = fetch_and_calculate()
    if data:
        return jsonify(data)
    else:
        return jsonify({'error': 'Failed to fetch data'}), 500

@app.route('/api/status')
def get_status():
    """endpoint לבדיקת סטטוס המערכת"""
    csv_exists = os.path.exists('/tmp/performance_data.csv')
    return jsonify({
        'csv_exists': csv_exists,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/debug')
def debug_info():
    """endpoint לדיבוג"""
    import os
    return jsonify({
        'working_directory': os.getcwd(),
        'files_in_tmp': os.listdir('/tmp') if os.path.exists('/tmp') else [],
        'csv_exists': os.path.exists('/tmp/performance_data.csv'),
        'csv_size': os.path.getsize('/tmp/performance_data.csv') if os.path.exists('/tmp/performance_data.csv') else 0
    })

def update_data_periodically():
    """עדכון נתונים כל 15 דקות"""
    while True:
        try:
            print("⏰ עדכון תקופתי...")
            result = fetch_and_calculate()
            if result:
                print("✅ עדכון הושלם בהצלחה")
            else:
                print("⚠️ עדכון נכשל")
        except Exception as e:
            print(f"❌ שגיאה בעדכון תקופתי: {e}")
        
        time.sleep(900)  # 15 דקות

if __name__ == "__main__":
    print("🚀 מתחיל AI Core Portfolio Tracker...")
    
    # עדכון ראשוני
    print("📊 עדכון ראשוני...")
    initial_result = fetch_and_calculate()
    if initial_result:
        print("✅ עדכון ראשוני הושלם")
    else:
        print("⚠️ עדכון ראשוני נכשל - המערכת תמשיך לנסות")
    
    # הפעלת thread לעדכון תקופתי
    print("⏰ הפעלת עדכון תקופתי...")
    update_thread = threading.Thread(target=update_data_periodically, daemon=True)
    update_thread.start()
    
    # הפעלת השרת
    port = int(os.environ.get("PORT", 5000))
    print(f"🌐 הפעלת שרת על פורט {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
