# KRW/VND 환율 계산기 💱

원화(KRW)와 베트남 동(VND) 간의 실시간 환율 계산 및 알림 서비스

## 📁 파일 구성

| 파일 | 설명 |
|------|------|
| `krw_vnd_calculator.html` | 웹 기반 환율 계산기 (차트 + 텔레그램 알림) |
| `exchange_rate_collector.py` | Python 환율 수집 스크립트 |
| `exchange_data/rates.json` | 누적 환율 데이터 |

## ✨ 주요 기능

### 웹 계산기 (HTML)
- 🔄 실시간 KRW ↔ VND 환율 변환
- 📈 환율 변동 차트 (1주일/30일)
- 🔔 목표 환율 도달 시 텔레그램 알림
- 📤 데이터 내보내기/불러오기

### Python 수집기
- 📊 매일 환율 데이터 자동 수집
- 💾 JSON 파일로 영구 저장
- 📱 텔레그램으로 일일 환율 알림

## 🚀 사용법

### 웹 계산기
1. `krw_vnd_calculator.html` 파일을 브라우저에서 열기
2. 금액 입력하여 환율 계산
3. 차트 버튼으로 환율 추이 확인

### Python 수집기
```bash
python exchange_rate_collector.py
```

### 자동 실행 설정
Windows 작업 스케줄러에서 매일 특정 시간에 실행되도록 설정

## 📊 데이터 형식

`exchange_data/rates.json`:
```json
{
  "2026-02-05": {
    "krwToVnd": 17.79,
    "vndToKrw": 5.62,
    "timestamp": "2026-02-05T15:40:00"
  }
}
```

## 🔗 API
- [ExchangeRate-API](https://api.exchangerate-api.com/) - 실시간 환율 데이터
