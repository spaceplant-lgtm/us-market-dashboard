# 미국 주식 수익률 대시보드

S&P 500 / NASDAQ 100 / Russell 2000 구성종목의 1일·1주·1개월·3개월·6개월 수익률 Top 20 / Bottom 20을
GitHub Actions가 매일 계산하고, GitHub Pages 웹 화면으로 보여준다.

## 구성

| 파일 | 역할 |
|---|---|
| `scripts/build_data.py` | 구성종목·가격 수집 → 수익률 계산 → `docs/data.json` 생성 |
| `.github/workflows/update.yml` | 매일 자동 실행(화~토 07:30 KST) 및 결과 커밋 |
| `docs/index.html` | 대시보드 화면 (`data.json`을 읽어 표시) |
| `requirements.txt` | Python 의존성 |

## 설치 (최초 1회, 약 10분)

1. GitHub에서 새 저장소 생성 (예: `us-market-dashboard`). **Public**으로 생성한다.
   (GitHub Free 요금제에서 Pages는 공개 저장소에서만 제공됨. 저장소에 올라가는 것은 공개 시세 데이터뿐이다.)
2. 이 폴더의 파일을 저장소에 업로드한다. (`Add file → Upload files`에 폴더째 끌어다 놓기)
   - `.github` 폴더는 숨김 폴더라 업로드에서 빠질 수 있다. 빠졌다면
     `Add file → Create new file`에서 파일 이름에 `.github/workflows/update.yml`을 입력하고
     동봉된 `update.yml` 내용을 붙여넣어 커밋한다.
3. `Settings → Pages → Build and deployment`에서 Source = **Deploy from a branch**,
   Branch = **main**, 폴더 = **/docs** 선택 후 Save.
4. `Actions` 탭 → **Update market data** → **Run workflow** 로 첫 실행. (약 5~15분 소요)
5. 완료 후 `https://<계정명>.github.io/<저장소명>/` 접속. 이 주소를 즐겨찾기에 등록한다.

이후에는 미국 정규장 마감 후 매일 자동 갱신된다(한국시간 화~토 07:30 전후, GitHub 예약 실행은 수십 분 지연될 수 있음).

## 수익률 정의

- 가격: Yahoo Finance 수정주가 (배당·분할 반영, `auto_adjust=True`)
- 1일: 기준일 종가 / 직전 거래일 종가 − 1
- 1주·1개월·3개월·6개월: 기준일 종가 / (기준일 − 해당 기간) 이전 마지막 거래일 종가 − 1 (달력 기준)
- 해당 기간의 과거 가격이 없는 종목(신규 상장 등)은 그 기간 순위에서 제외
- 기준일 종가가 없는 종목은 전 기간 제외되며 화면 하단 "가격 미수집" 목록에 표시

## 데이터 소스와 한계

- S&P 500: Wikipedia "List of S&P 500 companies" (실패 시 GitHub datasets CSV)
- NASDAQ 100: Wikipedia "List of NASDAQ-100 companies"
- Russell 2000: iShares Russell 2000 ETF(IWM) 보유종목 CSV — 지수 공식 구성종목 목록이 아닌 대용치
- Yahoo Finance는 비공식 무료 경로다. 일부 종목 누락, 수정주가 오류, 접속 차단이 발생할 수 있다.
  지수별 가격 수집률이 90% 미만이면 스크립트가 실패 처리하고 이전 데이터를 유지한다
  (화면 상단에 갱신 지연 경고 표시).
- 구성종목은 실행 시점의 현재 목록 기준이다(과거 편입·편출 이력 미반영).

## 로컬 실행 (선택)

```bash
pip install -r requirements.txt
python scripts/build_data.py
cd docs && python -m http.server 8000   # http://localhost:8000
```

## 설정 변경

- Top/Bottom 개수: `scripts/build_data.py`의 `TOP_N`
- 실행 시각: `.github/workflows/update.yml`의 `cron` (UTC 기준)
