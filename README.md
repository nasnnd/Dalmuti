# 달무티 온라인 (Dalmuti Online)

Flask + Flask-SocketIO 기반 실시간 멀티플레이어 달무티 카드게임

## 설치 & 실행

### 로컬 실행

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. 실행
python app.py
```

```bash
# (선택) 배포 환경처럼 실행
PORT=5000 FLASK_DEBUG=0 python app.py

```

→ 브라우저에서 `http://localhost:5000` 접속

여러 브라우저 탭/창으로 멀티플레이 테스트 가능합니다.

---

## 웹 호스팅 배포 가이드

### Railway (무료, 추천)

1. https://railway.app 가입
2. `New Project → Deploy from GitHub` 선택
3. 이 폴더를 GitHub에 업로드 후 연결
4. 환경변수: 없음 (자동 설정)
5. 배포 완료 후 URL 공유

### Render (무료)

1. https://render.com 가입
2. `New → Web Service` 선택
3. GitHub 연결 후:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python app.py`

### Replit (가장 간단)

1. https://replit.com 가입
2. `Create Repl → Import from GitHub`
3. 또는 파일 직접 업로드
4. Run 버튼 클릭
5. Replit이 제공하는 URL 공유

---

## 파일 구조

```
dalmuti/
├── app.py              # 서버 로직 (게임 엔진)
├── requirements.txt    # Python 의존성
├── README.md
└── templates/
    └── index.html      # 프론트엔드 전체
```

---

## 게임 플레이 방법

1. 사이트 접속 후 닉네임 설정 (2~10글자)
2. 방 만들기 또는 기존 방 입장
3. 모든 플레이어 준비 완료 → 방장이 게임 시작
4. 카드를 뽑아 초기 순서 결정 (1라운드만)
5. 카드 교환 후 게임 시작
6. 가장 먼저 카드를 다 내는 사람이 새 달무티!

---

## 카드 이미지 추가 방법

현재는 이모지+텍스트로 표시됩니다.
이미지를 추가하려면 `templates/index.html`의 `cardHTML` 함수를 수정:

```javascript
// 현재
return `<div class="${cls}" ...>
  <div class="card-emoji">${card.emoji}</div>
  <div class="card-num">${card.num}</div>
  ...

// 이미지 추가 후
return `<div class="${cls}" ...>
  <img src="/static/cards/${card.num}.png" style="width:48px;height:auto">
  ...
```

`static/cards/` 폴더에 `1.png` ~ `13.png` 파일을 넣으면 됩니다.
