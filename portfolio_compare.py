import yfinance as yf
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
import tempfile

app = Flask(__name__)

# תאריך התחלה קבוע
START_DATE = "2025-05-19"

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

def setup_session():
    """הגדרת session עם retry ו-headers מתאימים"""
    session = requests.Session()
    
    # הגדרת retry strategy
    retry_strategy = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # הגדרת headers
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    })
    
    return session

def fetch_ticker_data(ticker, start_date, end_date, max_retries=5):
    """משיכת נתונים עבור ticker בודד עם retry logic משופר"""
    for attempt in range(max_retries):
        try:
            print(f"🔄 נסיון {attempt + 1} למשיכת {ticker}")
            
            # המתנה בין נסיונות
            if attempt > 0:
                time.sleep(min(2 ** attempt, 10))  # עד 10 שניות מקסימום
            
            # יצירת Ticker object עם session מותאם
            session = setup_session()
            ticker_obj = yf.Ticker(ticker, session=session)
            
            # משיכת נתונים עם timeout
            hist = ticker_obj.history(
                start=start_date, 
                end=end_date, 
                auto_adjust=True,
                timeout=30
            )
            
            if not hist.empty and 'Close' in hist.columns and len(hist) > 0:
                print(f"✅ הצלחה: {ticker} - {len(hist)} נקודות נתונים")
                return hist['Close']
            else:
                print(f"⚠️ נתונים ריקים עבור {ticker}")
                
        except Exception as e:
            print(f"❌ שגיאה עבור {ticker} (נסיון {attempt + 1}): {str(e)}")
            
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
        
        # שמירת קובץ CSV בנתיב החדש
        csv_path = "/tmp/performance_data.csv"
        output.to_csv(csv_path, index=False)
        
        print(f"✅ S&P 500: {spy_return:.2f}%")
        print(f"✅ AI Core: {portfolio_return:.2f}%")
        print(f"✅ הפרש: {portfolio_return - spy_return:.2f}%")
        print(f"📝 נשמרו {len(output)} נקודות נתונים ב-{csv_path}")
        
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
