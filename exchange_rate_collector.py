"""
KRW/VND 환율 수집기
==================
매일 실행하여 환율 데이터를 JSON 파일에 저장하고 텔레그램으로 알림을 보냅니다.
HTML 환율 계산기의 '데이터 불러오기' 기능과 호환됩니다.

사용법:
    python exchange_rate_collector.py
    
자동 실행 설정:
    1. Windows 작업 스케줄러에서 매일 실행 설정
    2. 또는 시작 프로그램에 추가
"""

import json
import os
import requests
from datetime import datetime

# 설정
DATA_DIR = r"C:\gemini\exchange_data"
DATA_FILE = os.path.join(DATA_DIR, "rates.json")
API_URL = "https://api.exchangerate-api.com/v4/latest/KRW"

# 텔레그램 설정
TELEGRAM_BOT_TOKEN = "8297687133:AAHK1b_aInggvX3jUv8xseoqJqYJ774ovlM"
TELEGRAM_CHAT_ID = "393163178"

def ensure_data_dir():
    """데이터 폴더 생성"""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        print(f"📁 폴더 생성: {DATA_DIR}")

def load_existing_data():
    """기존 데이터 로드"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ 기존 데이터 로드 실패: {e}")
    return {}

def save_data(data):
    """데이터 저장"""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def fetch_exchange_rate():
    """API에서 환율 가져오기"""
    try:
        response = requests.get(API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        vnd_per_krw = data['rates']['VND']  # 1 KRW = X VND
        krw_per_100vnd = 100 / vnd_per_krw   # 100 VND = X KRW
        
        return {
            'krwToVnd': round(vnd_per_krw, 2),
            'vndToKrw': round(krw_per_100vnd, 2),
            'timestamp': datetime.now().isoformat()
        }
    except Exception as e:
        print(f"❌ API 호출 실패: {e}")
        return None

def send_telegram_message(rate_data, total_days):
    """텔레그램으로 환율 정보 전송"""
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    message = (
        f"💱 <b>오늘의 환율 정보</b>\n\n"
        f"📅 {today}\n\n"
        f"💹 1 KRW = <b>{rate_data['krwToVnd']} VND</b>\n"
        f"💹 100 VND = <b>{rate_data['vndToKrw']} KRW</b>\n\n"
        f"📊 총 저장 데이터: {total_days}일"
    )
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        response = requests.post(url, json={
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'HTML'
        }, timeout=10)
        
        if response.ok:
            print("📱 텔레그램 알림 전송 완료!")
            return True
        else:
            print(f"⚠️ 텔레그램 전송 실패: {response.text}")
            return False
    except Exception as e:
        print(f"❌ 텔레그램 전송 오류: {e}")
        return False

def main():
    print("=" * 50)
    print("💱 KRW/VND 환율 수집기")
    print("=" * 50)
    
    # 폴더 확인
    ensure_data_dir()
    
    # 기존 데이터 로드
    history = load_existing_data()
    existing_days = len(history)
    print(f"📊 기존 저장 데이터: {existing_days}일")
    
    # 오늘 날짜
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 이미 오늘 데이터가 있는지 확인
    if today in history:
        print(f"ℹ️ 오늘({today}) 데이터가 이미 존재합니다.")
        print(f"   1 KRW = {history[today]['krwToVnd']} VND")
        print(f"   100 VND = {history[today]['vndToKrw']} KRW")
    
    # 환율 가져오기
    print(f"\n🔄 환율 데이터 가져오는 중...")
    rate_data = fetch_exchange_rate()
    
    if rate_data:
        history[today] = rate_data
        save_data(history)
        
        total_days = len(history)
        print(f"\n✅ 저장 완료!")
        print(f"   📅 날짜: {today}")
        print(f"   💹 1 KRW = {rate_data['krwToVnd']} VND")
        print(f"   💹 100 VND = {rate_data['vndToKrw']} KRW")
        print(f"   📁 파일: {DATA_FILE}")
        print(f"   📊 총 저장: {total_days}일")
        
        # 텔레그램 알림 전송
        print(f"\n📱 텔레그램 알림 전송 중...")
        send_telegram_message(rate_data, total_days)
    else:
        print("\n❌ 환율 데이터를 가져오지 못했습니다.")
    
    print("\n" + "=" * 50)

if __name__ == "__main__":
    main()
