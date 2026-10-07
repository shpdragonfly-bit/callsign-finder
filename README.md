# Call Sign 오프라인 조회기 (대한항공 우선)

운항 전 인터넷이 될 때 **최신 Call Sign 자료를 내 기기에 받아두고**, 운항 중 인터넷이 없을 때 **Call Sign을 입력하면 출발공항 / 도착공항 / 기종**을 보여주는 웹 기반 프로그램입니다.
PC(Windows·Mac)는 물론 **iPhone · iPad · Android**에서 앱처럼 설치해 오프라인으로 사용할 수 있습니다.

```
 [인터넷 O : 운항 전]                                  [인터넷 X : 운항 중]
 updater/update.py ──▶ web/data.json, data.js ──▶ 기기에 저장 ──▶ index.html 에서 조회
   ├ 노선  : VRS standing-data (Call Sign → 공항)
   ├ 공항  : VRS airports (ICAO/IATA/공항명/도시)
   └ 기종  : adsb.lol / airplanes.live (실시간 비행기 관측 → 누적)
```

## 폴더 구성

| 경로 | 내용 |
|---|---|
| `web/` | 조회 화면 (index.html) + 데이터(data.json/data.js) + 오프라인용 Service Worker. **이 폴더만 있으면 조회 가능** |
| `updater/update.py` | 데이터 업데이트 프로그램 (Python 3.8+, 추가 설치 불필요) |
| `config/airlines.json` | 대상 항공사 목록 (현재 대한항공만 `enabled: true`) |
| `config/overrides.csv` | 노선·기종 수동 보정 |
| `data/observations.json` | 기종 관측 누적 기록 (업데이트할수록 정확해짐) |
| `.github/workflows/update.yml` | GitHub에 올렸을 때 자동 갱신 + 웹 배포 |

## 사용 방법

### A. PC에서 사용 (가장 간단)
1. Python 3 설치 (Windows: python.org 에서 설치 시 "Add to PATH" 체크)
2. 인터넷 연결 상태에서 업데이트 실행
   - Windows: `업데이트_Windows.bat` 더블클릭
   - Mac/Linux: `./update.sh`
3. `web/index.html` 을 브라우저(Chrome/Edge/Safari)로 열기 → 인터넷 없이 조회됨

### B. iPhone · iPad · Android에서 사용 (권장: GitHub Pages)
휴대기기는 웹 주소(https)로 한 번 열어두어야 오프라인 저장이 됩니다. 무료인 GitHub Pages가 가장 편합니다.

1. GitHub 계정에서 새 저장소(예: `callsign-finder`) 생성 후 이 폴더 전체를 업로드
2. 저장소 **Settings → Pages → Source: GitHub Actions** 선택
3. **Actions** 탭 → `update-callsign-data` → **Run workflow** (이후 6시간마다 자동 갱신)
4. 휴대기기에서 `https://<계정>.github.io/callsign-finder/` 접속
   - iPhone/iPad: Safari → 공유 → **홈 화면에 추가**
   - Android: Chrome → 메뉴 → **앱 설치 / 홈 화면에 추가**
5. **운항 전(인터넷 O)**: 앱을 열면 자동으로 최신 데이터 확인, 또는 **[최신 데이터 받기]** 버튼
6. **운항 중(인터넷 X)**: 홈 화면 아이콘으로 실행 → 저장된 데이터로 조회 (상단에 "오프라인" 표시)

> 저장소를 공개하고 싶지 않으면 private 저장소 + Pages는 유료 플랜이 필요합니다. 대안은 C 또는 D 방식입니다.

### C. 같은 Wi-Fi에서 PC → 휴대기기로 받기
`python3 updater/update.py --serve` 실행 후 화면에 나오는 `http://192.168.x.x:8000` 을 휴대기기에서 열고 **[최신 데이터 받기]** → 데이터가 기기에 저장됩니다.
(단, http 주소는 브라우저 정책상 앱 화면 자체가 오프라인 캐시되지 않을 수 있어 B 방식을 권장합니다.)

### D. 파일로 전달
PC에서 만든 `web/data.json` 을 AirDrop·메신저·파일앱으로 기기에 옮긴 뒤 앱에서 **[파일에서 가져오기]**.

## 입력 방법
`KAL017`, `KAL17`, `KE17`, `KE017`, `KOREANAIR 17`, `17` 모두 같은 편으로 인식합니다 (앞자리 0 무시).
`KAL103A` 처럼 문자 접미사가 붙은 Call Sign도 그대로 조회됩니다. 일치하는 자료가 없으면 비슷한 Call Sign 후보를 보여줍니다.

## 기종 정보에 대해 (중요)
- 노선은 Call Sign별로 공개 DB가 있지만, **편명별 기종은 무료 공개 DB가 없습니다.** 그래서 업데이트할 때마다 ADS-B로 **그 순간 비행 중인** 대한항공기를 기종별로 조회해 "이 편에 어떤 기종이 투입됐는지"를 누적합니다.
- 따라서 첫 실행 직후에는 기종이 일부 편에만 채워지며, **여러 시간대에 여러 날 반복 실행할수록** 채워지는 비율이 올라갑니다 (GitHub Actions 6시간 주기 권장).
- 화면에는 최근 45일 관측 빈도가 가장 높은 기종을 대표로, 그 외 관측 기종을 아래에 `B789 ×2` 처럼 표시합니다. 관측 기록은 120일 지나면 삭제됩니다.
- 확실히 아는 편은 `config/overrides.csv` 에 적으면 "수동 지정"으로 우선 표시됩니다.

## 다른 항공사 추가
`config/airlines.json` 에서 해당 항공사의 `"enabled": true` 로 바꾸거나 항목을 추가하고 업데이트를 다시 실행하면 됩니다. (아시아나 `AAR`, 진에어 `JNA` 예시 포함)
필요한 값은 ICAO 코드(3자리), IATA 코드(2자리), 무선호출부호(telephony)입니다. 해당 항공사 보유 기종이 `type_sweep` 목록에 없으면 추가하세요.

## 주의
- 데이터는 공개·제보 기반 참고자료입니다. 계절 스케줄 변경, 임시편, 기재 변경이 반영되지 않을 수 있으니 공식 운항 정보를 대체하지 않습니다.
- 화면 하단의 "데이터 기준" 시각이 7일 이상 지나면 경고가 표시됩니다.
- 출처: [Virtual Radar Server standing-data](https://github.com/vradarserver/standing-data), [adsb.lol](https://adsb.lol), [airplanes.live](https://airplanes.live) — 각 서비스의 이용 정책을 지켜 사용하세요.
